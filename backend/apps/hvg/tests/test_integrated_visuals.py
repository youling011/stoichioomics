import json,tempfile
from pathlib import Path
import numpy as np,pandas as pd
from django.test import TestCase
from backend.analysis_engine.hvg_research.artifacts import atomic_json,atomic_frame
from backend.apps.jobs.models import AnalysisJob
from backend.apps.jobs.services import _token_hash
from backend.apps.hvg.research_visuals import SECTIONS

class IntegratedVisualTests(TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);base=Path(self.tmp.name);self.run=base/'hvg_functional_comparison/runs/fixture'
  self.run.mkdir(parents=True);atomic_json(base/'hvg_functional_comparison/active_run.json',{'analysis_run_id':'fixture'})
  self.token='integration-fixture';AnalysisJob.objects.create(job_id='integrated_visual_fixture',workspace_path=str(base),access_token_hash=_token_hash(self.token))
  atomic_json(self.run/'run_manifest.json',{'analysis_run_id':'fixture','schema_version':'hvg_research_v1','research_status':'complete','stages':{},'contexts':[{'context_id':'global','directory':'contexts/global','H':2,'N':4}],'annotation_snapshot_id':'fixture-platform-release','artifacts':[]})
  atomic_frame(self.run/'labels/hvg_labels.parquet',pd.DataFrame({'gene_id':['a','b','c','d','e','f'],'context_id':'global','is_hvg':[True,True,False,False,False,False],'mean_expr':[1,2,3,4,5,6],'hvg_score':[6,5,4,3,2,1]}))
  atomic_frame(self.run/'features/feature_evidence_summary.parquet',pd.DataFrame({'feature_key':['protein::tiny','genome::large'],'context_id':'global','effect':[.4,-.3],'ci_low':[.2,-.5],'ci_high':[.6,-.1],'p_value':[.001,.03],'q_global':[.002,.03],'alias_of':['','']}))
  atomic_frame(self.run/'features/adjusted_feature_tests.parquet',pd.DataFrame({'feature_key':['protein::tiny'],'context_id':['global'],'model':['expression_detection_length'],'beta':[np.log(2)],'ci_low':[1.2],'ci_high':[3.2],'q_global':[.01]}))
  atomic_frame(self.run/'features/feature_values.parquet',pd.DataFrame({'gene_id':['a','b','c','d','e','f'],'context_id':'global','protein::tiny':[.01,.02,.03,.04,.05,.06]}))
  atomic_frame(self.run/'core/core_feature_audit.parquet',pd.DataFrame({'feature_key':['protein::tiny','genome::large'],'context_id':'global','omics':['proteome','genome'],'final_status':['tested','descriptive_only'],'missing_hvg':[0.,.2],'missing_nonhvg':[0.,.1]}))
 def get(self,kind,**params):return self.client.get('/api/hvg/integrated_visual_fixture/research/'+kind+'/',{'context_id':'global',**params},HTTP_X_JOB_TOKEN=self.token)
 def test_visuals_are_authorized(self):
  r=self.client.get('/api/hvg/integrated_visual_fixture/research/visuals/feature_forest/');self.assertEqual(r.status_code,403)
 def test_every_section_handles_missing_optional_tables(self):
  for kind in dict.fromkeys(k for s in SECTIONS.values() for k in s['plots']):
   r=self.get('visuals/'+kind);self.assertEqual(r.status_code,200,(kind,r.content));self.assertNotIn('NaN',r.content.decode())
 def test_plot_is_not_table_page_and_preserves_saved_effects(self):
  a=self.get('visuals/feature_forest',page=1,page_size=1).json()['data'];b=self.get('visuals/feature_forest',page=99,page_size=200).json()['data'];self.assertEqual(a,b);self.assertEqual(len(a['rows']),2);self.assertEqual(a['rows'][0]['effect'],.4)
 def test_adjusted_beta_interval_has_log_odds_units(self):
  a=self.get('visuals/adjusted_forest').json()['data'];self.assertAlmostEqual(a['rows'][0]['plot_ci_low'],np.log(1.2));self.assertAlmostEqual(a['rows'][0]['beta'],np.log(2))
 def test_distribution_uses_actual_full_reference(self):
  a=self.get('visuals/distribution',feature_key='protein::tiny').json()['data'];by={r['group']:r for r in a['rows']};self.assertEqual(by['HVG']['n'],2);self.assertEqual(by['non-HVG']['n'],4);self.assertAlmostEqual(by['HVG']['median'],.015)
 def test_single_context_is_not_invented_replication(self):
  a=self.get('summary').json()['data'];self.assertEqual(a['presentation']['sections']['context_patterns']['state'],'Not applicable');self.assertEqual(a['presentation']['annotation_snapshot_id'],'fixture-platform-release')
 def test_function_scope_does_not_hide_core_registry(self):
  a=self.get('visuals/core_omics',scope='all_annotated').json()['data'];self.assertEqual(a['total'],2);self.assertEqual(len(a['rows']),2)
 def test_context_capability_does_not_borrow_global_results(self):
  path=self.run/'run_manifest.json';m=json.loads(path.read_text());m['contexts'].append({'context_id':'empty_subset','directory':'contexts/empty_subset'});atomic_json(path,m)
  r=self.get('summary',context_id='empty_subset').json()['data'];self.assertEqual(r['presentation']['sections']['group_comparison']['state'],'Unavailable')
 def test_public_scientific_exports_remain_identical(self):
  import backend.analysis_engine as engine
  from backend.analysis_engine.phase1.runner_core import run_phase1_analysis_pipeline
  from backend.analysis_engine.phase2.runner_core import run_phase2_stoich_pipeline
  self.assertIs(engine.run_phase1_analysis_pipeline,run_phase1_analysis_pipeline);self.assertIs(engine.run_phase2_stoich_pipeline,run_phase2_stoich_pipeline)
 def test_gene_detail_keeps_all_Core_despite_function_scope(self):
  a=self.get('genes/a',scope='all_annotated',q_max=.05).json()['data'];self.assertEqual(len(a['core_feature_values']),2)
 def test_unknown_plot_and_invalid_q_rejected(self):
  self.assertEqual(self.get('visuals/unknown').status_code,400);self.assertEqual(self.get('visuals/feature_forest',q_max=-1).status_code,400)
