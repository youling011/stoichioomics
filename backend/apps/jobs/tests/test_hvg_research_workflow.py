from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
from unittest.mock import patch
import yaml
from django.test import TestCase,override_settings
from django.utils import timezone
from backend.apps.jobs.models import AnalysisJob
from backend.apps.jobs.services import run_job_async,save_job_config,cleanup_expired_analysis_jobs
class ResearchJobWorkflowTests(TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.ws=self.root/'job';self.ws.mkdir();self.cfg=self.ws/'config.yaml';self.cfg.write_text(yaml.safe_dump({'hvg_research':{'enabled':True}}));self.job=AnalysisJob.objects.create(job_id='workflow_fixture',workspace_path=str(self.ws),config_path=str(self.cfg),status='READY')
 @override_settings(HVG_RESEARCH_ENABLED=False)
 def test_disabled_research_rejected_before_claim(self):
  with self.assertRaises(ValueError):run_job_async(self.job)
  self.job.refresh_from_db();self.assertEqual(self.job.status,'READY')
 def test_failed_thread_start_releases_job_claim(self):
  with patch('backend.apps.jobs.services.threading.Thread') as thread:
   thread.return_value.start.side_effect=RuntimeError('fixture startup failure')
   with self.assertRaises(RuntimeError):run_job_async(self.job)
  self.job.refresh_from_db();self.assertEqual(self.job.status,'FAILED')
 def test_running_configuration_is_frozen(self):
  self.job.status='RUNNING';self.job.save();before=self.cfg.read_bytes()
  with self.assertRaises(RuntimeError):save_job_config(self.job,{'changed':True},'full')
  self.assertEqual(self.cfg.read_bytes(),before)
 def test_cleanup_respects_archive_and_retention(self):
  self.job.status='SUCCEEDED';self.job.metadata_json={'retain_until':(timezone.now()+timedelta(days=10)).isoformat()};self.job.save();AnalysisJob.objects.filter(pk=self.job.pk).update(updated_at=timezone.now()-timedelta(days=30))
  with override_settings(WORKSPACE_ROOT=self.root):
   self.assertEqual(cleanup_expired_analysis_jobs()['removed_count'],0);self.assertTrue(self.ws.exists())
   self.job.metadata_json={'archived':True};self.job.save();AnalysisJob.objects.filter(pk=self.job.pk).update(updated_at=timezone.now()-timedelta(days=30));self.assertEqual(cleanup_expired_analysis_jobs()['removed_count'],0)
