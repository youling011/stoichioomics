import tempfile,json,hashlib
from pathlib import Path
from unittest.mock import patch
import numpy as np,pandas as pd
from scipy import sparse,stats
from django.test import SimpleTestCase,TestCase,TransactionTestCase,override_settings
from backend.analysis_engine.common import ExpressionDataset
from backend.analysis_engine.hvg_research.primary_hvg import official_hvg
from backend.analysis_engine.hvg_research.config import validate_config,deep_merge
from backend.analysis_engine.hvg_research.artifacts import atomic_json,atomic_frame,safe_path,member_hash
from backend.analysis_engine.hvg_research.contracts import GeneUniverse
from backend.analysis_engine.hvg_research.statistics import rank_test,glm,fdr
from backend.analysis_engine.hvg_research.enrichment import ora
from backend.analysis_engine.hvg_research.locking import run_lock,RunConflict
class ScientificContracts(SimpleTestCase):
 def dataset(self):
  rng=np.random.default_rng(10);X=sparse.csr_matrix(rng.poisson(rng.gamma(1,2,600),(120,600)));obs=pd.DataFrame({'cell_id':[f'c{i}' for i in range(120)],'batch':['a']*60+['b']*60})
  return ExpressionDataset(X,[f'g{i}' for i in range(600)],[f'g{i}' for i in range(600)],obs.cell_id.tolist(),obs,{'matrix_semantics':'counts'})
 def test_T01_official_all_flavors_and_batch_oracle(self):
  import scanpy as sc
  for method in ['seurat_v3','seurat_v3_paper','seurat','cell_ranger']:
   d=self.dataset()
   if method in ['seurat','cell_ranger']:
    d.matrix=d.matrix.astype(float);d.matrix.data=np.log1p(d.matrix.data);d.uns['matrix_semantics']='log_normalized'
   L,E,A,M=official_hvg(d,{'hvg_method':method,'n_top_genes':50,'batch_key':'batch','min_cells':3,'min_counts':1})
   oracle=sc.pp.highly_variable_genes(A,**M['parameters'])
   np.testing.assert_array_equal(L.is_hvg,oracle.highly_variable)
   if 'highly_variable_rank' in oracle:np.testing.assert_allclose(L.highly_variable_rank,oracle.highly_variable_rank,equal_nan=True)
 def test_T01_wrong_semantics_and_unknown_flavor_rejected(self):
  d=self.dataset()
  with self.assertRaises(ValueError):official_hvg(d,{'hvg_method':'invented'})
  with self.assertRaises(ValueError):official_hvg(d,{'hvg_method':'seurat'})
  d.matrix=d.matrix.astype(float);d.matrix.data[0]+=.2
  with self.assertRaises(ValueError):official_hvg(d,{'hvg_method':'seurat_v3'})
 def test_T02_explicit_sparse_zero_and_QC_failure(self):
  from backend.analysis_engine.phase1.utils import filter_low_quality_genes
  d=self.dataset();d.matrix=sparse.csr_matrix(([0.,4.],([0,1],[0,1])),shape=d.matrix.shape)
  filtered,_=filter_low_quality_genes(d,min_cells=1,min_counts=0)
  self.assertEqual(filtered.gene_ids,['g1'])
 def test_T02_duplicate_gene_rejected(self):
  d=self.dataset();d.gene_ids[1]=d.gene_ids[0]
  with self.assertRaises(ValueError):official_hvg(d,{})
 def test_T03_official_labels_independent_of_stoich_config(self):
  d=self.dataset();a=official_hvg(d,{'n_top_genes':50})[0];b=official_hvg(d,{'n_top_genes':50,'model_enabled':False,'stoich':None})[0]
  np.testing.assert_array_equal(a.is_hvg,b.is_hvg)
 def test_T04_all_registry_snapshot_not_hardcoded_309(self):
  from backend.apps.hvg.feature_context import _load_registry
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'snapshot.json';fields=[{'omics':'genome','scope':'core','field':f'new{i}'} for i in range(310)];atomic_json(p,{'fields':fields});reg,_,_=_load_registry({'registry_snapshot_path':str(p)})
   self.assertEqual(len(reg['fields']),310)
 def test_T06_canonical_units_and_column_scaling(self):
  from backend.analysis_engine.hvg_research.preprocessing import canonicalize,scale_column
  a=np.array([1.,3.,7.,9.]);b,u=canonicalize(a/1000,'kb');np.testing.assert_allclose(b,a)
  np.testing.assert_allclose(scale_column(a),scale_column(a*1e9));np.testing.assert_allclose(canonicalize(a*10,'%')[0],a/10)
 def test_T07_complete_composition_ILR_and_incomplete_rejected(self):
  from backend.analysis_engine.hvg_research.preprocessing import composition_coordinates
  clr,ilr=composition_coordinates(np.array([[.2,.3,.5],[0,.4,.6]]));self.assertEqual(ilr.shape,(2,2));np.testing.assert_allclose(clr.sum(1),0,atol=1e-10)
  with self.assertRaises(ValueError):composition_coordinates(np.array([[.2,.3]]))
 def test_T08_effect_direction_ties_and_failed_GLM(self):
  r=rank_test(np.arange(30)+100,np.arange(30),boot=True,repeats=50);self.assertEqual(r['effect'],1);self.assertGreater(r['ci_low'],0)
  r=rank_test(np.ones(30),np.ones(30));self.assertEqual(r['effect'],0);self.assertEqual(r['p_value'],1)
  fit=glm(np.r_[np.zeros(30),np.ones(30)],np.ones((60,3)));self.assertEqual(fit['status'],'rank_deficient');self.assertTrue(np.isnan(fit['p_value']))
 def test_T09_ORA_hand_counts_zero_overlap_and_FDR(self):
  members=pd.DataFrame({'gene_id':['a','b','c','d'],'term_key':['t1','t1','t2','t2']});terms=pd.DataFrame([{'term_key':t,'term_id':t,'term_name':t,'source':'GO_BP'} for t in ['t1','t2']]);bg=set('abcdefghij')
  r=ora(set('ab'),bg,members,terms,min_term=1,max_term=10)
  self.assertEqual(r.k.tolist(),[2,0]);np.testing.assert_allclose(r.p_value,[stats.hypergeom.sf(1,10,2,2),1]);self.assertEqual(len(fdr(r.p_value)),2)
  with self.assertRaises(ValueError):ora({'outside'},bg,members,terms)
 def test_T11_nested_query_background_invariant(self):
  u=GeneUniverse('c',tuple('abcdef'),tuple('ab'));self.assertEqual(u.validate()['N'],4)
  with self.assertRaises(ValueError):GeneUniverse('c',('a',),('b',)).validate()
  self.assertEqual(member_hash(['b','a','a']),member_hash(['a','b']))
 def test_T13_actual_GSEA_direction_reversal(self):
  import gseapy.algorithm as ga
  if not hasattr(np,'in1d'):np.in1d=np.isin
  genes=[f'g{i}' for i in range(100)];score=np.linspace(2,-2,100);es,null,_,_=ga.enrichment_score(genes,score,genes[:20],nperm=50,seed=42)
  rev,_,_,_=ga.enrichment_score(genes[::-1],score,genes[:20],nperm=50,seed=42)
  self.assertGreater(es,0);self.assertLess(rev,0);self.assertEqual(len(null),50)
 def test_T18_exclusive_lock_and_atomic_JSON(self):
  with tempfile.TemporaryDirectory() as t:
   with run_lock(t):
    with self.assertRaises(RunConflict):
     with run_lock(t):pass
   p=Path(t)/'a.json';atomic_json(p,{'x':np.nan});self.assertIsNone(json.loads(p.read_text())['x'])
 def test_T21_traversal_absolute_and_long_unicode(self):
  with tempfile.TemporaryDirectory() as t:
   for bad in ['../other','C:/outside','a/../../b']:
    with self.assertRaises(ValueError):safe_path(t,bad)
   p=safe_path(t,'中文/'+('x'*180)+'.json');atomic_json(p,{'id':'基因/一'});self.assertTrue(p.is_file())
 def test_config_deep_merge_unknown_and_ranges(self):
  c=validate_config({'gene_sets':{'low_quantile':.1}});self.assertEqual(c['gene_sets']['high_quantile'],.8)
  for bad in [{'typo':1},{'pathway':{'gsea_permutations':0}},{'enabled':'yes'},{'execution':{'worker_count':2}}]:
   with self.assertRaises(ValueError):validate_config(bad)
