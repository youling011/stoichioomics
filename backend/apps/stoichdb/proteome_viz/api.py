from pathlib import Path
from functools import wraps
import hashlib,json,time
import numpy as np
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.urls import path
from rest_framework.decorators import api_view,permission_classes
from rest_framework.permissions import IsAdminUser
from backend.apps.common.responses import ok,err
from backend.apps.stoichdb.models import OmicsDataset,Species
from . import METHOD_VERSION
from .contracts import TITLES,CORE_FIELDS,ALIASES,FINGERPRINT
from .source import release_id
from . import artifacts as store
from . import work_requests
from .density import hexbin
from .statistics import conditional,correlation
from .ordination import cohort
from .exports import download

def guarded(fn):
    @wraps(fn)
    def call(request,*args,**kwargs):
        try:return fn(request,*args,**kwargs)
        except ObjectDoesNotExist:return err('Unknown species or Proteome dataset',404)
        except FileNotFoundError as exc:return err(str(exc),410 if str(exc)=='artifact_expired' else 404)
        except (ValueError,KeyError,TypeError) as exc:return err(str(exc),400)
    return call

def scope_for(request):
    scope=request.data.get('scope','core') if request.method=='POST' else request.GET.get('scope','core')
    if scope not in ['core','full']:raise ValueError('invalid_scope')
    return scope
