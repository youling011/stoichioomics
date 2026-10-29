"""Explicit logical sources; never monkey-patch open, Path, pandas or Arrow.

Unbound sources retain their original behavior. Only a verified per-alias binding
can provide Core from Full; an invalid bound Full never falls back to Core.
"""
from __future__ import annotations
import csv, hashlib, io, json, os
from dataclasses import dataclass
from functools import lru_cache,wraps
from contextvars import ContextVar
from backend.apps.common.host_paths import Path, mapped_path
from .projection import CoreRecipe, ProjectionError
from .readers import CoreCSVSource


def alias_key(path):
    # Stable across Windows/G-only Linux hosts, independent of Core existence.
    raw=os.fspath(path).replace('\\','/')
    runtime='/opt/local/project/data/features_parquet/'
    if raw.startswith(runtime):
        project=os.environ.get('STOICH_PROJECT_ROOT',r'G:\stoichioomics\项目平台数据\stoich_platform_postgres_open_search_v6_2_perf_fix\proj').replace('\\','/').rstrip('/')
        raw=project+'/data/features_parquet/'+raw[len(runtime):]
    mount=os.environ.get('STOICH_WINDOWS_DATA_MOUNT','').replace('\\','/').rstrip('/')
    if mount and (raw==mount or raw.startswith(mount+'/')):
        raw='G:/stoichioomics'+raw[len(mount):]
    if len(raw)>1 and raw[1]==':':raw=raw.casefold()
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class LogicalCore:
    record: dict

    @property
    def full_path(self):return Path(self.record['full_path'])
    @property
    def logical_name(self):return Path(self.record['legacy_path']).name
    @property
    def recipe(self):
        r=self.record['recipe']
        return CoreRecipe(r['omics_type'],tuple(r['columns_json']),r['fill_noncoding'],r['version'])
    @property
    def source(self):
        from .provenance import assert_runtime_rules
        assert_runtime_rules()
        selection=self.record['receipt_json'].get('row_selection')
        if selection and selection.get('kind')!='prefix':raise ProjectionError('Unknown Core row selection')
        return CoreCSVSource(self.full_path,self.recipe,expected_sha256=self.record['full_sha256'],row_limit=selection['count'] if selection else None)
    def check(self):
        stat=self.full_path.stat();expected=self.record['full_stat_json']
        if stat.st_size!=expected['size'] or stat.st_mtime_ns!=expected['mtime_ns']:
            raise ProjectionError('Full asset changed; reverify binding before reading')
        from .asset_state import change_token
        token=change_token(self.full_path)
        frozen=expected.get('host_change_tokens',{}).get(token['host']) or expected.get('change_token')
        if frozen and frozen['host']==token['host']:
            if frozen!=token:raise ProjectionError('Full metadata-change token differs; reverify binding')
        else:
            # A host whose native guard was not captured cannot trust only size
            # and mtime, including for header-only and partial reads.
            if not self.record['full_sha256']:raise ProjectionError('Capture native Full identity on this host before sampled-rule reads')
            _verify_host_asset(str(self.full_path),self.record['full_sha256'],stat.st_size,stat.st_mtime_ns,json.dumps(token,sort_keys=True))
        return self
    def legacy_metadata(self):
        old=self.record['legacy_stat_json'];host='nt' if os.name=='nt' else 'posix'
        captured=old.get('host_stats',{}).get(host)
        if captured:return captured
        token=old.get('change_token')
        if token and token['host']!=host:raise ProjectionError('Legacy source identity on this host was not captured before switching')
        return old
    def open_binary(self):
        self.check()
        return _CheckedStream(self.source.open_binary(**self.record['recipe']['serialization_json']),self.check)
    def open_text(self,encoding='utf-8-sig',newline=''):
        return io.TextIOWrapper(self.open_binary(),encoding=encoding,newline=newline)
    def physical_identity(self):
        self.check()
        return {'full_sha256':self.record['full_sha256'],'recipe_id':self.record['recipe_id'],
                'binding_id':self.record['binding_id'],'scope':'core','virtual_csv_sha256':self.record['virtual_csv_sha256']}


