from backend.apps.common.process_liveness import linux_process_has_exited,linux_pid_matches_record
import hashlib,json,os,time,uuid
from .artifacts import root,read_json,write_json
from . import METHOD_VERSION

def request_key(species_id,scope,chart_id,parameters):
    from .artifacts import implementation_hash
    from .source import release_id
    from backend.apps.stoichdb.models import OmicsDataset
    from backend.apps.common.host_paths import Path
    ds=OmicsDataset.objects.get(species__species_id=species_id,omics_type='proteome');signatures=[]
    for value in [ds.core_csv_path,ds.full_csv_path]:
        p=Path(value) if value else None;signatures.append([p.stat().st_size,p.stat().st_mtime_ns] if p and p.is_file() else None)
    return hashlib.sha256(json.dumps([species_id,ds.dataset_id,scope,chart_id,parameters,METHOD_VERSION,implementation_hash(),release_id(),ds.core_csv_path,ds.full_csv_path,signatures],sort_keys=True).encode()).hexdigest()
def path_for(key):
    if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('invalid_request_id')
    return root()/'work_requests'/(key+'.json')
def enqueue(species_id,scope,chart_id,parameters):
    key=request_key(species_id,scope,chart_id,parameters);p=path_for(key)
    if p.is_file():
        previous=read_json(p)
        if previous['readiness'] in ['queued','running','ready']:return previous
    payload={'request_id':key,'species_id':species_id,'scope':scope,'chart_id':chart_id,'parameters':parameters,'readiness':'queued','created':time.time(),'attempt_id':uuid.uuid4().hex}
    write_json(p,payload);return payload
def consumer_alive():
    p=root()/'consumer.json'
    if not p.is_file():return False
    state=read_json(p)
    try:return state.get('state')!='stopped' and process_alive(int(state['pid']),state.get('heartbeat',p.stat().st_mtime))
    except (OSError,KeyError,ValueError):return False
def process_alive(pid,recorded_at=None):
    if pid<=0:return False
    if recorded_at is not None and not linux_pid_matches_record(pid,recorded_at):return False
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];kernel.GetExitCodeProcess.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return ctypes.get_last_error()==5
        try:
            status=wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(status))) and status.value==259
        finally:kernel.CloseHandle(handle)
    if linux_process_has_exited(pid):return False
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True
def status(key,species_id):
    p=path_for(key)
    if not p.is_file():raise FileNotFoundError('unknown_request')
    value=read_json(p)
    if value['species_id']!=species_id:raise FileNotFoundError('unknown_request')
    if value['readiness']=='running' and not process_alive(int(value.get('worker_pid',0))):
        value['readiness']='interrupted';value['reason_code']='worker_interrupted';write_json(p,value)
    return value

def ensure_consumer():
    """Launch the real CLI consumer on demand; it exits after the queue is idle.

    This is a separate, observable process, never a request-thread computation.
    O_EXCL serializes launches across Django workers and the job claim serializes work.
    """
    from django.conf import settings
    from pathlib import Path
    import subprocess,sys
    if consumer_alive():return True
    if not getattr(settings,'PROTEOME_VIZ_ON_DEMAND',True):return False
    folder=root();folder.mkdir(parents=True,exist_ok=True);lock=folder/'consumer_launch.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        try:
            if time.time()-lock.stat().st_mtime>30:lock.unlink()
        except FileNotFoundError:pass
        return consumer_alive()
    try:
        os.close(fd)
        if consumer_alive():return True
        project=Path(settings.BASE_DIR);python=project/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        command=[str(python if python.is_file() else sys.executable),str(project/'manage.py'),'materialize_proteome_visuals','--consume-requests','--idle-exit-seconds','45','--poll-seconds','1','--output-dir',str(folder.resolve())]
        env=dict(os.environ);env.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']})
        with (folder/'consumer.log').open('ab') as log:
            process=subprocess.Popen(command,cwd=str(project),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,start_new_session=os.name!='nt')
        write_json(folder/'consumer.json',{'pid':process.pid,'heartbeat':time.time(),'state':'starting','idle_exit_seconds':45})
        return process_alive(process.pid)
    finally:lock.unlink(missing_ok=True)
