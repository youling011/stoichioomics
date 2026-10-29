from backend.apps.common.request_cache import request_scope,once
from functools import wraps
from pathlib import Path
import pandas as pd
from django.conf import settings
from django.urls import path
from django.core.exceptions import ObjectDoesNotExist
from rest_framework.decorators import api_view,permission_classes
from rest_framework.permissions import IsAdminUser
from backend.apps.common.responses import ok,err
from . import artifacts as a,cohort_artifacts as cohorts,work_requests as jobs
from .contracts import FIGURES,COHORT_IDS,MODES
from .source import registry
from .members import page_frame,candidates,selection
from .exports import export
def guarded(fn):
    @wraps(fn)
    @request_scope
    def call(r,*args,**kwargs):
        try:
            if r.method=='POST' and not isinstance(r.data,dict):raise ValueError('JSON_object_required')
            return fn(r,*args,**kwargs)
        except (LookupError,ObjectDoesNotExist) as e:return err(str(e),404)
        except FileNotFoundError as e:return err(str(e),410 if str(e)=='artifact_expired' else 404)
        except (ValueError,TypeError) as e:return err(str(e),409 if any(k in str(e) for k in ['stale','mismatch','source_changed']) else 400)
        except BlockingIOError as e:return err(str(e),409)
    return call
def check_stale(sid,p):
    return once(('integration',sid,str(p)),lambda:a.stale(sid,p))

def target(r,sid):
    registry(sid);p=a.lookup(sid,r.GET.get('artifact_version',''),validator=lambda m,p:not check_stale(sid,p))
    m=a.read(p/'manifest.json')
    if check_stale(sid,p):
        if not r.GET.get('artifact_version'):raise ValueError('source_or_method_stale; refresh preparation')
        m={**m,'historical_artifact':True,'availability_note':'Saved historical version; current source or method differs. Not eligible for current-source reuse.'}
    return p,m
def cohort_key(r,sid):return r.GET.get('cohort_key') or cohorts.identity(cohorts.default_ids(sid))
def cohort_result(r,sid):
    key=cohort_key(r,sid);p=cohorts.path(key)
    if not p.is_file():raise FileNotFoundError('cohort_not_prepared')
    result=a.read(p)
    if result['cohort_key']!=key:raise ValueError('cohort_key_mismatch')
    if cohorts.identity(result['species_ids'])!=key:raise ValueError('cohort_source_stale')
    if r.GET.get('cohort_version') and r.GET['cohort_version']!=result['cohort_version']:raise ValueError('cohort_version_mismatch')
    return public_cohort(result)
def public_cohort(result):
    # Centering algebra bounds rank by n-1 even when cancellation leaves a tiny
    # nonzero singular value. Keep the original numerical diagnostic explicit.
    result={**result};result['numerical_rank_at_1e_12']=result['rank'];result['rank']=min(result['rank'],max(0,len(result['included_species'])-1));result['rank_definition']='effective rank bounded by centered cohort dimensions; numerical rank retained separately'
    return result
def decorate(result):
    result={**result};missing=result.get('n_missing',max(0,(result.get('n_source') or 0)-(result.get('n_valid') or 0)))
    result['validity_counts']={'n_source':result.get('n_source'),'n_valid':result.get('n_valid'),'n_missing':missing};result.setdefault('n_missing',missing);result.setdefault('member_lookup',None)
    if result.get('id')=='OV01' and result.get('status')=='available' and result.get('species_id') not in result['data'].get('included_species',[]):result.update(status='partial',reason='Current species is outside the included cohort. Only the actual cohort median and IQR are shown.')
    return result