def _database_identity():
    from django.conf import settings
    return str(settings.DATABASES['default']['NAME'])


@lru_cache(maxsize=8192)
def _lookup(database,key,release_context):
    from . import resolver
    from ..models import FeatureSourceBinding
    rows=FeatureSourceBinding.objects.filter(legacy_source_key=key,status='full_backed').select_related('recipe')
    if release_context is not None:rows=rows.filter(release_context=release_context)
    matches=list(rows)
    if not matches:return None
    if len({(r.full_sha256,r.recipe_id,r.virtual_csv_sha256) for r in matches})!=1:
        raise ProjectionError('Ambiguous release binding; explicit release context required')
    r=matches[0]
    data={field.name:getattr(r,field.name) for field in r._meta.fields if field.name not in {'id','dataset','recipe','updated_at'}}
    data['recipe_id']=r.recipe.recipe_id
    data['recipe']={f:getattr(r.recipe,f) for f in ['omics_type','columns_json','fill_noncoding','version','serialization_json']}
    from .provenance import recipe_digest
    if recipe_digest(data['recipe'])!=data['recipe_id']:raise ProjectionError('Immutable Core recipe digest mismatch')
    if hashlib.sha256(json.dumps(r.recipe.columns_json).encode()).hexdigest()!=r.recipe.schema_hash:raise ProjectionError('Core schema identity mismatch')
    if alias_key(r.legacy_path)!=key:raise ProjectionError('Logical alias identity mismatch')
    return data


@lru_cache(maxsize=8192)
def _verify_host_asset(filename,expected,size,mtime,token_json):
    from .asset_state import change_token
    before=json.loads(token_json);h=hashlib.sha256()
    with Path(filename).open('rb') as handle:
        for block in iter(lambda:handle.read(4*1024*1024),b''):h.update(block)
    stat=Path(filename).stat()
    if h.hexdigest()!=expected or stat.st_size!=size or stat.st_mtime_ns!=mtime or change_token(filename)!=before:
        raise ProjectionError('Full identity on this host is unverified or changed')
    return True

def clear_binding_cache():
    _lookup.cache_clear();_binding_table_exists.cache_clear();_offline_manifest.cache_clear();_verify_host_asset.cache_clear();_storage_activation.cache_clear()


@lru_cache(maxsize=1)
def _storage_activation():
    filename=Path(__file__).resolve().parents[1]/'resources/corefull_storage_activation.json'
    if not filename.is_file():return False
    data=json.loads(filename.read_text(encoding='utf-8'))
    if data.get('format')!='corefull-storage-activation-v1':raise ProjectionError('Unknown storage activation format')
    return bool(data.get('active'))

def _requires_binding(path):
    from django.conf import settings
    active=getattr(settings,'STOICH_COREFULL_REQUIRE_BINDINGS',_storage_activation()) if settings.configured else _storage_activation()
    if not active:return False
    native=Path(path)
    roots=[Path(r'G:\stoichioomics\全组学特征数据')]
    if settings.configured:roots.append(Path(getattr(settings,'STOICH_FEATURE_ROOT',roots[0])))
    if any(native.is_relative_to(root) for root in roots):return '.core.' in native.name.lower() and native.suffix.lower()=='.csv'
    project=Path(__file__).resolve().parents[4]
    parquet_roots=[project/'data/features_parquet',Path(r'G:\stoichioomics\项目平台数据\stoich_platform_postgres_open_search_v6_2_perf_fix\proj\data\features_parquet')]
    return any(native.is_relative_to(root) for root in parquet_roots) and native.name.lower()=='core.parquet'

