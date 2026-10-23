from __future__ import annotations
from pathlib import Path
from typing import Dict, Any

from backend.input_adapter.merge import build_internal_dataset, export_standardized_dataset
from backend.validation.runner_core import run_validation_pipeline
from backend.mode_resolver.runner_core import run_mode_resolution_pipeline
from backend.analysis_engine.phase1.runner_core import run_phase1_analysis_pipeline
from backend.analysis_engine.phase2.runner_core import run_phase2_stoich_pipeline
from backend.apps.hvg.feature_context import build_hvg_multiomics_feature_context
from backend.workspace import prepare_workspace
from backend.portal.cache import build_case_cache
from backend.portal.jobs import update_job_status


def run_preanalysis_from_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    phase1 = cfg['phase1']
    phase2 = cfg['phase2']
    phase3 = cfg['phase3']
    ws = prepare_workspace(phase1)
    job_id = ws.get('job_id') if ws.get('enabled') else None
    workspace_root = Path(ws['paths']['raw']).parents[1] if ws.get('enabled') else None
    if ws.get('enabled'):
        update_job_status(workspace_root, job_id, 'running_preanalysis')
        phase1 = dict(phase1); phase2 = dict(phase2); phase3 = dict(phase3)
        phase1['output_dir'] = ws['paths']['standardized']
        phase2['input_dir'] = ws['paths']['standardized']; phase2['output_dir'] = ws['paths']['validation']
        if phase1.get('stoich', {}).get('file'):
            phase2['raw_stoich_file'] = str((Path(phase1['input_dir']) / phase1['stoich']['file']).resolve())
        phase3['validation_dir'] = ws['paths']['validation']; phase3['output_dir'] = ws['paths']['mode_resolution']

    ds, manifest, validation = build_internal_dataset(phase1)
    export_standardized_dataset(ds, phase1['output_dir'], manifest, validation, phase1)
    res2 = run_validation_pipeline(phase2)
    res3 = run_mode_resolution_pipeline(phase3)
    result = {'phase1_output_dir': str(Path(phase1['output_dir']).resolve()), 'validation': res2, 'mode_resolution': res3, 'workspace': ws}
    if ws.get('enabled'):
        build_case_cache(Path(ws['job_dir']))
        update_job_status(workspace_root, job_id, 'preanalysis_complete')
    return result


def run_full_pipeline_from_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    from backend.analysis_engine.hvg_research.runner import run_pipeline
    from backend.analysis_engine.hvg_research.workflow import normalize_workflow_config
    return run_pipeline(normalize_workflow_config(cfg))