def chart(r,sid,p,m,cid,complete=False):
    if cid not in FIGURES:raise LookupError('unknown_chart')
    if m.get('historical_artifact') and cid in COHORT_IDS:
        return decorate({'id':cid,'artifact_version':m['artifact_version'],'historical_artifact':True,'status':'unavailable','reason':'The saved species package does not bind a frozen cohort; current cohort values are not mixed into historical source results.','data':{}})
    if cid in COHORT_IDS:
        co=cohort_result(r,sid);contract=FIGURES[cid]
        return decorate({**{k:m[k] for k in ['species_id','artifact_version','method_version','source_hash','release_id','schema_version']},'id':cid,'title':contract['title'],'renderer_kind':contract['renderer_kind'],'status':co['status'],'population':'named real species, whole-Core descriptor medians','unit':'cohort standardized and layer weighted; original units in descriptors','parameters':contract['parameters'],'method':co['method'],'caveats':contract['interpretation'],'cohort_key':co['cohort_key'],'cohort_version':co['cohort_version'],'cohort_source_hash':co['source_hash'],'n_source':len(co['species_ids']),'n_valid':len(co['included_species']),'data':co})
    result=a.read(p/'charts'/(cid+'.json.gz'))
    if cid in ['OV02','OV03'] and not complete:
        data=result['data'];tracks=data.get('tracks',[]);color_limit=max([1.]+[abs(b['median']) for t in tracks for b in t.get('OV03',[]) if b['median'] is not None]);result={**result,'data':{**data,'tracks':tracks[:6],'tracks_total':len(tracks),'tracks_page':1,'tracks_page_size':6,'coordinate_color_limit':color_limit,'coordinates_endpoint':'coordinates/','display_policy':'paged coordinate tracks; full source population and stored bins unchanged'}}
    return decorate({**result,**{k:m[k] for k in ['historical_artifact','availability_note'] if k in m}})
@api_view(['GET'])
@guarded
def manifest_view(r,species_id):
    registry(species_id);enabled=getattr(settings,'INTEGRATION_VIZ_ENABLED',False)
    try:
        p=a.lookup(species_id,r.GET.get('artifact_version',''),validator=lambda m,p:not check_stale(species_id,p));m=a.read(p/'manifest.json');key=cohorts.identity(cohorts.default_ids(species_id));exists=cohorts.path(key).is_file();status='stale' if check_stale(species_id,p) else 'ready'
        co=a.read(cohorts.path(key)) if exists else None
        return ok({**m,'historical_artifact':status=='stale','implementation_compatibility':{'artifact_hash':m['implementation_hash'],'runtime_hash':a.implementation_hash(),'kind':'historical_unverified_for_current_reuse' if status=='stale' else 'identical' if m['implementation_hash']==a.implementation_hash() else 'explicit_rho_sorting_only_compatibility'},'status':status,'enabled':enabled,'default_cohort_key':key,'charts':[{**c,**({'status':'unavailable' if status=='stale' else co['status'] if co else 'queued','n_source':len(co['species_ids']) if co else None,'n_valid':len(co['included_species']) if co else None} if c['id'] in COHORT_IDS else {})} for c in m['charts']]})
    except FileNotFoundError:
        if r.GET.get('artifact_version'):raise
        return ok({'species_id':species_id,'status':'missing','enabled':enabled,'charts':[]})
@api_view(['POST'])
@guarded
def ensure_view(r,species_id):
    if r.data.get('policy','core_plus_optional_full')!='core_plus_optional_full':raise ValueError('invalid_policy')
    registry(species_id)
    try:
        p=a.lookup(species_id,validator=lambda m,p:not check_stale(species_id,p))
        if not check_stale(species_id,p):
            ids=cohorts.default_ids(species_id);key=cohorts.identity(ids)
            co=jobs.enqueue(species_id,'cohort',ids) if not cohorts.path(key).exists() else None
            return ok({'status':'ready','artifact_version':a.read(p/'manifest.json')['artifact_version'],'cohort_request':co,'default_cohort_key':key})
    except FileNotFoundError:pass
    return ok(jobs.enqueue(species_id),202)