def logical_source(path,release_context=None):
    if not path or not isinstance(path,(str,os.PathLike)):return None
    # Standalone tooling explicitly supplies an audited offline manifest.
    manifest=os.environ.get('STOICH_COREFULL_BINDINGS_MANIFEST')
    key=alias_key(path)
    if manifest:
        data=_offline_manifest(str(Path(manifest).resolve())).get(key)
    else:
        from django.apps import apps
        if not apps.ready:
            default_manifest=Path(__file__).resolve().parents[4]/'runtime/corefull_migration/active_bindings.json'
            if default_manifest.is_file():
                data=_offline_manifest(str(default_manifest)).get(key)
                if data is None and _requires_binding(path):raise ProjectionError('Core source has no verified Full binding')
                return LogicalCore(data).check() if data else None
            if _requires_binding(path):raise ProjectionError('Core source has no verified Full binding')
            return None
        from django.conf import settings
        if not getattr(settings,'STOICH_COREFULL_ENABLED',True):return None
        normalized=os.fspath(path).replace('\\','/').casefold()
        roots=['g:/stoichioomics/','/mnt/g/stoichioomics/']
        mount=os.environ.get('STOICH_WINDOWS_DATA_MOUNT','').replace('\\','/').casefold().rstrip('/')
        if mount:roots.append(mount+'/')
        if not any(normalized.startswith(root) for root in roots) and not getattr(settings,'STOICH_COREFULL_TEST_ALIASES',False):return None
        from django.db import connection
        # The additive migration may not yet have been applied during rollout.
        if not _binding_table_exists(_database_identity()):
            if _requires_binding(path):raise ProjectionError('Required Full binding registry is unavailable')
            return None
        data=_lookup(_database_identity(),key,release_context)
    if data is None and _requires_binding(path):raise ProjectionError('Core source has no verified Full binding')
    return LogicalCore(data).check() if data else None


@lru_cache(maxsize=8)
def _offline_manifest(filename):
    from .offline import IndexedBindings
    return IndexedBindings(filename,alias_key)


@lru_cache(maxsize=8)
def _binding_table_exists(database):
    from django.db import connection
    return 'stoichdb_featuresourcebinding' in connection.introspection.table_names()


def source_available(path):
    if not path:return False
    try:source=logical_source(path)
    except (OSError,ProjectionError):return False
    return bool(source) or Path(path).is_file()


def open_source(path,mode='r',encoding=None,newline=None):
    source=logical_source(path)
    if source:
        if source.record.get('representation')=='parquet':raise ProjectionError('Use the typed logical Parquet interface for this source')
        if mode not in {'r','rt','rb'}:raise ProjectionError('Logical source is read only')
        return source.open_binary() if 'b' in mode else source.open_text(encoding or 'utf-8',newline)
    kwargs={} if 'b' in mode else {'encoding':encoding,'newline':newline}
    return Path(path).open(mode,**kwargs)


def source_header(path):
    source=logical_source(path)
    if source:return list(source.recipe.columns)
    with open_source(path,encoding='utf-8-sig',newline='') as stream:return next(csv.reader(stream),[])


def source_sha256(path):
    source=logical_source(path)
    if source and source.record.get('representation')=='parquet':
        proof=source.record['receipt_json']
        if not proof.get('parquet_match') or not proof.get('parquet_recovery_match'):raise ProjectionError('Unverified legacy Parquet identity')
        return source.record['core_sha256']
    remembered=_remembered_hash(path)
    if remembered is not None:return remembered
    h=hashlib.sha256()
    with open_source(path,'rb') as handle:
        for block in iter(lambda:handle.read(4*1024*1024),b''):h.update(block)
    value=h.hexdigest();source=logical_source(path)
    if source and source.record['virtual_csv_sha256'] and value!=source.record['virtual_csv_sha256']:raise ProjectionError('Virtual Core checksum mismatch')
    return value


