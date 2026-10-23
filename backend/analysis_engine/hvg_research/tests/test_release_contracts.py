from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json,pandas as pd,numpy as np
from django.test import SimpleTestCase
from backend.analysis_engine.hvg_research.config import validate_config
from backend.apps.jobs.research_config_guard import validate_job_research_config
class ReleaseContracts(SimpleTestCase):
 def test_declared_ranges_and_paths_rejected(self):
  for c in [{'feature_tests':{'ci_repeats':0}},{'core':{'semantic_overlay':'../../private.json'}},{'gene_sets':{'compute_both_directions':False}}]:
   with self.assertRaises(ValueError):validate_config(c)
 def test_cross_job_raw_input_is_rejected(self):
  from types import SimpleNamespace
  with TemporaryDirectory() as t:
   root=Path(t)/'job';job=SimpleNamespace(workspace_path=str(root),job_id='job');cfg={'hvg_research':{'enabled':True},'input_adapter':{'input_dir':str(root/'raw'),'workspace':{'root_dir':str(root.parent),'job_id':'job'},'expression':{'file':'../other.h5ad'}}}
   with self.assertRaises(ValueError):validate_job_research_config(job,cfg)
 def test_optional_model_gets_var_features_without_replacing_labels(self):
  from backend.analysis_engine.hvg_research.reporting import run_optional_model
  from backend.analysis_engine.hvg_research.artifacts import atomic_json
  with TemporaryDirectory() as t:
   run=Path(t);ctx=run/'contexts/global';(ctx/'labels').mkdir(parents=True);(run/'work/standardized').mkdir(parents=True)
   labels=pd.DataFrame({'gene_id':['g1','g2'],'is_hvg':[True,False],'hvg_score':[2.,1.]});labels.to_csv(ctx/'labels/baseline.csv',index=False)
   pd.DataFrame({'gene_id':['g1','g2'],'gc_content':[.4,.6],'is_hvg':[False,True]}).to_csv(run/'work/standardized/standardized_var.csv',index=False);atomic_json(ctx/'labels/hvg_method_manifest.json',{'backend':'scanpy'})
   manifest={'analysis_run_id':'fixture','contexts':[{'directory':'contexts/global'}]}
   def accept(config):
    frame=pd.read_csv(config['input_baseline_csv']);self.assertEqual(frame.is_hvg.tolist(),[True,False]);self.assertIn('gc_content',frame);self.assertIn('research_comparison_reference',config);return {'summary':{'model_status':'complete'}}
   with patch('backend.analysis_engine.phase2.runner_core.run_phase2_stoich_pipeline',side_effect=accept):run_optional_model(run,run,{'phase2_stoich':{'model_enabled':True}},manifest)
   self.assertEqual(manifest['model_status'],'complete')

 def test_model_failure_preserves_scientific_labels(self):
  from backend.analysis_engine.hvg_research.reporting import run_optional_model
  from backend.analysis_engine.hvg_research.artifacts import atomic_json,digest
  with TemporaryDirectory() as t:
   run=Path(t);ctx=run/'contexts/global';(ctx/'labels').mkdir(parents=True)
   pd.DataFrame({'gene_id':['g1','g2'],'is_hvg':[True,False],'hvg_score':[2.,1.]}).to_csv(ctx/'labels/baseline.csv',index=False)
   atomic_json(ctx/'labels/hvg_method_manifest.json',{'backend':'scanpy'})
   before=digest(ctx/'labels/baseline.csv');manifest={'analysis_run_id':'fixture','contexts':[{'directory':'contexts/global'}]}
   with patch('backend.analysis_engine.phase2.runner_core.run_phase2_stoich_pipeline',side_effect=RuntimeError('injected model failure')):
    result=run_optional_model(run,run,{'phase2_stoich':{'model_enabled':True}},manifest)
   self.assertEqual(result['status'],'failed');self.assertEqual(manifest['model_status'],'failed');self.assertEqual(digest(ctx/'labels/baseline.csv'),before)


from django.test import TestCase
class WorkloadPreflightTests(TestCase):
 def test_real_backed_input_budget_no_scientific_truncation(self):
  import anndata as ad
  from backend.analysis_engine.hvg_research.preflight import workload_estimate
  from backend.analysis_engine.hvg_research.config import validate_config
  with TemporaryDirectory() as t:
   path=Path(t)/'input.h5ad';ad.AnnData(np.ones((3,7))).write_h5ad(path)
   result=workload_estimate({'input_adapter':{'input_dir':t,'expression':{'format':'h5ad','file':'input.h5ad'}}},validate_config(), 'not_registered_fixture',None)
   self.assertEqual((result['input_cells'],result['input_genes_before_QC']),(3,7));self.assertEqual(result['audited_core_fields'],309);self.assertEqual(result['requested_core_upper_bound'],309);self.assertEqual(result['gsea_permutations'],1000);self.assertEqual(result['source_terms_before_mapping_and_size_filter'],0)
   path.unlink();self.assertFalse(path.exists())