@api_view(['GET'])
@guarded
def request_view(r,species_id,request_id):
    registry(species_id)
    if len(request_id)!=16 or any(c not in '0123456789abcdef' for c in request_id):raise ValueError('invalid_request_id')
    result=a.read(a.root()/'requests'/(request_id+'.json'))
    if result['species_id']!=species_id:raise LookupError('request_species_mismatch')
    if result['status']=='running' and not jobs.alive(result.get('pid',0)):result.update(status='interrupted',reason='worker_exited')
    if result['status']=='queued':jobs.start_consumer()
    return ok(result)
@api_view(['GET'])
@guarded
def chart_view(r,species_id,chart_id):
    p,m=target(r,species_id)
    try:return ok(chart(r,species_id,p,m,chart_id))
    except FileNotFoundError as e:
        if str(e)!='cohort_not_prepared':raise
        return ok({'id':chart_id,'status':'queued','artifact_version':m['artifact_version'],'cohort_key':cohort_key(r,species_id)},202)
def paginated(r,m,result):return ok({**result,'artifact_version':m['artifact_version'],**{k:m[k] for k in ['historical_artifact','availability_note'] if k in m}})
@api_view(['GET'])
@guarded
def fields_view(r,species_id):
    p,m=target(r,species_id);omics=r.GET.get('omics','genome')
    if omics not in MODES:raise ValueError('invalid_omics')
    rows=a.read(p/'fields'/(omics+'.json')) if (p/'fields'/(omics+'.json')).exists() else []
    if r.GET.get('family'):rows=[v for v in rows if v['family']==r.GET['family']]
    result=page_frame(pd.DataFrame(rows),r.GET,12)
    result['items']=[a.field_profile(p,omics,v['field']) for v in result['items']]
    return paginated(r,m,result)
@api_view(['GET'])
@guarded
def metadata_view(r,species_id):
    p,m=target(r,species_id);omics=r.GET.get('omics','genome')
    if omics not in MODES:raise ValueError('invalid_omics')
    rows=a.read(p/'metadata'/(omics+'.json')) if (p/'metadata'/(omics+'.json')).exists() else [];field=r.GET.get('field')
    if field:
        if field not in {v['field'] for v in rows}:raise ValueError('invalid_metadata_field')
        data=dict(a.metadata_profile(p,omics,field));result=page_frame(pd.DataFrame(data.pop('categories')),r.GET,12);result.update(data)
    else:result=page_frame(pd.DataFrame(rows),r.GET,12)
    return paginated(r,m,result)
@api_view(['GET'])
@guarded
def members_view(r,species_id):
    p,m=target(r,species_id);f,key=selection(p,r.GET);result=page_frame(f,r.GET)
    from .member_evidence import enrich
    result['items']=enrich(p,result['items'])
    return paginated(r,m,{**result,'selection_id':key})
@api_view(['GET'])
@guarded
def candidates_view(r,species_id):
    p,m=target(r,species_id);return paginated(r,m,candidates(p,r.GET))
@api_view(['GET'])
@guarded
def tables_view(r,species_id,table_id):
    allowed={'x0_mapping','x0_conflicts','x1_shifts','x2_gc','x3_members','x4_pairs','x6_edges','x7_features'}
    if table_id not in allowed:raise LookupError('unknown_table')
    p,m=target(r,species_id);f=pd.DataFrame(cohort_result(r,species_id)['feature_ranking']) if table_id=='x7_features' else a.table(p,table_id)
    result=page_frame(f,r.GET)
    if table_id in ['x2_gc','x3_members']:
        from .table_evidence import enrich
        result['items']=enrich(p,result['items'])
    return paginated(r,m,result)
@api_view(['GET'])
@guarded
def correlations_view(r,species_id):
    p,m=target(r,species_id);f=a.table(p,'x6_edges');pair=r.GET.get('layer_pair','CGT');pairs={'CGT':('genome','transcriptome'),'CGP':('genome','proteome'),'CTP':('transcriptome','proteome')}
    if pair not in pairs:raise ValueError('invalid_layer_pair')
    x,y=pairs[pair];f=f[f.feature_a.str.startswith(x+'__')&f.feature_b.str.startswith(y+'__')]
    if r.GET.get('min_pair_n'):f=f[f.pair_n>=int(r.GET['min_pair_n'])]
    if r.GET.get('fields'):
        keys=r.GET['fields'].split(',');f=f[f.feature_a.isin(keys)|f.feature_b.isin(keys)]
    return paginated(r,m,{**page_frame(f,r.GET),'layer_pair':pair})
