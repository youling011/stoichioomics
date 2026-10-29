from backend.apps.common.artifact_locations import lookup_publication,pointer_target,read_roots,same_source_signatures,budget_cache
from backend.apps.stoichdb.feature_sources.compatibility import implementation_bytes
from pathlib import Path
from functools import lru_cache
import os,json,hashlib,uuid,gzip,time,re
import numpy as np
import pandas as pd
import orjson
from django.conf import settings
from backend.apps.stoichdb.proteome_viz.artifacts import clean
from . import METHOD_VERSION,SCHEMA_VERSION
from .contracts import FIGURES,COHORT_IDS
def root():return Path(getattr(settings,'INTEGRATION_VIZ_ROOT',settings.BASE_DIR/'runtime/integration_visuals_v1'))
def component(s):return hashlib.sha256(str(s).encode()).hexdigest()[:16]
def permission_retry(operation):
    # Windows virus scanners and concurrent atomic replacement can briefly
    # deny a read/rename. Retry only sharing/permission failures; preserve
    # missing-file and integrity errors and never return partially read JSON.
    for attempt in range(100):
        try:return operation()
        except PermissionError:
            if attempt==99:raise
            time.sleep(.01)

def write(p,data):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name('tmp_'+uuid.uuid4().hex[:12])
    # orjson emits non-finite values as JSON null and handles native numeric
    # arrays without a recursive Python copy of every field/ECDF scalar.
    content=orjson.dumps(data,option=orjson.OPT_SERIALIZE_NUMPY|orjson.OPT_NON_STR_KEYS,default=lambda x:x.item() if isinstance(x,np.generic) else str(x))
    if p.suffix=='.gz':content=gzip.compress(content,compresslevel=3)
    tmp.write_bytes(content);permission_retry(lambda:os.replace(tmp,p))
def read(p):
    p=Path(p)
    from backend.apps.common.artifact_integrity import verify_file
    from backend.apps.common.request_timing import stage
    with stage('integrity'):verify_file(p)
    with stage('artifact_io'):b=permission_retry(p.read_bytes)
    with stage('inflate'):decoded=gzip.decompress(b) if p.suffix=='.gz' else b
    with stage('decode'):return json.loads(decoded)
@lru_cache(maxsize=1)
def implementation_hash():
    h=hashlib.sha256()
    for n in ['source','contracts','statistics','mapping','analysis','correlations','coordinates','cohorts','builders']:
        h.update(implementation_bytes(Path(__file__).with_name(n+'.py')))
    h.update(Path(__file__).with_name('figure_contracts.json').read_bytes());return h.hexdigest()
def home(sid):return root()/'species'/component(sid)
def lookup(sid,version='',validator=None):
    if version and not re.fullmatch('[a-f0-9]{20}',version):raise ValueError('invalid_artifact_version')
    relative='species/'+component(sid)+'/published.json'
    return pointer_target('integration',root(),lookup_publication('integration',root(),relative,read,version,validator=validator))
def table(target,key):
    p=Path(target)/'tables'/(key+'.parquet')
    from backend.apps.common.artifact_integrity import verify_file
    if p.is_file():verify_file(p)
    return pd.read_parquet(p) if p.is_file() else pd.DataFrame()
def persist(sid,built):
    version=uuid.uuid4().hex[:20];stage=root()/'staging'/version;stage.mkdir(parents=True)
    source=built['source'];identity={'species_id':sid,'release_id':source['release_id'],'source_hash':source['source_hash'],'artifact_version':version,'method_version':METHOD_VERSION,'schema_version':SCHEMA_VERSION,'implementation_hash':implementation_hash()}
    charts=built['charts']
    for cid,c in charts.items():c.update(identity);write(stage/'charts'/(cid+'.json.gz'),c)
    for m,profiles in built['profiles'].items():
        write(stage/'fields'/(m+'.json.gz'),profiles)
        write(stage/'fields'/(m+'.json'),[{k:v for k,v in p.items() if k not in ['histogram','ecdf']} for p in profiles])
    for m,rows in built['metadata'].items():
        write(stage/'metadata'/(m+'.json.gz'),rows)
        write(stage/'metadata'/(m+'.json'),[{k:v for k,v in r.items() if k!='categories'} for r in rows])
    (stage/'tables').mkdir(exist_ok=True)
    for key,rows in built['tables'].items():
        f=pd.DataFrame(rows)
        # Scalar/list cells keep native identifiers; parquet eliminates JSON
        # materialization in request handlers and preserves numeric null masks.
        f.to_parquet(stage/'tables'/(key+'.parquet'),index=False,compression='zstd')
    for m,f in built['ds']['raw'].items():f.to_parquet(stage/'tables'/('source_'+m+'.parquet'),index=False,compression='zstd')
    write(stage/'members.json.gz',built['members']);write(stage/'source_audit.json',source);write(stage/'mapping_audit.json',built.get('mapping',{}));write(stage/'math.json',built.get('math',{}))
    manifest={**identity,'storage_version':2,'policy':'core_plus_optional_full','status':'ready','coverage':{'numeric_core_fields':sum(len(x) for x in built['profiles'].values()),'metadata_core_fields':sum(len(x) for x in built['metadata'].values())},'catalog':{m:[{k:v for k,v in p.items() if k not in ['ecdf','histogram']} for p in ps] for m,ps in built['profiles'].items()},'charts':[{'id':cid,'status':charts[cid]['status'] if cid in charts else 'queued','n_source':charts[cid]['n_source'] if cid in charts else None,'n_valid':charts[cid]['n_valid'] if cid in charts else None} for cid in FIGURES],'source_audit':{m:{k:v for k,v in v.items() if k not in ['header','invalid_counts']} for m,v in source['core'].items()},'supplement':source['supplement'],'links':{'charts':'charts/','fields':'fields/','metadata':'metadata/','candidates':'candidates/'}}
    write(stage/'manifest.json',manifest)
    from .evidence_store import attach
    attach(stage)
    audit=audit_target(stage)
    if not audit['passed']:raise ValueError('artifact_audit_failed:'+str(audit['errors']))
    from .source import signatures
    if signatures(sid)!=source['signatures']:raise ValueError('source_changed_before_publish')
    target=home(sid)/'versions'/version;target.parent.mkdir(parents=True,exist_ok=True);os.replace(stage,target)
    return target
