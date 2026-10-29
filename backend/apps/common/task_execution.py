from backend.apps.common.runtime_python import python_executable
"""Durable, bounded subprocess execution of existing scientific entry points."""
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib,json,os,sys,subprocess,time,uuid,threading,socket
from django.conf import settings
from django.db import close_old_connections
from .artifact_locations import file_lock,contained
from .atomic_json import atomic_write_json,read_json
from .maintenance import state_root,state,submission,accepts_record
from .process_liveness import linux_process_has_exited,linux_pid_matches_record
_slot_depth=ContextVar('heavy_slot_depth',default=0)
KINDS={'analysis_job','sequence','feature_export'}

def root():return state_root()/'runtime/task_execution'
def request_path(key):
 if len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('invalid_executor_request')
 return contained(root(),'requests/'+key+'.json')
def index_path(kind,task_id):
 if kind not in KINDS:raise ValueError('invalid_executor_kind')
 key=hashlib.sha256((kind+'\0'+task_id).encode()).hexdigest();return root()/'index'/(key+'.json')
def alive(record):
 pid=int(record.get('pid') or 0)
 if pid<=0 or record.get('host')!=socket.gethostname():return False
 if linux_process_has_exited(pid) or not linux_pid_matches_record(pid,record.get('started_at',0)):return False
 if os.name=='nt':
  import ctypes
  from ctypes import wintypes
  k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE;k.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];k.CloseHandle.argtypes=[wintypes.HANDLE]
  handle=k.OpenProcess(0x1000,False,pid)
  if not handle:return False
  try:
   code=wintypes.DWORD();return bool(k.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
  finally:k.CloseHandle(handle)
 try:os.kill(pid,0);return True
 except (OSError,ValueError):return False
def find(kind,task_id):
 p=index_path(kind,task_id)
 return read_json(request_path(read_json(p)['request_id'])) if p.is_file() else None

def enqueue(kind,task_id,payload):
 with submission() as fence:
  index=index_path(kind,task_id)
  with file_lock(root()/'queue.lock'):
   existing=find(kind,task_id)
   if existing and existing['status'] in ['queued','running']:
    if existing['status']=='running' and not alive(existing):raise RuntimeError('executor_interrupted; reconcile or explicitly resume before submitting')
    return existing
   rid=uuid.uuid4().hex;value={'format':'platform-task-executor-v1','owner':rid,'host':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip() if sys.platform.startswith('linux') else 'windows','request_id':rid,'kind':kind,'task_id':task_id,'payload':payload,'payload_sha256':hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),'status':'queued','generation':fence['generation'],'created_at':time.time(),'updated_at':time.time(),'attempt':int(existing.get('attempt',0))+1 if existing else 1,'previous_request':existing['request_id'] if existing else None}
   atomic_write_json(request_path(rid),value);atomic_write_json(index,{'request_id':rid})
  try:dispatch()
  except Exception as exc:
   value.update(status='failed',error='executor_start_failed: '+str(exc));atomic_write_json(request_path(rid),value);raise
  return value