def enabled():return bool(getattr(settings,'STOICH_PROTEOME_VIZ_V3_ENABLED',True))
def manifest_stale(m,ds):
    stale=m.get('dataset_id')!=ds.dataset_id or m.get('implementation_hash')!=store.implementation_hash() or m.get('method_version')!=METHOD_VERSION
    for kind in ['core','full']:
        raw=getattr(ds,kind+'_csv_path');p=Path(raw) if raw else None;sig={'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} if p and p.is_file() else None
        stale=stale or sig!=m.get('source',{}).get('file_signatures',{}).get(kind)
    return stale
def bounds(request,key,default,lo,hi):
    value=int(request.GET.get(key,default))
    if not lo<=value<=hi:raise ValueError(f'{key}_outside_{lo}_{hi}')
    return value
def target_for(request,species_id):
    OmicsDataset.objects.only('id').get(species__species_id=species_id,omics_type='proteome')
    target=store.lookup_version(species_id,scope_for(request),release_id(),request.GET.get('artifact_version',''))
    manifest=store.read_json(target/'manifest.json')
    if request.GET.get('source_hash') and request.GET['source_hash']!=manifest['source_hash']:raise ValueError('source_hash_mismatch_refresh_required')
    return target,manifest
def ready(payload):return ok({'readiness':'ready','result':payload})
def presentation(payload):
    # Interval views need original quantiles, not thousands of redundant ECDF/KDE
    # points embedded in every descriptor. Full profiles and exports remain intact.
    if payload.get('data',{}).get('kind') not in ['intervals','elements','quantile_bands','structure_atlas','strata_matrix']:return payload
    def trim(value):
        if isinstance(value,list):return [trim(v) for v in value]
        if isinstance(value,dict):return {k:trim(v) for k,v in value.items() if k not in ['histogram','kde','ecdf']}
        return value
    return {**payload,'data':trim(payload['data'])}

@api_view(['GET'])
@guarded
def manifest_view(request,species_id):
    scope=scope_for(request);ds=OmicsDataset.objects.get(species__species_id=species_id,omics_type='proteome');release=release_id()
    available=['core']+(['full'] if ds.full_csv_path and Path(ds.full_csv_path).is_file() else [])
    pointer=store.published(species_id,scope,release)
    base={'enabled':enabled(),'method_version':METHOD_VERSION,'species_id':species_id,'dataset_id':ds.dataset_id,'release_id':release,'primary_scope':scope,'available_scopes':available,'consumer_available':work_requests.consumer_alive()}
    if pointer:
        m=store.read_json(store.path_for(pointer)/'manifest.json')
        stale=manifest_stale(m,ds)
        return ok({**m,**base,'readiness':'stale' if stale else 'ready','reason_code':'source_changed_rebuild_required' if stale else None})
    return ok({**base,'readiness':'not_prepared','reason_code':'full_not_registered' if scope not in available else 'artifact_not_prepared','n_source':ds.row_count_core if scope=='core' else ds.row_count_full,'fields':[],'charts':[{'chart_id':c,'title':t,'status':'unavailable'} for c,t in TITLES.items()]})

@api_view(['GET'])
@guarded
def chart_view(request,species_id,chart_id):
    if chart_id not in TITLES:raise ValueError('unknown_chart_id')
    if chart_id in ['D11','D12','D16']:
        from .cohorts import payload
        raw=request.GET.get('species_ids','');r=payload(species_id,scope_for(request),release_id(),list(dict.fromkeys(raw.split(','))) if raw else None)
        return ready({'chart_id':chart_id,'title':TITLES[chart_id],'status':r.get('data',{}).get('status','unavailable'),'data':{'kind':'cohort','cohort':r}})
    try:target,m=target_for(request,species_id)
    except FileNotFoundError as exc:
        if str(exc)!='not_prepared':raise
        return ok({'readiness':'not_prepared','reason_code':'artifact_not_prepared','result':None})
    cid=ALIASES.get(chart_id,chart_id);payload=store.read_bundle(str(target))[cid]
    return ready(presentation({**payload,'requested_chart_id':chart_id}))

@api_view(['GET'])
@guarded
def fields_view(request,species_id):
    target,m=target_for(request,species_id);allowed=[f['key'] for f in m['fields']];requested=request.GET.get('fields','')
    if requested:
        fields=list(dict.fromkeys(requested.split(',')))
        if len(fields)>12 or not set(fields).issubset(allowed):raise ValueError('invalid_fields_or_more_than_12')
    else:
        page=bounds(request,'page',1,1,10000);size=bounds(request,'page_size',6,1,12);fields=allowed[(page-1)*size:page*size]
    profiles=store.read_json(target/'profiles.json.gz')
    return ok({'readiness':'ready','source_hash':m['source_hash'],'artifact_version':m['artifact_version'],'total_fields':len(allowed),'profiles':[profiles[f] for f in fields]})

def pair_payload(target,m,x,y,k=10,gridsize=42):
    allowed={f['key'] for f in m['fields']}
    if x not in allowed or y not in allowed:raise ValueError('field_not_in_current_scope_allowlist')
    if not 1<=k<=20 or not 8<=gridsize<=100:raise ValueError('invalid_binning_parameters')
    variant=hashlib.sha256(json.dumps([x,y,k,gridsize],separators=(',',':')).encode()).hexdigest()
    folder=target/'variants';key=variant[:16];json_path=folder/(key+'.json')
    if json_path.is_file():
        payload=store.read_json(json_path)
        for field in payload['fields']:field['unit']=next(f['unit'] for f in m['fields'] if f['key']==field['key'])
        return payload
    a=store.read_matrix(str(target));vx=a['matrix'][:,a['fields'].index(x)];vy=a['matrix'][:,a['fields'].index(y)];h=hexbin(vx,vy,gridsize);members=h.pop('membership');mask=h.pop('mask');gg=conditional(vx,vy,k)
    for g in gg:g.pop('_members')
    payload={'chart_id':'B15','title':f'{x} vs {y}','variant_id':variant,'artifact_version':m['artifact_version'],'method_version':METHOD_VERSION,'source_hash':m['source_hash'],'species_id':m['species_id'],'dataset_id':m['dataset_id'],'primary_scope':m['primary_scope'],'release_id':m['release_id'],'status':'available' if mask.any() else 'unavailable','reason_code':None if mask.any() else 'no_valid_pairs','fields':[{'key':x,'unit':'native','role':'x'},{'key':y,'unit':'native','role':'y'}],'coverage':{'n_source':m['n_source'],'n_valid':int(mask.sum()),'n_excluded':int((~mask).sum()),'sampling_policy':'none','aggregation':'hex_conditional'},'method':{'name':'complete_population_hexbin','parameters':{'gridsize':gridsize,'conditional_bins':k},'transforms':[]},'data':{'kind':'hex_conditional','x':x,'y':y,'hex':h,'conditional':gg,'correlation':correlation(vx,vy)}}
    import uuid
    folder.mkdir(exist_ok=True);temp=folder/(key+'.'+uuid.uuid4().hex[:8]+'.npz');np.savez_compressed(temp,members=members)
    import os
    os.replace(temp,folder/(key+'.npz'))
    for field in payload['fields']:field['unit']=next(f['unit'] for f in m['fields'] if f['key']==field['key'])
    store.write_json(json_path,payload)
    return payload

@api_view(['GET'])
@guarded
def pair_view(request,species_id):
    target,m=target_for(request,species_id);x=request.GET.get('x','pI');y=request.GET.get('y','N_atoms_per_aa')
    return ready(pair_payload(target,m,x,y,bounds(request,'conditional_bins',10,1,20),bounds(request,'gridsize',42,8,100)))

@api_view(['GET'])
@guarded
def members_view(request,species_id):
    target,m=target_for(request,species_id);cid=ALIASES.get(request.GET.get('chart_id','B15'),request.GET.get('chart_id','B15'));bid=request.GET.get('bin_id','');variant=request.GET.get('variant_id','')
    if variant:
        if len(variant)!=64 or any(c not in '0123456789abcdef' for c in variant):raise ValueError('invalid_variant')
        variant_payload=store.read_json(target/'variants'/(variant[:16]+'.json'))
        if variant_payload['variant_id']!=variant:raise ValueError('variant_identity_conflict')
        data=variant_payload['data'];array=np.load(target/'variants'/(variant[:16]+'.npz'),allow_pickle=False)
        try:membership=array['members']
        finally:array.close()
    else:
        data=store.read_bundle(str(target))[cid]['data'];membership=store.read_arrays(str(target)).get(cid+'_members')
    if membership is None or 'hex' not in data:raise ValueError('chart_has_no_bin_members')
    match=next((b for b in data['hex']['bins'] if b['bin_id']==bid),None)
    if match is None:raise ValueError('unknown_bin_id')
    row_indices=np.flatnonzero(membership==match['index']);assert len(row_indices)==match['count']
    page=bounds(request,'page',1,1,1000000);size=bounds(request,'page_size',50,1,200);meta=store.read_metadata(str(target));idx=row_indices[(page-1)*size:page*size]
    return ok({'total':len(row_indices),'page':page,'page_size':size,'artifact_version':m['artifact_version'],'rows':[{f:meta[f][i] for f in meta} for i in idx]})

@api_view(['GET'])
@guarded
def structure_view(request,species_id):
    target,m=target_for(request,species_id);d=store.read_bundle(str(target))['D07']['data']
    if request.GET.get('resolution','overview')=='overview':return ok({'artifact_version':m['artifact_version'],**d})
    start=bounds(request,'rank_start',0,0,max(0,m['n_source']-1));count=bounds(request,'rank_count',100,1,1000);a=store.read_arrays(str(target));matrix=store.read_matrix(str(target));meta=store.read_metadata(str(target));idx=a['D07_order'][start:start+count];columns=[matrix['fields'].index(f) if f in matrix['fields'] else None for f in d['fields']]
    rows=[{'rank':start+j,'protein_id':meta['protein_id'][i],'gene_id':meta['gene_id'][i],'values':[matrix['matrix'][i,c] if c is not None else None for c in columns],'z':a['D07_z'][i].tolist()} for j,i in enumerate(idx)]
    return ok({'artifact_version':m['artifact_version'],'source_hash':m['source_hash'],'fields':d['fields'],'n_source':m['n_source'],'rank_start':start,'rows':rows})

@api_view(['GET'])
@guarded
def cohort_view(request,species_id):
    search=request.GET.get('search','').strip()
    if search:
        from django.db.models import Q
        matches=Species.objects.filter(Q(species_id__icontains=search)|Q(display_name__icontains=search)).order_by('species_id').values('species_id','display_name','domain')[:20]
        return ok({'matches':list(matches)})
    from .cohorts import payload
    raw=request.GET.get('species_ids','')
    return ok(payload(species_id,scope_for(request),release_id(),list(dict.fromkeys(raw.split(','))) if raw else None))
@api_view(['GET'])
@guarded
def export_view(request,species_id):
    target,m=target_for(request,species_id)
    kind=request.GET.get('kind','chart')
    if kind not in ['chart','raw','pca','loadings','structure','candidates','percentiles','partial_candidates','ecdf','method']:raise ValueError('invalid_export_kind')
    return download(target,request.GET.get('chart_id','B01'),kind,'\t' if request.GET.get('file_format')=='tsv' else ',',request.GET.get('variant_id',''))

@api_view(['POST'])
@permission_classes([IsAdminUser])
@guarded
def prepare_view(request,species_id):
    scope=scope_for(request);OmicsDataset.objects.get(species__species_id=species_id,omics_type='proteome')
    cid=request.data.get('chart_id','all')
    if cid not in ['all',*TITLES]:raise ValueError('unknown_chart_id')
    if not work_requests.consumer_alive():return ok({'readiness':'not_prepared','reason_code':'consumer_not_running','operator_action':'Run materialize_proteome_visuals --consume-requests'})
    parameters=request.data.get('parameters',{})
    if not isinstance(parameters,dict) or set(parameters)-{'x','y','gridsize','conditional_bins'}:raise ValueError('invalid_prepare_parameters')
    result=work_requests.enqueue(species_id,scope,cid,parameters);result['status_url']=f'/api/stoichdb/species/{species_id}/proteome/visualizations/requests/{result["request_id"]}/'
    return ok(result,202 if result['readiness'] in ['queued','running'] else 200)

@api_view(['POST'])
@guarded
def ensure_view(request,species_id):
    """Public first-visit preparation of a registered dataset, with no arbitrary job parameters."""
    scope=scope_for(request);ds=OmicsDataset.objects.get(species__species_id=species_id,omics_type='proteome')
    if request.data and set(request.data)-{'scope'}:raise ValueError('ensure_accepts_scope_only')
    if scope=='full' and (not ds.full_csv_path or not Path(ds.full_csv_path).is_file()):return ok({'readiness':'unavailable','reason_code':'full_not_registered'})
    if not getattr(settings,'PROTEOME_VIZ_ON_DEMAND',True):return ok({'readiness':'not_prepared','reason_code':'on_demand_disabled'})
    result=work_requests.enqueue(species_id,scope,'all',{})
    if result['readiness']=='ready':
        # A previously verified product was removed or is now stale; the source identity
        # in the request key prevents reuse across releases/implementations/file changes.
        pointer=store.published(species_id,scope,release_id())
        if pointer and store.path_for(pointer).is_dir() and not manifest_stale(store.read_json(store.path_for(pointer)/'manifest.json'),ds):return ok(result)
        result['readiness']='queued';store.write_json(work_requests.path_for(result['request_id']),result)
    if not work_requests.ensure_consumer():return ok({'readiness':'not_prepared','reason_code':'consumer_start_failed','request_id':result['request_id']})
    return ok(result,202 if result['readiness'] in ['queued','running'] else 200)

@api_view(['GET'])
@guarded
def request_view(request,species_id,request_id):return ok(work_requests.status(request_id,species_id))

@api_view(['GET'])
@guarded
def candidates_view(request,species_id):
    target,m=target_for(request,species_id);bundle=store.read_bundle(str(target));names=bundle['D15']['data']['modules'];name=request.GET.get('module','Resource')
    if name not in names:raise ValueError('unknown_candidate_module')
    metadata=store.read_metadata(str(target));arrays=store.read_arrays(str(target));scores=arrays['candidate_scores'][:,names.index(name)];ids=np.array(metadata['protein_id']);page=bounds(request,'page',1,1,1000000);size=bounds(request,'page_size',25,1,100);mode=request.GET.get('evidence','complete')
    component_n=None
    if mode=='partial':
        prefix='partial_'+name.replace(' ','_');indices=arrays.get(prefix+'_rows',np.array([],int));values=arrays.get(prefix+'_scores',np.array([],float));component_n=arrays.get(prefix+'_component_n',np.array([],int));order=np.lexsort((ids[indices],-np.where(np.isfinite(values),values,-np.inf)));indices=indices[order];values=values[order];component_n=component_n[order]
    elif mode=='complete':
        indices=np.flatnonzero(np.isfinite(scores));indices=indices[np.lexsort((ids[indices],-scores[indices]))];values=scores[indices]
    else:raise ValueError('invalid_candidate_evidence')
    start=(page-1)*size;rows=[]
    for j,i in enumerate(indices[start:start+size],start):rows.append({**{f:metadata[f][i] for f in metadata},'score':float(values[j]) if np.isfinite(values[j]) else None,'component_n':int(component_n[j]) if component_n is not None else len(bundle['D14']['data']['evidence'].get(name,{}).get('fields',[name])),'rank':j+1})
    return ok({'module':name,'evidence':mode,'total':len(indices),'n_source':m['n_source'],'page':page,'page_size':size,'artifact_version':m['artifact_version'],'source_hash':m['source_hash'],'rows':rows})

urlpatterns=[path(f'species/<str:species_id>/proteome/visualizations/{suffix}',view) for suffix,view in [('',manifest_view),('charts/<str:chart_id>/',chart_view),('fields/',fields_view),('pair/',pair_view),('cohort/',cohort_view),('structure/',structure_view),('members/',members_view),('candidates/',candidates_view),('export/',export_view),('prepare/',prepare_view),('ensure/',ensure_view),('requests/<str:request_id>/',request_view)]]
