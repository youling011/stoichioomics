from functools import wraps
from pathlib import Path
import json,hashlib
import numpy as np
from django.conf import settings
from django.urls import path
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.decorators import api_view,permission_classes
from rest_framework.permissions import IsAdminUser
from backend.apps.common.responses import ok,err
from backend.apps.stoichdb.models import OmicsDataset
from backend.apps.stoichdb.complete_core.datasource import CompleteCoreDataSource
from . import artifacts as store,work_requests
from .source import release_id
from .contracts import FIGURES,META
from .exports import download
DISPLAY_TITLES=json.loads(Path(__file__).with_name('display_titles.json').read_text(encoding='utf8'))
def presentation(figure,manifest):
    result={**figure,'original_title':figure.get('title'),'title':DISPLAY_TITLES.get(figure['chart_id'],figure.get('title'))}
    if 'full' not in manifest['available_scopes']:result['source_capability_note']='No registered readable Full file. Available Core panels and complete original fields are retained; Full-dependent panels cannot be calculated.'
    if figure['chart_id']=='TS01' and any(x is None for row in figure['data'].get('rows',[]) for x in row.get('percentiles',[])):result.update(status='partial',reason_code='candidate_modules_incomplete; see per-module coverage')
    data=figure.get('data',{})
    if result.get('status')=='available':
        profiles=([data['profile']] if isinstance(data.get('profile'),dict) else data.get('profiles',[]))
        if profiles and any(p.get('n_valid',0)==0 for p in profiles):
            result.update(status='partial' if any(p.get('n_valid',0)>0 for p in profiles) else 'unavailable',reason_code='no_eligible_values_for_some_fields' if any(p.get('n_valid',0)>0 for p in profiles) else 'no_eligible_values')
        if isinstance(data.get('hex'),dict) and data['hex'].get('n')==0:result.update(status='unavailable',reason_code='no_jointly_eligible_pairs')
        if data.get('kind') in ['native_candidate_evidence','candidate_union_evidence'] and not data.get('rows'):result.update(status='unavailable',reason_code='no_eligible_candidate_scores')
    return result
def guarded(fn):
    @wraps(fn)
    def call(request,*args,**kwargs):
        try:return fn(request,*args,**kwargs)
        except ObjectDoesNotExist:return err('Unknown species or omics dataset',404)
        except FileNotFoundError as e:return err(str(e),410 if str(e)=='artifact_expired' else 404)
        except (ValueError,KeyError,TypeError) as e:return err(str(e),409 if any(x in str(e) for x in ['mismatch','stale']) else 400)
    return call
def scope(request):
    s=(request.data if request.method=='POST' else request.GET).get('scope','core')
    if s not in ['core','full']:raise ValueError('invalid_scope')
    return s
def bounds(r,k,d,lo,hi):
    v=int(r.GET.get(k,d))
    if not lo<=v<=hi:raise ValueError(k+'_outside_bounds')
    return v
def target(request,species_id,omics):
    OmicsDataset.objects.only('id').get(species__species_id=species_id,omics_type=omics);p=store.lookup(species_id,omics,scope(request),release_id(),request.GET.get('artifact_version',''));m=store.read_json(p/'manifest.json')
    if request.GET.get('source_hash') and request.GET['source_hash']!=m['source_hash']:raise ValueError('source_hash_mismatch')
    return p,m
def row(meta,v,i,key):
    return {**{k:a[i] for k,a in meta.items()},'entity_id':meta[key][i],'report_entity_key':meta[key][i],**{k:float(a[i]) if np.isfinite(a[i]) else None for k,a in v.items() if k in ['island_score','composition_score','dinuc_score','codon_score','resource_score','pattern_proxy_score','codon_distance','score_module_coverage','composition_coverage','resource_coverage']}}
@api_view(['GET'])
@guarded
def manifest_view(r,species_id,omics):
    ds=CompleteCoreDataSource(species_id,omics);s=scope(r);enabled=getattr(settings,'SEQUENCE_VIZ_'+omics.upper()+'_ENABLED',False);scopes=['core']+(['full'] if ds.full_path and ds.full_path.is_file() else [])
    if s not in scopes:return ok({'enabled':enabled,'readiness':'unavailable','reason_code':'full_not_registered' if not ds.dataset.full_csv_path else 'source_full_file_missing','available_scopes':scopes,'n_source':0,'fields':[]})
    try:
        p=store.lookup(species_id,omics,s,release_id());m=store.read_json(p/'manifest.json');stale=store.stale(m,ds);return ok({**m,'charts':[{**c,'original_title':c['title'],'title':DISPLAY_TITLES.get(c['chart_id'],c['title'])} for c in m['charts']],'enabled':enabled,'readiness':'stale' if stale else 'ready','available_scopes':scopes})
    except FileNotFoundError:return ok({'enabled':enabled,'readiness':'not_prepared','available_scopes':scopes,'n_source':0,'fields':[],'charts':[]})
