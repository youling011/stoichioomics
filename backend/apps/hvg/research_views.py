from pathlib import Path
import json,io,csv
from datetime import timedelta
from django.http import FileResponse
from django.utils import timezone
from rest_framework.decorators import api_view
from backend.apps.common.responses import ok,err
from backend.analysis_engine.hvg_research.artifacts import safe_path,atomic_json
from backend.analysis_engine.hvg_research.catalog import TABLES
from . import research_services as service
@api_view(['GET','POST'])
def research_endpoint(request,identifier,endpoint='summary',object_id=None):
 try:
  base=service.authorize(identifier,request.headers.get('X-Job-Token'));params=request.query_params.dict()
  if request.method=='POST':return _control(request,identifier,base,endpoint)
  if endpoint=='runs':
   rows=[]
   for p in (base/'hvg_functional_comparison/runs').glob('*/run_manifest.json'):
    m=json.loads(p.read_text(encoding='utf-8'));rows.append({k:m.get(k) for k in ['analysis_run_id','schema_version','created_at','completed_at','research_status','status','model_status','config_hash']})
   return ok({'rows':sorted(rows,key=lambda x:x['created_at'],reverse=True),'total':len(rows),'schema_version':'hvg_research_v1'})
  run,m=service.load_run(base,params.get('analysis_run_id'))
  if endpoint=='summary':return ok(service.summary(run,m,params))
  if endpoint=='original-comparison':
   from .unified_presentation import comparison_payload
   return ok(comparison_payload(run,m,params))
  if endpoint=='optional-model':
   if m.get('model_policy')=='removed':return ok({'analysis_run_id':m['analysis_run_id'],'model_status':'removed','reason':'Predictive model analysis is not part of this workflow.','summary':[],'model':[],'plots':[],'tables':{}})
   data={'analysis_run_id':m['analysis_run_id'],'context_id':'global','model_status':m.get('model_status'),'independent_branch':True}
   for kind,name in [('summary','hvg_summary.json'),('model','hvg_stoich_model.json'),('plots','plots_payload.json')]:
    p=run/'work/analysis_phase2'/name;data[kind]=[json.loads(p.read_text(encoding='utf-8'))] if p.exists() else []
   data['tables']={}
   for name in ['model_comparison','bootstrap_feature_stability','cv_predictions','negative_control_report']:
    p=run/'work/analysis_phase2'/(name+'.csv')
    if p.exists():
     import pandas as pd
     from backend.analysis_engine.hvg_research.artifacts import clean
     try:data['tables'][name]=clean(pd.read_csv(p).to_dict('records'))
     except pd.errors.EmptyDataError:data['tables'][name]=[]
   return ok(data)
  if endpoint=='contexts':return ok({'rows':[{k:v for k,v in c.items() if k!='directory'} for c in m.get('contexts',[])],'total':len(m.get('contexts',[])),'analysis_run_id':m['analysis_run_id'],'schema_version':m['schema_version']})
  if endpoint=='features' and object_id:return ok(service.feature_detail(run,m,object_id,params))
  if endpoint=='genes':return ok(service.gene_detail(run,m,object_id,params))
  if endpoint=='visuals':
   from .research_visuals import visuals
   return ok(visuals(run,m,object_id,params))
  if endpoint=='plots':return ok(service.plots(run,m,object_id,params))
  if endpoint=='phenomena':
   p=run/'reports/phenomena.json';rows=json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
   return ok({'rows':rows,'total':len(rows),'status':m['research_status'],'analysis_run_id':m['analysis_run_id']})
  if endpoint=='artifacts':return ok({'rows':[{k:v for k,v in a.items() if k!='path'}|{'name':Path(a['path']).name,'relative_path':a['path']} for a in m.get('artifacts',[])],'total':len(m.get('artifacts',[])),'analysis_run_id':m['analysis_run_id']})
  if endpoint=='download':
   row=next((a for a in m.get('artifacts',[]) if a['artifact_id']==object_id),None)
   if not row:raise FileNotFoundError('Unknown artifact for this run')
   p=safe_path(run,row['path'])
   if not p.is_file():raise FileNotFoundError('Artifact not available')
   return FileResponse(p.open('rb'),as_attachment=True,filename=p.name)
  if endpoint=='safe-export':
   frame=service.read_table(run,object_id,params)
   for col in frame.select_dtypes(include=['object','string']).columns:
    frame[col]=frame[col].map(lambda x:"'"+x if isinstance(x,str) and x.lstrip().startswith(('=','+','-','@','\t','\r')) else x)
   out=io.BytesIO(frame.to_csv(index=False).encode('utf-8-sig'));return FileResponse(out,as_attachment=True,filename=object_id+'_spreadsheet_safe.csv')
  mapping={'features':'features','core-audit':'core_audit','gene-sets':'sets','enrichment-comparison':'enrichment_comparison','within-pathways':'within_pathways','candidates':'candidates','stability':'replication'}
  if endpoint=='gene-sets' and object_id:
   params['set_id']=object_id;return ok({'definition':service.page_table(run,m,'sets',params),'members':service.page_table(run,m,'set_members',params)})
  if endpoint=='enrichment':
   kind=params.get('kind','baseline')
   if kind not in ['baseline','matched_baseline','subset','within_hvg','supplementary_ora']:raise ValueError('Invalid enrichment kind')
   return ok(service.page_table(run,m,kind,params))
  if endpoint=='feature-pathways':
   method=params.get('method','distribution');key={'distribution':'feature_pathways','gsea':'gsea','gsea_runs':'gsea_runs','interaction':'interactions','leading_edge':'leading_edge','ranked_genes':'ranked_genes'}.get(method)
   if not key:raise ValueError('Invalid pathway method')
   return ok(service.page_table(run,m,key,params))
  if endpoint=='table':return ok(service.page_table(run,m,object_id,params))
  if endpoint not in mapping:raise FileNotFoundError('Unknown research endpoint')
  return ok(service.page_table(run,m,mapping[endpoint],params))
 except PermissionError as e:return err(e,status=403)
 except FileNotFoundError as e:return err(e,status=404)
 except (ValueError,TypeError,KeyError) as e:return err(e,status=400)
 except RuntimeError as e:return err(e,status=409)
