
from __future__ import annotations
from typing import Dict, Any
import pandas as pd
from backend.analysis_engine.phase1.hvg_core import run_hvg_baseline
from backend.analysis_engine.phase1.utils import filter_low_quality_genes, merge_var_features, subset_dataset


def run_group_mode(dataset, var_df, config: Dict[str, Any], group_key: str):
    filtered, filter_report = filter_low_quality_genes(dataset, min_cells=config.get('min_cells',3), min_counts=config.get('min_counts',1))
    global_df, global_summary = run_hvg_baseline(filtered, method=config.get('hvg_method','dispersion'), n_top_genes=config.get('n_top_genes',2000), n_bins=config.get('n_bins',20), loess_span=float(config.get('loess_span', 0.3)))
    global_df = merge_var_features(global_df, var_df)
    subsets = []
    subset_summaries = []
    min_cells_per_subset = int(config.get('min_cells_per_subset', max(5, config.get('min_cells',3))))
    for label, sub_obs in filtered.obs.groupby(group_key, dropna=False):
        mask = filtered.obs.index.isin(sub_obs.index)
        sub_ds = subset_dataset(filtered, mask)
        if sub_ds.n_cells < min_cells_per_subset:
            subset_summaries.append({'label': str(label), 'skipped': True, 'reason': 'too_few_cells', 'n_cells': int(sub_ds.n_cells)})
            continue
        sub_df, sub_summary = run_hvg_baseline(sub_ds, method=config.get('hvg_method','dispersion'), n_top_genes=config.get('n_top_genes',2000), n_bins=config.get('n_bins',20), loess_span=float(config.get('loess_span', 0.3)))
        sub_df['subset_key'] = group_key
        sub_df['subset_value'] = str(label)
        subsets.append(sub_df)
        subset_summaries.append({'label': str(label), **sub_summary})
    subset_df = pd.concat(subsets, ignore_index=True) if subsets else pd.DataFrame()
    if not subset_df.empty:
        subset_df = merge_var_features(subset_df, var_df)
    mode_summary = {
        'analysis_mode': 'group_aware_hvg',
        'primary_label': 'global',
        'group_key': group_key,
        'filter_report': filter_report,
        'subset_summaries': subset_summaries,
        'auxiliary_outputs': ['group_specific_hvg.csv'] if not subset_df.empty else [],
    }
    return global_df, mode_summary, {'group_specific_hvg.csv': subset_df}