@api_view(['GET'])
@guarded
def chart_view(r,species_id,omics,chart_id):
    if chart_id not in FIGURES or FIGURES[chart_id]['omics']!=omics:raise ValueError('invalid_chart_id_for_omics')
    p,m=target(r,species_id,omics);figure=store.bundle(str(p))[chart_id]
    if figure['data'].get('cohort_ref'):
        from .cohorts import compute
        cohort=compute(species_id,omics,scope(r),dinuc=chart_id=='GD06');figure={**figure,'data':{'kind':FIGURES[chart_id]['proposed_kind'],'cohort':cohort},'status':cohort['pca']['status'] if chart_id in ['GD06','GD21','TD14'] else 'available' if len(cohort['species'])>=2 else 'unavailable','coverage':{'n_source':len(cohort['species']),'sampling_policy':'none'}}
    return ok({'readiness':'ready','result':store.clean(presentation(figure,m))})
@api_view(['GET'])
@guarded
def fields_view(r,species_id,omics):
    p,m=target(r,species_id,omics);ps=store.profiles(str(p));keys=list(ps);search=r.GET.get('q','').lower();keys=[k for k in keys if search in k.lower()];page=bounds(r,'page',1,1,100000);size=bounds(r,'page_size',6,1,12);chosen=keys[(page-1)*size:page*size]
    return ok({'profiles':[ps[k] for k in chosen],'total':len(keys),'page':page,'page_size':size,'catalog':m['catalog'],'metadata_coverage':m['metadata_coverage'],'artifact_version':m['artifact_version']})
def variant(r,p,m):
    from .builders import pair
    v=store.matrix(str(p));x=r.GET.get('x','');y=r.GET.get('y','');allowed={r['key'] for r in m['catalog'] if r['role']=='numeric'}|set(v)
    if x not in allowed or y not in allowed or x not in v or y not in v:raise ValueError('invalid_pair_field')
    params={'x':x,'y':y,'transform_x':r.GET.get('transform_x','identity'),'transform_y':r.GET.get('transform_y','identity'),'gridsize':bounds(r,'gridsize',40,10,80),'groups':bounds(r,'groups',10,1,20)};key=hashlib.sha256(json.dumps([m['artifact_version'],params],sort_keys=True).encode()).hexdigest();folder=p/'variants';folder.mkdir(exist_ok=True);jp=store.variant_path(p,key,'.json.gz');ap=store.variant_path(p,key,'.npy')
    if jp.is_file() and ap.is_file():
        data=store.read_json(jp)
        if data.get('_variant_id')!=key:raise ValueError('variant_identity_mismatch')
        return data,np.load(ap,allow_pickle=False),key
    with store._lock:
        d,mem=pair(v,x,y,m['n_source'],m['omics'],params['transform_x'],params['transform_y'],params['gridsize'],params['groups']);tmp=ap.with_suffix('.tmp')
        with tmp.open('wb') as f:np.save(f,mem,allow_pickle=False)
        import os
        d['_variant_id']=key;os.replace(tmp,ap);store.write_json(jp,d)
    return d,mem,key
@api_view(['GET'])
@guarded
def pair_view(r,species_id,omics):
    p,m=target(r,species_id,omics);d,mem,key=variant(r,p,m);return ok({'result':{**{k:m[k] for k in ['species_id','omics','dataset_id','release_id','source_hash','artifact_version','method_version','primary_scope']},'chart_id':'PAIR','variant_id':key,'status':'available' if d['n_pair'] else 'unavailable','coverage':{'n_source':m['n_source'],'n_pair':d['n_pair'],'sampling_policy':'none'},'method':{'name':'complete pair'},'data':d}})