def audit_target(target,save=True):
    target=Path(target);m=read(target/'manifest.json');errors=[];counts={}
    for omics,rows in m['catalog'].items():
        for r in rows:
            p=field_profile(target,omics,r['field'])
            if p['n_valid']+p['n_missing']!=p['n_source'] or sum(p['histogram']['counts'])!=p['n_valid'] or sum(p['ecdf']['counts'])!=p['n_valid']:errors.append(omics+':'+p['field'])
        counts[omics]=len(rows)
    members=read(target/'members.json.gz')
    for cid in FIGURES:
        if cid in COHORT_IDS:continue
        p=target/'charts'/(cid+'.json.gz')
        if not p.is_file():errors.append(cid+':missing');continue
        c=read(p);h=c['data'].get('hex')
        if h:
            if sum(b['count'] for b in h['bins'])!=h['n']:errors.append(cid+':hex_count')
            for b in h['bins']:
                if len(members[b['selection_id']])!=b['count']:errors.append(cid+':members')
    math=read(target/'math.json')
    errors.extend(k for k,v in math.get('checks',{}).items() if not v)
    if m.get('storage_version',1)>=3 and all(v.get('status')=='available' for v in m['source_audit'].values()):
        import pyarrow.parquet as pq
        p=target/'tables/gene_valid_counts.parquet';expected={'gene_id'}|{omics+'__'+r['field'] for omics,rows in m['catalog'].items() for r in rows}
        if not p.exists():errors.append('gene_valid_counts_missing')
        else:
            meta=pq.read_metadata(p)
            if set(meta.schema.names)!=expected or meta.num_rows!=pq.read_metadata(target/'tables/gene_matrix.parquet').num_rows:errors.append('gene_valid_counts_incomplete')
        for omics in m['catalog']:
            if not (target/'raw_sources'/(omics+'.csv.gz')).is_file():errors.append(omics+':lossless_source_snapshot_missing')
    r={'passed':not errors,'errors':errors,'coverage':m['coverage'],'fields_by_omics':counts,'artifact_version':m['artifact_version']}
    if save:write(target/'audit.json',r)
    return r
def publish(target):
    m=read(Path(target)/'manifest.json');a=read(Path(target)/'audit.json')
    if not a['passed']:raise ValueError('audit_required')
    write(home(m['species_id'])/'published.json',{'artifact_version':m['artifact_version'],'source_hash':m['source_hash']})
def compatible_implementation(manifest,target):
    current=implementation_hash()
    if manifest['implementation_hash']==current:return True
    # Explicit, one-fix compatibility for a presentation ordering edge case.
    # Future numerical/source changes still invalidate every old publication.
    policy=read(Path(__file__).with_name('implementation_compatibility.json'))
    if current==policy['current'] and manifest['implementation_hash']==policy['accepted_prior'] and read(Path(target)/'audit.json')['passed']:return True
    receipt=read(Path(__file__).with_name('deployment_io_compatibility.json'))
    return (receipt.get('format')=='exact-integration-io-chain-v1'
        and hashlib.sha256(Path(__file__).with_name('implementation_compatibility.json').read_bytes()).hexdigest()==receipt['prior_policy_sha256']
        and current==receipt['current'] and manifest['implementation_hash'] in receipt['accepted_prior']
        and read(Path(target)/'audit.json')['passed'])

def stale(sid,target):
    from .source import signatures
    m=read(Path(target)/'manifest.json');s=read(Path(target)/'source_audit.json')
    return not compatible_implementation(m,target) or not same_source_signatures(s['signatures'],signatures(sid))

@budget_cache('')
def _profile_file(filename):return read(Path(filename))

def profile_bundle(target,omics,kind='fields'):
    return _profile_file(str(Path(target)/kind/(omics+'.json.gz')))
