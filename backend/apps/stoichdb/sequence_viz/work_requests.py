from backend.apps.common.runtime_python import python_executable
from backend.apps.common.maintenance import guarded_submission
from backend.apps.stoichdb.feature_sources import io as feature_io
import os,time,json,hashlib,uuid,subprocess,sys,threading
from pathlib import Path
from django.conf import settings
from . import artifacts as store
from .source import release_id,signatures
from backend.apps.stoichdb.complete_core.datasource import CompleteCoreDataSource
from backend.apps.stoichdb.proteome_viz.work_requests import process_alive
def request_path(key):
    if len(key)!=64 or any(k not in '0123456789abcdef' for k in key):raise ValueError('invalid_request_id')
    return store.root()/'requests'/(key+'.json')
@guarded_submission
def enqueue(sid,m,scope):
    ds=CompleteCoreDataSource(sid,m);identity=[sid,m,scope,ds.dataset.dataset_id,release_id(),signatures(ds),store.implementation_hash_for(m,scope)];key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();p=request_path(key)
    if feature_io.source_available(p):
        old=status(key,sid,m)
        if old['readiness'] in ['queued','running','ready']:return old
    value={'request_id':key,'species_id':sid,'omics':m,'scope':scope,'readiness':'queued','created':time.time(),'attempt_id':uuid.uuid4().hex};store.write_json(p,value);return value
def status(key,sid,m):
    p=request_path(key)
    if not feature_io.source_available(p):raise FileNotFoundError('unknown_request')
    value=store.read_json(p)
    if value['species_id']!=sid or value['omics']!=m:raise FileNotFoundError('unknown_request')
    if value['readiness']=='running' and not process_alive(value.get('worker_pid',0)):value.update(readiness='interrupted',reason_code='worker_interrupted');store.write_json(p,value)
    return value
def ensure_consumer():
    if not getattr(settings,'SEQUENCE_VIZ_ON_DEMAND',True):return False
    folder=store.root();folder.mkdir(parents=True,exist_ok=True);state=folder/'consumer.json';lock=folder/'consumer_launch.lock'
    if feature_io.source_available(state):
        recorded=store.read_json(state)
        if recorded.get('state')!='stopped' and process_alive(recorded.get('pid',0),recorded.get('heartbeat',feature_io.source_metadata(state).mtime)):return True
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        if time.time()-feature_io.source_metadata(lock).mtime>30:lock.unlink(missing_ok=True)
        return False
    try:
        os.close(fd);project=Path(settings.BASE_DIR);python=project/'.venv/Scripts/python.exe';command=[python_executable(),str(project/'manage.py'),'materialize_sequence_visuals','--consume-requests','--publish','--resume','--idle-exit-seconds','45'];env=dict(os.environ);env.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']})
        with (folder/'consumer.log').open('ab') as log:p=subprocess.Popen(command,cwd=project,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,start_new_session=os.name!='nt')
        store.write_json(state,{'pid':p.pid,'state':'starting','heartbeat':time.time()});threading.Thread(target=p.wait,daemon=True,name='sequence-viz-worker-reaper').start();return True
    finally:lock.unlink(missing_ok=True)
def consume(once=False,idle_exit_seconds=45):
    from .execution import run_one
    folder=store.root();last=time.monotonic();state=folder/'consumer.json';lock=folder/'consumer.lock';folder.mkdir(parents=True,exist_ok=True)
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        if process_alive(store.read_json(lock).get('pid',0)):return
        lock.unlink();fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,json.dumps({'pid':os.getpid()}).encode());os.close(fd)
    try:
        while True:
            worked=False
            for p in sorted((folder/'requests').glob('*.json')):
                v=store.read_json(p);v=status(v['request_id'],v['species_id'],v['omics'])
                if v['readiness'] not in ['queued','interrupted']:continue
                if v.get('not_before',0)>time.time():continue
                v.update(readiness='running',worker_pid=os.getpid(),started=time.time());store.write_json(p,v);worked=True
                try:
                    r=run_one(v['species_id'],v['omics'],v['scope'],resume=True,publish=True);v.update(readiness='ready' if r['status']=='passed' else 'failed',result=r)
                except Exception as e:
                    if str(e)=='active_task_lock':v.update(readiness='queued',reason_code='another_producer_running',not_before=time.time()+3)
                    else:v.update(readiness='failed',error=str(e))
                store.write_json(p,v);last=time.monotonic()
            store.write_json(state,{'pid':os.getpid(),'state':'idle' if not worked else 'running','heartbeat':time.time()})
            if once or time.monotonic()-last>=idle_exit_seconds:break
            time.sleep(1)
    finally:lock.unlink(missing_ok=True);store.write_json(state,{'pid':0,'state':'stopped','heartbeat':time.time()})
