"""Edge-case regression tests for the reference mathematics, using synthetic fixtures only."""
import sys, unittest, tempfile
from pathlib import Path
sys.dont_write_bytecode = True
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from backend.apps.stoichdb.integration_viz.statistics import robust,profile,distribution,conditional
from backend.apps.stoichdb.integration_viz.mapping import link,aggregate
from backend.apps.stoichdb.integration_viz.analysis import agreement,chain_math
from backend.apps.stoichdb.integration_viz.correlations import cross_correlations
from backend.apps.stoichdb.integration_viz.source import read,numeric_frame,supplement
def load_core(record):
    f=read(record['core_csv_path'],record['omics_type']);a,fields,meta,invalid=numeric_frame(f,record['omics_type'])
    return a,fields,{'stats':{k:profile(a[k]) for k in fields}}



def frames():
    g = pd.DataFrame({'gene_id':['A','B'], 'source_gene_id':['gene:A','gene:B'], 'island_score':[0.,1.]})
    t = pd.DataFrame({'transcript_id':['TA','TB'], 'gene_id':['A','B'],
                      'protein_isoelectric_point':[7.,8.], 'protein_gravy':[0.,1.]})
    p = pd.DataFrame({'protein_id':['PA','PB'], 'gene_id':['A','B'], 'ensembl_gene_id':['',''],
                      'transcript_id':['TA','TB'], 'ensembl_transcript_id':['',''], 'pI':[7.,8.], 'gravy':[0.,1.]})
    return {'genome':g, 'transcriptome':t, 'proteome':p}


class IntegrationContracts(unittest.TestCase):
    def test_constant_resource_is_zero_not_nan(self):
        z, meta = robust(pd.Series([3.,3.,3.]))
        np.testing.assert_array_equal(z, [0.,0.,0.]); self.assertEqual(meta['fallback'],'constant')

    def test_mad_zero_uses_population_sd(self):
        z, meta = robust(pd.Series([0.,0.,0.,8.]))
        self.assertEqual(meta['fallback'],'SD'); self.assertAlmostEqual(meta['scale'], np.std([0,0,0,8]))
        self.assertEqual(z.iloc[0],0.)

    def test_conflicting_protein_does_not_merge_genome_anchors(self):
        f=frames(); f['proteome'].loc[0,'ensembl_gene_id']='B'
        linked, audit=link(f)
        self.assertEqual(audit['union_genes'],2); self.assertEqual(len(audit['protein_conflicts']),1)
        self.assertEqual(linked['proteome'].loc[0,'_gene'],'')
        self.assertEqual(len(f['proteome']),2)

    def test_symbol_is_not_mapping_evidence(self):
        f=frames(); f['transcriptome']['gene_id']=''; f['transcriptome']['gene_symbol']=['A','B']
        _, audit=link(f); self.assertEqual(audit['mapped_rows']['transcriptome'],0)

    def test_exact_pair_duplicate_proteins_are_averaged_once(self):
        f=frames(); f['proteome']=pd.concat([f['proteome'],f['proteome'].iloc[[0]].assign(protein_id='PA2',pI=9.)],ignore_index=True)
        l,_=link(f); pairs=agreement(l['transcriptome'],l['proteome'])
        self.assertEqual(len(pairs),2); self.assertEqual(pairs.loc['TA','protein_records'],2)
        self.assertEqual(pairs.loc['TA','pi_delta'],1.)

    def test_nonblank_unmatched_transcript_does_not_silently_fallback(self):
        f=frames(); f['proteome'].loc[0,'transcript_id']='NOT_A'; f['proteome'].loc[0,'ensembl_transcript_id']='TA'
        l,_=link(f); self.assertEqual(len(agreement(l['transcriptome'],l['proteome'])),1)

    def test_pairwise_ranks_must_be_recomputed_on_shared_mask(self):
        j=pd.DataFrame({'genome__a':[1.,2.,3.,100.,5.], 'transcriptome__b':[4.,np.nan,3.,2.,1.], 'proteome__c':[8.,7.,6.,np.nan,0.]})
        fields={'genome':['a'],'transcriptome':['b'],'proteome':['c']}
        edges=cross_correlations(j,fields)
        for r in edges.itertuples():
            pair=j[[r.feature_a,r.feature_b]].dropna()
            self.assertEqual(r.pair_n,len(pair)); self.assertAlmostEqual(r.rho,spearmanr(pair.iloc[:,0],pair.iloc[:,1]).statistic)

    def test_constant_and_two_member_correlations_remain_null(self):
        j=pd.DataFrame({'genome__a':[1.,1.,1.], 'transcriptome__b':[1.,2.,3.], 'proteome__c':[1.,np.nan,3.]})
        e=cross_correlations(j,{'genome':['a'],'transcriptome':['b'],'proteome':['c']})
        self.assertEqual(len(e),3); self.assertTrue(e.rho.isna().all())

    def test_literal_na_identifier_is_not_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'core.csv';p.write_text('protein_id,species_id,N_atoms_per_aa\nNA,s,1.2\nPB,s,0\n',encoding='utf8')
            f,fields,a=load_core({'omics_type':'proteome','core_csv_path':str(p),'row_count_core':2})
            self.assertEqual(f.protein_id.iloc[0],'NA');self.assertEqual(a['stats']['N_atoms_per_aa']['n_zero'],1)

    def test_duplicate_primary_identifier_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'core.csv';p.write_text('protein_id,N_atoms_per_aa\nA,1\nA,2\n',encoding='utf8')
            with self.assertRaisesRegex(ValueError,'duplicate_primary_id'):
                load_core({'omics_type':'proteome','core_csv_path':str(p),'row_count_core':2})

    def test_empty_chain_is_unavailable_without_invented_candidates(self):
        f=frames();l,_=link(f)
        j=pd.DataFrame(columns=['genome__exon_atoms_N_per_base','transcriptome__atoms_per_nt_N','proteome__N_atoms_per_aa','proteome__pI','proteome__gravy','transcriptome__gc_content','genome__exon_gc_percent'],dtype=float)
        c,e,m=chain_math(j,l['genome'],l['transcriptome'],l['proteome'])
        self.assertEqual(len(c),0);self.assertEqual(m['candidate_count'],0);self.assertIsNone(m['candidate_threshold'])


