"""Content-addressed cohort publication, independent of species computations.

The queue identity uses cheap source signatures. After full descriptor reading,
the immutable cohort key includes every actual input content SHA. An atomic
index resolves the queue signature to that final key without hashing files in
GET/ensure requests. Numerical methods remain in cohorts.py.
"""
from backend.apps.stoichdb.feature_sources import io as feature_io
from pathlib import Path
from backend.apps.common.artifact_locations import locate,same_source_signatures,read_roots
from backend.apps.common.task_execution import heavy_guarded
import hashlib,json
from . import cohorts as engine,artifacts as a
DEFAULT_SPECIES=engine.DEFAULT_SPECIES
default_ids=engine.default_ids
def path(key):
    relative=engine.path(key).relative_to(a.root())
    found=locate('integration',a.root(),relative,required=False)
    return found.target if found else engine.path(key)

def request_identity(ids):
    return hashlib.sha256((cheap_identity(ids)+hashlib.sha256(Path(__file__).read_bytes()).hexdigest()).encode()).hexdigest()

def cheap_identity(ids):
    # Identical metadata/JSON contract to engine.identity; use the established
    # source_signature protocol once instead of repeatedly obtaining physical_identity.
    from backend.apps.common.host_paths import Path as HostPath
    from .source import registry,release
    def signature(value):
        import stat
        from backend.apps.stoichdb.feature_sources.projection import ProjectionError
        p=HostPath(value) if value else None
        missing={'path':str(p or ''),'missing':True}
        if p is None:return missing
        # logical_source performs the complete native Full change guard. The
        # integration signature needs only the saved Core size/mtime, so a
        # second source_available/logical_source guard adds no information.
        try:logical=feature_io.logical_source(p)
        except (OSError,ProjectionError):return missing
        if logical:
            old=logical.legacy_metadata()
            return {'path':str(p),'bytes':old['size'],'mtime_ns':old['mtime_ns']}
        try:
            s=p.stat()
            return {'path':str(p),'bytes':s.st_size,'mtime_ns':s.st_mtime_ns} if stat.S_ISREG(s.st_mode) else missing
        except FileNotFoundError:return missing
        except OSError:return {'path':str(p),'unreadable':True}
    value=[release(),ids,[(sid,{m:(d.dataset_id,signature(d.core_csv_path)) for m,d in registry(sid).items()}) for sid in ids],a.implementation_hash()]
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
def index_path(request_key):return a.root()/'cohorts'/'index'/(request_key[:16]+'.json')
def identity(ids):
    request_key=request_identity(ids);p=index_path(request_key)
    if feature_io.source_available(p):
        index=a.read(p)
        if index['request_identity']!=request_key:raise ValueError('cohort_request_identity_mismatch')
        if path(index['cohort_key']).is_file():return index['cohort_key']
    portable=a.root()/'cohorts'/'portable_index.json'
    if portable.is_file():
        entry=a.read(portable).get('entries',{}).get(request_key)
        if entry:
            result_path=path(entry['cohort_key']);result=a.read(result_path)
            if hashlib.sha256(result_path.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('historical_cohort_checksum_mismatch')
            if result.get('species_ids')!=ids:raise ValueError('historical_cohort_species_mismatch')
            return entry['cohort_key']
    return request_key
@heavy_guarded
def build(ids):
    request_key=request_identity(ids);key=identity(ids)
    if key!=request_key and path(key).is_file():return a.read(path(key))
    reuse_core_snapshots(ids)
    valid,invalid,invalid_sources=validate_inputs(ids)
    result=engine.build(valid);result['species_ids']=ids;result['excluded_species']+=invalid;result['excluded_source_audit']=invalid_sources
    sources=[{'species_id':r['species_id'],'sources':r['source']} for r in result['descriptors']]
    source_hash=hashlib.sha256(json.dumps([result['release_id'],sources,result['excluded_species'],invalid_sources],sort_keys=True).encode()).hexdigest()
    key=hashlib.sha256(json.dumps([request_key,source_hash,ids,result['fields']],sort_keys=True).encode()).hexdigest()
    result={**result,'legacy_numerical_cache_key':result['cohort_key'],'cohort_key':key,'source_hash':source_hash,'request_identity':request_key,'cohort_version':hashlib.sha256(json.dumps([key,result['matrix'],result.get('scores')],sort_keys=True).encode()).hexdigest()[:20]}
    if request_identity(ids)!=request_key:raise ValueError('cohort_source_changed_before_content_publication')
    a.write(engine.path(key),result)
    a.write(index_path(request_key),{'request_identity':request_key,'cohort_key':key,'cohort_version':result['cohort_version'],'source_hash':source_hash})
    return result
def validate_inputs(ids):
    import numpy as np
    from .contracts import MODES,FP,KEY,unit
    from .statistics import numbers
    from .source import registry,signature,read as read_core,digest,release
    valid=[];invalid=[];invalid_sources=[];version=a.implementation_hash()
    for sid in ids:
        datasets=registry(sid)
        try:
            trusted=False
            try:
                manifest=a.read(a.lookup(sid)/'manifest.json');trusted=manifest['release_id']==release() and all(manifest['source_audit'].get(m,{}).get('status')=='available' and same_source_signatures(manifest['source_audit'][m].get('signature'),signature(datasets[m].core_csv_path)) and manifest['source_audit'][m].get('dataset_id')==datasets[m].dataset_id for m in MODES)
            except FileNotFoundError:pass
            for m in MODES:
                d=datasets[m];sig=signature(d.core_csv_path);cache=a.root()/'descriptors'/a.component(sid)/(m+'.json');cached=a.read(cache) if cache.exists() else None
                if cached and cached.get('signature')==sig and cached.get('dataset_id')==d.dataset_id and (trusted or cached.get('primary_ids_audited') and cached.get('descriptor_version')==version):continue
                f=read_core(d.core_csv_path,m,[KEY[m]]+FP[m]);values={};stats={}
                for field in FP[m]:
                    v=numbers(f[field]).dropna().to_numpy(float);k=m+'__'+field;values[k]=float(np.median(v)) if len(v) else None;stats[k]={'n_source':len(f),'n_valid':len(v),'unit':unit(m,field)}
                sha=digest(d.core_csv_path)
                if signature(d.core_csv_path)!=sig:raise ValueError('cohort_source_changed_during_validation')
                a.write(cache,{'signature':sig,'dataset_id':d.dataset_id,'source':{'dataset_id':d.dataset_id,'signature':sig,'sha256':sha},'values':values,'stats':stats,'primary_ids_audited':True,'descriptor_version':version})
            valid.append(sid)
        except (ValueError,OSError,KeyError) as e:
            invalid.append({'species_id':sid,'reason':'invalid_source: '+str(e)});inputs={}
            for m,d in datasets.items():
                try:sha=digest(d.core_csv_path)
                except OSError:sha=None
                inputs[m]={'dataset_id':d.dataset_id,'signature':signature(d.core_csv_path),'sha256':sha}
            invalid_sources.append({'species_id':sid,'sources':inputs})
    return valid,invalid,invalid_sources
def reuse_core_snapshots(ids):
    """Exact medians from all original Core snapshot rows, never gene means."""
    import numpy as np
    import pandas as pd
    from .contracts import MODES,FP,unit
    from .statistics import numbers
    from .source import registry,signature,release
    for sid in ids:
        try:target=a.lookup(sid);manifest=a.read(target/'manifest.json')
        except FileNotFoundError:continue
        if manifest['release_id']!=release() or a.stale(sid,target):continue
        datasets=registry(sid)
        for m in MODES:
            d=datasets[m];sig=signature(d.core_csv_path);cache=a.root()/'descriptors'/a.component(sid)/(m+'.json')
            if cache.is_file():
                cached=a.read(cache)
                if cached.get('signature')==sig and cached.get('dataset_id')==d.dataset_id:continue
            audit=manifest['source_audit'].get(m,{})
            if audit.get('status')!='available' or not same_source_signatures(audit.get('signature'),sig) or audit.get('dataset_id')!=d.dataset_id:continue
            p=target/'tables'/('source_'+m+'.parquet')
            if not feature_io.source_exists(p):continue
            f=pd.read_parquet(p,columns=FP[m]);values={};stats={}
            for field in FP[m]:
                x=numbers(f[field]).dropna().to_numpy(float);key=m+'__'+field;values[key]=float(np.median(x)) if len(x) else None;stats[key]={'n_source':len(f),'n_valid':len(x),'unit':unit(m,field)}
            if signature(d.core_csv_path)!=sig:raise ValueError('cohort_source_changed_during_snapshot_read')
            a.write(cache,{'signature':sig,'dataset_id':d.dataset_id,'source':{'dataset_id':d.dataset_id,'signature':sig,'sha256':audit['sha256']},'values':values,'stats':stats,'snapshot_artifact_version':manifest['artifact_version'],'population':'all original Core rows, no matching subset'})


def index_historical_cohorts():
    """Explicit offline indexing; all medians remain the saved whole-Core values."""
    from .source import registry,signature,digest,release
    from .contracts import MODES,FP,unit
    from backend.apps.stoichdb.feature_hub.sources import DatasetSourceResolver
    from backend.apps.stoichdb.feature_hub.cache_identity import source_content_identity
    entries={};rejected=[];registered_sources={};verified_inputs={};registries={};descriptors={}
    active_release=release();implementation=a.implementation_hash();reader_revision=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for root in read_roots('integration',a.root())[1:]:
        for p in sorted((root/'cohorts').glob('*/result.json.gz')):
            try:
                result=a.read(p);ids=result['species_ids']
                if not all(k in result for k in ['source_hash','cohort_version','fields']):raise ValueError('legacy_numerical_cache_without_content_receipt')
                if result['fields']!=[mode+'__'+field for mode in MODES for field in FP[mode]]:raise ValueError('cohort_field_contract_changed')
                if result.get('method')!='whole-Core medians; cohort population z; variable layer 1/sqrt(k); full SVD; Euclidean distance; average linkage order':raise ValueError('cohort_method_not_verified')
                if result['release_id']!=active_release:raise ValueError('different_release')
                if len(result['descriptors'])!=len(ids) or {v['species_id'] for v in result['descriptors']}!=set(ids):raise ValueError('cohort_descriptors_incomplete')
                for row in result['descriptors']:
                    if row['species_id'] not in registries:registries[row['species_id']]=registry(row['species_id'])
                    datasets=registries[row['species_id']]
                    for mode in MODES:
                        d=datasets[mode];saved=row['source'][mode]
                        source_key=(row['species_id'],mode)
                        if source_key not in verified_inputs:
                            source=DatasetSourceResolver().resolve(row['species_id'],mode,'core')
                            verified=(signature(d.core_csv_path),source_content_identity(source))
                            registered_sources[source_key]=source;verified_inputs[source_key]=verified
                        # The existing verified Full binding seals this exact virtual Core SHA;
                        # source_content_identity still checks its native change guard. Physical
                        # Core files use the existing guarded full-file digest cache instead.
                        sig,current_sha=verified_inputs[source_key]
                        if saved['dataset_id']!=d.dataset_id or not same_source_signatures(saved['signature'],sig) or saved['sha256']!=current_sha:raise ValueError('source_changed')
                        keys=[mode+'__'+f for f in FP[mode]]
                        if any(row['stats'][k]['n_source']!=d.row_count_core for k in keys):raise ValueError('row_population_changed')
                        values={k:row['values'][k] for k in keys};stats={k:row['stats'][k] for k in keys}
                        if source_key in descriptors:
                            if descriptors[source_key]!=(values,stats):raise ValueError('cohort_descriptor_conflict_for_same_complete_source')
                            continue
                        descriptors[source_key]=(values,stats)
                        cache=a.root()/'descriptors'/a.component(row['species_id'])/(mode+'.json')
                        a.write(cache,{'signature':sig,'dataset_id':d.dataset_id,'source':{**saved,'signature':sig},'values':values,'stats':stats,'primary_ids_audited':True,'descriptor_version':implementation,'verified_historical_cohort':str(p),'population':'all original Core rows'})
                # Invalid/missing-source cohorts are retained as historical only.
                if result.get('excluded_species'):raise ValueError('excluded_sources_require_new_validation')
                # The exact same identity JSON as cheap_identity, reusing checks
                # for the repeated default reference. Revalidated again below.
                identity=hashlib.sha256(json.dumps([active_release,ids,[(sid,{mode:(d.dataset_id,verified_inputs[(sid,mode)][0]) for mode,d in registries[sid].items()}) for sid in ids],implementation],sort_keys=True).encode()).hexdigest()
                request=hashlib.sha256((identity+reader_revision).encode()).hexdigest();entry={'cohort_key':result['cohort_key'],'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'species_ids':ids,'source_path':str(p)}
                if request in entries and entries[request]['sha256']!=entry['sha256']:raise ValueError('cohort_content_conflict')
                entries[request]=entry
            except (ValueError,KeyError,OSError,LookupError) as exc:rejected.append({'path':str(p),'reason':str(exc)})
    # Recheck every distinct sealed/native identity before publication. Repeated
    # default species are never reread for each cohort and never bypass changes.
    for key,source in registered_sources.items():
        if source_content_identity(source)!=verified_inputs[key][1]:raise ValueError('source_changed_during_historical_indexing')
    if release()!=active_release:raise ValueError('release_changed_during_historical_indexing')
    a.write(a.root()/'cohorts'/'portable_index.json',{'format':'portable-integration-cohort-index-v1','entries':entries,'rejected':rejected,'verified_distinct_sources':len(registered_sources)})
    return {'indexed':len(entries),'rejected':rejected,'verified_distinct_sources':len(registered_sources)}
