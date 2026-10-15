from __future__ import annotations
from pathlib import Path
from typing import Iterable, Dict, Any, List
import json, uuid

STAGE_DIRS = ['raw','standardized','validation','mode_resolution','analysis_phase1','analysis_phase2','logs','configs']


def ensure_job_dirs(workspace_root: str | Path, job_id: str | None = None) -> Dict[str, Any]:
    root = Path(workspace_root)
    job_id = job_id or f'job_{uuid.uuid4().hex[:8]}'
    job_dir = root / job_id
    paths = {stage: job_dir / stage for stage in STAGE_DIRS}
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    manifest = {'job_id': job_id, 'job_dir': str(job_dir.resolve()), 'paths': {k: str(v.resolve()) for k,v in paths.items()}, 'status': 'created'}
    with open(job_dir / 'job_manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def update_job_status(workspace_root: str | Path, job_id: str, status: str, extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    job_dir = Path(workspace_root) / job_id
    manifest_path = job_dir / 'job_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {'job_id': job_id, 'job_dir': str(job_dir.resolve())}
    manifest['status'] = status
    if extra:
        manifest.update(extra)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def _write_bytes(dest: Path, content: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, 'wb') as f:
        f.write(content)


def create_job_from_uploads(workspace_root: str | Path, uploaded_files: Iterable[Any], job_id: str | None = None) -> Dict[str, Any]:
    manifest = ensure_job_dirs(workspace_root, job_id=job_id)
    raw_dir = Path(manifest['paths']['raw'])
    saved = []
    for uf in uploaded_files:
        name = getattr(uf, 'name', None)
        if not name:
            continue
        data = uf.getvalue() if hasattr(uf, 'getvalue') else uf.read()
        dest = raw_dir / name
        _write_bytes(dest, data)
        saved.append(str(dest.resolve()))
    with open(raw_dir / 'uploaded_files.json', 'w', encoding='utf-8') as f:
        json.dump({'files': saved}, f, ensure_ascii=False, indent=2)
    update_job_status(workspace_root, manifest['job_id'], 'uploaded', {'uploaded_files': saved})
    return manifest


def list_workspace_jobs(workspace_root: str | Path) -> List[Dict[str, Any]]:
    root = Path(workspace_root)
    if not root.exists():
        return []
    jobs = []
    for job_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
        manifest_path = job_dir / 'job_manifest.json'
        manifest = None
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        jobs.append({
            'job_id': job_dir.name,
            'job_dir': str(job_dir.resolve()),
            'manifest': manifest,
            'status': manifest.get('status') if manifest else None,
            'has_phase2': (job_dir / 'analysis_phase2' / 'hvg_summary.json').exists(),
            'has_phase1': (job_dir / 'analysis_phase1' / 'hvg_baseline.csv').exists(),
            'has_mode_resolution': (job_dir / 'mode_resolution' / 'mode_resolution.json').exists(),
        })
    return jobs
