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
    p1 = cfg['input_adapter']
    p2 = cfg['validation']
    p3 = cfg['mode_resolution']
    p4a = cfg['phase1_analysis']
    p4b = cfg['phase2_stoich']

    ws = prepare_workspace(p1)
    job_id = ws.get('job_id') if ws.get('enabled') else None
    workspace_root = Path(ws['paths']['raw']).parents[1] if ws.get('enabled') else None
    if ws.get('enabled'):
        update_job_status(workspace_root, job_id, 'running_full_analysis')
        p1 = dict(p1); p2 = dict(p2); p3 = dict(p3); p4a = dict(p4a); p4b = dict(p4b)
        p1['output_dir'] = ws['paths']['standardized']
        p2['input_dir'] = ws['paths']['standardized']; p2['output_dir'] = ws['paths']['validation']
        if p1.get('stoich', {}).get('file'):
            p2['raw_stoich_file'] = str((Path(p1['input_dir']) / p1['stoich']['file']).resolve())
        p3['validation_dir'] = ws['paths']['validation']; p3['output_dir'] = ws['paths']['mode_resolution']
        p4a['standardized_input_dir'] = ws['paths']['standardized']; p4a['validation_dir'] = ws['paths']['validation']; p4a['mode_resolution_dir'] = ws['paths']['mode_resolution']; p4a['output_dir'] = ws['paths']['analysis_phase1']
        p4b['input_baseline_csv'] = str(Path(ws['paths']['analysis_phase1']) / 'hvg_baseline.csv')
        p4b['input_phase1_summary_json'] = str(Path(ws['paths']['analysis_phase1']) / 'phase1_mode_summary.json')
        p4b['validation_dir'] = ws['paths']['validation']
        p4b['output_dir'] = ws['paths']['analysis_phase2']

    ds, manifest, validation = build_internal_dataset(p1)
    export_standardized_dataset(ds, p1['output_dir'], manifest, validation, p1)
    r2 = run_validation_pipeline(p2)
    r3 = run_mode_resolution_pipeline(p3)
    r4 = run_phase1_analysis_pipeline(p4a)
    comparison_context = None
    if p4b.get('enable_hvg_nonhvg_comparison', True) and p4b.get('comparison_context_enabled', True):
        try:
            comparison_context = build_hvg_multiomics_feature_context(
                baseline_csv=p4b['input_baseline_csv'],
                output_dir=p4b['output_dir'],
                species_id=str(p4b.get('species_id') or 'unknown'),
                requested_omics=p4b.get('comparison_omics') or ['genome', 'transcriptome', 'proteome'],
                config=p4b,
            )
            p4b.update({
                'comparison_input_csv': comparison_context.get('comparison_input_csv'),
                'comparison_feature_provenance_path': comparison_context.get('feature_provenance_csv'),
                'comparison_mapping_summary_path': comparison_context.get('mapping_summary_json'),
                'comparison_context_manifest_path': comparison_context.get('assembly_manifest_json'),
                'comparison_block_coverage_path': comparison_context.get('block_coverage_csv'),
                'comparison_block_status': comparison_context.get('block_status') or {},
                'comparison_context_status': comparison_context.get('status'),
            })
        except Exception as exc:
            comparison_context = {
                'status': 'failed',
                'reason': f'{type(exc).__name__}: {exc}',
            }
            p4b['comparison_context_status'] = 'failed'
            p4b['comparison_context_error'] = comparison_context['reason']
    r5 = run_phase2_stoich_pipeline(p4b)
    result = {'input_adapter_output': str(Path(p1['output_dir']).resolve()), 'validation': r2, 'mode_resolution': r3, 'phase1_analysis': r4, 'comparison_context': comparison_context, 'phase2_stoich': r5, 'workspace': ws}
    if ws.get('enabled'):
        cache = build_case_cache(Path(ws['job_dir']))
        update_job_status(workspace_root, job_id, 'analysis_complete', {'cache_file': str((Path(ws['job_dir'])/'case_cache.json').resolve())})
    return result
