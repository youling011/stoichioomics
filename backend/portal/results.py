from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
import json
import pandas as pd


def _read_json(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return None


def _read_csv(path: Path, nrows: int | None = None):
    if path.exists():
        return pd.read_csv(path, nrows=nrows)
    return None


def load_case_outputs(base_dir: str | Path) -> Dict[str, Any]:
    base = Path(base_dir)
    return {
        'phase1_baseline': _read_csv(base / 'analysis_phase1' / 'hvg_baseline.csv'),
        'phase1_summary': _read_json(base / 'analysis_phase1' / 'phase1_mode_summary.json'),
        'phase1_method_benchmark': _read_csv(base / 'analysis_phase1' / 'hvg_method_benchmark.csv'),
        'phase1_consensus': _read_csv(base / 'analysis_phase1' / 'hvg_consensus.csv'),
        'phase1_backend_report': _read_json(base / 'analysis_phase1' / 'hvg_backend_report.json'),
        'phase2_scores': _read_csv(base / 'analysis_phase2' / 'hvg_stoich_scores.csv'),
        'phase2_summary': _read_json(base / 'analysis_phase2' / 'hvg_summary.json'),
        'phase2_model': _read_json(base / 'analysis_phase2' / 'hvg_stoich_model.json'),
        'overview_cards': _read_json(base / 'visualization' / 'overview_cards.json'),
        'tables_payload': _read_json(base / 'visualization' / 'tables_payload.json'),
        'visualization_manifest': _read_json(base / 'visualization' / 'visualization_manifest.json'),
        'feature_associations': _read_csv(base / 'analysis_phase2' / 'feature_associations.csv'),
        'hvg_nonhvg_summary': _read_json(base / 'analysis_phase2' / 'hvg_nonhvg_summary.json'),
        'hvg_nonhvg_feature_audit': _read_csv(base / 'analysis_phase2' / 'hvg_nonhvg_feature_audit.csv'),
        'hvg_nonhvg_feature_comparison': _read_csv(base / 'analysis_phase2' / 'hvg_nonhvg_feature_comparison.csv'),
        'hvg_nonhvg_adjusted_comparison': _read_csv(base / 'analysis_phase2' / 'hvg_nonhvg_adjusted_comparison.csv'),
        'hvg_nonhvg_distribution_quantiles': _read_csv(base / 'analysis_phase2' / 'hvg_nonhvg_distribution_quantiles.csv'),
        'hvg_nonhvg_family_summary': _read_csv(base / 'analysis_phase2' / 'hvg_nonhvg_family_summary.csv'),
        'hvg_nonhvg_plots_payload': _read_json(base / 'analysis_phase2' / 'hvg_nonhvg_plots_payload.json'),
        'hvg_nonhvg_run_manifest': _read_json(base / 'analysis_phase2' / 'hvg_nonhvg_run_manifest.json'),
        # Comparison-v2 context artifacts are kept separate from the legacy
        # eight comparison outputs and are loaded as first-class results.
        # The context and mapping table can be large. They are download-only
        # artifacts, so keep only their headers in the normal result bundle.
        'hvg_multiomics_core_features': _read_csv(base / 'analysis_phase2' / 'hvg_multiomics_core_features.csv', nrows=0),
        'hvg_multiomics_feature_provenance': _read_csv(base / 'analysis_phase2' / 'hvg_multiomics_feature_provenance.csv'),
        'hvg_multiomics_mapping_table': _read_csv(base / 'analysis_phase2' / 'hvg_multiomics_mapping_table.csv', nrows=0),
        'hvg_multiomics_mapping_summary': _read_json(base / 'analysis_phase2' / 'hvg_multiomics_mapping_summary.json'),
        'hvg_multiomics_assembly_manifest': _read_json(base / 'analysis_phase2' / 'hvg_multiomics_assembly_manifest.json'),
        'hvg_nonhvg_block_coverage': _read_csv(base / 'analysis_phase2' / 'hvg_nonhvg_block_coverage.csv'),
        'candidate_genes': _read_csv(base / 'analysis_phase2' / 'candidate_gene_table.csv'),
        'model_comparison': _read_csv(base / 'analysis_phase2' / 'model_comparison.csv'),
        'cv_predictions': _read_csv(base / 'analysis_phase2' / 'cv_predictions.csv', nrows=1000),
        'feature_block_importance': _read_csv(base / 'analysis_phase2' / 'feature_block_importance.csv'),
        'bootstrap_feature_stability': _read_csv(base / 'analysis_phase2' / 'bootstrap_feature_stability.csv'),
        'negative_control_report': _read_json(base / 'analysis_phase2' / 'negative_control_report.json'),
        'evidence_assessment': _read_json(base / 'analysis_phase2' / 'evidence_assessment.json'),
        'downstream_summary': _read_json(base / 'analysis_phase2' / 'downstream_summary.json'),
        'candidate_score_components': _read_csv(base / 'downstream' / 'candidate_score_components.csv'),
        'enrichment_ora': _read_csv(base / 'downstream' / 'enrichment_ora.csv'),
        'gsea_prerank_results': _read_csv(base / 'downstream' / 'gsea_prerank_results.csv'),
        'ppi_module_enrichment': _read_csv(base / 'downstream' / 'ppi_module_enrichment.csv'),
        'id_mapping_summary': _read_json(base / 'validation' / 'id_mapping_summary.json'),
        'plots_payload': _read_json(base / 'analysis_phase2' / 'plots_payload.json'),
        'gene_detail_payload': _read_json(base / 'analysis_phase2' / 'gene_detail_payload.json'),
        'workspace_manifest': _read_json(base / 'workspace_manifest.json'),
        'case_cache': _read_json(base / 'case_cache.json'),
        'job_manifest': _read_json(base / 'job_manifest.json'),
    }
