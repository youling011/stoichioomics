from pathlib import Path
import tempfile
import pandas as pd
import numpy as np
from django.test import TestCase
from backend.apps.stoichdb.models import Species,OmicsDataset
from backend.apps.stoichdb.proteome_viz.source import load
from backend.apps.stoichdb.proteome_viz.contracts import AA

class SourceFixture:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='proteome_source_test_');self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)
        self.core=pd.read_csv(Path(__file__).parent/'fixtures'/'proteome_viz_core12.csv',keep_default_na=False);self.core.protein_id=self.core.protein_id.astype(str)
        self.full=self.core.copy();length=pd.to_numeric(self.core.length_aa)
        for a in AA:self.full[f'AA_{a}_count']=np.rint(pd.to_numeric(self.core[f'AA_{a}_pct'])*length/100)
        self.full['length_canonical_aa']=length;self.full['unknown_residues_for_atoms']=0;self.full['stop_asterisk_count']=0
        self.full['ss_helix_frac']=.3;self.full['ss_turn_frac']=.1;self.full['ss_sheet_frac']=.2;self.full['flex_mean']=np.linspace(.1,.3,len(self.full));self.full['flex_std']=.02;self.full['surface_access_em_mean']=np.linspace(.2,.6,len(self.full))
        self.core_path=self.path/'core.csv';self.full_path=self.path/'full.csv';self.write()
        self.species=Species.objects.create(species_id='proteome_unit_species',display_name='Unit fixture',domain='Bacteria')
        self.dataset=OmicsDataset.objects.create(species=self.species,dataset_id='proteome_unit_dataset',omics_type='proteome',core_csv_path=str(self.core_path),full_csv_path=str(self.full_path),row_count_core=len(self.core),row_count_full=0)
    def write(self):self.core.to_csv(self.core_path,index=False);self.full.to_csv(self.full_path,index=False)
class SourceTests(SourceFixture,TestCase):
    def test_full_registration_zero_does_not_hide_real_file(self):
        d=load(self.species.species_id);self.assertEqual(d['source']['actual_full_n'],12);self.assertEqual(d['available_scopes'],['core','full']);self.assertEqual(d['source']['registered_full_n'],0)
    def test_strict_left_join_does_not_replace_core_or_fill_missing(self):
        self.full.loc[0,'C_atoms']=float(self.full.loc[0,'C_atoms'])+1;extra=self.full.iloc[[0]].copy();extra.protein_id='extra_full_record';self.full=pd.concat([self.full,extra],ignore_index=True);self.core.loc[1,'N_S_ratio']='';self.full.loc[1,'N_S_ratio']=50;self.write()
        d=load(self.species.species_id);self.assertEqual(d['n'],12);self.assertNotIn('extra_full_record',d['ids']);self.assertEqual(d['values']['C_atoms'][0],float(self.core.C_atoms.iloc[0]));self.assertTrue(np.isnan(d['values']['N_S_ratio'][1]));self.assertEqual(d['source']['conflicts']['C_atoms'],1);self.assertEqual(load(self.species.species_id,'full')['n'],13)
    def test_duplicate_id_fails_explicitly(self):
        self.full=pd.concat([self.full,self.full.iloc[[0]]]);self.write()
        with self.assertRaisesRegex(ValueError,'duplicate_protein_id'):load(self.species.species_id)
    def test_missing_full_preserves_core_and_reconstructs_counts(self):
        self.dataset.full_csv_path='';self.dataset.save(update_fields=['full_csv_path']);d=load(self.species.species_id);self.assertEqual(d['n'],12);self.assertTrue(np.isfinite(d['values']['AA_A_count']).all());self.assertNotIn('flex_mean',d['values'])
    def test_identifier_strings_and_semantic_invalid_reasons(self):
        self.core.loc[0,'protein_id']='0000123.04';self.full.loc[0,'protein_id']='0000123.04';self.core.loc[1,'gene_symbol']='NA';self.core.loc[2,'C_atoms']=-1;self.write();d=load(self.species.species_id);self.assertEqual(d['ids'][0],'0000123.04');self.assertEqual(d['metadata']['gene_symbol'][1],'NA');self.assertTrue(np.isnan(d['values']['C_atoms'][2]));self.assertEqual(d['source']['semantic_invalid_counts']['C_atoms'],1)
    def test_resource_hydrogen_uses_primary_core_atoms(self):
        self.full['H_atoms_per_aa']=999.;self.write();d=load(self.species.species_id);self.assertTrue(np.allclose(d['values']['H_atoms_per_aa'],pd.to_numeric(self.core.H_atoms)/pd.to_numeric(self.core.length_aa)))