def member_indices(r,p,m):
    cid=r.GET.get('chart_id','');variant_id=r.GET.get('variant_id','')
    if variant_id:
        if len(variant_id)!=64 or any(c not in '0123456789abcdef' for c in variant_id):raise ValueError('invalid_variant_id')
        f=store.variant_path(p,variant_id,'.npy')
        if not f.is_file():raise ValueError('variant_not_available')
        a=np.load(f,allow_pickle=False);d=store.read_json(store.variant_path(p,variant_id,'.json.gz'))
        if d.get('_variant_id')!=variant_id:raise ValueError('variant_identity_mismatch')
    else:
        if cid not in FIGURES or FIGURES[cid]['omics']!=m['omics']:raise ValueError('invalid_chart_id')
        a=store.arrays(str(p)).get(cid+'_membership');d=store.bundle(str(p))[cid]['data']
        if a is None:raise ValueError('members_not_available')
    raw=r.GET.get('bin_id','');bins=d.get('hex',{}).get('bins',[]);found=next((b['index'] for b in bins if b['bin_id']==raw),None) if bins else int(raw)
    if found is None:raise ValueError('unknown_bin_id')
    return np.flatnonzero(a==found)
@api_view(['GET'])
@guarded
def members_view(r,species_id,omics):
    p,m=target(r,species_id,omics);ix=member_indices(r,p,m);page=bounds(r,'page',1,1,1000000);size=bounds(r,'page_size',50,1,200);meta=store.metadata(str(p));v=store.matrix(str(p));return ok({'total':len(ix),'page':page,'rows':[row(meta,v,int(i),m['identity_field']) for i in ix[(page-1)*size:page*size]],'artifact_version':m['artifact_version']})
@api_view(['GET'])
@guarded
def candidates_view(r,species_id,omics):
    from .candidates import rank,module_score
    p,m=target(r,species_id,omics);v=store.matrix(str(p));meta=store.metadata(str(p));order,ranks,details=rank(v,meta[m['identity_field']],omics,r.GET.get('module',''),r.GET.get('coverage','all'),r.GET.get('top_ties',0));module=details['module'];a=module_score(v,module)
    page=bounds(r,'page',1,1,1000000);size=bounds(r,'page_size',25,1,200);rows=[]
    for i in order[(page-1)*size:page*size]:z=row(meta,v,int(i),m['identity_field']);z.update(rank=int(ranks[i]),score=float(a[i]) if np.isfinite(a[i]) else None);rows.append(z)
    return ok({'total':len(order),'rows':rows,'page':page,**details})
@api_view(['GET'])
@guarded
def coordinates_view(r,species_id,omics):
    if omics!='genome':raise ValueError('coordinates_require_genome')
    p,m=target(r,species_id,omics);cid=r.GET.get('chart_id','GD15')
    if cid not in ['GD02','GD15']:raise ValueError('invalid_coordinate_chart')
    d=store.bundle(str(p))[cid]['data'];catalog=[{k:t[k] for k in ['seqid','n','min','max','excluded_increment_n','status']} for t in d['tracks']];name=r.GET.get('seqid') or (catalog[0]['seqid'] if catalog else '');track=next((t for t in d['tracks'] if t['seqid']==name),None)
    if track is None:raise ValueError('unknown_seqid')
    if r.GET.get('resolution','overview')=='overview':return ok({'catalog':catalog,'track':track,'unplaced_n':d['unplaced_n']})
    v=store.matrix(str(p));meta=store.metadata(str(p));start=float(r.GET.get('start',track['min']));end=float(r.GET.get('end',track['max']))
    if not np.isfinite([start,end]).all() or end<start:raise ValueError('invalid_coordinate_window')
    ix=np.flatnonzero((np.array(meta['seqid'])==name)&(v['start_1']>=start)&(v['start_1']<=end)&np.isfinite(v['end_1'])&(v['end_1']>=v['start_1']));ix=ix[np.lexsort((np.array(meta['gene_id'])[ix],v['start_1'][ix]))];page=bounds(r,'page',1,1,1000000);size=bounds(r,'page_size',100,1,200);extra=store.arrays(str(p)).get('locus_gc_cumulative_count',np.full(m['n_source'],np.nan));rows=[]
    for i in ix[(page-1)*size:page*size]:z=row(meta,v,int(i),'gene_id');z.update(start=float(v['start_1'][i]),end=float(v['end_1'][i]),value=(float(extra[i]) if np.isfinite(extra[i]) else None) if cid=='GD02' else float(v['island_score'][i]) if np.isfinite(v['island_score'][i]) else None);rows.append(z)
    return ok({'catalog':catalog,'rows':rows,'total':len(ix),'page':page,'start':start,'end':end,'seqid':name})
