"""Content-addressed cohort publication, independent of species computations.

The queue identity uses cheap source signatures. After full descriptor reading,
the immutable cohort key includes every actual input content SHA. An atomic
index resolves the queue signature to that final key without hashing files in
GET/ensure requests. Numerical methods remain in cohorts.py.
"""
from pathlib import Path
import hashlib,json
from . import cohorts as engine,artifacts as a
DEFAULT_SPECIES=engine.DEFAULT_SPECIES
default_ids=engine.default_ids
path=engine.path
def request_identity(ids):
    return hashlib.sha256((engine.identity(ids)+hashlib.sha256(Path(__file__).read_bytes()).hexdigest()).encode()).hexdigest()
def index_path(request_key):return a.root()/'cohorts'/'index'/(request_key[:16]+'.json')
def identity(ids):
    request_key=request_identity(ids);p=index_path(request_key)
    if p.is_file():
        index=a.read(p)
        if index['request_identity']!=request_key:raise ValueError('cohort_request_identity_mismatch')
        if path(index['cohort_key']).is_file():return index['cohort_key']
    return request_key
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
    a.write(path(key),result)
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
                manifest=a.read(a.lookup(sid)/'manifest.json');trusted=manifest['release_id']==release() and all(manifest['source_audit'].get(m,{}).get('status')=='available' and manifest['source_audit'][m].get('signature')==signature(datasets[m].core_csv_path) and manifest['source_audit'][m].get('dataset_id')==datasets[m].dataset_id for m in MODES)
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
            if audit.get('status')!='available' or audit.get('signature')!=sig or audit.get('dataset_id')!=d.dataset_id:continue
            p=target/'tables'/('source_'+m+'.parquet')
            if not p.exists():continue
            f=pd.read_parquet(p,columns=FP[m]);values={};stats={}
            for field in FP[m]:
                x=numbers(f[field]).dropna().to_numpy(float);key=m+'__'+field;values[key]=float(np.median(x)) if len(x) else None;stats[key]={'n_source':len(f),'n_valid':len(x),'unit':unit(m,field)}
            if signature(d.core_csv_path)!=sig:raise ValueError('cohort_source_changed_during_snapshot_read')
            a.write(cache,{'signature':sig,'dataset_id':d.dataset_id,'source':{'dataset_id':d.dataset_id,'signature':sig,'sha256':audit['sha256']},'values':values,'stats':stats,'snapshot_artifact_version':manifest['artifact_version'],'population':'all original Core rows, no matching subset'})