@api_view(['GET'])
@guarded
def coordinates_view(r,species_id):
    p,m=target(r,species_id);cid=r.GET.get('chart_id','OV02')
    if cid not in ['OV02','OV03']:raise ValueError('invalid_coordinate_chart')
    data=chart(r,species_id,p,m,cid,complete=True)['data'];tracks=data.get('tracks',[])
    if r.GET.get('seqid'):tracks=[v for v in tracks if v['seqid']==r.GET['seqid']]
    if r.GET.get('search'):tracks=[v for v in tracks if r.GET['search'].lower() in v['seqid'].lower()]
    if r.GET.get('range'):
        bounds=r.GET['range'].split(',')
        if len(bounds)!=2:raise ValueError('range_requires_min_max')
        lo,hi=map(float,bounds)
        import math
        if not math.isfinite(lo) or not math.isfinite(hi) or lo<0 or hi<lo:raise ValueError('invalid_coordinate_range')
        tracks=[{**v,cid:[b for b in v[cid] if b['end']>=lo and b['start']<=hi]} for v in tracks]
    result=page_frame(pd.DataFrame(tracks),{k:v for k,v in r.GET.items() if k!='search'})
    return paginated(r,m,{**result,'n_source':data.get('n_source'),'n_unlocated':data.get('n_unlocated')})
@api_view(['GET','POST'])
@guarded
def cohort_view(r,species_id):
    registry(species_id)
    if r.method=='GET':return ok(cohort_result(r,species_id))
    ids=r.data.get('species_ids')
    if not isinstance(ids,list) or not 2<=len(ids)<=getattr(settings,'INTEGRATION_VIZ_COHORT_LIMIT',32) or len(set(ids))!=len(ids):raise ValueError('cohort_requires_2_to_32_unique_species')
    for sid in ids:registry(sid)
    key=cohorts.identity(ids)
    if cohorts.path(key).is_file():return ok(public_cohort(a.read(cohorts.path(key))))
    return ok(jobs.enqueue(species_id,'cohort',ids),202)
@api_view(['GET'])
@guarded
def export_view(r,species_id):
    p,m=target(r,species_id)
    def saved_cohort():
        if m.get('historical_artifact'):raise ValueError('historical_species_package_has_no_bound_frozen_cohort')
        return cohort_result(r,species_id)
    response=export(p,r.GET,lambda cid:chart(r,species_id,p,m,cid,complete=True),saved_cohort)
    if m.get('historical_artifact'):
        response['X-Historical-Artifact']='true';response['X-Artifact-Version']=m['artifact_version']
    return response
@api_view(['POST'])
@permission_classes([IsAdminUser])
@guarded
def prepare_view(r,species_id):return ok(jobs.enqueue(species_id,force=bool(r.data.get('force',False))),202)
prefix='species/<str:species_id>/integration/visualizations/'
urlpatterns=[path(prefix,manifest_view),path(prefix+'ensure/',ensure_view),path(prefix+'requests/<str:request_id>/',request_view),path(prefix+'charts/<str:chart_id>/',chart_view),path(prefix+'fields/',fields_view),path(prefix+'metadata/',metadata_view),path(prefix+'members/',members_view),path(prefix+'candidates/',candidates_view),path(prefix+'tables/<str:table_id>/',tables_view),path(prefix+'correlations/',correlations_view),path(prefix+'coordinates/',coordinates_view),path(prefix+'cohort/',cohort_view),path(prefix+'export/',export_view),path(prefix+'prepare/',prepare_view)]
