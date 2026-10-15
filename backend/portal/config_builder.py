from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
import json


def _rel(path: Path, start: Path) -> str:
    try:
        return str(path.relative_to(start))
    except Exception:
        return str(path)


def build_full_pipeline_config(project_root: str | Path, workspace_root: str | Path, job_id: str, input_mode: str,
                               expression_cfg: Dict[str, Any], metadata_file: Optional[str]=None,
                               stoich_cfg: Optional[Dict[str, Any]]=None,
                               analysis_overrides: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    project_root = Path(project_root).resolve()
    workspace_root = Path(workspace_root).resolve()
    job_dir = workspace_root / job_id
    raw_dir = job_dir / 'raw'
    std_dir = job_dir / 'standardized'
    val_dir = job_dir / 'validation'
    mode_dir = job_dir / 'mode_resolution'
    p1_dir = job_dir / 'analysis_phase1'
    p2_dir = job_dir / 'analysis_phase2'

    normalized_input_mode = 'csv' if input_mode in {'matrix_csv', 'csv_tsv'} else input_mode
    input_adapter = {
        'case_id': job_id,
        'input_dir': str(raw_dir),
        'output_dir': str(std_dir),
        'workspace': {'enabled': True, 'root_dir': str(workspace_root), 'job_id': job_id},
        'expression': {'format': normalized_input_mode, **expression_cfg},
        'metadata': {'file': metadata_file} if metadata_file else {'file': None},
        'stoich': stoich_cfg or {'require': False},
    }

    validation = {
        'case_id': f'{job_id}_validation',
        'input_dir': str(std_dir),
        'output_dir': str(val_dir),
        'thresholds': {
            'warn_gene_overlap_fraction_vs_expression': 0.80,
            'max_zero_only_gene_fraction': 0.20,
            'max_zero_only_cell_fraction': 0.20,
        }
    }

    mode_resolution = {
        'case_id': f'{job_id}_modes',
        'validation_dir': str(val_dir),
        'output_dir': str(mode_dir),
        'preferred_mode': None,
    }

    phase1_analysis = {
        'case_id': f'{job_id}_phase1',
        'standardized_input_dir': str(std_dir),
        'validation_dir': str(val_dir),
        'mode_resolution_dir': str(mode_dir),
        'output_dir': str(p1_dir),
        'analysis_mode': 'auto',
        'always_run_global': True,
        'run_supported_auxiliary_modes': True,
        'hvg_method': 'seurat_v3',
        'scanpy_hvg_method': 'seurat_v3',
        'loess_span': 0.3,
        'enable_scanpy_backend': False,
        'enable_seurat_r_backend': False,
        'n_top_genes': 2000,
        'min_cells': 3,
        'min_counts': 1,
        'n_bins': 20,
        'min_cells_per_subset': 10,
        'trajectory_bins': 6,
    }

    phase2_stoich = {
        'case_id': f'{job_id}_phase2',
        'species_id': 'unknown',
        'omics': 'transcriptome',
        'input_baseline_csv': str(p1_dir / 'hvg_baseline.csv'),
        'input_phase1_summary_json': str(p1_dir / 'phase1_mode_summary.json'),
        'validation_dir': str(val_dir),
        'output_dir': str(p2_dir),
        'feature_set': 'core',
        # The model and comparison are independent Phase 2 branches.  Keep
        # ``enabled`` as a legacy alias for old callers, but use
        # ``model_enabled`` for the stoichiometric model gate.
        'enabled': True,
        'model_enabled': True,
        'enable_hvg_nonhvg_comparison': True,
        'comparison_context_enabled': True,
        'comparison_schema_version': 'hvg_nonhvg_v2',
        'comparison_omics': ['genome', 'transcriptome', 'proteome'],
        'comparison_include_conditional': False,
        'comparison_auto_detect_blocks': True,
        'comparison_min_block_match_rate': 0.70,
        'comparison_min_block_mapped_genes': 40,
        'comparison_allow_alias_mapping': True,
        'comparison_require_unique_mapping': True,
        'comparison_allow_version_stripped_unique': True,
        'comparison_source_chunk_size': 50000,
        'comparison_min_group_n': 20,
        'comparison_max_missing_rate': 0.50,
        'comparison_bootstrap_ci_repeats': 500,
        'comparison_bootstrap_max_group_n': 1000,
        'comparison_worker_count': 1,
        'comparison_api_page_size_max': 200,
        'comparison_display_point_cap': 240,
        'comparison_categorical_min_cell_count': 5,
        'comparison_near_constant_tolerance': 1e-12,
        'comparison_high_correlation_threshold': 0.995,
        'comparison_applicability_policy': 'v2',
        'comparison_applicable_values': ['all', 'coding_only', 'protein_proxy_only'],
        'comparison_adjustment_enabled': True,
        'comparison_adjustment_policy': 'v2',
        'comparison_composition_adjustment': 'clr_v1',
        'comparison_composition_pseudocount_fraction': 1e-6,
        'comparison_input_csv': None,
        'comparison_feature_provenance_path': None,
        'comparison_mapping_summary_path': None,
        'comparison_context_manifest_path': None,
        'comparison_block_coverage_path': None,
        'comparison_block_status': {},
        'model_type': 'elasticnet',
        'hvg_target_type': 'score',
        'target_col': 'normalized_dispersion',
        'hvg_flag_col': 'is_hvg',
        'confounder_columns': ['mean_expr', 'pct_cells_detected', 'dropout_rate', 'length_nt', 'gc_content'],
        'winsorize_quantile': 0.01,
        'random_state': 42,
        'n_cv_folds': 5,
        'permutation_repeats': 8,
        'permutation_test_repeats': 8,
        'bootstrap_repeats': 40,
        'enable_functional_enrichment': True,
        'functional_enrichment_top_n': 300,
        'functional_enrichment_min_overlap': 2,
        'functional_enrichment_min_term_size': 3,
        'functional_enrichment_max_term_size': 500,
        'functional_enrichment_fdr': 0.05,
        'functional_enrichment_report_terms': 200,
        'functional_enrichment_plot_terms': 30,
        'functional_gsea_permutations': 100,
        'top_n_gene_details': 80,
    }

    if input_adapter['stoich'].get('file'):
        validation['raw_stoich_file'] = str(raw_dir / input_adapter['stoich']['file'])

    if analysis_overrides:
        for section_name, updates in analysis_overrides.items():
            if section_name in {'input_adapter','validation','mode_resolution','phase1_analysis','phase2_stoich'} and isinstance(updates, dict):
                locals()[section_name].update(updates)

    return {
        'input_adapter': input_adapter,
        'validation': validation,
        'mode_resolution': mode_resolution,
        'phase1_analysis': phase1_analysis,
        'phase2_stoich': phase2_stoich,
    }


def build_preanalysis_config(project_root: str | Path, workspace_root: str | Path, job_id: str, input_mode: str,
                             expression_cfg: Dict[str, Any], metadata_file: Optional[str]=None,
                             stoich_cfg: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    full = build_full_pipeline_config(project_root, workspace_root, job_id, input_mode, expression_cfg, metadata_file, stoich_cfg)
    return {
        'phase1': full['input_adapter'],
        'phase2': full['validation'],
        'phase3': full['mode_resolution'],
    }