profile_bundle.cache_clear=_profile_file.cache_clear
def field_profile(target,omics,field):
    if (Path(target)/'fields'/(omics+'.json.gz')).exists():return next(r for r in profile_bundle(str(target),omics) if r['field']==field)
    return read(Path(target)/'fields'/omics/(component(field)+'.json.gz'))
def metadata_profile(target,omics,field):
    if (Path(target)/'metadata'/(omics+'.json.gz')).exists():return next(r for r in profile_bundle(str(target),omics,'metadata') if r['field']==field)
    return read(Path(target)/'metadata'/omics/(component(field)+'.json.gz'))

def clone_immutable(source,dest):
    import shutil
    receipt={'hardlinked_files':0,'copied_sha_verified_files':0}
    def copy(src,dst):
        try:os.link(src,dst);receipt['hardlinked_files']+=1
        except OSError:
            shutil.copy2(src,dst)
            from .source import digest
            if digest(src)!=digest(dst):raise ValueError('immutable_copy_hash_mismatch')
            receipt['copied_sha_verified_files']+=1
        return dst
    shutil.copytree(source,dest,copy_function=copy);return receipt

def audit_ancillary(target,parent,receipt):
    import pyarrow.parquet as pq
    target,parent=Path(target),Path(parent);old=read(parent/'audit.json');m=read(target/'manifest.json');pm=read(parent/'manifest.json');errors=[]
    if not old['passed'] or m['source_hash']!=pm['source_hash'] or m['implementation_hash']!=pm['implementation_hash']:errors.append('verified_parent_identity_mismatch')
    expected={'gene_id'}|{omics+'__'+r['field'] for omics,rows in m['catalog'].items() for r in rows};p=target/'tables/gene_valid_counts.parquet'
    if not p.exists():errors.append('support_counts_missing')
    else:
        counts=pq.read_metadata(p)
        if set(counts.schema.names)!=expected or counts.num_rows!=pq.read_metadata(target/'tables/gene_matrix.parquet').num_rows:errors.append('support_count_shape_mismatch')
    for omics in m['catalog']:
        if not (target/'raw_sources'/(omics+'.csv.gz')).is_file():errors.append('raw_snapshot_missing:'+omics)
    result={**old,'passed':not errors,'errors':errors,'artifact_version':m['artifact_version'],'storage_version':3,'validation':'unchanged scientific artifacts inherit a passed immutable parent; raw CSV content SHA verified while copying; all new gene support columns/rows audited','verified_parent_version':pm['artifact_version'],'immutable_copy':receipt};write(target/'audit.json',result);return result

def upgrade_native(target,sid,publishing=True):
    import shutil
    from .source import registry,read as read_frame,numeric_frame,supplement,signatures
    from .native_evidence import compute,attach
    before=signatures(sid)
    if read(Path(target)/'manifest.json').get('storage_version',1)>=2:
        version=uuid.uuid4().hex[:20];stage=root()/'staging'/version;receipt=clone_immutable(target,stage)
        from .evidence_store import attach as attach_storage
        attach_storage(stage);m=read(stage/'manifest.json');m['artifact_version']=version;write(stage/'manifest.json',m)
        for f in (stage/'charts').glob('*.json.gz'):
            c=read(f);c['artifact_version']=version;write(f,c)
        if signatures(sid)!=before:raise ValueError('source_changed_during_support_upgrade')
        if not audit_ancillary(stage,target,receipt)['passed']:raise ValueError('support_upgrade_audit_failed')
        dest=home(sid)/'versions'/version;os.replace(stage,dest)
        if publishing:publish(dest)
        return dest
    d=registry(sid)['genome'];g=numeric_frame(read_frame(d.core_csv_path,'genome'),'genome')[0];g,_=supplement(g,d.full_csv_path);native,quality=compute(g)
    version=uuid.uuid4().hex[:20];stage=root()/'staging'/version;shutil.copytree(target,stage)
    built={'tables':{k:table(stage,k).to_dict('records') for k in ['chain_rows','candidates','x1_shifts']},'source':read(stage/'source_audit.json'),'math':read(stage/'math.json')};attach(built,native,quality)
    for k,v in built['tables'].items():pd.DataFrame(v).to_parquet(stage/'tables'/(k+'.parquet'),index=False,compression='zstd')
    write(stage/'source_audit.json',built['source']);write(stage/'math.json',built['math']);m=read(stage/'manifest.json');m.update(artifact_version=version,storage_version=2);write(stage/'manifest.json',m)
    for f in (stage/'charts').glob('*.json.gz'):
        c=read(f);c['artifact_version']=version;write(f,c)
    from .evidence_store import attach as attach_storage
    attach_storage(stage)
    if signatures(sid)!=before:raise ValueError('source_changed_during_native_evidence_upgrade')
    if not audit_target(stage)['passed']:raise ValueError('native_upgrade_audit_failed')
    dest=home(sid)/'versions'/version;os.replace(stage,dest)
    if publishing:publish(dest)
    return dest
