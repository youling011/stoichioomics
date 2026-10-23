import unittest,warnings
import numpy as np
from backend.apps.stoichdb.sequence_viz.builders import build
from backend.apps.stoichdb.sequence_viz.contracts import words,DNA
class CompleteSourceViews(unittest.TestCase):
    def test_raw_full_counts_zero_survive_analysis_ineligibility(self):
        n=4;values={'coding_valid':np.array([0.,0.,1.,1.]),'codon_total_valid':np.array([0.,0.,2.,2.]),'start_1':np.arange(n,dtype=float),'end_1':np.arange(n,dtype=float)+10,'locus_dinuc_total_valid':np.ones(n)}
        for w in words(DNA,3):values['codon_'+w+'_count']=np.array([0.,0.,2. if w=='AAA' else 0.,2. if w=='AAA' else 0.]);values['codon_'+w+'_freq']=np.array([0.,0.,1. if w=='AAA' else 0.,1. if w=='AAA' else 0.])
        fields=list(values);ds={'species_id':'fixture','omics':'genome','scope':'full','dataset_id':'fixture','release_id':'fixture','source_hash':'fixture','ids':['g0','g1','g2','g3'],'key':'gene_id','n':n,'fields':fields,'catalog':[{'key':k,'role':'numeric','primary':True} for k in fields],'values':values,'metadata':{'gene_id':['g0','g1','g2','g3'],'seqid':['s']*n},'source':{'invalid_counts':{},'same_name_conflicts':{}},'available_scopes':['core','full']}
        with warnings.catch_warnings():warnings.simplefilter('ignore',RuntimeWarning);result=build(ds)
        p=result['profiles']['codon_AAA_count'];self.assertEqual(p['n_valid'],4);self.assertEqual(p['n_zero'],2);np.testing.assert_array_equal(ds['values']['codon_AAA_count'],[0,0,2,2]);self.assertEqual(result['figures']['GD11']['coverage']['n_fit'],2);self.assertEqual(len(result['figures']),35)