class ResearchAPITests(TestCase):
 def setUp(self):
  from backend.apps.jobs.models import AnalysisJob
  from backend.apps.jobs.services import _token_hash
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name);self.token='fixture-token'
  self.job=AnalysisJob.objects.create(job_id='hvg_fixture_job',workspace_path=str(self.base),access_token_hash=_token_hash(self.token))
  run=self.base/'hvg_functional_comparison/runs/r1';self.run=run;run.mkdir(parents=True)
  atomic_json(self.base/'hvg_functional_comparison/active_run.json',{'analysis_run_id':'r1'})
  atomic_json(run/'run_manifest.json',{'analysis_run_id':'r1','schema_version':'hvg_research_v1','research_status':'complete','stages':{},'contexts':[],'artifacts':[{'artifact_id':'malicious','path':'../../secret','bytes':1}]})
  atomic_frame(run/'candidates/candidate_genes.parquet',pd.DataFrame({'gene_id':[f'基因{i:03}' for i in range(101)],'priority_rank':np.arange(101),'context_id':'global'}))
 def get(self,url,**params):return self.client.get('/api/hvg/hvg_fixture_job/research/'+url+'/',params,HTTP_X_JOB_TOKEN=self.token)
 def test_T17_authentication_before_run_access(self):
  self.assertEqual(self.client.get('/api/hvg/hvg_fixture_job/research/summary/').status_code,403)
  self.assertEqual(self.get('summary').status_code,200)
 def test_T17_all_pages_stable_and_invalid_parameters(self):
  seen=[]
  for p in range(1,4):
   r=self.get('candidates',page=p,page_size=50,sort='priority_rank').json()['data'];seen.extend(x['gene_id'] for x in r['rows'])
  self.assertEqual(len(set(seen)),101)
  self.assertEqual(self.get('candidates',sort='__dict__').status_code,400);self.assertEqual(self.get('candidates',page_size=201).status_code,400)
 def test_T17_cross_run_and_path_rejected(self):
  self.assertEqual(self.get('summary',analysis_run_id='../r2').status_code,400);self.assertEqual(self.get('summary',analysis_run_id='unowned').status_code,404);self.assertEqual(self.get('download/malicious').status_code,400)
 def test_T21_literal_query_unicode_and_empty(self):
  self.assertEqual(self.get('candidates',query='基因100').json()['data']['total'],1)
  self.assertEqual(self.get('candidates',query='.*').json()['data']['total'],0)
 def test_T18_duplicate_job_claim(self):
  from backend.apps.jobs.services import run_job_async
  self.job.status='RUNNING';self.job.save()
  with self.assertRaises(RunConflict):run_job_async(self.job)
