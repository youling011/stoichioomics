"""Bounded, protocol-aware task inspection; never changes task state."""
import json,socket
from pathlib import Path
from django.conf import settings
from django.db import transaction,connection
from backend.apps.common.maintenance import state_root
from backend.apps.common.task_execution import root as executor_root,alive

def inventory(include_requests=False):
 from backend.apps.jobs.models import AnalysisJob
 from backend.apps.stoichdb.compare_core.models import CompareRun
 from backend.apps.stoichdb.compare_core.contracts import ACTIVE
 active=[];errors=[];examined=0
 with transaction.atomic():
  if connection.vendor=='postgresql':
   with connection.cursor() as c:c.execute('SET TRANSACTION READ ONLY')
  active.extend({'module':'analysis_job','task_id':v['job_id'],'status':v['status']} for v in AnalysisJob.objects.filter(status__in=['UPLOADING','RUNNING','CANCEL_REQUESTED']).values('job_id','status'))
  active.extend({'module':'compare','task_id':str(v['run_id']),'status':v['status']} for v in CompareRun.objects.filter(status__in=ACTIVE).values('run_id','status'))
 roots=[('proteome',Path(settings.PROTEOME_VIZ_ROOT),'work_requests/*.json'),('sequence_viz',Path(settings.SEQUENCE_VIZ_ROOT),'requests/*.json'),('integration',Path(settings.INTEGRATION_VIZ_ROOT),'requests/*.json'),('feature_export',Path(getattr(settings,'STOICH_FEATURE_EXPORT_ROOT',settings.BASE_DIR/'runtime/feature_exports')),'*/status.json'),('sequence_job',Path(settings.SEQUENCE_ANALYSIS_WORKSPACE_ROOT),'seq_*/job.json'),('sequence_legacy',Path(settings.SEQUENCE_ANALYSIS_LEGACY_WORKSPACE_ROOT),'seq_*/job.json'),('executor',executor_root(),'requests/*.json')]
 roots.append(('heavy_compute',state_root(),'heavy-compute.json'))
 seen=set()
 for module,root,pattern in roots:
  for p in root.glob(pattern):
   if str(p.resolve()) in seen:continue
   seen.add(str(p.resolve()));examined+=1
   try:
    row=json.loads(p.read_text(encoding='utf8'))
    if not isinstance(row,dict):raise ValueError('Task metadata must be an object')
    status=str(row.get('readiness',row.get('status',''))).lower()
    if status in ['running','queued','pending','started','uploading','cancel_requested']:
     active.append({'module':module,'task_id':row.get('request_id',row.get('job_id',row.get('export_id',p.stem))),'status':status,'path':str(p),'executor_alive':alive(row) if module=='executor' and status=='running' else None})
   except (OSError,ValueError,TypeError) as e:errors.append({'module':module,'path':str(p),'error':str(e)})
 request_count=None
 if include_requests:
  path=getattr(settings,'UWSGI_STATS_SOCKET',None)
  if path:
   try:
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
     s.settimeout(3);s.connect(str(path));blocks=[]
     while True:
      b=s.recv(65536)
      if not b:break
      blocks.append(b)
      if sum(map(len,blocks))>4*1024**2:raise ValueError('Unexpected stats size')
    stats=json.loads(b''.join(blocks));request_count=sum(int(c.get('in_request',0)) for w in stats.get('workers',[]) for c in w.get('cores',[]))
    if request_count:active.append({'module':'http','status':'running','request_count':request_count})
   except (OSError,ValueError) as e:errors.append({'module':'uwsgi_stats','error':str(e)})
 return {'format':'platform-task-inventory-v1','active':active,'errors':errors,'metadata_files_examined':examined,'request_count':request_count,'safe_to_stop':not active and not errors}
