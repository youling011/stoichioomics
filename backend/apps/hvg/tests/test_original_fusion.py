import json,tempfile,hashlib
from pathlib import Path
import pandas as pd
from django.test import SimpleTestCase
from backend.analysis_engine.hvg_research.artifacts import atomic_frame,atomic_json
from backend.apps.hvg.research_visuals import visuals,SECTIONS
from backend.apps.hvg.research_services import read_table
from backend.apps.hvg.research_originals import ORIGINAL_PLOTS

class OriginalFusionTests(SimpleTestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.run=Path(self.tmp.name)/'hvg_functional_comparison/runs/fixture';self.run.mkdir(parents=True)
  self.m={'analysis_run_id':'fixture','contexts':[{'context_id':'global','directory':'contexts/global'},{'context_id':'subset','directory':'contexts/subset'}],'model_status':'completed','stages':{'official_hvg':{'execution_status':'completed','scientific_status':'completed','seconds':2}}}
  atomic_frame(self.run/'labels/hvg_labels.parquet',pd.DataFrame({'gene_id':['a','b','c'],'context_id':'global','is_hvg':[True,True,False],'hvg_rank':[1,2,3],'mean_expr':[0,2,3],'hvg_score':[.2,9,.1],'pct_cells_detected':[0,.5,1.],'dropout_rate':[1.,.5,0.]}))
  atomic_frame(self.run/'features/feature_evidence_summary.parquet',pd.DataFrame({'feature_key':['proteome::f'],'context_id':'global','omics':'proteome','family':'composition','effect':[0.],'q_global':[.01]}))
  atomic_frame(self.run/'features/adjusted_feature_tests.parquet',pd.DataFrame({'feature_key':['proteome::f'],'context_id':'global','model':'expression_detection_length','beta':[0.],'q_global':[.2]}))
  self.csv('work/analysis_phase2/hvg_stoich_scores.csv',[{'gene_id':'a','stoich_class':'explained','stoich_excess_var':0.},{'gene_id':'b','stoich_class':'excess','stoich_excess_var':1.}])
  atomic_json(self.run/'work/analysis_phase2/plots_payload.json',{'class_bar':[{'stoich_class':'explained','count':1},{'stoich_class':'excess','count':1}],'expected_observed_scatter':[{'gene_id':'a','stoich_expected_var':0.,'observed_hvg_signal':0.}]})
 def csv(self,rel,rows):
  p=self.run/rel;p.parent.mkdir(parents=True,exist_ok=True);pd.DataFrame(rows).to_csv(p,index=False)
 def visual(self,k,**params):return visuals(self.run,self.m,k,{'context_id':'global',**params})
 def test_original_questions_are_in_each_existing_section(self):
  self.assertEqual(len(SECTIONS),10)
  for section,kinds in ORIGINAL_PLOTS.items():self.assertTrue(set(kinds)<=set(SECTIONS[section]['plots']))
 def test_top_HVG_uses_saved_rank_not_sorted_score(self):
  p=self.visual('original_top_hvg');self.assertEqual([r['gene_id'] for r in p['rows']],['a','b']);self.assertEqual([r['value'] for r in p['rows']],[.2,9])
 def test_zero_detection_and_mean_are_retained(self):
  p=self.visual('original_dropout');self.assertEqual(p['rows'][0]['pct_cells_detected'],0)
  self.assertIn('a',[r['gene_id'] for r in self.visual('original_mean_score')['rows']])
 def test_unrecorded_detection_has_explicit_reason(self):
  atomic_frame(self.run/'labels/hvg_labels.parquet',pd.DataFrame({'gene_id':['a'],'context_id':'global','is_hvg':[True],'hvg_rank':[1]}))
  p=self.visual('original_dropout');self.assertEqual(p['rows'],[]);self.assertIn('not recorded',p['reason'])
 def test_raw_adjusted_keeps_zero_and_missing_scale(self):
  p=self.visual('original_raw_adjusted');self.assertEqual(p['rows'][0]['effect'],0);self.assertEqual(p['rows'][0]['beta'],0)
 def test_global_prediction_not_borrowed_by_subset(self):
  p=self.visual('original_expected_observed',context_id='subset');self.assertFalse(p['rows']);self.assertIn('global only',p['reason'])
 def test_zero_predictions_and_full_residuals(self):
  p=self.visual('original_expected_observed');self.assertEqual(p['rows'][0]['stoich_expected_var'],0);self.assertTrue(p['identity_line'])
  p=self.visual('original_residuals');self.assertEqual(p['total'],2);self.assertEqual(sum(r['value'] for r in p['rows']),2)
 def test_prediction_class_navigation_filters_saved_scores(self):
  f=read_table(self.run,'original_model_scores',{'context_id':'global','stoich_class':'excess'});self.assertEqual(f.gene_id.tolist(),['b'])
 def test_candidate_ORA_retains_its_own_query_and_FDR(self):
  self.csv('work/downstream/functional_enrichment_top_terms.csv',[{'term_id':'GO:1','source':'GO','query_label':'original_candidates','fdr_bh':.2,'status':'generated'}])
  p=self.visual('original_candidate_enrichment');self.assertEqual(p['rows'][0]['original_q'],.2);self.assertEqual(p['scope'],'candidate_score_branch')
 def test_missing_PPI_keeps_reason_in_table(self):
  f=read_table(self.run,'original_ppi',{'context_id':'global'});self.assertEqual(f.iloc[0]['status'],'not_generated');self.assertIn('ppi_module_enrichment',f.iloc[0]['reason'])
 def test_metadata_with_mixed_nested_values_is_readable(self):
  atomic_json(self.run/'work/standardized/input_validation_report.json',{'input_ok':True,'details':{'n':3,'field':'count'},'warnings':[1,'sparse',{'missing':False}]})
  f=read_table(self.run,'original_input_qc',{'context_id':'global'});self.assertEqual(json.loads(f.iloc[0]['warnings'])[2],{'missing':False})
 def test_unknown_context_cannot_read_a_global_chart(self):
  with self.assertRaisesRegex(ValueError,'Unknown analysis context'):self.visual('original_top_hvg',context_id='foreign')
 def test_original_visuals_never_rewrite_saved_evidence(self):
  def hashes():return {str(p.relative_to(self.run)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.run.rglob('*') if p.is_file()}
  before=hashes()
  for kinds in ORIGINAL_PLOTS.values():
   for k in kinds:self.visual(k)
  self.assertEqual(hashes(),before)
