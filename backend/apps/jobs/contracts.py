from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.apps.jobs.models import AnalysisJob


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _uploaded_manifest(job: AnalysisJob) -> list[dict[str, Any]]:
    path = Path(job.workspace_path) / 'logs' / 'upload_manifest.jsonl'
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def build_job_manifest(job: AnalysisJob, stage: str) -> dict[str, Any]:
    return {
        'generated_at': _now_iso(),
        'stage': stage,
        'job_id': job.job_id,
        'name': job.name,
        'module': job.module_name,
        'workflow_module': (job.metadata_json or {}).get('workflow_module') or 'Expression/HVG Stoich Extension',
        'status': job.status,
        'pipeline_type': job.pipeline_type,
        'created_at': job.created_at.isoformat() if job.created_at else None,
        'updated_at': job.updated_at.isoformat() if job.updated_at else None,
        'workspace_path': job.workspace_path,
        'config_path': job.config_path,
        'reproducibility_path': job.reproducibility_path,
        'uploaded_inputs': _uploaded_manifest(job),
        'workspace_policy': (job.metadata_json or {}).get('workspace_policy') or {},
    }


def build_input_qc(job: AnalysisJob, preflight: dict[str, Any] | None = None, auto_config: dict[str, Any] | None = None) -> dict[str, Any]:
    uploaded = _uploaded_manifest(job)
    checks = list((preflight or {}).get('checks') or [])
    blocking = [item for item in checks if item.get('status') == 'blocked']
    warnings = [item for item in checks if item.get('status') in {'degraded', 'pending'}]
    recommended = (auto_config or {}).get('recommended_run_plan') or {}
    expression = recommended.get('expression_matrix') or {}
    metadata = recommended.get('metadata') or {}
    stoich = recommended.get('stoich_features') or {}
    return {
        'generated_at': _now_iso(),
        'module': 'Expression/HVG Stoich Extension',
        'analysis_allowed': not blocking and bool(job.config_path),
        'phase1_allowed': expression.get('status') == 'ready' or bool(job.config_path),
        'phase2_allowed': False,
        'model_policy': 'removed',
        'comparison_allowed': bool(recommended.get('comparison', {}).get('will_run')),
        'uploaded_file_count': len(uploaded),
        'uploaded_inputs': uploaded,
        'auto_detect_summary': {
            'expression_matrix': expression,
            'metadata': metadata,
            'stoich_features': stoich,
            'warnings': (auto_config or {}).get('warnings') or [],
            'blocking_errors': (auto_config or {}).get('blocking_errors') or [],
        },
        'preflight': preflight or {},
        'blocking_errors': blocking + list((auto_config or {}).get('blocking_errors') or []),
        'warnings': warnings + list((auto_config or {}).get('warnings') or []),
    }


