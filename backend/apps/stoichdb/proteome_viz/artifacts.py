from pathlib import Path
from functools import lru_cache,wraps
from threading import RLock
from datetime import datetime,timezone
import gzip,hashlib,json,os,re,uuid,time
import numpy as np
from django.conf import settings
from . import METHOD_VERSION
from .contracts import TITLES,CORE_FIELDS,catalog
try:
    import orjson
except ImportError:
    orjson=None

def root():return Path(getattr(settings,'PROTEOME_VIZ_ROOT',settings.BASE_DIR/'runtime'/'proteome_visuals_v3'))
@lru_cache(maxsize=1)
def implementation_hash():
    digest=hashlib.sha256()
    for name in ['contracts.py','source.py','statistics.py','ordination.py','density.py','builders.py']:
        digest.update(name.encode());digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()
def component(value):return hashlib.sha256(str(value).encode()).hexdigest()[:16]
def clean(value):
    if isinstance(value,np.ndarray):return clean(value.tolist())
    if isinstance(value,np.generic):return clean(value.item())
    if isinstance(value,float) and not np.isfinite(value):return None
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    return value

def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.'+uuid.uuid4().hex[:8]+'.tmp')
    if orjson:
        def fallback(obj):
            if isinstance(obj,np.ndarray):return obj.tolist()
            if isinstance(obj,np.generic):return obj.item()
            raise TypeError(type(obj).__name__)
        encoded=orjson.dumps(data,option=orjson.OPT_SERIALIZE_NUMPY,default=fallback)
    else:encoded=json.dumps(clean(data),ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    if path.suffix=='.gz':
        with gzip.open(temp,'wb',compresslevel=1) as out:out.write(encoded)
    else:temp.write_bytes(encoded)
    os.replace(temp,path)

def read_json(path):
    path=Path(path)
    if path.suffix=='.gz':
        with gzip.open(path,'rb') as f:encoded=f.read()
    else:encoded=path.read_bytes()
    return orjson.loads(encoded) if orjson else json.loads(encoded)

def pointer_path(species_id,scope,release):return root()/'published'/component(release)/(component(species_id)+'_'+scope+'.json')
def published(species_id,scope,release):
    p=pointer_path(species_id,scope,release)
    return read_json(p) if p.is_file() else None

def path_for(pointer):
    target=(root()/pointer['path']).resolve()
    if not target.is_relative_to(root().resolve()):raise ValueError('invalid_artifact_path')
    return target

_read_lock=RLock()
def single_flight(fn):
    @wraps(fn)
    def call(*args):
        with _read_lock:return fn(*args)
    def clear():
        with _read_lock:fn.cache_clear()
    call.cache_clear=clear
    return call

@single_flight
@lru_cache(maxsize=1)
def read_bundle(path):return read_json(Path(path)/'figures.json.gz')
@single_flight
@lru_cache(maxsize=1)
def read_matrix(path):
    with np.load(Path(path)/'columns.npz',allow_pickle=False) as f:return {'fields':f['fields'].tolist(),'matrix':f['matrix']}
@single_flight
@lru_cache(maxsize=1)
def read_metadata(path):return read_json(Path(path)/'metadata.json.gz')
@single_flight
@lru_cache(maxsize=1)
def read_arrays(path):
    with np.load(Path(path)/'analysis.npz',allow_pickle=False) as f:return {k:f[k] for k in f.files}

def persist(ds,built,reuse=None):
    version=datetime.now(timezone.utc).strftime('%y%m%d%H%M%S')+'_'+uuid.uuid4().hex[:12]
    # Compact filesystem surrogates avoid Windows MAX_PATH; full identities remain in manifests.
    target=root()/component(ds['release_id'])/component(ds['dataset_id'])/ds['source_hash'][:20]/METHOD_VERSION/version
    target.mkdir(parents=True,exist_ok=False)
    try:
        if reuse:
            for name in ['columns.npz','analysis.npz','metadata.json.gz','profiles.json.gz']:os.link(Path(reuse)/name,target/name)
        else:
            fields=list(ds['values']);np.savez_compressed(target/'columns.npz',fields=np.array(fields),matrix=np.column_stack([ds['values'][f] for f in fields]))
            np.savez_compressed(target/'analysis.npz',**built['arrays'])
            write_json(target/'metadata.json.gz',ds['metadata'])
            write_json(target/'profiles.json.gz',built['profiles'])
        for cid,p in built['figures'].items():
            p['artifact_version']=version
            if 'data' in p:p['data_rows_url']=f'/api/stoichdb/species/{ds["species_id"]}/proteome/visualizations/export/?scope={ds["scope"]}&chart_id={cid}&kind=chart&artifact_version={version}'
        write_json(target/'figures.json.gz',built['figures'])
        manifest={'method_version':METHOD_VERSION,'artifact_version':version,'species_id':ds['species_id'],'dataset_id':ds['dataset_id'],'release_id':ds['release_id'],'source_hash':ds['source_hash'],'primary_scope':ds['scope'],'n_source':ds['n'],'available_scopes':ds['available_scopes'],'fields':catalog(built['fields']),'charts':[{'chart_id':cid,'title':TITLES[cid],'status':p.get('status','available'),'chart_ref':p.get('chart_ref'),'reason_code':p.get('reason_code')} for cid,p in built['figures'].items()],'source':ds['source'],'metadata_coverage':built['metadata_coverage'],'fingerprint':built['fingerprint'],'built_at':datetime.now(timezone.utc).isoformat(),'ready':True}
        manifest['implementation_hash']=implementation_hash()
        write_json(target/'manifest.json',manifest)
    except Exception as exc:
        write_json(target/'failed.json',{'error':str(exc),'time':time.time()});raise
    return target

def audit_path(target):
    target=Path(target);m=read_json(target/'manifest.json');figs=read_bundle(str(target));errors=[]
    if len(m['fields'])<52 or not set(CORE_FIELDS).issubset({f['key'] for f in m['fields']}):errors.append('incomplete_core_field_catalog')
    if set(figs)!=set(TITLES):errors.append('missing_chart_positions')
    profiles=read_json(target/'profiles.json.gz')
    for f,p in profiles.items():
        if p['n_valid']+p['n_missing']!=m['n_source']:errors.append(f'{f}:coverage')
        if sum(p['histogram']['counts'])!=p['histogram']['n_valid']:errors.append(f'{f}:histogram')
    for cid,p in figs.items():
        if p.get('chart_ref'):continue
        if p.get('status')=='failed':errors.append(cid+':failed_result')
        d=p['data'];cov=p['coverage']
        if cov['n_source']!=m['n_source'] or cov['n_valid']+cov['n_excluded']!=m['n_source']:errors.append(cid+':coverage')
        if 'hex' in d and sum(b['count'] for b in d['hex']['bins'])!=d['hex']['n']:errors.append(cid+':hex_count')
        if 'conditional' in d and sum(g['n'] for g in d['conditional'])!=d['hex']['n']:errors.append(cid+':conditional_count')
        if cid=='B04' and sum(q['count'] for q in d['categories'])!=m['n_source']:errors.append(cid+':qc_count')
        if cid=='D06' and sum(q['n'] for q in d['quadrants'])!=d['hex']['n']:errors.append(cid+':quadrants')
        if cid=='D07' and sum(q['n'] for q in d['blocks'])!=m['n_source']:errors.append(cid+':structure_blocks')
        if cid=='D10' and d['contours']['reason']=='grid_convergence_tolerance':errors.append(cid+':density_not_converged')
    a=read_arrays(str(target));meta=read_metadata(str(target));ids=meta['protein_id']
    if len(ids)!=m['n_source'] or len(set(ids))!=len(ids):errors.append('ids_not_unique_or_complete')
    if sorted(a['D07_order'].tolist())!=list(range(m['n_source'])):errors.append('structure_ids_incomplete')
    result={'species_id':m['species_id'],'scope':m['primary_scope'],'artifact_version':m['artifact_version'],'source_hash':m['source_hash'],'n_source':m['n_source'],'chart_positions':len(figs),'status':'passed' if not errors else 'failed','errors':errors}
    write_json(target/'audit.json',result)
    read_bundle.cache_clear();read_matrix.cache_clear();read_metadata.cache_clear();read_arrays.cache_clear()
    return result

def publish(target):
    target=Path(target);audit=read_json(target/'audit.json')
    if audit['status']!='passed':raise ValueError('unverified_artifact_cannot_be_published')
    m=read_json(target/'manifest.json');pointer={'path':target.relative_to(root()).as_posix(),'artifact_version':m['artifact_version'],'source_hash':m['source_hash'],'dataset_id':m['dataset_id'],'fingerprint':m['fingerprint'],'audit':'passed'}
    write_json(pointer_path(m['species_id'],m['primary_scope'],m['release_id']),pointer)
    write_json(root()/'versions'/component(m['species_id'])/m['primary_scope']/(m['artifact_version']+'.json'),pointer)
    return pointer

def lookup_version(species_id,scope,release,version=''):
    pointer=published(species_id,scope,release)
    if not pointer:raise FileNotFoundError('not_prepared')
    if not version or version==pointer['artifact_version']:return path_for(pointer)
    # Resolve only siblings of a registered source, never a client filesystem path.
    if not re.fullmatch(r'[A-Za-z0-9_]+',version):raise ValueError('invalid_artifact_version')
    index=root()/'versions'/component(species_id)/scope/(version+'.json')
    if index.is_file():
        candidate=path_for(read_json(index))
        if candidate.is_dir() and (candidate/'manifest.json').is_file():return candidate
    raise FileNotFoundError('artifact_expired')
