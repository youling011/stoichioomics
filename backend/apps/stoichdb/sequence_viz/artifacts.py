from pathlib import Path
from functools import lru_cache
from threading import RLock
import hashlib,json,os,uuid,re
import numpy as np
from django.conf import settings
from backend.apps.stoichdb.proteome_viz.artifacts import read_json,write_json,clean
from . import METHOD_VERSION
from .contracts import FIGURES,ALIASES
def root():return Path(getattr(settings,'SEQUENCE_VIZ_ROOT',settings.BASE_DIR/'runtime/sequence_visuals_v1'))
def component(x):return hashlib.sha256(str(x).encode()).hexdigest()[:16]
def variant_path(target,key,suffix):
    if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('invalid_variant_id')
    # Full identity stays in the payload. Compact surrogates keep atomic temporary
    # names below Windows MAX_PATH even inside a versioned source directory.
    return Path(target)/'variants'/(key[:16]+suffix)
@lru_cache(maxsize=1)
def implementation_hash():
    h=hashlib.sha256()
    for f in ['source.py','contracts.py','composition.py','statistics.py','ordination.py','genome.py','transcriptome.py','builders.py','figure_contracts.json']:h.update(Path(__file__).with_name(f).read_bytes())
    return h.hexdigest()
def implementation_hash_for(omics,scope):
    base=implementation_hash()
    if omics=='genome':base=hashlib.sha256((base+hashlib.sha256(Path(__file__).with_name('coordinates.py').read_bytes()).hexdigest()).encode()).hexdigest()
    if omics=='genome' and scope=='full':return hashlib.sha256((base+hashlib.sha256(Path(__file__).with_name('full_scope.py').read_bytes()).hexdigest()).encode()).hexdigest()
    return base
def pointer_path(sid,m,scope,release):return root()/'published'/component(release)/m/(component(sid)+'_'+scope+'.json')
def path_for(p):
    target=(root()/p['path']).resolve()
    if not target.is_relative_to(root().resolve()):raise ValueError('invalid_artifact_path')
    return target
def lookup(sid,m,scope,release,version=''):
    p=pointer_path(sid,m,scope,release)
    if not p.is_file():raise FileNotFoundError('not_prepared')
    pointer=read_json(p)
    if version and version!=pointer['artifact_version']:
        if not re.fullmatch(r'[A-Za-z0-9_]+',version):raise ValueError('invalid_artifact_version')
        p=root()/'versions'/component(sid)/m/scope/(version+'.json')
        if not p.is_file():raise FileNotFoundError('artifact_expired')
        pointer=read_json(p)
    target=path_for(pointer)
    if not target.is_dir():raise FileNotFoundError('artifact_expired')
    return target
_lock=RLock()
def serialized(fn):
    def call(*args):
        with _lock:return fn(*args)
    call.cache_clear=fn.cache_clear
    return call
@serialized
@lru_cache(maxsize=1)
def bundle(target):return read_json(Path(target)/'figures.json.gz')
@serialized
@lru_cache(maxsize=1)
def matrix(target):
    with np.load(Path(target)/'columns.npz',allow_pickle=False) as f:return {k:f[k] for k in f.files}
@serialized
@lru_cache(maxsize=1)
def arrays(target):
    with np.load(Path(target)/'analysis.npz',allow_pickle=False) as f:return {k:f[k] for k in f.files}
@serialized
@lru_cache(maxsize=1)
def metadata(target):return read_json(Path(target)/'metadata.json.gz')
@serialized
@lru_cache(maxsize=1)
def profiles(target):return read_json(Path(target)/'profiles.json.gz')
def clear():
    for f in [bundle,matrix,arrays,metadata,profiles]:f.cache_clear()
