import csv
import hashlib
import json
import tempfile
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from backend.apps.stoichdb.compare_core import analysis, catalog, exports, profiles, runs, worker
from backend.apps.stoichdb.compare_core.contracts import Cancelled, CompareError, clean, digest
from backend.apps.stoichdb.compare_core.models import CompareRun, CompareCoreProfile
from backend.apps.stoichdb.compare_core.sources import signature, hashed_text
from backend.apps.stoichdb.models import Species, OmicsDataset


def field(name='value', role='numeric', **kw):
    return dict(field=name, field_key='genome.'+name, omics='genome', compare_role=role, family='chemistry',
                composition_group=None, canonical_factor=1., unit_source='count', unit_canonical='count',
                bounded_min=None, bounded_max=None, applicability_rule=[], redundancy_group=None, **kw)


def fixture(n=6):
    fs=[field('v'), field('w'),field('part_A','composition'),field('part_B','composition'),field('is_coding','binary_summary'),field('gene_id','metadata')]
    for f in fs[2:4]:f['composition_group']='genome.comp';f['family']='genome.comp'
    cat={'fields':fs,'field_count':6,'semantic_hash':'fixture','review_required':[]}
    ids=[f's{i}' for i in range(n)]
    request={'task':'multi_species','species_ids':ids,'omics':['genome'],'reference':{'mode':'selected','species_ids':ids},'summary_stat':'median','normalization':'auto','field_selection':{'mode':'all_core'},'thresholds':{'min_valid_rows':10,'min_valid_fraction':.8}}
    ps=[]
    for i,sid in enumerate(ids):
        rows=[]
        for j,f in enumerate(fs):
            value=(i+1)**(1 if j==0 else 2) if j<2 else (.1+.1*i if j==2 else .9-.1*i)
            rows.append(dict(f,species_id=sid,status='ok',n_source=20,n_valid=20,n_applicable=20,median=value,mean=value))
        ps.append({'species_id':sid,'omics':'genome','fields':rows,'categories':[], 'composition_blocks':[{'group':'genome.comp','values':[.1+.1*i,.9-.1*i],'field_keys':['genome.part_A','genome.part_B'],'n_valid':20,'n_applicable':20,'status':'ok','n_invalid_composition':0}]})
    species=[{'species_id':sid,'display_name':sid,'taxonomy_id':str(100+i)} for i,sid in enumerate(ids)]
    return request,cat,ps,species


