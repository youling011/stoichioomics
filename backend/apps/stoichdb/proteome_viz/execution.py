"""Explicit CLI producer. HTTP views never spawn threads or re-fit scientific models."""
import copy,hashlib,json,os,time
from pathlib import Path
import numpy as np
from django.db import close_old_connections
from . import artifacts as store
from .builders import build
from .contracts import CORE_FIELDS,META
from . import METHOD_VERSION

def draft_path(sid,scope):return store.root()/'drafts'/(store.component(sid)+'_'+scope+'.json')

def reusable(sid,scope,release,model):
    p=store.published(sid,scope,release)
    if not p:return None
    target=store.path_for(p)
    try:
        m=store.read_json(target/'manifest.json')
        if m['method_version']!=METHOD_VERSION or m.get('implementation_hash')!=store.implementation_hash():return None
        for kind in ['core','full']:
            raw=model[kind+'_csv_path'];path=Path(raw) if raw else None;expected=m['source'].get('file_signatures',{}).get(kind)
            actual={'bytes':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns} if path and path.is_file() else None
            if actual!=expected:return None
            if actual:
                from .source import content_hash
                if content_hash(path)!=m['source']['hashes'].get(kind):return None
        return target
    except (OSError,KeyError,ValueError):return None

def run_one(task):
    import django
    django.setup();close_old_connections()
    from .source import load,release_id,numeric
    from django.conf import settings
    if task.get('output_dir'):settings.PROTEOME_VIZ_ROOT=Path(task['output_dir']).resolve()
    sid=task['species_id'];scope=task.get('scope','core');release=release_id();start=time.monotonic();lock=store.root()/'locks'/(store.component(sid)+'_'+scope+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        from .work_requests import process_alive
        try:owner=json.loads(lock.read_text(encoding='utf-8'))
        except (OSError,ValueError):return {'species_id':sid,'scope':scope,'status':'failed','error':'unreadable_task_lock; inspect owner'}
        if not task.get('resume') or process_alive(int(owner.get('pid',0))):return {'species_id':sid,'scope':scope,'status':'failed','error':'task_lock_exists; owner still active or resume not requested'}
        try:
            os.rename(lock,lock.with_suffix('.interrupted_'+str(time.time_ns())))
            fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except OSError:return {'species_id':sid,'scope':scope,'status':'failed','error':'lock_recovery_claim_changed; retry'}
    os.write(fd,json.dumps({'pid':os.getpid(),'started':time.time()}).encode());os.close(fd)
    try:
        if task.get('resume') and not task.get('force'):
            cached=reusable(sid,scope,release,task)
            if cached:
                result={'species_id':sid,'scope':scope,'status':'passed','resumed':True,'path':str(cached),'seconds':time.monotonic()-start}
                if task.get('with_full') and scope=='core' and task.get('full_csv_path'):
                    full_cached=reusable(sid,'full',release,task)
                    result['full']={'status':'passed','resumed':True,'path':str(full_cached)} if full_cached else run_one({**task,'scope':'full','with_full':False})
                return result
        if scope=='full' and not task['full_csv_path']:
            result={'species_id':sid,'scope':scope,'status':'unavailable','reason':'full_not_registered','seconds':time.monotonic()-start};store.write_json(draft_path(sid,scope),result);return result
        ds=load(sid,scope)
        if task.get('fingerprints_only'):
            fp={'species_id':sid,'scope':scope,'source_hash':ds['source_hash'],'n':ds['n'],'means':{f:float(np.nanmean(ds['values'][f])) if np.isfinite(ds['values'][f]).any() else None for f in __import__('backend.apps.stoichdb.proteome_viz.contracts',fromlist=['FINGERPRINT']).FINGERPRINT}}
            fp.update({'counts':{f:int(np.isfinite(ds['values'][f]).sum()) for f in fp['means']},'dataset_id':ds['dataset_id'],'release_id':release,'implementation_hash':store.implementation_hash(),'file_signatures':ds['source']['file_signatures']})
            store.write_json(store.root()/'fingerprints'/store.component(release)/(store.component(sid)+'_'+scope+'.json'),fp);return {'species_id':sid,'scope':scope,'status':'fingerprint_ready'}
        built=build(ds);target=store.persist(ds,built);audit=store.audit_path(target)
        store.write_json(draft_path(sid,scope),{'path':target.relative_to(store.root()).as_posix(),**audit})
        if audit['status']=='passed' and task.get('publish'):store.publish(target)
        result={**audit,'path':str(target),'seconds':time.monotonic()-start}
        # Reuse computation only after exact equality of the complete primary rows/fields.
        if task.get('with_full') and scope=='core' and ds['_full_frame'] is not None:
            f=ds['_full_frame'];c=ds['_core_frame'];fv=numeric(f)
            equal=list(f.protein_id.astype(str))==ds['ids'] and all(k in fv and np.array_equal(fv[k],ds['values'][k],equal_nan=True) for k in CORE_FIELDS)
            equal=equal and all(k in ds['values'] and np.array_equal(a,ds['values'][k],equal_nan=True) for k,a in fv.items())
            equal=equal and all(k not in c or k not in f or c[k].astype(str).tolist()==f[k].astype(str).tolist() for k in META)
            if equal:
                full_ds={**ds,'scope':'full','original_fields':list(fv),'source':copy.deepcopy(ds['source'])}
                hashes={**ds['source']['hashes'],'scope':'full','schema':list(f.columns)};full_ds['source']['hashes']=hashes;full_ds['source_hash']=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
                fb={**built,'fields':list(dict.fromkeys(CORE_FIELDS+list(fv))),'figures':copy.deepcopy(built['figures']),'fingerprint':{**built['fingerprint'],'scope':'full','source_hash':full_ds['source_hash']}}
                for p in fb['figures'].values():
                    if 'data' in p:p['primary_scope']='full';p['source_hash']=full_ds['source_hash']
                # Field atlas defaults stay six fields, extended catalog remains fully reachable.
                from .contracts import catalog
                fb['figures']['B13']['data']['fields']=catalog(fb['fields']);fb['figures']['B13']['data']['total_fields']=len(fb['fields'])
                ft=store.persist(full_ds,fb,reuse=target);fa=store.audit_path(ft);store.write_json(draft_path(sid,'full'),{'path':ft.relative_to(store.root()).as_posix(),**fa})
                if fa['status']=='passed' and task.get('publish'):store.publish(ft)
                result['full']={**fa,'path':str(ft),'computation_reused_after_exact_primary_equality':True}
            else:
                # Primary universes differ: fit the separate Full population without borrowing Core statistics.
                full_task={**task,'scope':'full','with_full':False}
                ds=built=f=c=fv=None
                import gc
                gc.collect()
                result['full']=run_one(full_task)
        return result
    except Exception as exc:
        import traceback
        result={'species_id':sid,'scope':scope,'status':'failed','error':f'{type(exc).__name__}: {exc}','traceback':traceback.format_exc(),'seconds':time.monotonic()-start};store.write_json(draft_path(sid,scope),result);return result
    finally:
        try:lock.unlink()
        except FileNotFoundError:pass
        close_old_connections()
        ds=built=fb=full_ds=f=c=fv=None
        import gc
        gc.collect()
        try:
            from .source import pa
            if pa is not None:pa.default_memory_pool().release_unused()
        except (ImportError,AttributeError):pass

def select_tasks(options):
    from backend.apps.stoichdb.models import OmicsDataset
    q=OmicsDataset.objects.filter(omics_type='proteome').order_by('species__species_id')
    ids=list(options.get('species_id') or [])
    if options.get('species_file'):ids.extend(s.strip() for s in Path(options['species_file']).read_text(encoding='utf-8-sig').splitlines() if s.strip())
    if ids and options.get('all_registered'):raise ValueError('all_registered_and_species_selection_are_mutually_exclusive')
    if ids:
        q=q.filter(species__species_id__in=ids)
        missing=set(ids)-set(q.values_list('species__species_id',flat=True))
        if missing:raise ValueError('unknown_species:'+','.join(sorted(missing)))
    elif not options.get('all_registered'):raise ValueError('choose_species_or_all_registered')
    return [{**options,'species_id':r['species__species_id'],'domain':r['species__domain'],'row_count_core':r['row_count_core'],'core_csv_path':r['core_csv_path'],'full_csv_path':r['full_csv_path']} for r in q.values('species__species_id','species__domain','row_count_core','core_csv_path','full_csv_path')]
