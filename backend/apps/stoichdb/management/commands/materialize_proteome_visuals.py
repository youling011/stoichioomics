import os,time,json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import multiprocessing
from django.core.management.base import BaseCommand,CommandError
from django.conf import settings

class Command(BaseCommand):
    help='Build and audit whole-population Proteome v3 products without changing curated source data.'
    requires_system_checks=[]
    def add_arguments(self,p):
        p.add_argument('--species-id',action='append');p.add_argument('--species-file');p.add_argument('--all-registered',action='store_true');p.add_argument('--scope',choices=['core','full'],default='core');p.add_argument('--output-dir',default='runtime/proteome_visuals_v3');p.add_argument('--method-version',default='proteome_viz_v3_0');p.add_argument('--workers',type=int,default=1)
        for name in ['resume','force','fingerprints-only','publish','with-full','consume-requests','once']:p.add_argument('--'+name,action='store_true')
        p.add_argument('--poll-seconds',type=float,default=5)
        p.add_argument('--idle-exit-seconds',type=float,default=0)
    def handle(self,*args,**o):
        from backend.apps.stoichdb.proteome_viz import METHOD_VERSION
        from backend.apps.stoichdb.proteome_viz import artifacts as store
        from backend.apps.stoichdb.proteome_viz.execution import run_one,select_tasks
        if o['method_version']!=METHOD_VERSION:raise CommandError('unsupported_method_version')
        if not 1<=o['workers']<=4:raise CommandError('workers must be between 1 and 4')
        for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:os.environ[key]='1'
        os.environ['PYTHONDONTWRITEBYTECODE']='1';settings.PROTEOME_VIZ_ROOT=Path(o['output_dir']).resolve();o['output_dir']=str(settings.PROTEOME_VIZ_ROOT)
        if o['consume_requests']:return self.consume(o)
        tasks=select_tasks(o);run_id=time.strftime('%Y%m%d_%H%M%S');log=store.root()/'runs'/f'{run_id}.jsonl';log.parent.mkdir(parents=True,exist_ok=True)
        status={'total':len(tasks),'completed':0,'failed':0,'unavailable':0,'pid':os.getpid(),'started':time.time()};store.write_json(log.with_suffix('.json'),status)
        def record(result):
            status['completed']+=1;status['failed']+=int(result['status']=='failed' or result.get('full',{}).get('status')=='failed');status['unavailable']+=int(result['status']=='unavailable');status['heartbeat']=time.time()
            with log.open('a',encoding='utf-8') as f:f.write(json.dumps(store.clean(result),ensure_ascii=False)+'\n')
            store.write_json(log.with_suffix('.json'),status)
            self.stdout.write(json.dumps({k:result[k] for k in ['species_id','scope','status','seconds'] if k in result}|{'completed':status['completed'],'total':status['total']},ensure_ascii=True));self.stdout.flush()
        try:
            if o['workers']==1:
                for task in tasks:record(run_one(task))
            else:
                with ProcessPoolExecutor(max_workers=o['workers'],mp_context=multiprocessing.get_context('spawn')) as pool:
                    pending={};cursor=0
                    # Large proteomes run alone: retain four small-species workers without
                    # fitting several 100k+ row Core/Full populations in memory together.
                    while pending or cursor<len(tasks):
                        while cursor<len(tasks) and len(pending)<o['workers']:
                            task=tasks[cursor];heavy=(task.get('row_count_core') or 0)>=100000
                            if heavy and pending:break
                            pending[pool.submit(run_one,task)]=task['species_id'];cursor+=1
                            if heavy:break
                        if not pending:continue
                        future=next(as_completed(pending));sid=pending.pop(future)
                        try:record(future.result())
                        except Exception as exc:record({'species_id':sid,'scope':o['scope'],'status':'failed','error':str(exc)})
        finally:
            status['finished']=time.time();store.write_json(log.with_suffix('.json'),status)
        self.stdout.write(json.dumps(status))
        if status['failed']:raise CommandError(f'{status["failed"]} species failed; inspect {log}')
    def consume(self,o):
        from backend.apps.stoichdb.proteome_viz import artifacts as store,work_requests
        from backend.apps.stoichdb.proteome_viz.execution import run_one,select_tasks
        if o.get('species_id') or o.get('species_file') or o.get('all_registered'):raise CommandError('consumer_and_species_selectors_are_mutually_exclusive')
        heartbeat=store.root()/'consumer.json';last_work=time.monotonic()
        try:
            while True:
                store.write_json(heartbeat,{'pid':os.getpid(),'heartbeat':time.time()});folder=store.root()/'work_requests';folder.mkdir(parents=True,exist_ok=True);count=0
                for p in folder.glob('*.json'):
                    job=store.read_json(p)
                    if job['readiness']=='running' and not work_requests.process_alive(int(job.get('worker_pid',0))):job['readiness']='interrupted'
                    if job['readiness'] not in ['queued','interrupted']:continue
                    lock=p.with_suffix('.claim')
                    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
                    except FileExistsError:
                        try:
                            if work_requests.process_alive(int(lock.read_text())):continue
                            lock.unlink();fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
                        except (OSError,ValueError):continue
                    os.write(fd,str(os.getpid()).encode());os.close(fd);count+=1
                    try:
                        job['readiness']='running';job['worker_pid']=os.getpid();job['heartbeat']=time.time();store.write_json(p,job)
                        if job['chart_id']=='B15' and job['parameters']:
                            from backend.apps.stoichdb.proteome_viz.api import pair_payload
                            from backend.apps.stoichdb.proteome_viz.source import release_id
                            target=store.lookup_version(job['species_id'],job['scope'],release_id());m=store.read_json(target/'manifest.json');parameters=dict(job['parameters'])
                            if 'conditional_bins' in parameters:parameters['k']=parameters.pop('conditional_bins')
                            pair_payload(target,m,**parameters)
                            result={'status':'passed'}
                        else:
                            task=select_tasks({**o,'species_id':[job['species_id']],'scope':job['scope'],'publish':True,'force':False,'resume':True})[0];result=run_one(task)
                        job['readiness']='ready' if result['status']=='passed' else 'failed';job['result']=result
                    except Exception as exc:job['readiness']='failed';job['error']=str(exc)
                    finally:
                        job['finished']=time.time();store.write_json(p,job);lock.unlink(missing_ok=True);last_work=time.monotonic()
                if o['once']:break
                if o.get('idle_exit_seconds') and time.monotonic()-last_work>=o['idle_exit_seconds']:break
                time.sleep(max(.2,o['poll_seconds']))
        finally:
            if heartbeat.is_file() and store.read_json(heartbeat).get('pid')==os.getpid():heartbeat.unlink()