@api_view(['GET'])
@guarded
def cohort_view(r,species_id,omics):
    from .cohorts import compute
    target(r,species_id,omics);selected=r.GET.get('species');selected=list(dict.fromkeys(x for x in selected.split(',') if x)) if selected is not None else None
    if selected:
        known=set(OmicsDataset.objects.filter(omics_type=omics,species__species_id__in=selected).values_list('species__species_id',flat=True))
        if set(selected)!=known:raise ValueError('unregistered_cohort_species')
    return ok(store.clean(compute(species_id,omics,scope(r),selected)))
@api_view(['GET'])
@guarded
def export_view(r,species_id,omics):
    p,m=target(r,species_id,omics);kind=r.GET.get('kind','complete_rows')
    if kind=='cohort':
        from .cohorts import compute
        from django.http import JsonResponse
        selected=list(dict.fromkeys(x for x in r.GET['species'].split(',') if x)) if 'species' in r.GET else None
        data=compute(species_id,omics,scope(r),selected);return JsonResponse(store.clean(data),json_dumps_params={'allow_nan':False})
    cid=r.GET.get('chart_id','')
    if kind=='chart' and cid in store.bundle(str(p)) and store.bundle(str(p))[cid]['data'].get('cohort_ref'):
        from .cohorts import compute
        from django.http import JsonResponse
        cohort=compute(species_id,omics,scope(r),list(dict.fromkeys(x for x in r.GET['species'].split(',') if x)) if 'species' in r.GET else None,dinuc=cid=='GD06');figure=store.bundle(str(p))[cid];figure={**figure,'data':{'kind':figure['design_kind'],'cohort':cohort},'coverage':{'n_source':len(cohort['species']),'sampling_policy':'none'},'status':cohort['pca']['status'] if cid in ['GD06','GD21','TD14'] else 'available' if len(cohort['species'])>=2 else 'unavailable'};return JsonResponse(store.clean(presentation(figure,m)),json_dumps_params={'allow_nan':False})
    response=download(r,p,m,kind,r.GET.get('chart_id',''),member_indices(r,p,m) if kind=='members' else None)
    if kind=='chart':
        from django.http import JsonResponse
        return JsonResponse(presentation(json.loads(response.content),m),json_dumps_params={'ensure_ascii':False,'allow_nan':False})
    return response
@api_view(['POST'])
@guarded
def ensure_view(r,species_id,omics):
    if set(r.data)-{'scope'}:raise ValueError('ensure_accepts_scope_only')
    ds=CompleteCoreDataSource(species_id,omics);s=scope(r)
    if s=='full' and not (ds.full_path and ds.full_path.is_file()):return ok({'readiness':'unavailable','reason_code':'full_not_registered'})
    try:
        p=store.lookup(species_id,omics,s,release_id());m=store.read_json(p/'manifest.json')
        if not store.stale(m,ds):return ok({'readiness':'ready','artifact_version':m['artifact_version']})
    except FileNotFoundError:pass
    v=work_requests.enqueue(species_id,omics,s);launched=work_requests.ensure_consumer();return ok({**v,'consumer_available':launched})
@api_view(['GET'])
@guarded
def request_view(r,species_id,omics,request_id):return ok(work_requests.status(request_id,species_id,omics))
@api_view(['POST'])
@permission_classes([IsAdminUser])
@guarded
def prepare_view(r,species_id,omics):
    if set(r.data)-{'scope'}:raise ValueError('prepare_accepts_scope_only')
    v=work_requests.enqueue(species_id,omics,scope(r));work_requests.ensure_consumer();return ok(v)
urlpatterns=[]
for mode in ['genome','transcriptome']:
    prefix=f'species/<str:species_id>/{mode}/visualizations/'
    for suffix,view in [('',manifest_view),('charts/<str:chart_id>/',chart_view),('fields/',fields_view),('pair/',pair_view),('members/',members_view),('coordinates/',coordinates_view),('cohort/',cohort_view),('candidates/',candidates_view),('export/',export_view),('ensure/',ensure_view),('requests/<str:request_id>/',request_view),('prepare/',prepare_view)]:urlpatterns.append(path(prefix+suffix,view,{'omics':mode}))