class AdditionalContracts(unittest.TestCase):
    def test_exact_ecdf_zero_and_missing(self):
        p=distribution([0,0,1,np.nan,np.inf]);self.assertEqual(p['n_valid'],3);self.assertEqual(p['ecdf']['counts'],[2,1]);self.assertEqual(p['n_zero'],2);self.assertEqual(sum(p['histogram']['counts']),3)
    def test_constant_groups_do_not_split_ties(self):
        groups,b=conditional([1,1,1],[2,3,4]);self.assertEqual(len(groups),1);self.assertEqual(groups[0]['n'],3)
    def test_full_failure_does_not_destroy_core(self):
        g=pd.DataFrame({'gene_id':['A'],'exon_gc_percent':[0.]})
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'full.csv';p.write_text('gene_id,locus_atoms_N_per_base\nA,7\nA,9\n')
            out,a=supplement(g,str(p));self.assertEqual(a['status'],'full_invalid');pd.testing.assert_frame_equal(g,out)
    def test_full_id_mismatch_is_not_partial_left_join(self):
        g=pd.DataFrame({'gene_id':['A'],'exon_gc_percent':[0.]})
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'full.csv';p.write_text('gene_id,locus_atoms_N_per_base\nB,7\n')
            out,a=supplement(g,str(p));self.assertEqual(a['status'],'full_invalid');pd.testing.assert_frame_equal(g,out)
    def test_restricted_gene_versions_and_ambiguous_aliases(self):
        f=frames();f['genome']['source_gene_id']=['same','same'];f['transcriptome'].loc[0,'gene_id']='same'
        l,a=link(f);self.assertEqual(l['transcriptome'].loc[0,'_gene'],'');self.assertGreater(a['ambiguous_genome_alias_n'],0)
    def test_negative_numeric_export_and_formula_text(self):
        from backend.apps.stoichdb.integration_viz.exports import cell
        self.assertEqual(cell(-1.2),'-1.2');self.assertEqual(cell('=1+1',True),"'=1+1");self.assertEqual(cell(False),'False')