def build_analysis_design(job: AnalysisJob, cfg: dict[str, Any] | None = None, auto_config: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = job.metadata_json or {}
    phase1 = (cfg or {}).get('phase1_analysis') or (auto_config or {}).get('effective_config', {}).get('phase1_analysis') or {}
    phase2 = (cfg or {}).get('phase2_stoich') or (auto_config or {}).get('effective_config', {}).get('phase2_stoich') or {}
    return {
        'generated_at': _now_iso(),
        'module': 'Expression/HVG Stoich Extension',
        'research_question': metadata.get('research_question') or 'Identify expression variability and test whether stoichiometric features explain HVG-associated signals.',
        'dataset_context': metadata.get('dataset_context') or '',
        'pipeline_type': job.pipeline_type,
        'phase1_analysis': phase1,
        'phase2_stoich': phase2,
        'statistical_plan': {
            'phase1': 'HVG detection and metadata-stratified summaries when metadata are available.',
            'phase2': 'Non-predictive Core feature comparisons and functional associations; the historical predictive model branch is removed.',
            'validation': 'Use feature confidence intervals, matching, technical resampling, sensitivity analyses and metadata-mode status. Predictive CV and residual classification are excluded.',
        },
        'evidence_policy': {
            'phase1_only': 'Supports descriptive expression-variability results.',
            'phase2_ready': 'Predictive modeling is removed. Feature associations require applicable Core fields, sufficient group sizes, recorded correction families and explicit annotation backgrounds.',
            'registry_promotion': 'Promoted cases must carry manifests, reproducibility metadata, run logs, and download manifest.',
        },
    }


def build_result_interpretation(job: AnalysisJob, input_qc: dict[str, Any], analysis_design: dict[str, Any]) -> dict[str, Any]:
    return {
        'generated_at': _now_iso(),
        'job_id': job.job_id,
        'status': job.status,
        'research_question': analysis_design.get('research_question'),
        'interpretation_scope': {
            'phase1_hvg_descriptive': job.status == AnalysisJob.Status.SUCCEEDED and bool(input_qc.get('phase1_allowed')),
            'phase2_stoich_association': False,
            'nonmodel_feature_association': job.status == AnalysisJob.Status.SUCCEEDED and bool(input_qc.get('comparison_allowed')),
            'model_policy': 'removed',
            'registry_ready': job.status == AnalysisJob.Status.SUCCEEDED and not input_qc.get('blocking_errors'),
        },
        'recommended_read_order': [
            'input_qc.json',
            'analysis_design.json',
            'phase1_summary.json',
            'phase2_summary.json',
            'id_mapping_summary.json',
            'method_metadata.json',
            'reproducibility_manifest.json',
        ],
        'claim_guardrails': [
            'Report HVG method, matrix value semantics, metadata availability, and gene/sample counts.',
            'Report stoichiometric mapping rate and skipped Phase 2 reasons before interpreting associations.',
            'Treat degraded preflight or missing validation as exploratory evidence only.',
        ],
        'warnings': input_qc.get('warnings') or [],
    }


def build_download_manifest(job: AnalysisJob) -> dict[str, Any]:
    workspace = Path(job.workspace_path)
    candidates = [
        ('job_manifest', workspace / 'workflow_contracts' / 'job_manifest.json'),
        ('input_qc', workspace / 'workflow_contracts' / 'input_qc.json'),
        ('analysis_design', workspace / 'workflow_contracts' / 'analysis_design.json'),
        ('result_interpretation', workspace / 'workflow_contracts' / 'result_interpretation.json'),
        ('reproducibility_manifest', Path(job.reproducibility_path) if job.reproducibility_path else workspace / 'logs' / 'reproducibility_manifest.json'),
        ('run_log', workspace / 'logs' / 'job_events.log'),
        ('auto_detect_report', workspace / 'configs' / 'auto_detect_report.json'),
        ('recommended_run_plan', workspace / 'configs' / 'recommended_run_plan.json'),
        ('effective_config', workspace / 'configs' / 'effective_config.json'),
        ('skipped_outputs', workspace / 'logs' / 'skipped_outputs.json'),
    ]
    items = []
    for kind, path in candidates:
        items.append({
            'kind': kind,
            'path': str(path),
            'exists': path.exists(),
            'size_bytes': path.stat().st_size if path.exists() else None,
        })
    return {
        'generated_at': _now_iso(),
        'job_id': job.job_id,
        'items': items,
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


def write_workflow_contracts(
    job: AnalysisJob,
    *,
    stage: str,
    cfg: dict[str, Any] | None = None,
    auto_config: dict[str, Any] | None = None,
    preflight: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    contract_dir = Path(job.workspace_path) / 'workflow_contracts'
    job_manifest = build_job_manifest(job, stage)
    input_qc = build_input_qc(job, preflight=preflight, auto_config=auto_config)
    analysis_design = build_analysis_design(job, cfg=cfg, auto_config=auto_config)
    result_interpretation = build_result_interpretation(job, input_qc, analysis_design)
    download_manifest = build_download_manifest(job)
    payloads = {
        'job_manifest': job_manifest,
        'input_qc': input_qc,
        'analysis_design': analysis_design,
        'result_interpretation': result_interpretation,
        'download_manifest': download_manifest,
    }
    for key, payload in payloads.items():
        _write_json(contract_dir / f'{key}.json', payload)
    download_manifest = build_download_manifest(job)
    _write_json(contract_dir / 'download_manifest.json', download_manifest)
    payloads['download_manifest'] = download_manifest
    _write_json(Path(job.workspace_path) / 'logs' / 'job_manifest.json', job_manifest)
    return payloads
