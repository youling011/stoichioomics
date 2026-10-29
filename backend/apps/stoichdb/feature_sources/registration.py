"""Validate immutable source receipts and attach new Full-only imports."""
import hashlib,json,re,os
from functools import lru_cache
from pathlib import Path as NativePath
from django.core.management.base import CommandError
from backend.apps.common.host_paths import Path
from .asset_state import change_token

def canonical_asset_path(path):
    path=Path(path)
    if os.name=='posix':
        try:descriptor=os.open(path,os.O_PATH|os.O_CLOEXEC)
        except FileNotFoundError:return path.resolve()
        try:
            value=os.readlink('/proc/self/fd/'+str(descriptor))
            if value.endswith(' (deleted)'):raise CommandError('Source disappeared during root validation')
            return Path(value)
        finally:os.close(descriptor)
    return path.resolve()

@lru_cache(maxsize=32)
def canonical_roots(names):
    return tuple(Path(name).resolve() for name in names)

def require_source_root(path):
    from django.conf import settings
    roots=[Path(r'G:\stoichioomics\全组学特征数据'),Path(settings.BASE_DIR)/'data/features_parquet',
        Path(r'G:\stoichioomics\项目平台数据\stoich_platform_postgres_open_search_v6_2_perf_fix\proj\data\features_parquet')]
    roots.extend(Path(value) for value in getattr(settings,'STOICH_COREFULL_ALLOWED_SOURCE_ROOTS',[]))
    resolved=canonical_asset_path(path)
    if not any(resolved.is_relative_to(root) for root in canonical_roots(tuple(str(root) for root in roots))):
        raise CommandError('Source alias is outside the exact permitted feature roots')

def validate_receipt(row,*,require_legacy_core=False):
    from .projection import CoreRecipe
    from .resolver import alias_key
    from .sampling import is_sampled,validate_metadata
    sampled=is_sampled(row)
    if sampled:validate_metadata(row)
    recipe=row['recipe']
    digest=hashlib.sha256(json.dumps(recipe,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    if digest!=row['recipe_id']:raise CommandError('Frozen recipe digest mismatch')
    columns=recipe['columns_json']
    if not columns or len(columns)!=len(set(columns)):raise CommandError('Duplicate or empty Core schema')
    CoreRecipe(recipe['omics_type'],tuple(columns),recipe['fill_noncoding'],recipe['version'])
    for key in ['core_sha256','full_sha256','virtual_csv_sha256','logical_cell_hash']:
        if sampled and row[key]=='':continue
        if not re.fullmatch('[0-9a-f]{64}',row[key]):raise CommandError('Invalid '+key)
    if not isinstance(row['rows'],int) or row['rows']<0:raise CommandError('Invalid Core row count')
    selection=row.get('row_selection')
    if selection and (selection.get('kind')!='prefix' or selection.get('count')!=row['rows'] or selection.get('full_rows',-1)<row['rows']):
        raise CommandError('Unverified Core population selector')
    for key in ['core_path','full_path']:require_source_root(row[key])
    path=Path(row['full_path']);stat=path.stat();expected=row['full_stat'];token=change_token(path)
    if stat.st_size!=expected['size'] or stat.st_mtime_ns!=expected['mtime_ns']:raise CommandError('Full asset changed')
    frozen=expected.get('host_change_tokens',{}).get(token['host']) or expected.get('change_token')
    if not frozen or frozen['host']!=token['host'] or frozen!=token:raise CommandError('Full native change guard is missing or changed on this host')
    core=Path(row['core_path'])
    if row.get('baseline_kind')!='new_full_only':
        if core.is_file():
            actual=core.stat();old=row['core_stat'];native=change_token(core)
            captured=old.get('host_stats',{}).get(native['host'],old)
            expected_token=captured.get('change_token') or old.get('host_change_tokens',{}).get(native['host'])
            if actual.st_size!=old['size'] or actual.st_mtime_ns!=old['mtime_ns'] or expected_token!=native:
                raise CommandError('Original Core changed after equivalence proof')
        elif require_legacy_core:raise CommandError('Original Core was not retained before this switch')

def register_imported_sources(datasets):
    filename=os.environ.get('STOICH_COREFULL_BINDINGS_MANIFEST')
    if not filename:return
    from .resolver import _offline_manifest,alias_key,clear_binding_cache
    from ..models import CoreProjectionRecipe,FeatureSourceBinding
    from django.db import transaction
    manifest=_offline_manifest(str(Path(filename).resolve()))
    from .provenance import frozen_provenance
    provenance=frozen_provenance()
    with transaction.atomic():
        for dataset in datasets:
            source=manifest.get(alias_key(dataset.core_csv_path))
            if source is None:
                if not Path(dataset.core_csv_path).is_file():raise CommandError('Full-only import has no audited logical Core recipe')
                continue
            row=dict(source['receipt_json']);row['recipe']=source['recipe'];row['recipe_id']=source['recipe_id']
            row['core_path']=source['legacy_path'];row['full_path']=source['full_path']
            validate_receipt(row)
            if alias_key(dataset.full_csv_path)!=alias_key(source['full_path']):raise CommandError('Imported Full differs from frozen source')
            recipe_data=source['recipe'];rid=source['recipe_id']
            expected={**recipe_data,'schema_hash':hashlib.sha256(json.dumps(recipe_data['columns_json']).encode()).hexdigest(),
                'extractor_sha256':provenance['extractors'][dataset.omics_type]['sha256']}
            recipe,_=CoreProjectionRecipe.objects.get_or_create(recipe_id=rid,defaults=expected)
            if any(getattr(recipe,k)!=v for k,v in expected.items()):raise CommandError('Immutable Core recipe conflict')
            key=alias_key(dataset.core_csv_path);context=''
            binding_id=hashlib.sha256((dataset.dataset_id+'|'+context+'|'+key).encode()).hexdigest()
            defaults={k:v for k,v in source.items() if k not in {'binding_id','recipe','recipe_id','dataset_id','id','updated_at'}}
            defaults.update(dataset=dataset,recipe=recipe,release_context=context,legacy_source_key=key)
            defaults['receipt_json']={**source['receipt_json'],'dataset_id':dataset.dataset_id,'source_library_only':False,'release_context':context}
            FeatureSourceBinding.objects.update_or_create(
                dataset=dataset,release_context=context,legacy_source_key=key,
                defaults=defaults,create_defaults={**defaults,'binding_id':binding_id})
    clear_binding_cache()