def dispatch():
 if not getattr(settings,'TASK_EXECUTION_AUTOSTART',True):return None
 root().mkdir(parents=True,exist_ok=True)
 with file_lock(root()/'consumer_start.lock'):
  marker=root()/'consumer.json';old=read_json(marker) if marker.is_file() else {}
  if alive(old):return old.get('pid')
  env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
  command=[python_executable(),'-B',str(settings.BASE_DIR/'manage.py'),'run_task_executor','--drain']
  log=root()/'executor.log'
  with log.open('ab') as handle:
   options={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
   p=subprocess.Popen(command,cwd=str(settings.BASE_DIR),env=env,stdin=subprocess.DEVNULL,stdout=handle,stderr=handle,**options)
  atomic_write_json(marker,{'pid':p.pid,'host':socket.gethostname(),'started_at':time.time(),'status':'starting'})
  threading.Thread(target=p.wait,daemon=True,name='task-executor-reaper').start();return p.pid

@contextmanager
def heavy_compute_slot():
 if _slot_depth.get():yield;return
 with file_lock(state_root()/'heavy-compute.lock',timeout=86400):
  budget_record={'format':'heavy-compute-owner-v1','pid':os.getpid(),'host':socket.gethostname(),'started_at':time.time(),'status':'running'}
  atomic_write_json(state_root()/'heavy-compute.json',budget_record)
  token=_slot_depth.set(1)
  try:yield
  finally:
   _slot_depth.reset(token);atomic_write_json(state_root()/'heavy-compute.json',{**budget_record,'status':'completed','finished_at':time.time()})

def heavy_guarded(fn):
 from functools import wraps
 @wraps(fn)
 def call(*args,**kwargs):
  with heavy_compute_slot():return fn(*args,**kwargs)
 return call

def _invoke(record):
 kind=record['kind'];task=record['task_id'];p=record['payload']
 if kind=='analysis_job':
  from backend.apps.jobs.services import _run_job_sync
  return _run_job_sync(task)
 if kind=='sequence':
  from backend.apps.sequence_analysis.services import _run_sequence_job
  return _run_sequence_job(task,[Path(v) for v in p['input_files']],[Path(v) for v in p['annotation_files']],Path(p['sample_sheet_path']) if p['sample_sheet_path'] else None,Path(p['output_dir']),p['params'])
 if kind=='feature_export':
  from backend.apps.stoichdb.feature_hub.export import _run_export_job
  return _run_export_job(p)
 raise ValueError('invalid_executor_kind')

def execute(request_id):
 path=request_path(request_id)
 with file_lock(root()/'claims'/(request_id+'.lock'),timeout=1):
  record=read_json(path)
  if record['status'] not in ['queued']:return record
  if not accepts_record(record):raise RuntimeError('request_generation_not_admitted')
  if hashlib.sha256(json.dumps(record['payload'],sort_keys=True).encode()).hexdigest()!=record['payload_sha256']:raise ValueError('executor_payload_mismatch')
  # Hold the heavy slot before marking the scientific operation running.
  with heavy_compute_slot():
   record.update(status='running',pid=os.getpid(),host=socket.gethostname(),started_at=time.time(),updated_at=time.time());atomic_write_json(path,record)
   stop=threading.Event()
   def heartbeat():
    while not stop.wait(5):
     current=read_json(path);current['heartbeat']=time.time();current['updated_at']=time.time();atomic_write_json(path,current)
   ticker=threading.Thread(target=heartbeat,daemon=True);ticker.start();close_old_connections()
   try:
    _invoke(record)
    # Existing scientific entry points may persist their own terminal failure.
    final=_scientific_status(record);record.update(status='completed' if final in ['SUCCEEDED','completed'] else 'cancelled' if final in ['CANCELLED','cancelled'] else 'failed',scientific_status=final,error=None if final in ['SUCCEEDED','completed','CANCELLED','cancelled'] else 'Scientific task did not complete successfully')
   except BaseException as exc:
    record.update(status='failed',error=type(exc).__name__+': '+str(exc));_mark_interrupted(record,str(exc),failure=True)
   finally:
    stop.set();ticker.join(timeout=10);close_old_connections();record.update(finished_at=time.time(),updated_at=time.time());atomic_write_json(path,record)
  return record

def _scientific_status(record):
 if record['kind']=='analysis_job':
  from backend.apps.jobs.models import AnalysisJob
  return AnalysisJob.objects.get(job_id=record['task_id']).status
 if record['kind']=='sequence':
  from backend.apps.sequence_analysis.services import _job_meta_path
  return read_json(_job_meta_path(record['task_id']))['status']
 from backend.apps.stoichdb.feature_hub.export import export_status
 return export_status(record['task_id'])['status']

def _mark_interrupted(record,reason,failure=False):
 if record['kind']=='analysis_job':
  from backend.apps.jobs.models import AnalysisJob
  job=AnalysisJob.objects.get(job_id=record['task_id'])
  if job.status in ['RUNNING','CANCEL_REQUESTED']:
   job.status='FAILED';job.error_message=reason;job.metadata_json={**job.metadata_json,'executor_state':'failed' if failure else 'interrupted'};job.save(update_fields=['status','error_message','metadata_json','updated_at'])
 elif record['kind']=='sequence':
  from backend.apps.sequence_analysis.services import _job_meta_path
  p=_job_meta_path(record['task_id']);value=read_json(p)
  if value['status'] in ['RUNNING','QUEUED','CREATED']:value.update(status='FAILED',error=reason,executor_state='interrupted');atomic_write_json(p,value)
 else:
  from backend.apps.stoichdb.feature_hub.export import _set_status
  _set_status(record['task_id'],{'status':'failed','error':reason,'executor_state':'interrupted'})

def reconcile(apply=False):
 rows=[]
 budget=state_root()/'heavy-compute.json'
 if budget.is_file():
  record=read_json(budget)
  if record.get('status')=='running' and not alive(record):
   rows.append({'kind':'heavy_compute','status':'interrupted','pid':record.get('pid')})
   if apply:atomic_write_json(budget,{**record,'status':'interrupted','updated_at':time.time()})
 for path in sorted((root()/'requests').glob('*.json')):
  record=read_json(path)
  if record['status']=='running' and not alive(record):
   rows.append({'request_id':record['request_id'],'kind':record['kind'],'task_id':record['task_id'],'status':'interrupted'})
   if apply:
    try:scientific=_scientific_status(record)
    except (OSError,ValueError,KeyError):scientific=None
    if scientific in ['SUCCEEDED','completed','CANCELLED','cancelled']:
     record.update(status='completed' if scientific in ['SUCCEEDED','completed'] else 'cancelled',scientific_status=scientific,updated_at=time.time(),error=None);atomic_write_json(path,record)
    else:
     record.update(status='interrupted',updated_at=time.time(),error='Executor exited before terminal publication');atomic_write_json(path,record);_mark_interrupted(record,record['error'])
 return rows

def resume(kind,task_id):
 with submission():
  record=find(kind,task_id)
  if not record or record['status'] not in ['failed','interrupted']:raise ValueError('Only a failed or interrupted executor attempt can be explicitly resumed')
  # New immutable request/attempt; prior output and scientific failure stay recorded.
  return enqueue(kind,task_id,record['payload'])

def drain():
 try:
  with file_lock(root()/'consumer.lock',timeout=.1):
   try:
    while True:
     pending=[read_json(p) for p in sorted((root()/'requests').glob('*.json'))]
     pending=[r for r in pending if r['status']=='queued' and accepts_record(r)]
     if pending:
      for record in pending:execute(record['request_id'])
      continue
     with file_lock(root()/'consumer_start.lock'):
      if any(read_json(p).get('status')=='queued' and accepts_record(read_json(p)) for p in (root()/'requests').glob('*.json')):continue
      atomic_write_json(root()/'consumer.json',{'pid':0,'status':'stopped','finished_at':time.time(),'host':socket.gethostname()})
      return
   except BaseException:
    with file_lock(root()/'consumer_start.lock'):
     atomic_write_json(root()/'consumer.json',{'pid':0,'status':'failed','finished_at':time.time(),'host':socket.gethostname()})
    raise
 except TimeoutError:return
