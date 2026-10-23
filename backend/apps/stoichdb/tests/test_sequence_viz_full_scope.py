import unittest
import numpy as np
from backend.apps.stoichdb.sequence_viz.full_scope import apply
class FullEligibility(unittest.TestCase):
    def fixture(self):return {'omics':'genome','scope':'full','n':4,'values':{'is_coding':np.array([1,1,0,1]),'codon_total_valid':np.array([4,0,4,4]),'aa_total_20':np.array([3,0,3,3])},'metadata':{},'catalog':[],'source':{}}
    def test_full_predicate_uses_only_full_rows(self):
        ds=self.fixture();apply(ds);np.testing.assert_array_equal(ds['values']['coding_valid'],[1,0,0,1]);self.assertEqual(ds['source']['full_coding_eligibility']['n_eligible'],2);self.assertFalse(ds['catalog'][0]['primary'])
    def test_existing_flag_including_missing_is_never_filled(self):
        ds=self.fixture();ds['values']['coding_valid']=np.array([np.nan,0,1,0]);apply(ds);self.assertTrue(np.isnan(ds['values']['coding_valid'][0]));self.assertEqual(ds['values']['coding_valid'][2],1);self.assertNotIn('full_coding_eligibility',ds['source'])
    def test_core_not_changed(self):
        ds=self.fixture();ds['scope']='core';apply(ds);self.assertNotIn('coding_valid',ds['values'])
