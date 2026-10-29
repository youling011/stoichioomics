from __future__ import annotations
from backend.apps.common.atomic_json import atomic_write_json
from django.conf import settings
from backend.apps.common.artifact_locations import file_lock
from functools import wraps

def registry_transaction(fn):
    @wraps(fn)
    def call(project_root,*args,**kwargs):
        with file_lock(_registry_path(project_root).with_suffix(".lock")):
            return fn(project_root,*args,**kwargs)
    return call

from backend.apps.common.host_paths import Path
from typing import Dict, Any, List
import json

REGISTRY_FILE = 'workspace/case_registry.json'


def _registry_path(project_root: str | Path) -> Path:
    if settings.configured and Path(project_root).resolve()==Path(settings.BASE_DIR).resolve():return Path(settings.CASE_REGISTRY_FILE)
    return Path(project_root)/REGISTRY_FILE

def workspace_root(project_root):
    if settings.configured and Path(project_root).resolve()==Path(settings.BASE_DIR).resolve():return Path(settings.WORKSPACE_ROOT)
    return Path(project_root)/'workspace/jobs'

def examples_root(project_root):
    if settings.configured and Path(project_root).resolve()==Path(settings.BASE_DIR).resolve():return Path(settings.ANALYSIS_EXAMPLES_ROOT)
    return Path(project_root)/'data/examples'


def load_registry(project_root: str | Path) -> Dict[str, Any]:
    path = _registry_path(project_root)
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'cases': []}


def save_registry(project_root: str | Path, registry: Dict[str, Any]) -> Path:
    path = _registry_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path,registry)
    return path


@registry_transaction
def register_case(project_root: str | Path, base_dir: str | Path, label: str | None = None, source: str = 'manual', tags: List[str] | None = None) -> Dict[str, Any]:
    project_root = Path(project_root)
    base_dir = Path(base_dir).resolve()
    registry = load_registry(project_root)
    cases = registry.setdefault('cases', [])
    existing = next((c for c in cases if Path(c['base_dir']).resolve() == base_dir), None)
    entry = {
        'case_id': base_dir.name,
        'label': label or base_dir.name,
        'source': source,
        'base_dir': str(base_dir),
        'tags': tags or [],
        'is_registered': True,
    }
    if existing:
        existing.update(entry)
    else:
        cases.append(entry)
    save_registry(project_root, registry)
    return entry


@registry_transaction
def unregister_case(project_root: str | Path, base_dir: str | Path) -> bool:
    project_root = Path(project_root)
    base_dir = Path(base_dir).resolve()
    registry = load_registry(project_root)
    cases = registry.get('cases', [])
    new_cases = [c for c in cases if Path(c['base_dir']).resolve() != base_dir]
    changed = len(new_cases) != len(cases)
    registry['cases'] = new_cases
    save_registry(project_root, registry)
    return changed


def promote_workspace_job(project_root: str | Path, job_id: str, label: str | None = None, tags: List[str] | None = None) -> Dict[str, Any]:
    project_root = Path(project_root)
    base_dir = workspace_root(project_root) / job_id
    return register_case(project_root, base_dir, label=label or f'Workspace job: {job_id}', source='workspace_registered', tags=tags)