class AnalysisTests(SimpleTestCase):
    def test_full_accounting_and_distance_contribution(self):
        data,t=analysis.analyze(*fixture())
        self.assertEqual(data['field_accounting']['resolved_dataset_field_records'],36)
        self.assertEqual(data['field_accounting']['n_blocks'],3)
        for pair in t['distances']:
            parts=[r for r in t['contributions'] if r['source']==pair['source'] and r['target']==pair['target']]
            self.assertAlmostEqual(sum(p['squared_contribution'] for p in parts),pair['distance']**2)
            self.assertAlmostEqual(sum(p['share'] for p in parts),1)
        self.assertEqual(data['analysis_status']['pca']['status'],'ok')

    def test_pair_without_reference_has_composition_only(self):
        req,cat,ps,sp=fixture(2);req['task']='pairwise'
        data,t=analysis.analyze(req,cat,ps,sp)
        self.assertEqual(data['analysis_status']['distance']['kind'],'composition_only')
        self.assertTrue(all(r['reference_scaled_delta'] is None for r in t['differences']))
        self.assertEqual(data['analysis_status']['pca']['status'],'not_estimable')

    def test_partial_composition_never_auto_completed(self):
        req,cat,ps,sp=fixture(2);req['field_selection']={'mode':'custom','fields':['genome.part_A']}
        data,t=analysis.analyze(req,cat,ps,sp)
        self.assertEqual(data['analysis_status']['distance']['status'],'not_estimable')
        self.assertIn({'field_key':'genome.part_A','reason':'incomplete_composition_selection'},t['excluded_fields'])

    def test_missing_layer_does_not_silently_reduce_joint_scope(self):
        req,cat,ps,sp=fixture();req['omics'].append('proteome')
        data,t=analysis.analyze(req,cat,ps,sp)
        self.assertEqual(data['analysis_status']['distance']['reason'],'required_omics_unavailable')
        self.assertEqual(data['cross_omics_layers']['genome']['status'],'ok')
        self.assertEqual(data['cross_omics_layers']['proteome']['status'],'not_estimable')

    def test_zero_distance_contributions_are_null(self):
        x,desc=analysis.weighted_embedding([{'key':'x','omics':'genome','family':'chemistry','kind':'scalar','fields':['x'],'values':[0,0]}],['genome'])
        pairs,parts,d=analysis.geometry(x,['a','b'],desc)
        self.assertEqual(pairs[0]['status'],'zero_distance');self.assertIsNone(parts[0]['share'])

    def test_hellinger_boundary(self):
        x,desc=analysis.weighted_embedding([{'key':'c','omics':'genome','family':'c','kind':'composition','fields':['a','b'],'values':[[1,0],[0,1]]}],['genome'])
        self.assertAlmostEqual(analysis.geometry(x,['a','b'],desc)[0][0]['distance'],1)

    def test_robust_fallback_and_constant(self):
        self.assertEqual(analysis.scale_info([0,0,0,1])['fallback'],'population_std')
        self.assertEqual(analysis.scale_info([1,1,1])['scale'],0)

    def test_pca_geometry_and_order_invariance(self):
        req,cat,ps,sp=fixture();data,t=analysis.analyze(req,cat,ps,sp)
        req['species_ids'].reverse();data2,t2=analysis.analyze(req,cat,ps,sp)
        lookup={frozenset([r['source'],r['target']]):r['distance'] for r in t['distances']}
        for row in t2['distances']:self.assertAlmostEqual(row['distance'],lookup[frozenset([row['source'],row['target']])])
        self.assertAlmostEqual(sum(data['analysis_status']['pca']['explained_variance_ratio']),sum(data2['analysis_status']['pca']['explained_variance_ratio']))

    def test_group_seed_direction_and_small_samples(self):
        x=analysis.compare_groups(range(5),range(5,10),'field')
        self.assertEqual(x,analysis.compare_groups(range(5),range(5,10),'field'))
        self.assertEqual(x['cliffs_delta'],-1)
        self.assertEqual(analysis.compare_groups(range(4),range(5),'f')['status'],'descriptive_only')

    def test_group_constant_is_p_one_zero_interval(self):
        x=analysis.compare_groups([1]*5,[1]*5,'field');self.assertEqual(x['p_value'],1);self.assertEqual(x['ci_low'],0);self.assertEqual(x['ci_high'],0)

    def test_group_bh_and_taxonomy_gate(self):
        req,cat,ps,sp=fixture(10)
        # Keep the full composition valid for this larger fixture.
        for p in ps:p['composition_blocks'][0]['values']=[.5,.5]
        req['task']='two_groups';req['groups']={'A':req['species_ids'][:5],'B':req['species_ids'][5:]}
        data,t=analysis.analyze(req,cat,ps,sp)
        self.assertEqual(len(t['group_comparison']),2)
        self.assertTrue(all(r['m_tested']==2 and r['q_value']>=r['p_value'] for r in t['group_comparison']))
        sp[0]['taxonomy_id']=sp[1]['taxonomy_id'];data,t=analysis.analyze(req,cat,ps,sp)
        self.assertTrue(all(r['p_value'] is None for r in t['group_comparison']))

    def test_explicit_reference_scaling_and_percentiles(self):
        req,cat,ps,sp=fixture();req['species_ids']=['s0'];req['task']='reference_profile';req['reference']={'mode':'explicit','species_ids':['s1','s2','s3','s4','s5']}
        data,t=analysis.analyze(req,cat,ps,sp)
        self.assertEqual(data['normalization_info']['mode'],'fixed_reference_robust_z')
        self.assertEqual(len([r for r in t['rankings'] if r['field_key']=='__reference_distance__']),5)
        self.assertTrue(all(r['percentile']==0 for r in t['candidates']))

    def test_json_finiteness(self):
        self.assertEqual(clean({'x':np.array([np.nan,np.inf,0])}),{'x':[None,None,0.]})


