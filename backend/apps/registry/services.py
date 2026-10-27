from __future__ import annotations
import json
from backend.apps.common.host_paths import Path
from typing import List, Dict, Any
from datetime import datetime, timezone
from django.conf import settings
from backend.portal.registry import scan_cases
from backend.portal.library import register_case, unregister_case, promote_workspace_job
from backend.portal.compare import compare_cases
from backend.apps.stoichdb import case_studies


def _model8_case5_registry_cases() -> list[dict[str, Any]]:
    try:
        summary = case_studies.model8_case5_summary_payload()
    except Exception:
        return []

    generated_at = summary.get('generated_at_utc')
    rows = summary.get('species_status') or []
    out: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get('case_code') or '').upper()
        if not code:
            continue
        phase2_status = row.get('phase2_status') or 'unknown'
        phase2_mode = row.get('phase2_mode') or phase2_status
        out.append({
            'case_id': f'model8-case5-{code}',
            'label': f'Model-8 HVG-Stoich: {code}',
            'source': 'curated_model8_case5',
            'base_dir': str((settings.BASE_DIR / 'data' / 'case_studies' / 'model8' / 'case5_hvg_stoich').resolve()),
            'phase1_dir': None,
            'phase2_dir': None,
            'workspace_manifest': None,
            'cache_file': None,
            'tags': ['Model-8', 'HVG-Stoich', code, 'curated case'],
            'workflow_module': 'Expression/HVG Stoich Extension',
            'case_family': 'model8_case5_hvg_stoich',
            'species_case_code': code,
            'status': 'SUCCEEDED' if phase2_status == 'complete' else str(phase2_status).upper(),
            'updated_at': generated_at,
            'summary': {
                'accession': row.get('accession'),
                'genes_profiled': row.get('genes_profiled'),
                'cells_or_samples': row.get('cells_or_samples'),
                'mapped_genes': row.get('mapped_genes'),
                'mapping_rate': row.get('mapping_rate'),
                'hvg_consensus_count': row.get('hvg_consensus_count'),
                'phase2_mode': phase2_mode,
            },
            'description': 'Curated Model-8 species case rendered through the same Expression/HVG workflow result page as a saved job.',
        })
    return out


def list_cases() -> List[Dict[str, Any]]:
    cases = scan_cases(settings.BASE_DIR)
    existing_ids = {case.get('case_id') for case in cases}
    for case in _model8_case5_registry_cases():
        if case['case_id'] not in existing_ids:
            cases.append(case)
    return cases


def refresh_registry_cache() -> List[Dict[str, Any]]:
    return list_cases()


def register_existing_case(base_dir: str, label: str | None = None, tags: list[str] | None = None):
    return register_case(settings.BASE_DIR, base_dir, label=label, tags=tags or [])


def unregister_existing_case(base_dir: str):
    return unregister_case(settings.BASE_DIR, base_dir)


def promote_job(job_id: str, label: str | None = None, tags: list[str] | None = None):
    payload = promote_workspace_job(settings.BASE_DIR, job_id, label=label, tags=tags or [])
    base_dir_raw = payload.get('base_dir') or payload.get('case_dir')
    base_dir = Path(str(base_dir_raw)) if base_dir_raw else None
    if base_dir and base_dir.exists():
        manifest = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'job_id': job_id,
            'label': label,
            'tags': tags or [],
            'registry_payload': payload,
            'required_research_contract': [
                'job_manifest',
                'input_qc',
                'analysis_design',
                'method_metadata',
                'result_interpretation',
                'download_manifest',
                'reproducibility_manifest',
            ],
        }
        (base_dir / 'registry_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def compare_case_ids(case_ids: list[str]):
    cases = [c for c in list_cases() if c['case_id'] in set(case_ids)]
    return compare_cases(cases)
