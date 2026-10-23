from pathlib import Path
import os,sys,argparse,json,yaml
PROJECT_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.config.settings');os.environ['PYTHONDONTWRITEBYTECODE']='1'
import django;django.setup()
from backend.portal.pipeline_runner import run_full_pipeline_from_config
def main():
 p=argparse.ArgumentParser(description='Unified web/CLI full analysis pipeline');p.add_argument('--config',required=True);args=p.parse_args();config_path=Path(args.config).resolve()
 cfg=yaml.safe_load(config_path.read_text(encoding='utf-8'));workspace=(cfg.get('input_adapter') or {}).get('workspace') or {}
 from backend.apps.jobs.models import AnalysisJob
 job=AnalysisJob.objects.filter(job_id=workspace.get('job_id')).first() if workspace.get('job_id') else None
 if job:
  from django.db import transaction
  from backend.apps.jobs.services import _run_job_sync
  from backend.analysis_engine.hvg_research.locking import RunConflict
  if (Path(workspace['root_dir'])/workspace['job_id']).resolve()!=Path(job.workspace_path).resolve():raise ValueError('CLI workspace does not belong to registered job')
  with transaction.atomic():
   locked=AnalysisJob.objects.select_for_update().get(pk=job.pk)
   if locked.status in ['RUNNING','CANCEL_REQUESTED']:raise RunConflict('Registered job already has an active execution')
   locked.config_path=str(config_path);locked.pipeline_type='full';locked.status='RUNNING';locked.save(update_fields=['config_path','pipeline_type','status','updated_at'])
  result=_run_job_sync(job.job_id)
 else:result=run_full_pipeline_from_config(cfg)
 print(json.dumps(result,ensure_ascii=False,default=str))
if __name__=='__main__':main()
