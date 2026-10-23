"""Reuse fitted arrays only after exact complete-population/source equality checks."""
import copy
import numpy as np
from . import artifacts as store
from .source import release_id
from .contracts import unit
from .statistics import profile
def try_reuse(ds):
    if ds['scope']!='full':return None
    try:target=store.lookup(ds['species_id'],ds['omics'],'core',release_id())
    except FileNotFoundError:return None
    m=store.read_json(target/'manifest.json')
    if m.get('implementation_hash')!=store.implementation_hash_for(ds['omics'],'core') or m['source']['hashes']!=ds['source']['hashes'] or m['n_source']!=ds['n']:return None
    meta=store.metadata(str(target))
    if set(meta)!=set(ds['metadata']) or any(meta[k]!=ds['metadata'][k] for k in meta):return None
    core=store.matrix(str(target));physical=dict(ds['values']);n=ds['n'];original_core_numeric=[c['key'] for c in m['catalog'] if c['primary'] and c['role']=='numeric']
    # Additional Full columns in the Core scope came from these same content-
    # hashed Full bytes and the same ordered, unique IDs. Shared Core physical
    # values/missing masks must also match Full exactly, with no tolerance.
    if any(k not in physical or not np.array_equal(core[k],physical[k],equal_nan=True) for k in original_core_numeric):return None
    if ds['omics']=='genome':
        from .genome import derive
    else:from .transcriptome import derive
    derive(ds);v=ds['values']
    if set(core)!=set(v) or any(not np.array_equal(core[k],v[k],equal_nan=True) for k in core):
        v.clear();v.update(physical);return None
    figures=copy.deepcopy(store.bundle(str(target)));old_profiles=store.profiles(str(target));profiles={}
    for k in ds['fields']:
        p=copy.deepcopy(old_profiles[k]) if k in old_profiles else {**profile(physical[k],k,unit(k,ds['omics'])),'n_invalid':ds['source']['invalid_counts'].get(k,0)}
        p['n_invalid']=ds['source']['invalid_counts'].get(k,0)
        p['n_raw_missing']=p['n_missing']-p['n_invalid'];profiles[k]=p
    for cid,f in figures.items():
        f.update(species_id=ds['species_id'],omics=ds['omics'],dataset_id=ds['dataset_id'],release_id=ds['release_id'],primary_scope='full',source_hash=ds['source_hash'])
        d=f['data']
        if f['design_kind'] in ['complete_field_atlas','native_quantile_table','core_quantile_signature']:
            d.update(fields=ds['fields'],total=len(profiles))
            if f['design_kind']=='core_quantile_signature':d['rows']=[{'field':k,'quantiles':p['quantiles'],'z':[(q-p['quantiles'][3])/p['scale'] for q in p['quantiles']] if p['quantiles'] else [None]*7,'n':p['n_valid'],'constant':p.get('fallback')=='constant'} for k,p in profiles.items()]
    imported={r['key'] for r in ds['catalog']}
    for k in v:
        if k not in imported:ds['catalog'].append({'key':k,'role':'numeric','origin':'derived','declared_feature_family':'derived','source_file_scope':'derived','unit':unit(k,ds['omics']),'primary':False})
    for k,a in physical.items():v[k]=a
    ds['source']['equality_reuse']={'status':'verified_exact','source_artifact_version':m['artifact_version'],'source_scope':'core','destination_scope':'full','complete_ordered_ids_and_all_metadata_equal':True,'source_file_hashes_equal':True,'shared_original_numeric_fields_equal':len(original_core_numeric),'all_analysis_columns_equal':len(core),'numeric_comparison':'exact numeric equality and identical missing masks, equal_nan=True; no tolerance','full_original_profiles_recomputed_or_exact_shared_fields_reused':len(profiles),'full_original_primary_columns':len(ds['source']['primary_header'])}
    return {'figures':figures,'arrays':{},'reuse_analysis':str(target),'profiles':profiles,'fingerprint':copy.deepcopy(m['fingerprint']),'metadata_coverage':copy.deepcopy(m['metadata_coverage'])}
