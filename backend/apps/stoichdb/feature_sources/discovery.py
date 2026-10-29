"""Discover physical paths and explicit logical aliases without creating files."""
import os
from pathlib import PurePosixPath
from backend.apps.common.host_paths import Path
from .resolver import _offline_manifest,_binding_table_exists,_database_identity,alias_key

def binding_records():
    filename=os.environ.get('STOICH_COREFULL_BINDINGS_MANIFEST')
    if filename:
        yield from _offline_manifest(str(Path(filename).resolve())).alias_records();return
    from django.apps import apps
    if not apps.ready:
        filename=Path(__file__).resolve().parents[4]/'runtime/corefull_migration/active_bindings.json'
        if filename.is_file():yield from _offline_manifest(str(filename)).alias_records()
        return
    from django.conf import settings
    if not getattr(settings,'STOICH_COREFULL_ENABLED',True):return
    if not _binding_table_exists(_database_identity()):return
    from ..models import FeatureSourceBinding
    yield from FeatureSourceBinding.objects.filter(status='full_backed').values('legacy_path','representation').iterator(chunk_size=512)

def logical_glob(root,pattern,*,recursive=False):
    root=Path(root)
    seen=set()
    for path in (root.rglob(pattern) if recursive else root.glob(pattern)):
        seen.add(alias_key(path));yield path
    # Match aliases only within the exact requested directory tree. A recipe
    # never manufactures an unknown species or a speculative Core path.
    for row in binding_records():
        path=Path(row['legacy_path'])
        try:relative=path.relative_to(root)
        except ValueError:continue
        name=relative.as_posix()
        if not recursive and '/' not in pattern and len(relative.parts)!=1:continue
        matches=PurePosixPath(name).match(pattern) or (recursive and PurePosixPath(name).match('**/'+pattern))
        key=alias_key(path)
        if matches and key not in seen:
            from .resolver import source_available
            if source_available(path):seen.add(key);yield path

def logical_rglob(root,pattern):
    return logical_glob(root,pattern,recursive=True)
