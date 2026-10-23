from django.test import SimpleTestCase
import numpy as np
from scipy.stats import gaussian_kde
from backend.apps.stoichdb.proteome_viz.statistics import summary,ecdf,histogram,conditional,correlation,robust,percentile
from backend.apps.stoichdb.proteome_viz.density import hexbin,kde1,kde2
from backend.apps.stoichdb.proteome_viz.ordination import pca,cohort
from backend.apps.stoichdb.proteome_viz.contracts import FINGERPRINT
from backend.apps.stoichdb.proteome_viz.work_requests import process_alive
import os

class StatisticsTests(SimpleTestCase):
    def test_zero_missing_negative_constant(self):
        p=summary([0,0,-1,np.nan,np.inf]);self.assertEqual((p['n_valid'],p['n_missing'],p['n_zero']),(3,2,2));self.assertEqual(summary([0,0,0])['fallback'],'constant');self.assertIsNone(summary([np.nan])['mean'])
    def test_exact_ecdf_and_count_conservation(self):
        self.assertEqual(ecdf([0,0,2],False)['cdf'],[2/3,1]);self.assertEqual(sum(histogram([0,0,2])['counts']),3)
        h=histogram([-1,0,1,10,100],True);self.assertEqual(sum(h['counts']),3);self.assertEqual(h['invalid_nonpositive'],2)
    def test_average_ties_and_large_population(self):
        self.assertAlmostEqual(correlation([0,0,1,2],[3,3,5,8])['rho'],1);self.assertIsNone(correlation([0,0,0],[1,2,3])['rho'])
        a=np.arange(200001,dtype=float);self.assertAlmostEqual(correlation(a,a[::-1])['rho'],-1)
    def test_tied_strata_not_split_and_hex_members_conserve(self):
        x=np.r_[np.zeros(40),np.ones(60)];y=np.arange(100.);groups=conditional(x,y,10);self.assertEqual(sum(g['n'] for g in groups),100);self.assertLess(len(groups),10)
        h=hexbin(x,y);self.assertEqual(sum(b['count'] for b in h['bins']),100)
        for b in h['bins']:self.assertEqual(int((h['membership']==b['index']).sum()),b['count'])
    def test_mad_sd_fallback_and_infinity(self):
        z,meta=robust([0,0,0,2,np.inf]);self.assertEqual(meta['fallback'],['SD']);self.assertTrue(np.isnan(z[-1]));self.assertEqual(percentile([0,0,0]).tolist(),[200/3]*3)
    def test_centered_pca_and_degenerate_guards(self):
        x=np.array([[10,8],[11,10],[13,9],[9,12]],float);p=pca(x);self.assertTrue(np.allclose(p['coordinates'].mean(0),0,atol=1e-12));self.assertEqual(p['n'],4)
        self.assertEqual(pca([[1,1]]*4)['status'],'unavailable');self.assertEqual(pca([[1,2],[2,4],[3,6],[4,8]])['status'],'partial')
    def test_kde_is_full_gaussian_fit(self):
        x=np.random.default_rng(82).normal(size=900);p=kde1(x);expected=gaussian_kde(x)(p['x']);self.assertTrue(np.allclose(p['density'],expected,rtol=1e-10,atol=1e-12));self.assertEqual(p['n'],900)
        y=.3*x+np.random.default_rng(83).normal(size=900);d=kde2(x,y);self.assertEqual(d['status'],'available');self.assertLess(abs(d['integral']-1),.005);self.assertEqual(d['n'],900);self.assertEqual([r['mass'] for r in d['paths']],[.5,.8,.95])
        self.assertEqual(kde2(x,x)['reason'],'rank_lt_two')
    def test_shared_cohort_distance_and_native_context(self):
        rows=[{'species_id':str(i),'means':{f:10.+i*(j+1) for j,f in enumerate(FINGERPRINT)}} for i in range(5)];r=cohort(rows);self.assertTrue(np.allclose(r['distance'],r['distance'].T));self.assertTrue(np.all(np.diag(r['distance'])==0));self.assertEqual(len(r['raw_summary']),11)
    def test_process_liveness_does_not_signal_windows_process(self):
        self.assertTrue(process_alive(os.getpid()));self.assertFalse(process_alive(-1))
    def test_numerical_point_mass_does_not_make_zero_width_bins(self):
        a=np.array([1.,np.nextafter(1.,2.),1.]);self.assertEqual(histogram(a)['kind'],'point_mass');self.assertEqual(kde1(a)['kind'],'point_mass');self.assertEqual(sum(histogram(a)['counts']),3)
