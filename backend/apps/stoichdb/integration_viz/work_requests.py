from backend.apps.common.process_liveness import linux_process_has_exited,linux_pid_matches_record
import os,time,uuid,subprocess,sys,ctypes
from pathlib import Path
from contextlib import contextmanager
from django.conf import settings
from . import artifacts as a
def alive(pid,recorded_at=None):
    if int(pid)<=0:return False
    if recorded_at is not None and not linux_pid_matches_record(pid,recorded_at):return False
    if os.name=='nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)];kernel.GetExitCodeProcess.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        h=kernel.OpenProcess(0x1000,False,int(pid))
        if not h:return False
        try:
            code=wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(h,ctypes.byref(code))) and code.value==259
        finally:kernel.CloseHandle(h)
    if linux_process_has_exited(pid):return False
    try:os.kill(int(pid),0);return True
    except OSError:return False
def unlink_retry(p):
    for i in range(100):
        try:p.unlink(missing_ok=True);return
        except PermissionError:
            if i==99:raise
            time.sleep(.01)
@contextmanager
def file_lock(name):
    p=a.root()/'locks'/(name+'.json');p.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(2):
        try:
            fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd);break
        except FileExistsError:
            try:pid=int(p.read_text())
            except FileNotFoundError:continue
            except (ValueError,OSError):raise BlockingIOError('integration_lock_initializing')
            if pid>0 and alive(pid):raise BlockingIOError('integration_worker_active')
            unlink_retry(p)
    else:raise BlockingIOError('integration_lock_busy')
    try:yield
    finally:unlink_retry(p)
@contextmanager
def kernel_guard(name):
    # Named kernel mutexes serialize threads AND processes on Windows. The PID
    # file remains readable by prior producers; kernel ownership dies with its
    # process. No lock handle survives this context, including error paths.
    if os.name=='nt':
        from ctypes import wintypes
        k=ctypes.WinDLL('kernel32');k.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR];k.CreateMutexW.restype=wintypes.HANDLE;k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];k.WaitForSingleObject.restype=wintypes.DWORD;k.ReleaseMutex.argtypes=[wintypes.HANDLE];k.CloseHandle.argtypes=[wintypes.HANDLE]
        h=k.CreateMutexW(None,False,'Local\\StoichIntegration_'+a.component(str(a.root().resolve())+'|'+name))
        if not h:raise OSError('integration_mutex_creation_failed')
        held=False
        try:
            if k.WaitForSingleObject(h,0) not in [0,0x80]:raise BlockingIOError('integration_mutex_busy')
            held=True;yield
        finally:
            if held:k.ReleaseMutex(h)
            k.CloseHandle(h)
    else:
        import fcntl
        p=a.root()/'locks'/(name+'.guard');p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('a+b') as f:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:raise BlockingIOError('integration_mutex_busy')
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)
@contextmanager
def lock(name):
    with kernel_guard(name):
        with file_lock(name):yield
def enqueue(sid,kind='species',ids=None,start=True,force=False):
    from .source import signatures
    from .cohort_artifacts import identity
    key=identity(ids) if kind=='cohort' else a.component([signatures(sid),a.implementation_hash()]);rid=a.component([kind,key]);p=a.root()/'requests'/(rid+'.json')
    with waiting_lock('enqueue'):
        if p.is_file():
            r=a.read(p)
            if r['status'] in ['queued','running','ready']:
                if r['status']=='running' and not alive(r.get('pid',0)):r.update(status='interrupted',reason='worker_exited')
                else:
                    if r['status']=='ready' and force:r['status']='interrupted'
                    if r['status']=='ready':
                        try:
                            if kind=='species':
                                p=a.lookup(sid)
                                if a.stale(sid,p):raise FileNotFoundError('ready_result_stale')
                            else:
                                from .cohort_artifacts import path
                                if not path(key).exists():raise FileNotFoundError('ready_cohort_missing')
                        except FileNotFoundError:r['status']='interrupted'
                    if r['status']=='interrupted':pass
                    else:
                        if start and r['status']!='ready':start_consumer()
                        return r
        r={'request_id':rid,'species_id':sid,'task_kind':kind,'species_ids':ids,'status':'queued','created':time.time(),'updated':time.time(),'progress':0,'identity':key,'force':bool(force)};a.write(p,r)
    if start:start_consumer()
    return r