def persist(ds,built):
    version=uuid.uuid4().hex[:20];target=root()/component(ds['release_id'])/component(ds['dataset_id'])/ds['scope']/ds['source_hash'][:16]/version;target.mkdir(parents=True)
    np.savez_compressed(target/'columns.npz',**ds['values'])
    if built.get('reuse_analysis'):
        import shutil
        source=Path(built['reuse_analysis'])/'analysis.npz'
        try:os.link(source,target/'analysis.npz')
        except OSError:shutil.copy2(source,target/'analysis.npz')
    else:np.savez_compressed(target/'analysis.npz',**built['arrays'])
    write_json(target/'metadata.json.gz',ds['metadata']);write_json(target/'profiles.json.gz',built['profiles'])
    for p in built['figures'].values():p['artifact_version']=version
    write_json(target/'figures.json.gz',built['figures'])
    m={k:ds[k] for k in ['species_id','omics','dataset_id','release_id','source_hash','available_scopes']};m.update(primary_scope=ds['scope'],method_version=METHOD_VERSION,artifact_version=version,n_source=ds['n'],fields=[r for r in ds['catalog'] if r['role']=='numeric' and r['primary']],catalog=ds['catalog'],primary_header=ds['source']['primary_header'],source=ds['source'],identity_field=ds['key'],canonical_aliases=ALIASES,implementation_hash=implementation_hash_for(ds['omics'],ds['scope']),metadata_coverage=built['metadata_coverage'],fingerprint=built['fingerprint'],charts=[{'chart_id':k,'title':p['title'],'section':FIGURES[k]['section'],'status':p['status'],'reason_code':p['reason_code'],'kind':p['design_kind']} for k,p in built['figures'].items()]);write_json(target/'manifest.json',m)
    return target
def audit(target):
    target=Path(target);m=read_json(target/'manifest.json');figs=bundle(str(target));ps=read_json(target/'profiles.json.gz');errors=[];expected={k for k,v in FIGURES.items() if v['omics']==m['omics']}
    if set(figs)!=expected:errors.append('chart_positions_incomplete')
    primary=[r['key'] for r in m['catalog'] if r['primary']]
    if primary!=m['primary_header'] or len(set(primary))!=len(primary):errors.append('primary_header_catalog_mismatch')
    if {r['key'] for r in m['fields']}!=set(ps):errors.append('numeric_profiles_incomplete')
    for k,p in ps.items():
        if p['n_valid']+p['n_missing']!=m['n_source'] or p['n_invalid']>p['n_missing']:errors.append(k+':coverage')
        if sum(p['histogram']['counts'])!=p['n_valid']:errors.append(k+':histogram')
        if p['ecdf']['cdf'] and p['ecdf']['cdf'][-1]!=1:errors.append(k+':cdf')
    ids=metadata(str(target))[m['identity_field']]
    if len(ids)!=m['n_source'] or len(set(ids))!=len(ids):errors.append('native_identity_incomplete')
    for cid,p in figs.items():
        d=p['data']
        if 'hex' in d and sum(b['count'] for b in d['hex']['bins'])!=d['hex']['n']:errors.append(cid+':hex')
        if 'conditional' in d and sum(g['n'] for g in d['conditional'])!=d['hex']['n']:errors.append(cid+':conditional')
        if p['status'] not in ['available','partial','unavailable']:errors.append(cid+':status')
    result={'status':'failed' if errors else 'passed','errors':errors,'species_id':m['species_id'],'omics':m['omics'],'scope':m['primary_scope'],'n_source':m['n_source'],'numeric_fields':len(ps),'primary_columns':len(primary),'chart_positions':len(figs),'source_hash':m['source_hash'],'artifact_version':m['artifact_version']};write_json(target/'audit.json',result);clear();return result
def publish(target):
    target=Path(target);a=read_json(target/'audit.json')
    if a['status']!='passed':raise ValueError('audit_required_before_publish')
    m=read_json(target/'manifest.json');p={'path':target.relative_to(root()).as_posix(),'artifact_version':m['artifact_version'],'source_hash':m['source_hash'],'dataset_id':m['dataset_id'],'fingerprint':m['fingerprint']};write_json(pointer_path(m['species_id'],m['omics'],m['primary_scope'],m['release_id']),p);write_json(root()/'versions'/component(m['species_id'])/m['omics']/m['primary_scope']/(m['artifact_version']+'.json'),p)
def stale(m,ds):
    from .source import signatures
    return m.get('implementation_hash')!=implementation_hash_for(m['omics'],m['primary_scope']) or m['dataset_id']!=ds.dataset.dataset_id or m['method_version']!=METHOD_VERSION or signatures(ds)!=m['source']['file_signatures']
