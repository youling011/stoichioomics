import json,tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np,pandas as pd
from scipy.sparse import csr_matrix
from django.test import SimpleTestCase
from backend.analysis_engine.common import ExpressionDataset
from backend.analysis_engine.hvg_research.artifacts import atomic_json,atomic_frame
from backend.analysis_engine.hvg_research.primary_hvg import official_hvg
from backend.analysis_engine.hvg_research.unified_modes import run_modes,MODE_FUNCS
from backend.analysis_engine.hvg_research.workflow import normalize_workflow_config
from backend.apps.hvg.research_visuals import presentation,SECTIONS,visuals

class UnifiedWorkflowTests(SimpleTestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.run=Path(self.tmp.name)
  n,g=120,100;rng=np.random.default_rng(42)
  X=np.log1p(rng.poisson(rng.uniform(.5,6,g),(n,g))).astype(float)
  self.obs=pd.DataFrame({'cell_id':['c'+str(i) for i in range(n)],'cluster':['A']*60+['B']*60,'condition':['control','treated']*60,'timepoint':np.repeat(['1','2','3'],40),'sample_id':np.repeat(['s1','s2','s3','s4'],30),'pseudotime':np.linspace(0,1,n)})
  self.ds=ExpressionDataset(csr_matrix(X),['g'+str(i) for i in range(g)],['g'+str(i) for i in range(g)],list(self.obs.cell_id),self.obs,{'matrix_semantics':'log_normalized'})
  self.cfg={'hvg_method':'seurat','matrix_semantics':'log_normalized','primary_backend':'scanpy','n_top_genes':20,'min_cells':3,'min_counts':1,'trajectory_bins':4}
  L,E,A,M=official_hvg(self.ds,self.cfg);self.L=L;self.ctx=self.run/'contexts/global'
  atomic_frame(self.ctx/'labels/hvg_labels.parquet',L);atomic_json(self.ctx/'labels/hvg_method_manifest.json',M)
  p=self.run/'work/standardized/standardized_var.csv';p.parent.mkdir(parents=True);pd.DataFrame({'gene_id':self.ds.gene_ids}).to_csv(p,index=False)
  self.modes={'global_hvg':{'available':True}}
  for mode,key in [('group_aware_hvg','cluster'),('condition_aware_hvg','condition'),('timecourse_hvg','timepoint'),('sample_consensus_hvg','sample_id'),('trajectory_hvg','pseudotime')]:self.modes[mode]={'available':True,'selected_key':key}
  self.write_modes()
 def write_modes(self):atomic_json(self.run/'work/mode_resolution/mode_resolution.json',{'available_modes':self.modes})
 def execute(self):return run_modes(self.run,self.ds,self.cfg,self.ctx,'fixture')
 def test_full_entry_forces_single_workflow_and_never_old_model(self):
  from backend.portal.pipeline_runner import run_full_pipeline_from_config
  cfg={'hvg_research':{'enabled':False},'phase2_stoich':{'model_enabled':True},'phase1_analysis':{}}
  with patch('backend.analysis_engine.hvg_research.runner.run_pipeline',return_value={'ok':True}) as call,patch('backend.portal.pipeline_runner.run_phase2_stoich_pipeline',side_effect=AssertionError('Model must not run')):
   self.assertEqual(run_full_pipeline_from_config(cfg),{'ok':True});effective=call.call_args.args[0]
  self.assertTrue(effective['hvg_research']['enabled']);self.assertFalse(effective['phase2_stoich']['model_enabled']);self.assertTrue(cfg['phase2_stoich']['model_enabled'])
 def test_all_six_modes_execute_and_preserve_global_labels(self):
  result=self.execute();self.assertEqual(result['completed_modes'],6,result)
  pd.testing.assert_frame_equal(pd.read_csv(self.run/'work/analysis_phase1/hvg_baseline.csv'),self.L,check_dtype=False)
  self.assertTrue((self.run/'work/analysis_phase1/auxiliary_modes/condition_aware_hvg/condition_hvg_patterns.csv').exists())
  self.assertTrue((self.run/'work/analysis_phase1/auxiliary_modes/timecourse_hvg/timecourse_hvg_patterns.csv').exists())
  members=pd.read_parquet(self.run/'workflow/members.parquet');self.assertEqual(set(members['mode']),set(MODE_FUNCS))
 def test_subset_labels_equal_direct_official_scanpy(self):
  self.execute();from backend.analysis_engine.phase1.utils import subset_dataset
  expected,*_=official_hvg(subset_dataset(self.ds,self.obs.cluster.eq('A').to_numpy()),self.cfg)
  actual=pd.read_parquet(self.run/'workflow/members.parquet');actual=actual[(actual['mode']=='group_aware_hvg')&actual.subset_value.eq('A')]
  self.assertEqual(set(actual.loc[actual.is_hvg,'gene_id']),set(expected.loc[expected.is_hvg,'gene_id']))
 def test_missing_modes_are_explicit_and_not_fabricated(self):
  for m in MODE_FUNCS:self.modes[m]={'available':False,'reasons':['Missing required metadata']}
  self.write_modes();self.assertEqual(self.execute()['completed_modes'],1)
  modes=pd.read_parquet(self.run/'workflow/modes.parquet');self.assertEqual(sum(modes.status.eq('not_applicable')),5)
 def test_failed_mode_does_not_erase_other_modes(self):
  self.modes['condition_aware_hvg']['selected_key']='absent';self.write_modes();r=self.execute()
  self.assertEqual(r['status'],'partial');self.assertEqual(r['completed_modes'],5)
 def test_missing_metadata_is_not_a_new_category(self):
  self.obs.loc[0,'condition']=None;self.execute()
  members=pd.read_parquet(self.run/'workflow/members.parquet');f=members[members['mode'].eq('condition_aware_hvg')]
  self.assertEqual(set(f.subset_value),{'control','treated'})
 def test_cell_identifiers_are_preserved_by_subsetting(self):
  from backend.analysis_engine.phase1.utils import subset_dataset
  ds=ExpressionDataset(self.ds.matrix,self.ds.gene_ids,self.ds.gene_names,self.ds.cell_ids,self.obs.drop(columns='cell_id'),self.ds.uns)
  self.assertEqual(subset_dataset(ds,np.arange(120)>=60).cell_ids,self.ds.cell_ids[60:])
 def test_model_plots_removed_per_run_without_mutating_archives(self):
  self.execute();m={'analysis_run_id':'fixture','contexts':[{'context_id':'global','directory':'contexts/global'}],'model_policy':'removed','stages':{}}
  p=presentation(self.run,m);self.assertEqual(len(p['sections']),10)
  self.assertEqual(p['sections']['context_patterns']['state'],'Ready')
  self.assertFalse(any('original_model' in x or x in ['original_classes','original_candidate_bubble'] for s in p['sections'].values() for x in s['plots']))
  self.assertIn('original_model_comparison',SECTIONS['model_evidence']['plots'])
 def test_original_mode_charts_read_real_mode_counts(self):
  self.execute();m={'analysis_run_id':'fixture','contexts':[{'context_id':'global','directory':'contexts/global'}],'model_policy':'removed','stages':{}}
  p=visuals(self.run,m,'original_pattern_counts',{'context_id':'global'})
  self.assertTrue(p['rows']);self.assertTrue(any('condition' in x['label'] for x in p['rows']))
 def test_normalizer_keeps_research_statistical_settings(self):
  c=normalize_workflow_config({'hvg_research':{'feature_tests':{'ci_repeats':800}},'phase2_stoich':{'model_enabled':True}})
  self.assertEqual(c['hvg_research']['feature_tests']['ci_repeats'],800);self.assertFalse(c['phase2_stoich']['model_enabled'])