def _control(request,identifier,base,endpoint):
 from backend.apps.jobs.models import AnalysisJob
 from backend.apps.jobs.services import run_job_async
 from backend.analysis_engine.hvg_research.locking import run_lock
 job=AnalysisJob.objects.get(job_id=identifier)
 if endpoint=='retention':
  days=int(request.data.get('retain_days',30))
  if not 1<=days<=3650:raise ValueError('retain_days must be 1..3650')
  archived=request.data.get('archived',False)
  if type(archived) is not bool:raise ValueError('archived must be boolean')
  job.metadata_json={**(job.metadata_json or {}),'retain_until':(timezone.now()+timedelta(days=days)).isoformat(),'archived':archived};job.save(update_fields=['metadata_json','updated_at']);return ok({'retain_until':job.metadata_json['retain_until'],'archived':archived})
 if endpoint=='resume':
  import yaml
  rid=request.data.get('analysis_run_id');run,m=service.load_run(base,rid)
  if m['research_status']=='complete':raise ValueError('Completed run is immutable')
  with run_lock(base/'hvg_functional_comparison'):
   if job.status in ['RUNNING','CANCEL_REQUESTED']:
    from django.utils.dateparse import parse_datetime
    heartbeat=parse_datetime(m.get('heartbeat_at') or m['created_at'])
    if heartbeat and (timezone.now()-heartbeat).total_seconds()<120:raise RuntimeError('Execution still has a recent heartbeat')
   cfg=yaml.safe_load(Path(job.config_path).read_text(encoding='utf-8'));cfg.setdefault('hvg_research',{}).setdefault('execution',{})['resume_run_id']=rid
   Path(job.config_path).write_text(yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False),encoding='utf-8');job.status='READY';job.save(update_fields=['status','updated_at'])
  run_job_async(job);return ok({'started':True,'analysis_run_id':rid})
 raise ValueError('Unsupported research control action')
