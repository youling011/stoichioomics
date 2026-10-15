from __future__ import annotations

from pathlib import Path

from django.conf import settings

from backend.apps.stoichdb.models import StorageObject


ROOT_ALIAS_SETTINGS = {
    'STOICH_DATA_ROOT': 'STOICH_DATA_ROOT',
    'STOICH_FEATURE_ROOT': 'STOICH_FEATURE_ROOT',
    'STOICH_PROJECT_ROOT': 'STOICH_PROJECT_ROOT',
    'STOICH_PROJECT_DATA_ROOT': 'STOICH_PROJECT_DATA_ROOT',
    'STOICHIOOMICS_ROOT': 'STOICHIOOMICS_ROOT',
    'STOICH_RUNTIME_ROOT': 'STOICH_RUNTIME_ROOT',
    'STOICH_BACKUP_ROOT': 'STOICH_BACKUP_ROOT',
}


def root_for_alias(root_alias: str) -> Path:
    base_dir = Path(settings.BASE_DIR)
    setting_name = ROOT_ALIAS_SETTINGS.get(root_alias)
    if setting_name:
        value = getattr(settings, setting_name, None)
        if value:
            return Path(value)
    if root_alias == 'STOICH_FEATURE_ROOT':
        return base_dir.parents[2] / '\u5168\u7ec4\u5b66\u7279\u5f81\u6570\u636e'
    if root_alias == 'STOICH_PROJECT_ROOT':
        return base_dir
    if root_alias == 'STOICH_PROJECT_DATA_ROOT':
        return base_dir / 'data'
    if root_alias == 'STOICHIOOMICS_ROOT':
        return base_dir.parents[2]
    if root_alias == 'STOICH_DATA_ROOT':
        return Path(getattr(settings, 'STOICHDB_DATA_ROOT', base_dir / 'data'))
    if root_alias == 'STOICH_RUNTIME_ROOT':
        return base_dir / 'runtime'
    if root_alias == 'STOICH_BACKUP_ROOT':
        return base_dir / 'backups'
    return base_dir


def resolve_storage_object(storage_object: StorageObject) -> Path | str:
    if storage_object.object_uri:
        return storage_object.object_uri
    relative_path = storage_object.relative_path.replace('\\', '/').lstrip('/')
    return root_for_alias(storage_object.root_alias) / relative_path


def resolve_storage_object_by_key(logical_key: str) -> Path | str | None:
    storage_object = StorageObject.objects.filter(logical_key=logical_key).first()
    if storage_object is None:
        return None
    return resolve_storage_object(storage_object)
