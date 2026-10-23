
from __future__ import annotations
from typing import Dict, Any
from backend.analysis_engine.phase1.hvg_core import run_configured_hvg
from backend.analysis_engine.phase1.utils import filter_low_quality_genes, merge_var_features


def run_global_mode(dataset, var_df, config: Dict[str, Any]):
    filtered, filter_report = filter_low_quality_genes(dataset, min_cells=config.get('min_cells',3), min_counts=config.get('min_counts',1))
    base, summary = run_configured_hvg(filtered, config)
    base = merge_var_features(base, var_df)
    mode_summary = {
        'analysis_mode': 'global_hvg',
        'primary_label': 'global',
        'filter_report': filter_report,
        'subset_summaries': [{'label': 'global', **summary}],
        'auxiliary_outputs': [],
    }
    return base, mode_summary, {}