class AnnotationReleaseTests(TransactionTestCase):
 def test_T10_release_and_species_isolation(self):
  from backend.apps.stoichdb.models import Species,GeneIndex,FunctionalAnnotationRelease,GOAnnotation
  from backend.apps.hvg.research_repository import annotation_snapshot
  species=Species.objects.create(species_id='test_hvg_species',display_name='fixture');GeneIndex.objects.create(species=species,gene_id='g1')
  a=FunctionalAnnotationRelease.objects.create(release_id='test_rel_a',label='A');b=FunctionalAnnotationRelease.objects.create(release_id='test_rel_b',label='B')
  GOAnnotation.objects.create(species=species,species_id_text=species.species_id,release=a,gene_id='g1',go_id='GO:A',go_name='chosen',go_namespace='biological_process')
  GOAnnotation.objects.create(species=species,species_id_text=species.species_id,release=b,gene_id='g1',go_id='GO:B',go_name='not chosen',go_namespace='biological_process')
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);atomic_frame(root/'labels/hvg_labels.parquet',pd.DataFrame({'gene_id':['g1'],'is_hvg':[True]}));out=annotation_snapshot(root,species.species_id,a.release_id,{'sources':['GO_BP']});members=pd.read_parquet(root/'annotations/gene_term_membership.parquet');self.assertEqual(set(members.term_id),{'GO:A'});self.assertEqual(out['evidence_code'],'unavailable_in_schema')
