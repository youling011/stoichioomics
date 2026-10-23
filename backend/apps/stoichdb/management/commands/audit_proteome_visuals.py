from pathlib import Path
import csv,json
import numpy as np
from django.core.management.base import BaseCommand,CommandError
from django.conf import settings

class Command(BaseCommand):
    help='Audit every Proteome chart position, counts, source identity and optional independent references.'
    requires_system_checks=[]
    def add_arguments(self,p):
        p.add_argument('--species-id',action='append');p.add_argument('--species-file');p.add_argument('--all-registered',action='store_true');p.add_argument('--scope',choices=['core','full'],default='core');p.add_argument('--artifact-root',default='runtime/proteome_visuals_v3');p.add_argument('--reference-root');p.add_argument('--report-json',required=True);p.add_argument('--report-csv',required=True);p.add_argument('--fail-on-error',action='store_true');p.add_argument('--publish',action='store_true')
    def handle(self,*a,**o):
        from backend.apps.stoichdb.proteome_viz import artifacts as store
        from backend.apps.stoichdb.proteome_viz.execution import select_tasks,draft_path
        from backend.apps.stoichdb.proteome_viz.source import release_id
        settings.PROTEOME_VIZ_ROOT=Path(o['artifact_root']).resolve();release=release_id();results=[];records=[]
        for task in select_tasks(o):
            sid=task['species_id'];scope=o['scope']
            try:
                d=draft_path(sid,scope);draft=store.read_json(d) if d.is_file() else store.published(sid,scope,release)
                if scope=='full' and not task['full_csv_path']:
                    result={'species_id':sid,'scope':scope,'status':'unavailable','reason':'full_not_registered','errors':[]};results.append(result)
                    for cid in __import__('backend.apps.stoichdb.proteome_viz.contracts',fromlist=['TITLES']).TITLES:records.append({**result,'chart_id':cid,'domain':task['domain']})
                    continue
                if not draft or not draft.get('path'):raise ValueError('artifact_not_prepared:'+str(draft.get('error','') if draft else ''))
                target=store.path_for(draft);result=store.audit_path(target)
                if o.get('reference_root') and scope=='core':
                    ref=Path(o['reference_root'])/(sid+'.json')
                    if ref.is_file():
                        reference=store.read_json(ref);profiles=store.read_json(target/'profiles.json.gz')
                        for row in reference['numeric_stats']:
                            p=profiles[row['field']];keys=['min','p05','p25','median','p75','p95','max']
                            if p['n_valid']!=row['n_valid'] or not np.allclose(p['quantiles'],[row[k] for k in keys],atol=1e-10,rtol=1e-8,equal_nan=True) or not np.isclose(p['mean'],row['mean'],atol=1e-10,rtol=1e-8):result['errors'].append(row['field']+':reference_mismatch')
                        result['reference_fields_checked']=len(reference['numeric_stats'])
                result['status']='failed' if result['errors'] else 'passed'
                if o['publish'] and result['status']=='passed':store.publish(target)
                m=store.read_json(target/'manifest.json');figs=store.read_bundle(str(target))
                from backend.apps.stoichdb.proteome_viz.cohorts import payload
                shared=payload(sid,scope,release)
                if shared['readiness']!='ready':raise ValueError('cohort_not_prepared')
                result['cohort_hash']=shared['cohort_hash'];result['cohort_species']=len(shared['species_ids'])
                for cid,p in figs.items():
                    if cid in ['D11','D12','D16']:
                        data=shared['data'];status=data.get('pca',{}).get('status','unavailable') if cid=='D11' else data['status'];reason=data.get('pca',{}).get('reason') if cid=='D11' else data.get('reason')
                        records.append({'species_id':sid,'scope':scope,'domain':task['domain'],'dataset_id':m['dataset_id'],'chart_id':cid,'status':status,'reason':reason,'n_source':len(shared['species_ids']),'n_valid':len(data.get('species',[])),'n_proteome_source':m['n_source'],'source_hash':shared['cohort_hash'],'artifact_version':'cohort_'+shared['cohort_hash'][:16],'conservation_passed':not bool(result['errors']),'errors':';'.join(result['errors'])});continue
                    ref=figs.get(p.get('chart_ref'),p);records.append({'species_id':sid,'scope':scope,'domain':task['domain'],'dataset_id':m['dataset_id'],'chart_id':cid,'status':ref.get('status'),'reason':ref.get('reason_code'),'n_source':m['n_source'],'n_valid':ref.get('coverage',{}).get('n_valid'),'source_hash':m['source_hash'],'artifact_version':m['artifact_version'],'conservation_passed':not bool(result['errors']),'errors':';'.join(result['errors'])})
            except Exception as exc:result={'species_id':sid,'scope':scope,'status':'failed','errors':[str(exc)]};records.append({**result,'chart_id':'all'})
            results.append(result)
        report={'scope':o['scope'],'species':len(results),'passed':sum(r['status']=='passed' for r in results),'unavailable':sum(r['status']=='unavailable' for r in results),'failed':sum(r['status']=='failed' for r in results),'results':results}
        store.write_json(Path(o['report_json']),report);p=Path(o['report_csv']);p.parent.mkdir(parents=True,exist_ok=True)
        if o['publish'] and not report['failed']:
            import hashlib
            selection=hashlib.sha256('\n'.join(sorted(r['species_id'] for r in results)).encode()).hexdigest()[:16]
            store.write_json(store.root()/'release_indexes'/store.component(release)/(scope+'_'+selection+'.json'),{'release_id':release,'scope':scope,'selection_hash':selection,'status':'audited','species':results})
        keys=list(dict.fromkeys(k for r in records for k in r))
        with p.open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader();writer.writerows(records)
        self.stdout.write(json.dumps({k:v for k,v in report.items() if k!='results'}))
        if o['fail_on_error'] and report['failed']:raise CommandError('Proteome audit failed')