class AtomicStorageTests(unittest.TestCase):
    def test_windows_transient_permission_retry_preserves_complete_json(self):
        from unittest.mock import patch
        from backend.apps.stoichdb.integration_viz import artifacts as a
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'request.json';a.write(p,{'status':'ready','progress':1})
            original=Path.read_bytes
            attempts=[]
            def guarded(path):
                attempts.append(1)
                if len(attempts)<3:raise PermissionError('temporary Windows sharing lock')
                return original(path)
            with patch.object(Path,'read_bytes',guarded):self.assertEqual(a.read(p),{'status':'ready','progress':1})
            self.assertEqual(len(attempts),3)
    def test_windows_atomic_replace_retries_without_partial_publication(self):
        from unittest.mock import patch
        from backend.apps.stoichdb.integration_viz import artifacts as a
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'request.json';a.write(p,{'status':'queued'})
            original=a.os.replace;attempts=[]
            def guarded(src,dst):
                attempts.append(1)
                self.assertEqual(a.read(p),{'status':'queued'})
                if len(attempts)<3:raise PermissionError('temporary Windows sharing lock')
                return original(src,dst)
            with patch.object(a.os,'replace',guarded):a.write(p,{'status':'ready'})
            self.assertEqual(a.read(p),{'status':'ready'});self.assertEqual(len(attempts),3)

