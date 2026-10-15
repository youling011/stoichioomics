from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
import json, shutil

STAGES = ['raw', 'standardized', 'validation', 'mode_resolution', 'analysis_phase1', 'analysis_phase2', 'logs']


def prepare_workspace(config: Dict[str, Any]) -> Dict[str, Any]:
    ws = config.get('workspace', {}) or {}
    enabled = bool(ws.get('enabled', False))
    if not enabled:
        return {'enabled': False}
    root = Path(ws.get('root_dir', 'workspace/jobs'))
    job_id = ws.get('job_id') or config.get('case_id') or 'job_001'
    job_dir = root / job_id
    paths = {stage: job_dir / stage for stage in STAGES}
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    manifest = {
        'enabled': True,
        'job_id': job_id,
        'job_dir': str(job_dir.resolve()),
        'paths': {k: str(v.resolve()) for k, v in paths.items()},
    }
    with open(job_dir / 'workspace_manifest.json', 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest
