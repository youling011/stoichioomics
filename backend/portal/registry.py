from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any
import json
from .library import load_registry


def _detect_case(base: Path, label: str, source: str, tags: list[str] | None = None) -> Dict[str, Any] | None:
    phase1 = base / 'analysis_phase1' / 'hvg_baseline.csv'
    phase2 = base / 'analysis_phase2' / 'hvg_summary.json'
    research = base / 'hvg_functional_comparison' / 'active_run.json'
    if not phase1.exists() and not phase2.exists() and not research.exists():
        return None
    cache_path = base / 'case_cache.json'
    return {
        'case_id': base.name,
        'has_hvg_research': research.exists(),
        'label': label,
        'source': source,
        'base_dir': str(base.resolve()),
        'phase1_dir': str((base / 'analysis_phase1').resolve()) if (base / 'analysis_phase1').exists() else None,
        'phase2_dir': str((base / 'analysis_phase2').resolve()) if (base / 'analysis_phase2').exists() else None,
        'workspace_manifest': str((base / 'workspace_manifest.json').resolve()) if (base / 'workspace_manifest.json').exists() else None,
        'cache_file': str(cache_path.resolve()) if cache_path.exists() else None,
        'tags': tags or [],
    }


def scan_cases(project_root: str | Path) -> List[Dict[str, Any]]:
    project_root = Path(project_root)
    out: List[Dict[str, Any]] = []
    seen = set()

    ex_root = project_root / 'data' / 'examples'
    if ex_root.exists():
        for d in sorted([p for p in ex_root.iterdir() if p.is_dir()]):
            c = _detect_case(d, f'Example: {d.name}', 'example')
            if c:
                out.append(c); seen.add(Path(c['base_dir']).resolve())

    jobs_root = project_root / 'workspace' / 'jobs'
    if jobs_root.exists():
        for d in sorted([p for p in jobs_root.iterdir() if p.is_dir()]):
            c = _detect_case(d, f'Workspace job: {d.name}', 'workspace')
            if c and Path(c['base_dir']).resolve() not in seen:
                out.append(c); seen.add(Path(c['base_dir']).resolve())

    registry = load_registry(project_root)
    for item in registry.get('cases', []):
        base = Path(item['base_dir'])
        c = _detect_case(base, item.get('label', base.name), item.get('source', 'manual'), tags=item.get('tags', []))
        if c and Path(c['base_dir']).resolve() not in seen:
            out.append(c); seen.add(Path(c['base_dir']).resolve())

    return out
