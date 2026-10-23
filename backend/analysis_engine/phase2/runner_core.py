from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from .associations import compute_feature_associations
from .classify import classify_genes
from .downstream import build_candidate_gene_table, build_downstream_summary
from .io import read_baseline_csv, read_json_if_exists, write_json
from .model_prep import coerce_numeric, winsorize_df
from .model_comparison import run_model_comparison
from .permutation_tests import build_permutation_assessment
from .bootstrap_stability import bootstrap_feature_stability
from .stoich_model import fit_stoich_model
from .summarize import build_gene_detail_payload, build_plot_payload, build_summary_json
from .validate import choose_confounder_columns, choose_feature_columns, validate_required_columns
from .group_comparison import run_hvg_nonhvg_comparison, write_unavailable_comparison
from .comparison_schema import COMPARISON_SCHEMA_VERSION, LEGACY_COMPARISON_SCHEMA_VERSION
from backend.analysis_engine.downstream.domain_annotation import build_candidate_score_components
from backend.analysis_engine.downstream.enrichment import run_enrichment_outputs
from backend.analysis_engine.downstream.network_modules import run_network_module_outputs
from backend.analysis_engine.visualization import build_visualization_artifacts


def _resolve_validation_dir(config: Dict[str, Any]) -> Path | None:
    explicit = config.get('validation_dir')
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
    baseline = Path(config['input_baseline_csv'])
    candidate = baseline.parent.parent / 'validation'
    return candidate if candidate.exists() else None


def _load_validation_context(validation_dir: Path | None) -> Dict[str, Any]:
    if validation_dir is None:
        return {}
    context = {
        'validation_summary': read_json_if_exists(validation_dir / 'validation_summary.json'),
        'matrix_qc': read_json_if_exists(validation_dir / 'matrix_check_report.json'),
        'gene_mapping': read_json_if_exists(validation_dir / 'gene_mapping_report.json'),
        'metadata_qc': read_json_if_exists(validation_dir / 'metadata_check_report.json'),
        'stoich_qc': read_json_if_exists(validation_dir / 'stoich_check_report.json'),
        'semantics_qc': read_json_if_exists(validation_dir / 'semantics_check_report.json'),
        'id_mapping_summary': read_json_if_exists(validation_dir / 'id_mapping_summary.json'),
    }
    return {k: v for k, v in context.items() if v is not None}


def _derive_mapping_summary(df: pd.DataFrame, feature_cols: list[str], hvg_flag_col: str) -> Dict[str, Any]:
    present_features = [c for c in feature_cols if c in df.columns]
    if not present_features:
        return {
            'expression_genes': int(df.shape[0]),
            'stoich_genes': 0,
            'matched_genes': 0,
            'matched_hvgs': 0,
            'unmatched_hvgs': 0,
            'match_rate': 0.0,
        }
    feature_block = df[present_features].copy()
    matched_mask = feature_block.notna().all(axis=1)
    partial_mask = feature_block.notna().any(axis=1)
    hvg_mask = df[hvg_flag_col].fillna(False).astype(bool) if hvg_flag_col in df.columns else pd.Series(False, index=df.index)
    matched_hvg = int((matched_mask & hvg_mask).sum())
    total_hvg = int(hvg_mask.sum())
    return {
        'expression_genes': int(df.shape[0]),
        'stoich_genes': int(partial_mask.sum()),
        'matched_genes': int(matched_mask.sum()),
        'matched_hvgs': matched_hvg,
        'unmatched_hvgs': int(max(total_hvg - matched_hvg, 0)),
        'match_rate': float(matched_mask.mean()),
        'partial_match_rate': float(partial_mask.mean()),
    }


