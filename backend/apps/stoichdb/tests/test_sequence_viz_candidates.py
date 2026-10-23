import unittest
import numpy as np
from backend.apps.stoichdb.sequence_viz.candidates import rank
class CandidateRanks(unittest.TestCase):
    def test_ineligible_raw_zero_is_not_an_available_module_score(self):
        from backend.apps.stoichdb.sequence_viz.candidates import module_score
        v={'orf_len_aa':np.array([0.,5.,10.]),'orf_len_aa_percentile':np.array([np.nan,50,100]),'score_module_coverage':np.array([3,6,6])};self.assertTrue(np.isnan(module_score(v,'orf_len_aa')[0]));order,_,_=rank(v,['a','b','c'],'transcriptome',module='orf_len_aa');self.assertEqual(order.tolist(),[2,1,0]);self.assertEqual(v['orf_len_aa'][0],0)
    def fixture(self):return {'resource_score':np.array([2.,5.,5.,5.,0.,np.nan]),'resource_score_percentile':np.array([40.,80.,80.,80.,20.,np.nan]),'score_module_coverage':np.array([6,6,5,6,0,0])}
    def test_ties_retain_all_at_cutoff_and_stable_ids(self):
        order,ranks,detail=rank(self.fixture(),['z','c','a','b','0','x'],'transcriptome',top_ties=1);self.assertEqual(order.tolist(),[2,3,1]);self.assertEqual(detail['tie_cutoff_raw'],5);self.assertEqual(ranks[2],1)
    def test_full_rank_preserved_for_partial_subset(self):
        order,ranks,detail=rank(self.fixture(),['z','c','a','b','0','x'],'transcriptome',coverage='partial');self.assertEqual(order.tolist(),[2,4,5]);self.assertEqual(ranks[4],5);self.assertEqual(detail['rank_population_n'],6)
    def test_constant_top_keeps_every_tied_member(self):
        v={'resource_score':np.zeros(83),'score_module_coverage':np.full(83,6)};order,_,d=rank(v,[str(i) for i in range(83)],'transcriptome',top_ties=3);self.assertEqual(len(order),83);self.assertEqual(d['tie_cutoff_raw'],0)
    def test_undefined_not_zero_candidate(self):
        v={'resource_score':np.full(5,np.nan),'score_module_coverage':np.zeros(5)};order,_,d=rank(v,['a','b','c','d','e'],'transcriptome',top_ties=3);self.assertEqual(len(order),0);self.assertIsNone(d['tie_cutoff_raw'])
