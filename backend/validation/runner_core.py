from __future__ import annotations
from pathlib import Path
from typing import Dict, Any

from .loader import load_standardized_bundle
from .gene_id_check import build_gene_mapping_report
from .matrix_check import build_matrix_check_report
from .metadata_check import build_metadata_check_report
from .stoich_check import build_stoich_check_report
from .semantics_check import build_semantics_check_report
from .duplicate_check import build_duplicate_check_report
from .id_mapping import build_strict_id_mapping
from .summary import summarize_reports
from .utils import write_json

DEFAULT_THRESHOLDS = {
    'warn_gene_overlap_fraction_vs_expression': 0.8,
    'max_zero_only_gene_fraction': 0.2,
    'max_zero_only_cell_fraction': 0.2,
}


def run_validation_pipeline(config: Dict[str, Any]) -> Dict[str, Any]:
    input_dir = config['input_dir']
    output_dir = Path(config['output_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)

    bundle = load_standardized_bundle(input_dir, config.get('raw_stoich_file'))
    bundle_summary = bundle.to_basic_summary()

    gene_map = build_gene_mapping_report(bundle)
    matrix = build_matrix_check_report(bundle)
    metadata = build_metadata_check_report(bundle)
    stoich = build_stoich_check_report(bundle)
    semantics = build_semantics_check_report(bundle)
    dup = build_duplicate_check_report(bundle)
    mapping_table, mapping_conflicts, unmatched_genes, mapping_summary = build_strict_id_mapping(bundle)

    thresholds = DEFAULT_THRESHOLDS.copy()
    thresholds.update(config.get('thresholds', {}) or {})
    summary = summarize_reports(bundle_summary, gene_map, matrix, metadata, stoich, semantics, dup, thresholds)
    summary['id_mapping_summary'] = mapping_summary
    if not mapping_summary.get('ready_for_phase2_stoich', False):
        summary['ready_for_phase2_stoich'] = False
        summary.setdefault('warnings', []).append({
            'code': 'LOW_STRICT_ID_MATCH_RATE',
            'severity': 'error',
            'message': (
                f"Strict gene ID match rate {mapping_summary.get('match_rate', 0):.3f} is below "
                f"{mapping_summary.get('minimum_phase2_match_rate', 0.70):.2f}; phase2 stoichiometric modeling should be blocked."
            ),
        })

    write_json(gene_map, output_dir / 'gene_mapping_report.json')
    write_json(matrix, output_dir / 'matrix_check_report.json')
    write_json(metadata, output_dir / 'metadata_check_report.json')
    write_json(stoich, output_dir / 'stoich_check_report.json')
    write_json(semantics, output_dir / 'semantics_check_report.json')
    write_json(dup, output_dir / 'duplicate_check_report.json')
    mapping_table.to_csv(output_dir / 'mapping_table.csv', index=False)
    mapping_conflicts.to_csv(output_dir / 'mapping_conflicts.csv', index=False)
    unmatched_genes.to_csv(output_dir / 'unmatched_genes.csv', index=False)
    write_json(mapping_summary, output_dir / 'id_mapping_summary.json')
    write_json(summary, output_dir / 'validation_summary.json')
    write_json(summary['warnings'], output_dir / 'user_warnings.json')

    run_log = {
        'case_id': config.get('case_id'),
        'input_dir': str(Path(input_dir).resolve()),
        'output_dir': str(output_dir.resolve()),
        'raw_stoich_file': config.get('raw_stoich_file'),
        'bundle_summary': bundle_summary,
        'id_mapping_summary': mapping_summary,
        'overall_status': summary['overall_status'],
    }
    write_json(run_log, output_dir / 'run_log.json')

    return {
        'bundle_summary': bundle_summary,
        'overall_status': summary['overall_status'],
        'ready_for_phase1_hvg': summary['ready_for_phase1_hvg'],
        'ready_for_phase2_stoich': summary['ready_for_phase2_stoich'],
        'supports_analysis_modes': summary['supports_analysis_modes'],
        'output_dir': str(output_dir.resolve()),
    }