class ManagementScopeTests(unittest.TestCase):
    def test_capability_scan_cannot_materialize_or_publish(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        for flag in ['--publish','--with-default-cohort','--audit-only','--internal-one']:
            with self.subTest(flag=flag),self.assertRaises(CommandError):call_command('materialize_integration_visuals','--scan-capabilities','--all-registered',flag)
    def test_read_only_audit_cannot_publish(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):call_command('materialize_integration_visuals','--species','arabidopsis_thaliana','--audit-only','--publish')

class StreamingEvidenceTests(unittest.TestCase):
    def test_csv_frames_are_lazy_and_emit_one_complete_header(self):
        import csv,io
        from backend.apps.stoichdb.integration_viz.exports import csv_frames_response
        seen=[]
        def frames():
            for ids in [['001','NA'],['003']]:
                seen.append(ids);yield pd.DataFrame({'entity_id':ids,'value':[-1.2]*len(ids)})
        response=csv_frames_response(frames(),'members',{'species_id':'test_species'})
        stream=iter(response.streaming_content);self.assertEqual(next(stream).decode('utf8'),'\ufeff');self.assertEqual(seen,[])
        rows=list(csv.DictReader(io.StringIO(b''.join(stream).decode('utf8'))));self.assertEqual([r['entity_id'] for r in rows],['001','NA','003']);self.assertTrue(all(r['species_id']=='test_species' for r in rows));self.assertTrue(all(r['value']=='-1.2' for r in rows))
    def test_member_evidence_is_bounded_before_csv_streaming(self):
        import csv,io
        from unittest.mock import patch
        from backend.apps.stoichdb.integration_viz import exports
        source=pd.DataFrame({'entity_id':[str(i) for i in range(1201)],'entity_type':'gene'});seen=[]
        manifest={k:'test' for k in ['species_id','artifact_version','release_id','source_hash','method_version']}
        def enrich(target,rows):seen.append(len(rows));return rows
        with patch.object(exports.a,'read',return_value=manifest),patch.object(exports,'selection',return_value=(source,'test_selection')),patch('backend.apps.stoichdb.integration_viz.member_evidence.enrich',side_effect=enrich):
            response=exports.export(Path('.'),{'kind':'members'},None,None);self.assertEqual(seen,[])
            rows=list(csv.DictReader(io.StringIO(b''.join(response.streaming_content).decode('utf-8-sig'))))
        self.assertEqual(len(rows),1201);self.assertEqual(seen,[500,500,201]);self.assertEqual(rows[-1]['entity_id'],'1200')

class ExactImplementationCompatibilityTests(unittest.TestCase):
    def test_only_explicit_audited_prior_ordering_version_is_compatible(self):
        from unittest.mock import patch
        from backend.apps.stoichdb.integration_viz import artifacts as a
        policy=a.read(Path(a.__file__).with_name('implementation_compatibility.json'))
        with tempfile.TemporaryDirectory() as root:
            target=Path(root);a.write(target/'audit.json',{'passed':True})
            old={'implementation_hash':policy['accepted_prior']}
            with patch.object(a,'implementation_hash',return_value=policy['current']):self.assertTrue(a.compatible_implementation(old,target))
            with patch.object(a,'implementation_hash',return_value='future_numerical_change'):self.assertFalse(a.compatible_implementation(old,target))
            with patch.object(a,'implementation_hash',return_value=policy['current']):self.assertFalse(a.compatible_implementation({'implementation_hash':'unknown_old_version'},target))
    def test_failed_prior_audit_cannot_be_reused(self):
        from unittest.mock import patch
        from backend.apps.stoichdb.integration_viz import artifacts as a
        policy=a.read(Path(a.__file__).with_name('implementation_compatibility.json'))
        with tempfile.TemporaryDirectory() as root:
            target=Path(root);a.write(target/'audit.json',{'passed':False})
            with patch.object(a,'implementation_hash',return_value=policy['current']):self.assertFalse(a.compatible_implementation({'implementation_hash':policy['accepted_prior']},target))

@unittest.skipUnless(__import__('os').name=='nt','Windows process handles')
class WindowsProcessLivenessTests(unittest.TestCase):
    def test_exited_child_is_dead_even_while_popen_retains_its_handle(self):
        import subprocess
        from backend.apps.stoichdb.integration_viz.work_requests import alive
        child=subprocess.Popen([sys.executable,'-c','pass'],creationflags=subprocess.CREATE_NO_WINDOW)
        child.wait(timeout=30)
        self.assertFalse(alive(child.pid))
    def test_running_child_is_alive_then_dead_without_handle_reaping(self):
        import subprocess
        from backend.apps.stoichdb.integration_viz.work_requests import alive
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(1)'],creationflags=subprocess.CREATE_NO_WINDOW)
        try:self.assertTrue(alive(child.pid));child.wait(timeout=30);self.assertFalse(alive(child.pid))
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=30)

class CohortMetadataScopeTests(unittest.TestCase):
    def test_metadata_snapshot_restores_readers_after_failure(self):
        from unittest.mock import patch
        from backend.apps.stoichdb.integration_viz import cohort_metadata as c
        original_source=c.source.registry;original_engine=c.cohorts.registry;dataset=object()
        with patch.object(c,'load_snapshot',return_value=({'registered':{'genome':dataset}},'same')):
            with self.assertRaisesRegex(ValueError,'body_failure'):
                with c.registry_snapshot(['registered']):
                    self.assertIs(c.source.registry('registered')['genome'],dataset);raise ValueError('body_failure')
        self.assertIs(c.source.registry,original_source);self.assertIs(c.cohorts.registry,original_engine)
    def test_metadata_changes_are_rejected_and_scope_cannot_leak(self):
        from unittest.mock import patch
        from backend.apps.stoichdb.integration_viz import cohort_metadata as c
        original_source=c.source.registry;original_engine=c.cohorts.registry
        with patch.object(c,'load_snapshot',side_effect=[({'registered':{}},'before'),({'registered':{}},'after')]):
            with self.assertRaisesRegex(ValueError,'registry_changed'):
                with c.registry_snapshot(['registered']):pass
        self.assertIs(c.source.registry,original_source);self.assertIs(c.cohorts.registry,original_engine)

if __name__=='__main__': unittest.main(verbosity=2)