def source_signature(path,style='compare'):
    source=logical_source(path)
    if source:
        old=source.legacy_metadata()
        # Compatibility receipt preserves the original scientific source identity.
        # Full identity is independently checked and is never presented as Core stat.
        size,mtime,ino=old['size'],old['mtime_ns'],old.get('ino',0)
        name=old.get('resolved_path',str(path))
    else:
        p=Path(path);stat=p.stat();size,mtime,ino=stat.st_size,stat.st_mtime_ns,stat.st_ino;name=str(p.resolve())
    if style=='sequence':return {'bytes':size,'mtime_ns':mtime}
    if style=='integration':return {'path':str(path),'bytes':size,'mtime_ns':mtime}
    return {'path':name,'size':size,'mtime_ns':mtime,'file_id':ino}


def pandas_input(path):
    source=logical_source(path)
    return source.open_binary() if source else Path(path)


def read_csv(path,*args,**kwargs):
    import pandas as pd
    source=logical_source(path)
    if not source:return pd.read_csv(mapped_path(path),*args,**kwargs)
    stream=source.open_binary()
    try:
        result=pd.read_csv(stream,*args,**kwargs)
    except BaseException:
        stream.close();raise
    if kwargs.get('chunksize') or kwargs.get('iterator'):
        # pandas TextFileReader owns this explicitly opened stream via this wrapper.
        return _ClosingReader(result,stream)
    stream.close();return result


class _ClosingReader:
    def __init__(self,reader,stream):self.reader,self.stream=reader,stream
    def __iter__(self):return self
    def __next__(self):
        try:return next(self.reader)
        except BaseException:self.close();raise
    def close(self):
        try:self.reader.close()
        finally:self.stream.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def __getattr__(self,key):return getattr(self.reader,key)
    def __del__(self):self.close()


class _CheckedStream(io.BufferedReader):
    def __init__(self,stream,check):self._source_check=check;super().__init__(stream)
    def close(self):
        if not self.closed:
            source=self._source_check.__self__
            raw=self.raw.raw
            complete=getattr(raw,'completed',False)
            actual=raw.byte_digest.hexdigest() if complete else None
            byte_count=raw._position if complete else None
            try:super().close()
            finally:self._source_check()
            if complete:
                if source.record['virtual_csv_sha256'] and actual!=source.record['virtual_csv_sha256']:
                    raise ProjectionError('Virtual Core checksum differs from its verified recipe')
                expected_size=source.record.get('virtual_size',source.record['receipt_json'].get('virtual_size'))
                if expected_size is not None and byte_count!=expected_size:
                    raise ProjectionError('Virtual Core byte count differs from the retained source contract')
                _remember_source(source,actual,getattr(raw,'full_digest',None))


_scope_proofs=ContextVar('stoich_corefull_read_scope',default=None)

def read_scope(function):
    """Reuse proven content identities only inside one bounded business read."""
    @wraps(function)
    def invoke(*args,**kwargs):
        token=_scope_proofs.set({})
        try:return function(*args,**kwargs)
        finally:_scope_proofs.reset(token)
    return invoke

def _remember_source(source,core_sha,observed_full_sha=None):
    proofs=_scope_proofs.get()
    if proofs is None:return
    from .asset_state import change_token
    full=source.full_path;stat=full.stat();state=(stat.st_size,stat.st_mtime_ns,change_token(full))
    proofs[alias_key(source.record['legacy_path'])]=(core_sha,full,state)
    full_sha=observed_full_sha or source.record['full_sha256']
    if full_sha:proofs[alias_key(full)]=(full_sha,full,state)

def _remembered_hash(path):
    proofs=_scope_proofs.get()
    if proofs is None or not isinstance(path,(str,os.PathLike)):return None
    saved=proofs.get(alias_key(path))
    if saved is None:return None
    value,full,state=saved
    from .asset_state import change_token
    stat=full.stat()
    if (stat.st_size,stat.st_mtime_ns,change_token(full))!=state:raise ProjectionError('Full changed during one scientific read')
    return value
