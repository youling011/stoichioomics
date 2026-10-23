import unittest
import numpy as np
from backend.apps.stoichdb.sequence_viz.coordinates import apply
class CoordinateRules(unittest.TestCase):
    def test_duplicate_start_uses_gene_id_and_missing_never_becomes_zero(self):
        ds={'omics':'genome','n':5,'ids':['b','a','d','c','e'],'values':{'start_1':np.array([10,10,20,20,30.]),'end_1':np.array([11,90,21,22,31.]),'locus_count_G':np.array([4.,9.,np.nan,5.,-1]),'locus_count_C':np.array([1.,2.,0.,1.,0.])},'metadata':{'seqid':['s']*5},'source':{}};built={'arrays':{},'figures':{'GD02':{'data':{},'method':{'parameters':{}}}}};apply(ds,built);self.assertEqual(built['arrays']['GD02_order'].tolist(),[1,0,3,2,4]);np.testing.assert_allclose(built['arrays']['locus_gc_cumulative_count'][:4],[10,7,np.nan,14],equal_nan=True);self.assertTrue(np.isnan(built['arrays']['locus_gc_cumulative_count'][4]));self.assertEqual(built['figures']['GD02']['status'],'partial');self.assertEqual(ds['source']['coordinate_method']['n_valid_increments'],3)
    def test_all_missing_GC_is_unavailable_while_coordinates_remain(self):
        ds={'omics':'genome','n':2,'ids':['a','b'],'values':{'start_1':np.array([1.,10]),'end_1':np.array([4.,13])},'metadata':{'seqid':['s','s']},'source':{}};b={'arrays':{},'figures':{'GD02':{'data':{},'method':{'parameters':{}}}}};apply(ds,b);self.assertEqual(b['figures']['GD02']['status'],'unavailable');self.assertEqual(b['figures']['GD02']['data']['n_coordinates'],2);self.assertTrue(np.isnan(b['arrays']['locus_gc_cumulative_count']).all())
