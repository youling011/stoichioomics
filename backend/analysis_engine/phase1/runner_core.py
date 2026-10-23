
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timezone
import pandas as pd
import json

from backend.analysis_engine.phase1.dispatcher import run_phase1_dispatch
from backend.analysis_engine.phase1.consensus import build_hvg_consensus, build_method_benchmark, backend_report
from backend.analysis_engine.phase1.backends.internal_hvg import coerce_existing_baseline
from backend.analysis_engine.phase1.backends.scanpy_hvg import run_scanpy_backend
from backend.analysis_engine.phase1.backends.seurat_hvg_bridge import run_seurat_backend
from backend.analysis_engine.common import bundle_to_expression_dataset
from backend.validation.loader import load_standardized_bundle
from backend.analysis_engine.phase1.utils import write_json


def run_phase1_analysis_pipeline(config: Dict[str, Any]) -> Dict[str, Any]:
    if config.get('primary_backend') == 'scanpy':
        from backend.analysis_engine.hvg_research.primary_adapter import run_primary_pipeline
        return run_primary_pipeline(config)
    output_dir = Path(config['output_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)
    mode, (baseline_df, mode_summary, aux_outputs) = run_phase1_dispatch(config)

    baseline_df = baseline_df.copy()
    baseline_df['analysis_mode'] = mode
    baseline_path = output_dir / 'hvg_baseline.csv'
    baseline_df.to_csv(baseline_path, index=False)

    backend_results = [coerce_existing_baseline(baseline_df, config)]
    try:
        bundle = load_standardized_bundle(config['standardized_input_dir'], config.get('raw_stoich_file'))
        dataset = bundle_to_expression_dataset(bundle)
        backend_results.append(run_scanpy_backend(dataset, config))
        if bool(config.get('enable_seurat_r_backend', False)):
            backend_results.append(run_seurat_backend(dataset, config))
        else:
            seurat_status = run_seurat_backend(dataset, config)
            seurat_status['status'] = 'disabled' if seurat_status.get('status') != 'unavailable' else seurat_status.get('status')
            backend_results.append(seurat_status)
    except Exception as exc:
        backend_results.append({'backend': 'optional_backends', 'status': 'failed', 'result': None, 'summary': {}, 'error': str(exc)})

    method_benchmark = build_method_benchmark(backend_results)
    consensus_df = build_hvg_consensus(backend_results, n_top_genes=int(config.get('n_top_genes', 2000)))
    backend_report_json = backend_report(backend_results, consensus_df)
    benchmark_path = output_dir / 'hvg_method_benchmark.csv'
    consensus_path = output_dir / 'hvg_consensus.csv'
    backend_report_path = output_dir / 'hvg_backend_report.json'
    method_benchmark.to_csv(benchmark_path, index=False)
    consensus_df.to_csv(consensus_path, index=False)
    write_json(backend_report_json, backend_report_path)

    aux_written = {}
    for filename, df in aux_outputs.items():
        path = output_dir / filename
        if isinstance(df, pd.DataFrame):
            df.to_csv(path, index=False)
        aux_written[filename] = str(path.resolve())

    auxiliary_mode_outputs = {}
    skipped_modes = []
    if bool(config.get('run_supported_auxiliary_modes', False)) and config.get('mode_resolution_dir'):
        mode_path = Path(config['mode_resolution_dir']) / 'mode_resolution.json'
        if mode_path.exists():
            mode_resolution = json.loads(mode_path.read_text(encoding='utf-8'))
            available_modes = mode_resolution.get('available_modes') or {}
            requested_modes = [
                m for m, info in available_modes.items()
                if info.get('available') and m != mode
            ]
            if bool(config.get('always_run_global', True)) and mode != 'global_hvg' and 'global_hvg' not in requested_modes:
                requested_modes.insert(0, 'global_hvg')
            aux_mode_dir = output_dir / 'auxiliary_modes'
            aux_mode_dir.mkdir(parents=True, exist_ok=True)
            for aux_mode in requested_modes:
                try:
                    aux_cfg = dict(config)
                    aux_cfg['analysis_mode'] = aux_mode
                    _, (aux_df, aux_summary, aux_extra) = run_phase1_dispatch(aux_cfg)
                    aux_df = aux_df.copy()
                    aux_df['analysis_mode'] = aux_mode
                    aux_path = aux_mode_dir / f'{aux_mode}.csv'
                    aux_df.to_csv(aux_path, index=False)
                    extra_written = {}
                    for extra_name, extra_df in aux_extra.items():
                        extra_path = aux_mode_dir / f'{aux_mode}__{extra_name}'
                        if isinstance(extra_df, pd.DataFrame):
                            extra_df.to_csv(extra_path, index=False)
                        extra_written[extra_name] = str(extra_path.resolve())
                    auxiliary_mode_outputs[aux_mode] = {
                        'status': 'success',
                        'output': str(aux_path.resolve()),
                        'summary': aux_summary,
                        'auxiliary_outputs': extra_written,
                    }
                except Exception as exc:
                    skipped_modes.append({'mode': aux_mode, 'status': 'skipped', 'reason_code': 'auxiliary_mode_failed', 'message': str(exc)})
        else:
            skipped_modes.append({'mode': 'auxiliary_modes', 'status': 'skipped', 'reason_code': 'missing_mode_resolution'})

    method_meta = {}
    if not baseline_df.empty:
        method_meta = {
            'hvg_method': str(baseline_df['hvg_method'].dropna().iloc[0]) if 'hvg_method' in baseline_df.columns and baseline_df['hvg_method'].notna().any() else None,
            'hvg_score_semantics': str(baseline_df['hvg_score_semantics'].dropna().iloc[0]) if 'hvg_score_semantics' in baseline_df.columns and baseline_df['hvg_score_semantics'].notna().any() else None,
            'n_top_genes': int(config.get('n_top_genes', 2000)),
            'n_bins': int(config.get('n_bins', 20)),
            'min_cells': int(config.get('min_cells', 3)),
            'min_counts': int(config.get('min_counts', 1)),
        }

    validation_summary = None
    semantics_qc = None
    if config.get('validation_dir'):
        vdir = Path(config['validation_dir'])
        vs = vdir / 'validation_summary.json'
        ss = vdir / 'semantics_check_report.json'
        if vs.exists():
            validation_summary = json.loads(vs.read_text(encoding='utf-8'))
        if ss.exists():
            semantics_qc = json.loads(ss.read_text(encoding='utf-8'))

    summary = {
        **mode_summary,
        'analysis_mode': mode,
        'method_metadata': method_meta,
        'matrix_semantics': (validation_summary or {}).get('bundle_summary', {}).get('matrix_semantics') if validation_summary else None,
        'semantics_qc': semantics_qc,
        'validation_overall_status': (validation_summary or {}).get('overall_status') if validation_summary else None,
        'n_rows_primary': int(baseline_df.shape[0]),
        'n_hvgs_primary': int(baseline_df['is_hvg'].fillna(False).astype(bool).sum()) if 'is_hvg' in baseline_df.columns else None,
        'primary_output': str(baseline_path.resolve()),
        'method_benchmark_output': str(benchmark_path.resolve()),
        'consensus_output': str(consensus_path.resolve()),
        'backend_report_output': str(backend_report_path.resolve()),
        'backend_report': backend_report_json,
        'auxiliary_mode_outputs': auxiliary_mode_outputs,
        'skipped_modes': skipped_modes,
        'auxiliary_outputs': aux_written,
    }
    write_json(summary, output_dir / 'phase1_mode_summary.json')

    run_log = {
        'case_id': config.get('case_id'),
        'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'standardized_input_dir': str(Path(config['standardized_input_dir']).resolve()),
        'validation_dir': str(Path(config['validation_dir']).resolve()) if config.get('validation_dir') else None,
        'mode_resolution_dir': str(Path(config['mode_resolution_dir']).resolve()) if config.get('mode_resolution_dir') else None,
        'output_dir': str(output_dir.resolve()),
        'analysis_mode': mode,
        'config': {k:v for k,v in config.items() if k not in {'output_dir'}},
        'summary': summary,
    }
    write_json(run_log, output_dir / 'run_log.json')
    return {'analysis_mode': mode, 'output_dir': str(output_dir.resolve()), 'baseline_csv': str(baseline_path.resolve()), 'summary': summary}
