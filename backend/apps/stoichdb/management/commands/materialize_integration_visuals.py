from pathlib import Path
import json,os,sys,time,subprocess,gc,traceback
from django.core.management.base import BaseCommand,CommandError
from django.conf import settings
from backend.apps.stoichdb.models import Species
from backend.apps.stoichdb.integration_viz import artifacts as a,cohort_artifacts as cohorts,work_requests as jobs
from backend.apps.stoichdb.integration_viz.source import load,registry,release
class Command(BaseCommand):
    help='Complete-Core integration materialization, isolated queue consumer and capability audit.'
    def add_arguments(self,p):
        g=p.add_mutually_exclusive_group();g.add_argument('--species-file');g.add_argument('--species',action='append');g.add_argument('--all-registered',action='store_true');g.add_argument('--consume-requests',action='store_true')
        p.add_argument('--output-root');p.add_argument('--resume',action='store_true');p.add_argument('--publish',action='store_true');p.add_argument('--audit-only',action='store_true');p.add_argument('--scan-capabilities',action='store_true');p.add_argument('--with-default-cohort',action='store_true');p.add_argument('--max-workers',type=int,default=1);p.add_argument('--idle-exit-seconds',type=int,default=45);p.add_argument('--internal-one',action='store_true');p.add_argument('--report')
    def handle(self,**o):
        if o['scan_capabilities'] and any(o[k] for k in ['publish','audit_only','with_default_cohort','internal_one','consume_requests']):raise CommandError('capability audit cannot publish or materialize visualization/cohort results')
        if o['audit_only'] and any(o[k] for k in ['publish','internal_one','consume_requests']):raise CommandError('artifact audit is read-only')
        if o['output_root']:settings.INTEGRATION_VIZ_ROOT=Path(o['output_root']).resolve()
        if o['max_workers'] not in [1,2,4] or (not o['scan_capabilities'] and o['max_workers']!=1):raise CommandError('one scientific build worker; capability-only scans allow one, two or four bounded readers')
        if o['consume_requests']:
            jobs.consume(o['idle_exit_seconds']);return
        if o['species_file']:
            p=Path(o['species_file']);text=p.read_text('utf-8-sig')
            if p.suffix=='.json':
                data=json.loads(text);rows=data['selected_species'] if isinstance(data,dict) else data;ids=[r['species_id'] if isinstance(r,dict) else r for r in rows]
            else:ids=[s.strip() for s in text.splitlines() if s.strip() and not s.startswith('#')]
        elif o['species']:ids=o['species']
        elif o['all_registered']:
            if not o['scan_capabilities']:raise CommandError('all-registered is restricted to capability scan; use explicit common list for precomputation')
            ids=list(Species.objects.order_by('species_id').values_list('species_id',flat=True))
        else:raise CommandError('explicit species selection required')
        if len(ids)!=len(set(ids)):raise CommandError('duplicate_species_selection')
        reports=[];errors=[];start=time.time();report=Path(o['report']) if o['report'] else a.root()/'reports'/('capabilities.json' if o['scan_capabilities'] else 'audit.json' if o['audit_only'] else 'batch.json')
        if o['scan_capabilities'] and o['resume'] and report.exists():reports=a.read(report).get('results',[])
        capability_dir=a.root()/'reports'/'capabilities'
        if o['scan_capabilities'] and o['resume']:
            reports=[{'species_id':v['species_id'],'status':v['status'],'path':str(f)} for f in capability_dir.glob('*.json.gz') for v in [a.read(f)]] if capability_dir.exists() else []
        done={r['species_id'] for r in reports}
        if o['scan_capabilities'] and o['max_workers']>1:
            from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
            from backend.apps.stoichdb.integration_viz.scan_worker import initialize,run
            from backend.apps.stoichdb.integration_viz.performance import available_physical
            from backend.apps.stoichdb.models import OmicsDataset
            from django.db.models import Max
            big=set(OmicsDataset.objects.values('species__species_id').annotate(n=Max('row_count_core')).filter(n__gte=100000).values_list('species__species_id',flat=True))
            def save(future):
                result=future.result();sid=result['species_id'];capfile=capability_dir/(a.component(sid)+'.json.gz')
                if result['status']=='failed':errors.append(result)
                else:a.write(capfile,result)
                reports.append({'species_id':sid,'status':result['status'],'path':str(capfile),'seconds':result['seconds']})
                if len(reports)%100==0 or len(reports)==len(ids):a.write(report,{'release_id':release(),'requested':len(ids),'completed':len(reports),'errors':errors,'seconds':time.time()-start,'workers':o['max_workers'],'large_species_serialized':True,'results':reports})
                self.stdout.write(json.dumps({'completed':len(reports),'requested':len(ids),'species_id':sid,'status':result['status'],'seconds':result['seconds']}));self.stdout.flush()
            with ProcessPoolExecutor(max_workers=o['max_workers'],initializer=initialize,max_tasks_per_child=50) as pool:
                pending=set()
                for sid in ids:
                    if sid in done:continue
                    free=available_physical()
                    if free is not None and free<2*1024**3:
                        for f in pending:save(f)
                        pending.clear()
                        while (available_physical() or 2*1024**3)<1024**3:time.sleep(.5)
                        save(pool.submit(run,sid));continue
                    if sid in big:
                        for f in pending:save(f)
                        pending.clear();save(pool.submit(run,sid));continue
                    pending.add(pool.submit(run,sid))
                    if len(pending)>=o['max_workers']:
                        finished,pending=wait(pending,return_when=FIRST_COMPLETED)
                        for f in finished:save(f)
                for f in pending:save(f)
            if errors:raise CommandError(str(len(errors))+' capability failures; see report')
            return
        for sid in ids:
            if sid in done:continue
            t=time.time()
            try:
                if o['scan_capabilities']:
                    # Read all required rows and literal IDs, not header-only claims.
                    from backend.apps.stoichdb.integration_viz.capabilities import scan
                    full_result=scan(sid);capfile=capability_dir/(a.component(sid)+'.json.gz');a.write(capfile,full_result);result={'species_id':sid,'status':full_result['status'],'path':str(capfile)}
                elif o['audit_only']:
                    p=a.lookup(sid);result={'species_id':sid,**a.audit_target(p,save=False)}
                    if a.stale(sid,p):raise ValueError('stale_artifact')
                    if not result['passed']:raise ValueError('artifact_audit_failed')
                elif o['internal_one'] or all(d.row_count_core<100000 for d in registry(sid).values()):
                    p=jobs.execute(sid,o['publish'],o['resume']);result={'species_id':sid,'status':'ready','artifact_version':a.read(p/'manifest.json')['artifact_version'],'artifact_path':str(p),'published':o['publish']}
                else:
                    cmd=[sys.executable,str(settings.BASE_DIR/'manage.py'),'materialize_integration_visuals','--species',sid,'--internal-one','--output-root',str(a.root())]
                    if o['publish']:cmd+=['--publish']
                    if o['resume']:cmd+=['--resume']
                    env=os.environ.copy();env.update({k:'1' for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']})
                    child=subprocess.run(cmd,cwd=settings.BASE_DIR,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    if child.returncode:raise ValueError(child.stdout[-3000:])
                    result=json.loads(next(line for line in reversed(child.stdout.splitlines()) if line.startswith('{"species_id"')))
                result['seconds']=round(time.time()-t,3);reports.append(result)
            except Exception as e:
                result={'species_id':sid,'status':'failed','error':str(e),'seconds':round(time.time()-t,3)};reports.append(result);errors.append(result)
            if not o['internal_one']:
                if not o['scan_capabilities'] or len(reports)%100==0 or len(reports)==len(ids):a.write(report,{'release_id':release(),'requested':len(ids),'completed':len(reports),'errors':errors,'seconds':time.time()-start,'results':reports})
                self.stdout.write(json.dumps({'completed':len(reports),'requested':len(ids),**{k:result[k] for k in ['species_id','status','seconds'] if k in result}}));self.stdout.flush()
            gc.collect()
            if o['internal_one']:self.stdout.write(json.dumps(result));self.stdout.flush()
        if o['with_default_cohort']:
            from backend.apps.stoichdb.integration_viz.cohort_metadata import registry_snapshot
            with registry_snapshot(list(dict.fromkeys(cohorts.DEFAULT_SPECIES+ids))):
                self.default_cohorts(ids,o,errors)
        if errors:raise CommandError(str(len(errors))+' classified failures; see report')

    def default_cohorts(self,ids,o,errors):
        for sid in ids:
            selected=cohorts.default_ids(sid);key=cohorts.identity(selected)
            if o['audit_only']:
                if not cohorts.path(key).is_file():errors.append({'species_id':sid,'error':'default_cohort_missing'})
            elif not cohorts.path(key).exists():cohorts.build(selected)

