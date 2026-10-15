from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
import json

REGISTRY_FILE = 'workspace/case_registry.json'


def _registry_path(project_root: str | Path) -> Path:
    return Path(project_root) / REGISTRY_FILE


def load_registry(project_root: str | Path) -> Dict[str, Any]:
    path = _registry_path(project_root)
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'cases': []}


def save_registry(project_root: str | Path, registry: Dict[str, Any]) -> Path:
    path = _registry_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


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
    base_dir = project_root / 'workspace' / 'jobs' / job_id
    return register_case(project_root, base_dir, label=label or f'Workspace job: {job_id}', source='workspace_registered', tags=tags)
