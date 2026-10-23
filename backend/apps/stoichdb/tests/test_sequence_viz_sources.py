from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import numpy as np
from backend.apps.stoichdb.sequence_viz.source import load,frame
class Sources(TestCase):
    def setUp(self):self.tmp=TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def fixture(self,core,full):
        cp=self.root/'core.csv';fp=self.root/'full.csv';cp.write_text(core,encoding='utf8');fp.write_text(full,encoding='utf8');return SimpleNamespace(core_path=cp,full_path=fp,dataset=SimpleNamespace(dataset_id='fixture',row_count_core=2,row_count_full=0,full_csv_path=str(fp)))
    def runload(self,ds,m='genome',scope='core'):
        with patch('backend.apps.stoichdb.sequence_viz.source.CompleteCoreDataSource',return_value=ds),patch('backend.apps.stoichdb.sequence_viz.source.release_id',return_value='fixture'):return load('species',m,scope)
    def test_strict_left_order_null_preservation_and_extra_rows(self):
        ds=self.fixture('gene_id,gene_name,locus_gc_percent\n0001,NA,\n0002,Name,0\n','gene_id,gene_name,locus_gc_percent,extra\n0002,Name,1,7\n0003,Other,3,9\n0001,NA,5,8\n');r=self.runload(ds);self.assertEqual(r['ids'],['0001','0002']);self.assertEqual(r['metadata']['gene_name'][0],'NA');self.assertTrue(np.isnan(r['values']['locus_gc_percent'][0]));self.assertEqual(r['values']['locus_gc_percent'][1],0);np.testing.assert_array_equal(r['values']['extra'],[8,7]);self.assertEqual(r['n'],2);self.assertTrue(r['source']['registry_count_mismatch']);self.assertEqual(r['source']['same_name_conflicts']['locus_gc_percent']['n'],1)
    def test_full_is_independent_population(self):
        ds=self.fixture('gene_id,locus_gc_percent\na,1\nb,2\n','gene_id,locus_gc_percent\nb,20\na,10\nc,30\n');r=self.runload(ds,scope='full');self.assertEqual(r['n'],3);self.assertEqual(r['ids'],['b','a','c']);np.testing.assert_array_equal(r['values']['locus_gc_percent'],[20,10,30])
    def test_duplicate_full_never_keep_first(self):
        ds=self.fixture('gene_id,locus_gc_percent\na,1\nb,2\n','gene_id,locus_gc_percent\na,10\na,20\n')
        with self.assertRaisesRegex(ValueError,'duplicate_gene_id'):self.runload(ds)
    def test_rna_no_gene_fallback_or_version_removal(self):
        ds=self.fixture('transcript_id,gene_id,gc_content\nT.1,G,0\nT.2,G,1\n','transcript_id,gene_id,gc_content\nT.2,G,1\nT.1,G,0\n');r=self.runload(ds,'transcriptome');self.assertEqual(r['ids'],['T.1','T.2']);ds.core_path.write_text('transcript_id,gene_id,gc_content\n,G,1\n',encoding='utf8')
        with self.assertRaisesRegex(ValueError,'empty_transcript_id'):self.runload(ds,'transcriptome')
    def test_unknown_numeric_and_literal_text_columns_retained(self):
        ds=self.fixture('gene_id,locus_gc_percent,new_numeric,new_annotation\na,0,7,NA\nb,1,-9,other\n','gene_id,locus_gc_percent\na,0\nb,1\n');r=self.runload(ds);self.assertIn('new_numeric',r['fields']);self.assertIn('new_annotation',r['metadata']);self.assertEqual(len([r for r in r['catalog'] if r['primary']]),4)