def _write_phase2_skipped_outputs(
    output_dir: Path,
    baseline: pd.DataFrame | None,
    reason_code: str,
    reason_message: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    downstream_dir = output_dir.parent / 'downstream'
    downstream_dir.mkdir(parents=True, exist_ok=True)
    base = baseline.copy() if baseline is not None else pd.DataFrame(columns=['gene_id'])
    if not base.empty:
        base['phase2_status'] = 'skipped'
        base['phase2_skip_reason'] = reason_code
    scores_path = output_dir / 'hvg_stoich_scores.csv'
    base.to_csv(scores_path, index=False)
    empty_specs = {
        'feature_associations.csv': ['feature', 'status', 'reason_code', 'reason_message'],
        'candidate_gene_table.csv': ['gene_id', 'status', 'reason_code', 'reason_message'],
        'model_comparison.csv': ['model_id', 'status', 'reason_code', 'reason_message'],
        'cv_predictions.csv': ['model_id', 'fold', 'gene_id', 'observed', 'prediction', 'status'],
        'feature_block_importance.csv': ['model_id', 'status', 'reason_code', 'reason_message'],
        'bootstrap_feature_stability.csv': ['feature', 'status', 'reason_code', 'reason_message'],
    }
    paths = {}
    for filename, cols in empty_specs.items():
        df = pd.DataFrame([{c: None for c in cols}])
        df['status'] = 'skipped'
        df['reason_code'] = reason_code
        df['reason_message'] = reason_message
        path = output_dir / filename
        df.to_csv(path, index=False)
        paths[filename] = str(path.resolve())
    for filename in [
        'enrichment_ora.csv',
        'gsea_prerank_results.csv',
        'functional_enrichment_top_terms.csv',
        'ppi_module_enrichment.csv',
        'candidate_score_components.csv',
    ]:
        path = downstream_dir / filename
        pd.DataFrame([{'status': 'skipped', 'reason_code': reason_code, 'reason_message': reason_message}]).to_csv(path, index=False)
    write_json({'status': 'skipped', 'reason_code': reason_code, 'reason_message': reason_message, 'rows': []}, downstream_dir / 'functional_enrichment_dotplot.json')
    write_json({'status': 'skipped', 'reason_code': reason_code, 'reason_message': reason_message}, downstream_dir / 'functional_enrichment_summary.json')
    report = {
        'status': 'skipped',
        'reason_code': reason_code,
        'reason_message': reason_message,
        'block_entire_job': False,
        'case_id': config.get('case_id'),
    }
    summary = {
        'case_id': config.get('case_id', 'unknown_case'),
        'total_genes': int(base.shape[0]),
        'phase2_status': 'skipped',
        'phase2_skip_reason': report,
        'warnings': [{'code': reason_code, 'severity': 'info', 'message': reason_message}],
    }
    write_json(report, output_dir / 'phase2_skipped_report.json')
    write_json(report, output_dir / 'negative_control_report.json')
    write_json(report, output_dir / 'evidence_assessment.json')
    write_json({'phase2_status': 'skipped', 'reason': report}, output_dir / 'hvg_stoich_model.json')
    write_json(summary, output_dir / 'hvg_summary.json')
    write_json({'phase2_status': 'skipped', 'reason': report}, output_dir / 'downstream_summary.json')
    write_json({'plots': [], 'phase2_status': 'skipped', 'reason': report}, output_dir / 'plots_payload.json')
    write_json({'rows': [], 'by_gene_id': {}, 'phase2_status': 'skipped', 'reason': report}, output_dir / 'gene_detail_payload.json')
    run_log = {
        'case_id': config.get('case_id'),
        'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'output_dir': str(output_dir.resolve()),
        'phase2_status': 'skipped',
        'reason': report,
        'config': config,
    }
    write_json(run_log, output_dir / 'run_log.json')
    visualization = build_visualization_artifacts(output_dir.parent)
    return {
        'output_dir': str(output_dir.resolve()),
        'scores_csv': str(scores_path.resolve()),
        'summary': summary,
        'phase2_status': 'skipped',
        'skip_reason': report,
        'visualization': visualization,
    }


def _run_phase2_stoich_model_pipeline(config: Dict[str, Any]) -> Dict[str, Any]:
    output_dir = Path(config['output_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)

    target_col = config.get('target_col', 'normalized_dispersion')
    hvg_flag_col = config.get('hvg_flag_col', 'is_hvg')
    hvg_target_type = config.get('hvg_target_type', 'score')
    baseline = read_baseline_csv(config['input_baseline_csv'])
    model_enabled = bool(config.get('model_enabled')) if 'model_enabled' in config else config.get('enabled') is not False
    if not model_enabled:
        return _write_phase2_skipped_outputs(output_dir, baseline, str(config.get('model_skip_reason') or config.get('skip_reason') or 'phase2_model_disabled'), 'The stoichiometric model branch was disabled by automatic configuration; the HVG comparison branch remains independent.', config)
    validation_dir = _resolve_validation_dir(config)
    validation_context = _load_validation_context(validation_dir)
    strict_mapping = validation_context.get('id_mapping_summary') or {}
    if strict_mapping and not strict_mapping.get('ready_for_phase2_stoich', True):
        return _write_phase2_skipped_outputs(
            output_dir,
            baseline,
            'low_gene_id_match_rate',
            f"Strict gene ID match rate {strict_mapping.get('match_rate', 0):.3f} is below {strict_mapping.get('minimum_phase2_match_rate', 0.70):.2f}; Phase 2 was skipped.",
            config,
        )
    report = validate_required_columns(baseline, target_col=target_col, hvg_flag_col=hvg_flag_col)
    try:
        feature_cols = choose_feature_columns(baseline, feature_set=config.get('feature_set', 'core'))
    except Exception as exc:
        return _write_phase2_skipped_outputs(output_dir, baseline, 'too_few_stoich_features', str(exc), config)
    confounder_cols = choose_confounder_columns(baseline, explicit_columns=config.get('confounder_columns'))

    df = baseline.copy()
    if 'dropout_rate' not in df.columns and 'pct_cells_detected' in df.columns:
        pct = pd.to_numeric(df['pct_cells_detected'], errors='coerce')
        df['dropout_rate'] = 1.0 - pct.clip(lower=0.0, upper=1.0)
    numeric_cols = list(set(
        feature_cols
        + confounder_cols
        + [target_col, 'mean_expr', 'pct_cells_detected', 'n_cells_detected', 'dropout_rate']
    ))
    df = coerce_numeric(df, [c for c in numeric_cols if c in df.columns])
    winsor_cols = [c for c in set(feature_cols + confounder_cols + [target_col]) if c in df.columns]
    df = winsorize_df(df, winsor_cols, q=float(config.get('winsorize_quantile', 0.01)))

    modeled, artifacts = fit_stoich_model(
        df=df,
        feature_columns=feature_cols,
        target_col=target_col,
        hvg_flag_col=hvg_flag_col,
        model_type=config.get('model_type', 'ridge'),
        ridge_alpha=float(config.get('ridge_alpha', 1.0)),
        n_cv_folds=int(config.get('n_cv_folds', 5)),
        random_state=int(config.get('random_state', 42)),
        hvg_target_type=hvg_target_type,
        confounder_columns=confounder_cols,
        permutation_repeats=int(config.get('permutation_repeats', 8)),
    )
    classified, thresholds, artifacts = classify_genes(modeled, hvg_flag_col=hvg_flag_col, artifacts=artifacts)
    feature_associations = compute_feature_associations(classified, feature_cols, hvg_flag_col=hvg_flag_col, min_group_n=int(config.get('min_group_n', 8)))
    candidate_genes = build_candidate_gene_table(classified, top_n=int(config.get('top_n_candidate_genes', 300)))
    downstream_summary = build_downstream_summary(classified, feature_associations=feature_associations)
    model_comparison, cv_predictions, feature_block_importance, evidence_assessment = run_model_comparison(
        classified,
        stoich_features=artifacts.feature_columns,
        confounders=artifacts.confounder_columns,
        config=config,
    )
    negative_control_report = build_permutation_assessment(model_comparison, config)
    bootstrap_stability = bootstrap_feature_stability(
        classified,
        feature_columns=artifacts.feature_columns,
        target_col=target_col,
        random_state=int(config.get('random_state', 42)),
        n_bootstrap=int(config.get('bootstrap_repeats', 40)),
    )
    downstream_dir = output_dir.parent / 'downstream'
    candidate_components = build_candidate_score_components(classified)
    downstream_paths = {}
    downstream_paths.update(run_enrichment_outputs(classified, downstream_dir, config=config))
    downstream_paths.update(run_network_module_outputs(classified, downstream_dir))
    functional_enrichment_summary = read_json_if_exists(downstream_paths.get('functional_enrichment_summary', ''))

    scores_path = output_dir / 'hvg_stoich_scores.csv'
    classified.to_csv(scores_path, index=False)
    assoc_path = output_dir / 'feature_associations.csv'
    feature_associations.to_csv(assoc_path, index=False)
    candidate_path = output_dir / 'candidate_gene_table.csv'
    candidate_genes.to_csv(candidate_path, index=False)
    model_comparison_path = output_dir / 'model_comparison.csv'
    cv_predictions_path = output_dir / 'cv_predictions.csv'
    feature_block_path = output_dir / 'feature_block_importance.csv'
    bootstrap_path = output_dir / 'bootstrap_feature_stability.csv'
    candidate_components_path = downstream_dir / 'candidate_score_components.csv'
    model_comparison.to_csv(model_comparison_path, index=False)
    cv_predictions.to_csv(cv_predictions_path, index=False)
    feature_block_importance.to_csv(feature_block_path, index=False)
    bootstrap_stability.to_csv(bootstrap_path, index=False)
    downstream_dir.mkdir(parents=True, exist_ok=True)
    candidate_components.to_csv(candidate_components_path, index=False)

    phase1_summary = (
        read_json_if_exists(config.get('input_phase1_summary_json', ''))
        if config.get('input_phase1_summary_json')
        else None
    )
    mapping_summary = _derive_mapping_summary(classified, feature_cols, hvg_flag_col=hvg_flag_col)
    if strict_mapping:
        mapping_summary.update({
            'strict_match_rate': strict_mapping.get('match_rate'),
            'strict_mapping_ready_for_phase2': strict_mapping.get('ready_for_phase2_stoich'),
            'strict_mapping_source': strict_mapping.get('mapping_source'),
        })

    model_info = {
        'feature_set': config.get('feature_set', 'core'),
        'feature_columns': artifacts.feature_columns,
        'confounder_columns': artifacts.confounder_columns,
        'baseline_feature_columns': artifacts.baseline_feature_columns,
        'augmented_feature_columns': artifacts.augmented_feature_columns,
        'analysis_mode_from_phase1': phase1_summary.get('analysis_mode') if phase1_summary else None,
        'baseline_metrics': artifacts.baseline_metrics,
        'model_metrics': artifacts.model_metrics,
        'delta_metrics': artifacts.delta_metrics,
        'model_diagnostics': artifacts.model_diagnostics,
    }

    summary = build_summary_json(
        classified,
        case_id=config.get('case_id', 'unknown_case'),
        species_id=config.get('species_id', 'unknown_species'),
        omics=config.get('omics', 'transcriptome'),
        model_info=model_info,
        phase1_summary=phase1_summary,
        validation_summary=validation_context.get('validation_summary', {}),
        mapping_summary=mapping_summary,
        feature_associations=feature_associations,
    )
    summary['downstream_summary'] = downstream_summary
    summary['functional_enrichment_summary'] = functional_enrichment_summary or {}
    summary['evidence_assessment'] = evidence_assessment
    summary['negative_control_report'] = negative_control_report
    summary['downstream_outputs'] = {**downstream_paths, 'candidate_score_components': str(candidate_components_path.resolve())}
    plots = build_plot_payload(classified, model_info=model_info, feature_associations=feature_associations)
    details = build_gene_detail_payload(classified, top_n=int(config.get('top_n_gene_details', 80)))

    model_json = {
        'validation_report': report,
        'feature_columns': artifacts.feature_columns,
        'confounder_columns': artifacts.confounder_columns,
        'baseline_feature_columns': artifacts.baseline_feature_columns,
        'augmented_feature_columns': artifacts.augmented_feature_columns,
        'numeric_summary': artifacts.numeric_summary,
        'baseline_metrics': artifacts.baseline_metrics,
        'model_metrics': artifacts.model_metrics,
        'delta_metrics': artifacts.delta_metrics,
        'feature_importance': artifacts.feature_importance,
        'permutation_importance': artifacts.permutation_importance,
        'model_diagnostics': artifacts.model_diagnostics,
        'model_comparison': model_comparison.replace([float('inf'), float('-inf')], pd.NA).where(pd.notnull(model_comparison), None).to_dict(orient='records'),
        'feature_block_importance': feature_block_importance.replace([float('inf'), float('-inf')], pd.NA).where(pd.notnull(feature_block_importance), None).to_dict(orient='records'),
        'bootstrap_feature_stability': bootstrap_stability.head(50).replace([float('inf'), float('-inf')], pd.NA).where(pd.notnull(bootstrap_stability.head(50)), None).to_dict(orient='records'),
        'negative_control_report': negative_control_report,
        'evidence_assessment': evidence_assessment,
        'functional_enrichment_summary': functional_enrichment_summary or {},
        'feature_association_top': feature_associations.head(50).replace([float('inf'), float('-inf')], pd.NA).where(
            pd.notnull(feature_associations.head(50)),
            None,
        ).to_dict(orient='records'),
        'downstream_summary': downstream_summary,
        'thresholds': thresholds,
        'phase1_summary': phase1_summary,
        'validation_context': validation_context,
        'mapping_summary': mapping_summary,
    }
    write_json(model_json, output_dir / 'hvg_stoich_model.json')
    write_json(summary, output_dir / 'hvg_summary.json')
    write_json(plots, output_dir / 'plots_payload.json')
    write_json(details, output_dir / 'gene_detail_payload.json')
    write_json(downstream_summary, output_dir / 'downstream_summary.json')
    write_json(negative_control_report, output_dir / 'negative_control_report.json')
    write_json(evidence_assessment, output_dir / 'evidence_assessment.json')

    run_log = {
        'case_id': config.get('case_id'),
        'species_id': config.get('species_id'),
        'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'input_baseline_csv': str(Path(config['input_baseline_csv']).resolve()),
        'input_phase1_summary_json': str(Path(config['input_phase1_summary_json']).resolve()) if config.get('input_phase1_summary_json') else None,
        'validation_dir': str(validation_dir.resolve()) if validation_dir else None,
        'output_dir': str(output_dir.resolve()),
        'config': config,
        'n_rows': int(classified.shape[0]),
        'model_comparison_csv': str(model_comparison_path.resolve()),
        'downstream_outputs': {**downstream_paths, 'candidate_score_components': str(candidate_components_path.resolve())},
    }
    write_json(run_log, output_dir / 'run_log.json')
    visualization = build_visualization_artifacts(output_dir.parent)
    return {
        'output_dir': str(output_dir.resolve()),
        'scores_csv': str(scores_path.resolve()),
        'feature_association_csv': str(assoc_path.resolve()),
        'candidate_gene_csv': str(candidate_path.resolve()),
        'model_comparison_csv': str(model_comparison_path.resolve()),
        'cv_predictions_csv': str(cv_predictions_path.resolve()),
        'feature_block_importance_csv': str(feature_block_path.resolve()),
        'bootstrap_feature_stability_csv': str(bootstrap_path.resolve()),
        'visualization': visualization,
        'summary': summary,
        'model_metrics': artifacts.model_metrics,
        'delta_metrics': artifacts.delta_metrics,
    }


def _merge_phase2_branch_status(
    output_dir: Path,
    result: Dict[str, Any],
    comparison_result: Dict[str, Any],
    model_status: str,
) -> Dict[str, Any]:
    comparison_summary = comparison_result.get('summary') or {}
    summary_path = output_dir / 'hvg_summary.json'
    summary = read_json_if_exists(summary_path) or result.get('summary') or {}
    summary['hvg_group_comparison'] = comparison_summary
    summary['comparison_status'] = comparison_summary.get('comparison_status') or comparison_summary.get('status') or 'unavailable'
    summary['model_status'] = model_status
    if model_status == 'complete':
        summary.setdefault('phase2_status', 'complete')
    write_json(summary, summary_path)

    model_path = output_dir / 'hvg_stoich_model.json'
    model_payload = read_json_if_exists(model_path) or {}
    model_payload['comparison_status'] = summary['comparison_status']
    model_payload['hvg_group_comparison'] = {
        'status': summary['comparison_status'],
        'schema_version': comparison_summary.get('schema_version'),
        'resolved_blocks': comparison_summary.get('resolved_blocks') or [],
        'counts': comparison_summary.get('counts') or {},
    }
    model_payload['model_status'] = model_status
    write_json(model_payload, model_path)

    run_log_path = output_dir / 'run_log.json'
    run_log = read_json_if_exists(run_log_path) or {}
    run_log['comparison_status'] = summary['comparison_status']
    run_log['model_status'] = model_status
    run_log['hvg_nonhvg_artifacts'] = comparison_summary.get('artifacts') or {}
    write_json(run_log, run_log_path)

    result['summary'] = summary
    result['comparison_status'] = summary['comparison_status']
    result['model_status'] = model_status
    result['hvg_nonhvg_summary_json'] = str((output_dir / 'hvg_nonhvg_summary.json').resolve())
    result['hvg_nonhvg_feature_comparison_csv'] = str((output_dir / 'hvg_nonhvg_feature_comparison.csv').resolve())
    result['visualization'] = build_visualization_artifacts(output_dir.parent)
    return result


def run_phase2_stoich_pipeline(config: Dict[str, Any]) -> Dict[str, Any]:
    output_dir = Path(config['output_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline = read_baseline_csv(config['input_baseline_csv'])
    validation_dir = _resolve_validation_dir(config)
    validation_context = _load_validation_context(validation_dir)
    strict_mapping = validation_context.get('id_mapping_summary') or {}
    phase1_summary = (
        read_json_if_exists(config.get('input_phase1_summary_json', ''))
        if config.get('input_phase1_summary_json') else {}
    ) or {}

    comparison_config = dict(config)
    comparison_result: Dict[str, Any]
    comparison_disabled = config.get('enable_hvg_nonhvg_comparison') is False
    if config.get('research_comparison_summary') is not None:
        comparison_result = {'summary': config['research_comparison_summary'], 'status': 'completed', 'research_reference': config.get('research_comparison_reference')}
    elif comparison_disabled:
        comparison_result = write_unavailable_comparison(
            output_dir,
            reason='HVG/non-HVG comparison was disabled by configuration.',
            config=comparison_config,
            mapping_context=strict_mapping,
            phase1_metadata=phase1_summary.get('method_metadata') or phase1_summary,
        )
    else:
        context_path = Path(str(config.get('comparison_input_csv') or '')) if config.get('comparison_input_csv') else None
        context_available = bool(context_path and context_path.exists() and context_path.is_file())
        context_status = str(config.get('comparison_context_status') or '').lower()
        legacy_hints = any(
            str(column).lower().startswith(('transcript_', 'transcriptome_', 'protein_', 'proteome_'))
            or str(column).lower() in {'length_nt', 'protein_length', 'aa_entropy', 'c_atoms_per_aa'}
            for column in baseline.columns
        )
        configured_schema = str(config.get('comparison_schema_version') or '')
        use_legacy = not context_available and (
            configured_schema == LEGACY_COMPARISON_SCHEMA_VERSION
            or config.get('comparison_context_enabled') is False
            or ('comparison_schema_version' not in config and legacy_hints)
        )
        if context_status in {'failed', 'unavailable'} and not use_legacy:
            comparison_result = write_unavailable_comparison(
                output_dir,
                reason=f'Feature Context Builder status is {context_status}; no validated v2 comparison context is available.',
                config=comparison_config,
                mapping_context=strict_mapping,
                phase1_metadata=phase1_summary.get('method_metadata') or phase1_summary,
            )
        elif not context_available and not use_legacy:
            comparison_result = write_unavailable_comparison(
                output_dir,
                reason='HVG Feature Context Builder did not produce a validated v2 context; comparison is explicitly unavailable.',
                config=comparison_config,
                mapping_context=strict_mapping,
                phase1_metadata=phase1_summary.get('method_metadata') or phase1_summary,
            )
        else:
            if context_available:
                comparison_config['comparison_schema_version'] = COMPARISON_SCHEMA_VERSION
                comparison_input = pd.read_csv(context_path)
            else:
                comparison_config['comparison_schema_version'] = LEGACY_COMPARISON_SCHEMA_VERSION
                comparison_input = baseline
            try:
                comparison_result = run_hvg_nonhvg_comparison(
                    comparison_input,
                    comparison_config,
                    output_dir=output_dir,
                    phase1_metadata=phase1_summary.get('method_metadata') or phase1_summary,
                    mapping_context=strict_mapping,
                )
            except Exception as exc:
                comparison_result = write_unavailable_comparison(
                    output_dir,
                    status='failed',
                    reason=f'Comparison branch failed: {type(exc).__name__}: {exc}',
                    config=comparison_config,
                    mapping_context=strict_mapping,
                    phase1_metadata=phase1_summary.get('method_metadata') or phase1_summary,
                )

    try:
        result = _run_phase2_stoich_model_pipeline(config)
        model_status = 'skipped' if result.get('phase2_status') == 'skipped' else 'complete'
    except Exception as exc:
        result = _write_phase2_skipped_outputs(
            output_dir,
            baseline,
            'model_branch_failed',
            f'Model branch failed independently: {type(exc).__name__}: {exc}',
            config,
        )
        model_status = 'failed'
    return _merge_phase2_branch_status(output_dir, result, comparison_result, model_status)
