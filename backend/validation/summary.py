from __future__ import annotations
from typing import Dict, Any, List


def summarize_reports(bundle_summary: Dict[str, Any], gene_map: Dict[str, Any], matrix: Dict[str, Any], metadata: Dict[str, Any], stoich: Dict[str, Any], semantics: Dict[str, Any], dup: Dict[str, Any], thresholds: Dict[str, Any]) -> Dict[str, Any]:
    warnings: List[Dict[str, Any]] = []

    def warn(level: str, code: str, message: str):
        warnings.append({'level': level, 'code': code, 'message': message})

    if gene_map.get('overlap_fraction_vs_expression', 0) < thresholds.get('warn_gene_overlap_fraction_vs_expression', 0.8):
        warn('warning', 'LOW_GENE_OVERLAP', f"Gene overlap vs expression is {gene_map.get('overlap_fraction_vs_expression'):.3f}, below recommended threshold.")
    if matrix.get('zero_only_gene_fraction', 0) > thresholds.get('max_zero_only_gene_fraction', 0.2):
        warn('warning', 'MANY_ZERO_ONLY_GENES', f"Zero-only gene fraction is {matrix.get('zero_only_gene_fraction'):.3f}.")
    if matrix.get('zero_only_cell_fraction', 0) > thresholds.get('max_zero_only_cell_fraction', 0.2):
        warn('warning', 'MANY_ZERO_ONLY_CELLS', f"Zero-only cell fraction is {matrix.get('zero_only_cell_fraction'):.3f}.")
    if matrix.get('has_negative_values'):
        warn('error', 'NEGATIVE_VALUES', 'Matrix contains negative values, incompatible with standard count-based HVG workflows.')
    if not dup.get('duplicates_ok', False):
        warn('error', 'DUPLICATES_PRESENT', 'Duplicate cell or gene identifiers detected.')
    if not stoich.get('ready_for_stoich_phase2', False):
        warn('warning', 'INSUFFICIENT_STOICH_FIELDS', 'Stoichiometric annotations are insufficient for full phase 2 analysis.')
    if not metadata.get('supports_analysis_modes', {}).get('global_hvg', False):
        warn('error', 'NO_MINIMAL_METADATA', 'Minimal metadata structure invalid.')
    if semantics.get('heuristic_inference', {}).get('inferred_semantics') == 'log_or_normalized_like' and bundle_summary.get('matrix_semantics') in {'raw_counts', 'raw_counts_like'}:
        warn('warning', 'SEMANTICS_MISMATCH', 'Declared matrix semantics look count-like, but heuristic values look log/normalized-like.')

    overall_status = 'pass'
    if any(w['level'] == 'error' for w in warnings):
        overall_status = 'fail'
    elif warnings:
        overall_status = 'warn'

    next_steps = []
    if overall_status == 'pass':
        next_steps.append('Proceed to analysis mode resolution and phase 1 HVG computation.')
    else:
        if any(w['code'] == 'LOW_GENE_OVERLAP' for w in warnings):
            next_steps.append('Check whether expression gene IDs and stoich gene IDs use the same naming convention.')
        if any(w['code'] == 'SEMANTICS_MISMATCH' for w in warnings):
            next_steps.append('Verify whether the uploaded matrix is raw counts, normalized counts, or log-transformed values.')
        if not stoich.get('ready_for_stoich_phase2', False):
            next_steps.append('Provide a richer stoich feature table or generate one using the existing stoich extractor pipeline.')
        if not metadata.get('supports_analysis_modes', {}).get('timecourse_hvg', False):
            next_steps.append('If time-course analysis is desired, provide a metadata column named timepoint.')

    summary = {
        'bundle_summary': bundle_summary,
        'overall_status': overall_status,
        'ready_for_phase1_hvg': bool(matrix.get('ready_for_hvg', False) and dup.get('duplicates_ok', False)),
        'ready_for_phase2_stoich': bool(stoich.get('ready_for_stoich_phase2', False) and gene_map.get('ready_for_stoich_phase2', False)),
        'supports_analysis_modes': metadata.get('supports_analysis_modes', {}),
        'warnings': warnings,
        'next_steps': next_steps,
    }
    return summary
