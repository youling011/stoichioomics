from backend.apps.common.task_execution import heavy_guarded
from backend.apps.stoichdb.feature_sources import io as feature_io
import os,time,json,gc
from pathlib import Path
from . import artifacts as store
from .source import load,release_id,content_hash,signatures
from .builders import build
from backend.apps.stoichdb.complete_core.datasource import CompleteCoreDataSource
from backend.apps.stoichdb.proteome_viz.work_requests import process_alive
@heavy_guarded
def run_one(sid,m,scope='core',resume=False,publish=False,audit_only=False):
    start=time.monotonic();ds=CompleteCoreDataSource(sid,m);lock=store.root()/'locks'/(store.component(sid)+'_'+m+'_'+scope+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    if audit_only:
        target=store.lookup(sid,m,scope,release_id());manifest=store.read_json(target/'manifest.json')
        if store.stale(manifest,ds):raise ValueError('stale_artifact')
        for s,p in [('core',ds.core_path),('full',ds.full_path)]:
            if p and feature_io.source_available(p) and content_hash(p)!=manifest['source']['hashes'][s]:raise ValueError('source_content_hash_mismatch')
        return store.audit(target)
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        old=store.read_json(lock)
        if not resume or process_alive(int(old.get('pid',0))):raise ValueError('active_task_lock')
        os.replace(lock,lock.with_suffix('.interrupted_'+str(time.time_ns())));fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    os.write(fd,json.dumps({'pid':os.getpid(),'started':time.time()}).encode());os.close(fd)
    try:
        if resume:
            try:
                target=store.lookup(sid,m,scope,release_id());manifest=store.read_json(target/'manifest.json')
                if not store.stale(manifest,ds) and all(not p or not feature_io.source_available(p) or content_hash(p)==manifest['source']['hashes'][s] for s,p in [('core',ds.core_path),('full',ds.full_path)]):
                    a=store.read_json(target/'audit.json')
                    if a['status']=='passed':return {**a,'resumed':True,'seconds':time.monotonic()-start}
                from .coordinate_upgrade import compatible,upgrade
                if manifest['dataset_id']==ds.dataset.dataset_id and compatible(manifest) and all(not p or not feature_io.source_available(p) or content_hash(p)==manifest['source']['hashes'][s] for s,p in [('core',ds.core_path),('full',ds.full_path)]) and store.read_json(target/'audit.json')['status']=='passed':
                    data,built=upgrade(target);new=store.persist(data,built);a=store.audit(new)
                    if a['status']!='passed':raise ValueError('coordinate_upgrade_audit_failed')
                    if publish:store.publish(new)
                    return {**a,'path':str(new),'coordinate_upgrade':True,'published':publish,'seconds':time.monotonic()-start}
            except FileNotFoundError:pass
        if scope=='full' and not (ds.full_path and feature_io.source_available(ds.full_path)):return {'status':'unavailable','species_id':sid,'omics':m,'scope':scope,'reason_code':'full_not_registered' if not ds.dataset.full_csv_path else 'source_full_file_missing'}
        data=load(sid,m,scope)
        from .full_scope import apply
        apply(data)
        # The verified numeric arrays and literal metadata now own the analysis
        # inputs. Drop original DataFrames before large complete-population fits.
        data.pop('_core',None);data.pop('_full',None);gc.collect()
        try:
            import pyarrow as pa
            pa.default_memory_pool().release_unused()
        except ImportError:pass
        from .equality_reuse import try_reuse
        built=try_reuse(data)
        if built is None:built=build(data)
        from .coordinates import apply as coordinate_apply
        coordinate_apply(data,built)
        if signatures(ds)!=data['source']['file_signatures']:raise ValueError('source_changed_during_build')
        target=store.persist(data,built);result=store.audit(target)
        if result['status']!='passed':raise ValueError('artifact_audit_failed:'+str(result['errors']))
        if publish:store.publish(target)
        return {**result,'path':str(target),'published':publish,'seconds':time.monotonic()-start}
    finally:lock.unlink(missing_ok=True);store.clear();gc.collect()
