from pathlib import Path
from unittest.mock import patch
import csv,io,os,time
from django.test import override_settings,TestCase
from rest_framework.test import APIClient
from backend.apps.stoichdb.tests.test_proteome_viz_sources import SourceFixture
from backend.apps.stoichdb.proteome_viz.source import load
from backend.apps.stoichdb.proteome_viz.builders import build
from backend.apps.stoichdb.proteome_viz import artifacts as store

class ApiTests(SourceFixture,TestCase):
    def setUp(self):
        super().setUp();self.override=override_settings(PROTEOME_VIZ_ROOT=self.path/'products');self.override.enable();self.addCleanup(self.override.disable)
        for fn in [store.read_bundle,store.read_matrix,store.read_metadata,store.read_arrays]:fn.cache_clear()
        self.client=APIClient();self.base=f'/api/stoichdb/species/{self.species.species_id}/proteome/visualizations/'
        ds=load(self.species.species_id);self.target=store.persist(ds,build(ds));self.audit=store.audit_path(self.target);self.assertEqual(self.audit['errors'],[]);store.publish(self.target)
    def get(self,path,**params):
        r=self.client.get(self.base+path,params);self.assertEqual(r.status_code,200,r.content[:300]);return r.json()['data']
    def test_manifest_positions_and_alias(self):
        m=self.get('');self.assertEqual(len(m['charts']),31);self.assertEqual(len(m['fields']),52);a=self.get('charts/B10/')['result'];b=self.get('charts/D02/')['result'];self.assertEqual(a['data']['hex'],b['data']['hex'])
    def test_pair_bin_members_are_exact_not_bounding_box(self):
        p=self.get('pair/',x='pI',y='N_atoms_per_aa')['result'];b=p['data']['hex']['bins'][0];r=self.get('members/',chart_id='B15',variant_id=p['variant_id'],bin_id=b['bin_id'],artifact_version=p['artifact_version']);self.assertEqual(r['total'],b['count']);self.assertEqual(len(r['rows']),b['count'])
    def test_invalid_fields_and_cohort_limit(self):
        self.assertEqual(self.client.get(self.base+'pair/',{'x':'__proto__','y':'pI'}).status_code,400)
        self.assertEqual(self.client.get(self.base+'cohort/',{'species_ids':','.join('s'+str(i) for i in range(65))}).status_code,400)
    def test_structure_every_row_and_exact_id(self):
        r=self.get('structure/',resolution='window',rank_start=10,rank_count=2);self.assertEqual(len(r['rows']),2);self.assertEqual(r['n_source'],12);self.assertEqual(r['rows'][0]['rank'],10)
    def test_candidate_population_and_full_stream_exports(self):
        r=self.get('candidates/',module='Hydropathy');self.assertEqual(r['total'],12)
        response=self.client.get(self.base+'export/',{'chart_id':'D14','kind':'candidates'});text=b''.join(response.streaming_content).decode('utf-8-sig');rows=list(csv.reader(io.StringIO(text)));self.assertEqual(len(rows)-1,12);self.assertEqual(len({r[0] for r in rows[1:]}),12)
    def test_pending_is_not_fabricated_when_consumer_absent(self):
        self.assertFalse((store.root()/'consumer.json').exists());r=self.client.post(self.base+'prepare/',{'scope':'core','chart_id':'all'},format='json');self.assertIn(r.status_code,[401,403])
    def test_file_change_is_marked_stale(self):
        with self.core_path.open('a',encoding='utf-8') as f:f.write('\n')
        self.assertEqual(self.get('')['readiness'],'stale')
        self.assertEqual(self.get('cohort/')['readiness'],'not_prepared')
    def test_unknown_version_cannot_be_read_as_current(self):
        self.assertEqual(self.client.get(self.base+'charts/B01/',{'artifact_version':'unknown_version'}).status_code,410)
    def test_dynamic_pair_export_uses_the_selected_variant(self):
        p=self.get('pair/',x='gravy',y='Se_atoms')['result'];response=self.client.get(self.base+'export/',{'chart_id':'B15','kind':'method','variant_id':p['variant_id']});self.assertEqual(response.status_code,200);self.assertEqual(response.json()['figure']['data']['x'],'gravy');self.assertEqual(response.json()['figure']['data']['y'],'Se_atoms')
    def test_public_first_visit_cannot_supply_worker_parameters(self):
        response=self.client.post(self.base+'ensure/',{'scope':'core','force':True},format='json');self.assertEqual(response.status_code,400)
        response=self.client.post(self.base+'ensure/',{'scope':'core'},format='json');self.assertEqual(response.status_code,200);self.assertEqual(response.json()['data']['reason_code'],'on_demand_disabled')
    def test_same_size_and_mtime_source_change_does_not_reuse_content(self):
        from backend.apps.stoichdb.proteome_viz.execution import reusable
        from backend.apps.stoichdb.proteome_viz.source import release_id
        task={'core_csv_path':str(self.core_path),'full_csv_path':str(self.full_path)}
        self.assertIsNotNone(reusable(self.species.species_id,'core',release_id(),task));before=self.core_path.stat();content=bytearray(self.core_path.read_bytes());i=content.index(10)+2;content[i]=120 if content[i]!=120 else 121;self.core_path.write_bytes(content);os.utime(self.core_path,ns=(before.st_atime_ns,before.st_mtime_ns));self.assertEqual(self.core_path.stat().st_size,before.st_size);self.assertEqual(self.core_path.stat().st_mtime_ns,before.st_mtime_ns);self.assertIsNone(reusable(self.species.species_id,'core',release_id(),task))
    def test_a_dead_worker_is_reported_as_interrupted(self):
        from backend.apps.stoichdb.proteome_viz import work_requests
        job=work_requests.enqueue(self.species.species_id,'core','all',{});job.update(readiness='running',worker_pid=99999999);store.write_json(work_requests.path_for(job['request_id']),job);r=self.get('requests/'+job['request_id']+'/');self.assertEqual(r['readiness'],'interrupted')
    def test_quantile_export_includes_every_field_and_real_tsv(self):
        response=self.client.get(self.base+'export/',{'chart_id':'B14','kind':'chart','file_format':'tsv'});self.assertEqual(response.status_code,200);text=b''.join(response.streaming_content).decode('utf-8-sig');rows=list(csv.reader(io.StringIO(text),delimiter='\t'));self.assertEqual(len(rows)-1,len(self.get('')['fields']));self.assertIn('n_zero',rows[0]);self.assertTrue(any(row[0]=='AA_other_pct' for row in rows))
