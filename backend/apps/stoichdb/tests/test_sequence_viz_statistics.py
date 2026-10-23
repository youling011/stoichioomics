import unittest
import numpy as np
from scipy.stats import gaussian_kde,spearmanr
from backend.apps.stoichdb.sequence_viz.statistics import profile,kde,conditional,pareto,native,smooth_contours,correlation
from backend.apps.stoichdb.sequence_viz.ordination import fit,cluster
from backend.apps.stoichdb.sequence_viz.composition import counts,clr
from backend.apps.stoichdb.sequence_viz.contracts import scientific_mask,FIGURES,CORE,META
class Statistics(unittest.TestCase):
    def test_all_original_columns_and_positions(self):
        self.assertEqual(len(FIGURES),68);self.assertEqual(len(CORE['genome']),146);self.assertEqual(len(CORE['transcriptome']),74);self.assertEqual(len(CORE['genome'])+len(META['genome'])+len(CORE['transcriptome'])+len(META['transcriptome']),246)
    def test_zero_negative_missing_constant(self):
        p=profile(np.array([-5.,0.,0.,4.,np.nan]));self.assertEqual(p['n_valid'],4);self.assertEqual(p['n_zero'],2);self.assertEqual(sum(p['histogram']['counts']),4);self.assertEqual(p['ecdf']['cdf'][-1],1);self.assertEqual(profile(np.zeros(7))['histogram']['kind'],'point_mass')
    def test_scott_full_n_and_word_grid(self):
        a=np.repeat([0.,.3,1.,4.],[9,30,7,2]);r=kde(a);expected=gaussian_kde(a)(r['x']);np.testing.assert_allclose(r['density'],expected,rtol=1e-12,atol=1e-12);self.assertEqual(r['x'][0],a.min());self.assertEqual(r['x'][-1],a.max());self.assertEqual(len(r['x']),128)
    def test_rank_one_and_rank_zero(self):
        info,s,valid,x=fit(np.ones((9,3)));self.assertEqual(info['reason_code'],'constant_matrix');info,s,valid,x=fit(np.column_stack([np.arange(9)]*3));self.assertEqual(info['rank'],1);self.assertEqual(s.shape,(9,1));self.assertEqual(info['status'],'partial')
    def test_pca_all_rows_and_centered(self):
        rng=np.random.default_rng(17);a=rng.poisson(3,(7013,16)).astype(float);info,s,valid,x=fit(a,composition=True);self.assertEqual(len(s),7013);np.testing.assert_allclose(s.mean(0),0,atol=1e-12);np.testing.assert_allclose(x.sum(1),0,atol=1e-12)
    def test_quantile_ties_constant_and_members(self):
        for a in [np.zeros(57),np.repeat([0.,1.,2.],[17,21,49])]:
            groups=conditional(a,np.arange(len(a)),10);self.assertEqual(sum(g['n'] for g in groups),len(a));members=np.concatenate([g['_members'] for g in groups]);self.assertEqual(sorted(members),list(range(len(a))))
    def test_correlations_undefined_not_zero(self):
        self.assertIsNone(correlation([0]*8,list(range(8)))['rho']);self.assertAlmostEqual(correlation([1,2,2,4],[4,2,2,1])['rho'],spearmanr([1,2,2,4],[4,2,2,1]).statistic)
    def test_pareto_exact_ties(self):
        x=np.array([1,1,2,3,4,4,5,np.nan]);y=np.array([3,3,2,4,4,5,4,7]);np.testing.assert_array_equal(pareto(x,y),[True,True,False,True,False,True,False,False])
    def test_native_constant_fallback_is_one(self):
        a=np.array([0.,0.,0.,0.,10.]);np.testing.assert_allclose(native(a),a)
    def test_condition_only_targeted_fields(self):
        v={'coding_valid':np.array([0,1,0]),'aa_len':np.array([0,3,0]),'codon_valid_codons':np.array([0,3,0])};self.assertTrue(scientific_mask(v,['gc_content','atoms_per_nt_N'],'transcriptome',3).all());np.testing.assert_array_equal(scientific_mask(v,['protein_gravy'],'transcriptome',3),[False,True,False]);np.testing.assert_array_equal(scientific_mask(v,['codon_entropy_bits'],'genome',3),[False,True,False])
    def test_smooth_count_mass_conservation(self):
        rng=np.random.default_rng(8);a=rng.normal(size=(8000,2));c=smooth_contours(a[:,0],a[:,1]);self.assertEqual(c['grid'],[70,70]);self.assertEqual(c['n_fit'],8000);self.assertEqual(c['sigma'],1.2);self.assertEqual(len(c['paths']),3);self.assertTrue(all(p['region_mass']>=p['mass'] for p in c['paths']))
    def test_invalid_counts_and_reconstruction(self):
        v={'fA':np.array([.5,.5,.5]),'fB':np.array([.5,.5,.5]),'total':np.array([4,3,0])};a,info=counts(v,['cA','cB'],['fA','fB'],'total',3);np.testing.assert_array_equal(a[0],[2,2]);self.assertTrue(np.isnan(a[1:]).all());self.assertEqual(info['n_valid'],1)
    def test_direct_reconstruction_conflicts_excluded(self):
        v={'fA':np.array([.5]),'fB':np.array([.5]),'total':np.array([4]),'cA':np.array([1]),'cB':np.array([3])};a,info=counts(v,['cA','cB'],['fA','fB'],'total',1);self.assertTrue(np.isnan(a).all());self.assertEqual(info['conflict_n'],1)
    def test_standard_aa_not_redistributed(self):
        v={'fA':np.array([.3]),'fB':np.array([.2]),'total':np.array([10])};a,info=counts(v,['a','b'],['fA','fB'],'total',1,True);np.testing.assert_array_equal(a,[[3,2]])
    def test_cluster_not_projection(self):
        a=np.column_stack([np.arange(30),np.sin(np.arange(30)),np.cos(np.arange(30))]);labels,info=cluster(a,np.arange(30));self.assertEqual(len(labels),30);self.assertEqual(info['fit_dimensions'],3);self.assertEqual(sum(info['counts']),30);self.assertIsNone(cluster(np.ones((10,3)),np.arange(10))[0])