class ProfileTests(SimpleTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.settings_context=override_settings(COMPARE_CORE_ROOT=self.root/'cache');self.settings_context.enable();self.addCleanup(self.settings_context.disable)

    def build(self,rows,fields=None):
        path=self.root/'core.csv';fields=fields or [field(),field('gene_id','metadata')]
        with path.open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        source=SimpleNamespace(path=path,species_id='s',omics='genome',warnings=[])
        return profiles.build_profile(source,SimpleNamespace(dataset_id='d',row_count_core=len(rows)),list(rows[0]),signature(path),{'fields':fields,'semantic_hash':'s'},lambda:None)[0]

    def test_zero_missing_nonfinite_invalid_and_duplicate_identity(self):
        rows=[{'gene_id':str(i),'value':v} for i,v in enumerate(['0','','nan','inf','bad','2','4'])];rows.append({'gene_id':'6','value':'5'})
        data=self.build(rows);f=data['fields'][0]
        self.assertEqual([f[k] for k in ('n_source','n_valid','n_zero','n_missing','n_nonfinite','n_invalid')],[8,4,1,1,2,1])
        self.assertEqual(f['median'],3);self.assertEqual(data['duplicate_identity_n'],1);self.assertEqual(data['conflicting_identity_n'],1)

    def test_structural_na_and_missing_column(self):
        f=field();f['applicability_rule']=[['coding','eq',1]]
        data=self.build([{'gene_id':'a','coding':'0','value':'0'},{'gene_id':'b','coding':'1','value':'0'}],[f,field('absent')])
        r=data['fields'][0];self.assertEqual(r['n_structural_na'],1);self.assertEqual(r['n_zero'],1);self.assertEqual(data['fields'][1]['status'],'missing_field')

    def test_missing_dependency_blocks_admission_but_preserves_raw(self):
        f=field();f['applicability_rule']=[['missing','eq',1]]
        data=self.build([{'gene_id':'a','value':'2'}],[f]);self.assertEqual(data['fields'][0]['status'],'applicability_unverified');self.assertEqual(data['fields'][0]['mean'],2)

    def test_empty_and_constant(self):
        data=self.build([{'gene_id':'a','value':''}]);self.assertIsNone(data['fields'][0]['mean']);self.assertEqual(data['fields'][0]['status'],'no_valid_values')
        data=self.build([{'gene_id':'a','value':'0'},{'gene_id':'b','value':'0'}]);self.assertEqual(data['fields'][0]['population_std'],0)

    def test_complete_composition_and_bad_closure(self):
        fs=[field('a','composition'),field('b','composition')]
        for f in fs:f['composition_group']='c'
        data=self.build([{'gene_id':'1','a':0,'b':1},{'gene_id':'2','a':.5,'b':.5},{'gene_id':'3','a':.8,'b':.8}],fs)
        comp=data['composition_blocks'][0];self.assertEqual(comp['n_valid'],2);self.assertEqual(comp['n_invalid_composition'],1);self.assertEqual(comp['values'],[.25,.75])

    def test_source_mutation_and_cleanup(self):
        calls=[0]
        with patch('backend.apps.stoichdb.compare_core.profiles.signature',return_value={'changed':True}):
            with self.assertRaises(CompareError):self.build([{'gene_id':'a','value':'1'}])
        self.assertFalse(list((self.root/'cache'/'building').glob('*')))

    def test_different_stream_chunk_sizes_preserve_exact_statistics(self):
        rows=[{'gene_id':str(i),'value':str(i%7)} for i in range(37)]
        expected=self.build(rows)['fields'][0]
        original=profiles.pd.read_csv
        def small(*args,**kwargs):kwargs['chunksize']=3;return original(*args,**kwargs)
        with patch.object(profiles.pd,'read_csv',side_effect=small):actual=self.build(rows)['fields'][0]
        for key in ('n_source','n_valid','n_zero','mean','median','population_std','p10','p25','p75','p90'):self.assertEqual(actual[key],expected[key])

    def test_same_stream_sha256(self):
        path=self.root/'file.csv';path.write_bytes(b'a,b\n1,2\n');stream,reader=hashed_text(path)
        with stream:self.assertEqual(stream.read(),'a,b\n1,2\n')
        self.assertEqual(reader.hasher.hexdigest(),hashlib.sha256(path.read_bytes()).hexdigest())


class DatabaseTests(TestCase):
    def setUp(self):
        self.client=APIClient();Species.objects.create(species_id='s0',display_name='S0',has_genome=True)
        self.cat=fixture()[1]

    def test_models_isolated_and_request_validation(self):
        with patch.object(runs,'catalog',return_value=self.cat):
            for payload in ({'species_ids':['s0'],'scope':'full'},{'species_ids':['s0'],'task':'pairwise'},{'species_ids':['s0'],'omics':['fake']},{'species_ids':['s0'],'task':'species_profile','field_selection':{'mode':'custom','fields':['bad']}}):
                with self.assertRaises(CompareError):runs.normalize(payload)
            request=runs.normalize({'species_ids':['s0','s0'],'task':'species_profile','omics':['genome']});self.assertEqual(request['species_ids'],['s0'])

    def test_group_overlap_rejected(self):
        with patch.object(runs,'catalog',return_value=self.cat):
            with self.assertRaises(CompareError):runs.normalize({'task':'two_groups','groups':{'A':['s0'],'B':['s0']}})

    def test_cancel_and_terminal_gate(self):
        r=CompareRun.objects.create();self.assertEqual(runs.cancel(r).status,'cancelled')
        self.assertEqual(runs.cancel(r).status,'cancelled')
        r.status='completed';r.save()
        with self.assertRaises(CompareError):runs.cancel(r)

    def test_resume_lease_and_expired_recovery(self):
        r=CompareRun.objects.create(status='profiling',lease_until=timezone.now()-timedelta(seconds=1),attempts=[{'attempt':1}]);worker.recover_stale();r.refresh_from_db();self.assertEqual(r.status,'queued')
        r.status='profiling';r.attempts=[{},{}];r.lease_until=timezone.now()-timedelta(seconds=1);r.save();worker.recover_stale();r.refresh_from_db();self.assertEqual(r.status,'interrupted')
        with patch.object(runs,'dispatch'):self.assertEqual(runs.resume(r).status,'queued')

    def test_api_status_pagination_and_errors(self):
        r=CompareRun.objects.create()
        self.assertEqual(self.client.get(f'/api/stoichdb/compare/core/runs/{r.pk}/').status_code,200)
        self.assertEqual(self.client.get(f'/api/stoichdb/compare/core/runs/{r.pk}/result/').status_code,409)
        self.assertEqual(self.client.get('/api/stoichdb/compare/core/species/?page_size=201').status_code,400)
        self.assertEqual(self.client.get('/api/stoichdb/compare/core/species/?query=nosuchspecies').json()['data']['total'],0)
        self.assertEqual(self.client.get('/api/stoichdb/compare/core/species/').json()['data']['items'][0]['species_id'],'s0')
        with override_settings(COMPARE_CORE_ENABLED=False):self.assertEqual(self.client.get('/api/stoichdb/compare/core/catalog/').status_code,503)

    def test_profile_lease_single_owner(self):
        ds=OmicsDataset.objects.create(dataset_id='s0:genome',species=Species.objects.get(species_id='s0'),omics_type='genome')
        item,owned=profiles._claim(ds,{'sig':1},'h');self.assertTrue(owned)
        other,owned=profiles._claim(ds,{'sig':1},'h');self.assertIsNone(owned);self.assertEqual(item.pk,other.pk)

    def test_worker_cancel_and_unusable_source_terminal_states(self):
        with tempfile.TemporaryDirectory() as tmp,override_settings(COMPARE_CORE_ROOT=tmp):
            req=fixture()[0];req['semantic_hash']=self.cat['semantic_hash']
            for exception,expected in ((Cancelled(),'cancelled'),(CompareError('Missing source','source_unavailable'),'failed')):
                r=CompareRun.objects.create(request_json=req)
                with patch.object(worker,'catalog',return_value=self.cat),patch.object(worker,'get_profile',side_effect=exception):
                    self.assertTrue(worker.process_one(r.pk))
                r.refresh_from_db();self.assertEqual(r.status,expected)
                with self.assertRaises(CompareError):exports.result(r)

    def test_export_package_checksum_and_complete_table(self):
        with tempfile.TemporaryDirectory() as tmp,override_settings(COMPARE_CORE_ROOT=tmp):
            req,cat,ps,sp=fixture();data,t=analysis.analyze(req,cat,ps,sp)
            req.update(missing_policy='common_panel_no_imputation',weights={'omics':'equal','families':'equal'})
            run=CompareRun.objects.create(request_json=req)
            result,checks=exports.publish(run,data,t,cat,[],lambda:None)
            run.status='completed';run.summary_json={'artifact_checks':checks};run.save()
            self.assertTrue(exports.run_artifacts_valid(run))
            self.assertEqual(exports.table(run,'coverage',page_size=5)['total'],36)
            self.assertEqual(len(exports.table(run,'coverage',page_size=5)['items']),5)
            with (exports.run_dir(run)/'field_coverage.csv').open(encoding='utf-8-sig') as f:self.assertEqual(len(list(csv.DictReader(f))),36)
            (exports.run_dir(run)/'manifest.json').write_text('corrupt');self.assertFalse(exports.run_artifacts_valid(run))


class ConcurrentCreationTests(TransactionTestCase):
    def test_identical_requests_coalesce_under_real_postgres_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections
        Species.objects.create(species_id='s0',display_name='S0')
        payload={'task':'species_profile','species_ids':['s0'],'omics':['genome']}
        def submit(_):
            try:return str(runs.create(payload)[0].pk)
            finally:connections.close_all()
        with override_settings(COMPARE_CORE_AUTOSTART=False),patch.object(runs,'catalog',return_value=fixture()[1]),patch.object(runs,'source_probe',return_value=[]):
            with ThreadPoolExecutor(max_workers=4) as pool:ids=list(pool.map(submit,range(4)))
        self.assertEqual(len(set(ids)),1)
        self.assertEqual(CompareRun.objects.count(),1)
