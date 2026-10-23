import json,os
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from django.conf import settings
def execute_task(task):
    import django
    django.setup()
    from backend.apps.stoichdb.sequence_viz.execution import run_one
    from django.conf import settings
    if task.get('output_dir'):settings.SEQUENCE_VIZ_ROOT=Path(task['output_dir']).resolve()
    if 'scopes' not in task:return run_one(task['sid'],task['omics'],task['scope'],task['resume'],task['publish'],task['audit_only'])
    return [run_one(task['sid'],task['omics'],scope,task['resume'],task['publish'],task['audit_only']) for scope in task['scopes']]
class Command(BaseCommand):
    help='Build audited complete Genome/Transcriptome visualizations for explicit species only.'
    def add_arguments(self,p):
        g=p.add_mutually_exclusive_group();g.add_argument('--species-file');g.add_argument('--species',nargs='+');g.add_argument('--all-registered',action='store_true')
        p.add_argument('--omics',choices=['genome','transcriptome','both'],default='both');p.add_argument('--scope',choices=['core','full','both'],default='core');p.add_argument('--workers',type=int,choices=[1,2],default=1);p.add_argument('--resume',action='store_true');p.add_argument('--publish',action='store_true');p.add_argument('--audit-only',action='store_true');p.add_argument('--consume-requests',action='store_true');p.add_argument('--once',action='store_true');p.add_argument('--idle-exit-seconds',type=int,default=45);p.add_argument('--output-dir');p.add_argument('--report')
    def handle(self,*args,**o):
        from backend.apps.stoichdb.models import OmicsDataset
        if o['audit_only'] and o['publish']:raise CommandError('--audit-only and --publish are mutually exclusive')
        if o['consume_requests'] and (o['species_file'] or o['species'] or o['all_registered'] or o['audit_only']):raise CommandError('consumer cannot use species selectors or audit-only')
        if not o['consume_requests'] and not (o['species_file'] or o['species'] or o['all_registered']):raise CommandError('Explicit --species-file, --species or --all-registered is required')
        if o['output_dir']:settings.SEQUENCE_VIZ_ROOT=Path(o['output_dir']).resolve()
        if o['consume_requests']:
            from backend.apps.stoichdb.sequence_viz.work_requests import consume
            consume(o['once'],o['idle_exit_seconds']);return
        from backend.apps.stoichdb.sequence_viz.execution import run_one
        from backend.apps.stoichdb.sequence_viz.artifacts import write_json
        species=list(dict.fromkeys(Path(o['species_file']).read_text(encoding='utf-8-sig').split())) if o['species_file'] else o['species'];modes=['genome','transcriptome'] if o['omics']=='both' else [o['omics']];scopes=['core','full'] if o['scope']=='both' else [o['scope']]
        q=OmicsDataset.objects.filter(omics_type__in=modes)
        if species:q=q.filter(species__species_id__in=species)
        found=list(q.values_list('species__species_id','omics_type').order_by('species__species_id','omics_type'));results=[]
        if species:
            positions={s:i for i,s in enumerate(species)};found.sort(key=lambda x:(positions[x[0]],x[1]))
        if species:
            present=set(found)
            for sid in species:
                for m in modes:
                    if (sid,m) not in present:results.append({'species_id':sid,'omics':m,'status':'unavailable','reason_code':'dataset_not_registered'})
        # A bounded spawn pool has one native BLAS thread per worker. Large datasets
        # are scheduled alone so their complete matrices never overlap in memory.
        if o['workers']==2 and not o['audit_only']:
            from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
            import multiprocessing
            tasks=[{'sid':sid,'omics':m,'scopes':scopes,'resume':o['resume'],'publish':o['publish'],'audit_only':False,'output_dir':o['output_dir']} for sid,m in found]
            sizes={(sid,m):count for sid,m,count in q.values_list('species__species_id','omics_type','row_count_core')}
            # Recycle after each scope: large pandas/Arrow/SVD allocations must be
            # returned to Windows rather than retained in a long-lived worker heap.
            with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn'),max_tasks_per_child=1) as pool:
                pending={}
                def finish(done):
                    for future in done:
                        task=pending.pop(future)
                        try:r=future.result()
                        except Exception as e:
                            if o['report']:write_json(o['report'],results+[{'species_id':task['sid'],'omics':task['omics'],'scope':task.get('scope','/'.join(task.get('scopes',[]))),'status':'failed','error':str(e)}])
                            raise CommandError(str(e)) from e
                        for item in (r if isinstance(r,list) else [r]):results.append(item);self.stdout.write(json.dumps(item,ensure_ascii=True))
                        if o['report']:write_json(o['report'],results)
                for task in tasks:
                    heavy=sizes.get((task['sid'],task['omics']),0)>=100000
                    if heavy and pending:finish(wait(pending).done)
                    while len(pending)>=2:finish(wait(pending,return_when=FIRST_COMPLETED).done)
                    future=pool.submit(execute_task,task);pending[future]=task
                    if heavy:finish(wait(pending).done)
                if pending:finish(wait(pending).done)
            self.stdout.write(f'Completed {len(results)} explicit dataset scopes');return
        for sid,m in found:
            for scope in scopes:
                try:r=run_one(sid,m,scope,o['resume'],o['publish'],o['audit_only'])
                except Exception as e:
                    results.append({'species_id':sid,'omics':m,'scope':scope,'status':'failed','error':str(e)})
                    if o['report']:write_json(o['report'],results)
                    raise CommandError(f'{sid}/{m}/{scope}: {e}') from e
                results.append(r);self.stdout.write(json.dumps(r,ensure_ascii=True))
                if o['report']:write_json(o['report'],results)
        self.stdout.write(f'Completed {len(results)} explicit dataset scopes')