@contextmanager
def waiting_lock(name):
    begin=time.monotonic()
    while True:
        guard=lock(name)
        try:guard.__enter__();break
        except BlockingIOError:
            if time.monotonic()-begin>=2:raise
            time.sleep(.02)
    try:yield
    finally:guard.__exit__(None,None,None)
def start_consumer():
    if not getattr(settings,'INTEGRATION_VIZ_ON_DEMAND',True):return
    p=a.root()/'locks'/'consumer.json'
    if p.is_file():
        try:
            if alive(int(p.read_text()),p.stat().st_mtime):return
        except (ValueError,OSError):pass
    log=a.root()/'reports'/'consumer.log';log.parent.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy();env.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']})
    cmd=[sys.executable,str(settings.BASE_DIR/'manage.py'),'materialize_integration_visuals','--consume-requests','--idle-exit-seconds','45','--output-root',str(a.root())]
    with waiting_lock('launch'):
        state=a.root()/'locks'/'consumer_launch_state.json'
        if state.exists():
            recorded=a.read(state)
            if alive(recorded.get('pid',0),recorded.get('launched',state.stat().st_mtime)):return
        with log.open('ab') as f:child=subprocess.Popen(cmd,cwd=settings.BASE_DIR,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        a.write(state,{'pid':child.pid,'launched':time.time()})
def execute(sid,publish=True,resume=True,on_progress=None):
    from .source import load
    from .builders import build
    with lock('species_'+a.component(sid)):
        if resume:
            try:
                target=a.lookup(sid)
                if not a.stale(sid,target) and a.read(target/'audit.json')['passed']:
                    if a.read(target/'manifest.json').get('storage_version',1)<3:return a.upgrade_native(target,sid,publish)
                    return target
            except FileNotFoundError:pass
        begin=time.monotonic();ds=load(sid);loaded=time.monotonic()
        if on_progress:on_progress('source_audited',.25)
        built=build(ds);calculated=time.monotonic()
        if on_progress:on_progress('whole_population_calculated',.7)
        if 'genome' in ds['frames'] and len(ds['frames'])==3:
            from .native_evidence import compute,attach
            native,quality=compute(ds['frames']['genome']);attach(built,native,quality)
        target=a.persist(sid,built);end=time.monotonic()
        from .performance import memory
        a.write(target/'performance.json',{'load_seconds':loaded-begin,'build_seconds':calculated-loaded,'persist_and_evidence_seconds':end-calculated,'total_seconds':end-begin,**memory()})
        if on_progress:on_progress('artifact_audited',.95)
        if publish:a.publish(target)
        return target
def consume(idle=45):
    from .cohort_artifacts import build as build_cohort
    import gc
    try:
        with lock('consumer'):
            last=time.monotonic()
            while time.monotonic()-last<idle:
                files=sorted((a.root()/'requests').glob('*.json')) if (a.root()/'requests').exists() else []
                for p in files:
                    r=a.read(p)
                    if r['status']=='running' and not alive(r.get('pid',0)):r.update(status='interrupted',reason='worker_exited');a.write(p,r)
                queued=[p for p in files if (lambda r:r['status']=='queued' and r.get('next_after',0)<=time.time())(a.read(p))]
                if not queued:time.sleep(.5);continue
                p=queued[0];r=a.read(p);r.update(status='running',pid=os.getpid(),updated=time.time(),progress=.1);a.write(p,r)
                from threading import Thread,Event,RLock
                stop=Event();request_lock=RLock()
                def progress(stage=None,value=None):
                    with request_lock:
                        if stage is not None:r.update(stage=stage,progress=value)
                        r.update(heartbeat=time.time(),updated=time.time());a.write(p,r)
                def heartbeat():
                    while not stop.wait(5):progress()
                ticker=Thread(target=heartbeat,daemon=True);ticker.start()
                try:
                    if r['task_kind']=='cohort':
                        from .cohort_metadata import registry_snapshot
                        with registry_snapshot(r['species_ids']):result=build_cohort(r['species_ids'])
                        r['cohort_key']=result['cohort_key']
                    else:
                        target=execute(r['species_id'],resume=not r.get('force',False),on_progress=progress);r['artifact_version']=a.read(target/'manifest.json')['artifact_version']
                    r.update(status='ready',progress=1)
                except BlockingIOError:r.update(status='queued',reason='batch_owns_species_lock',next_after=time.time()+3)
                except Exception as e:r.update(status='failed',reason=str(e),error_type=type(e).__name__)
                finally:stop.set();ticker.join()
                r['updated']=time.time();a.write(p,r);last=time.monotonic();gc.collect()
    except BlockingIOError:return
