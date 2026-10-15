
from __future__ import annotations
from typing import Dict, Any
import numpy as np
import pandas as pd
from backend.analysis_engine.phase1.hvg_core import run_hvg_baseline
from backend.analysis_engine.phase1.utils import filter_low_quality_genes, merge_var_features, subset_dataset
from backend.analysis_engine.phase1.sample_consensus_hvg import _aggregate_consensus


def run_trajectory_mode(dataset, var_df, config: Dict[str, Any], pseudotime_key: str):
    filtered, filter_report = filter_low_quality_genes(dataset, min_cells=config.get('min_cells',3), min_counts=config.get('min_counts',1))
    if pseudotime_key not in filtered.obs.columns:
        raise ValueError(f'Pseudotime key not found: {pseudotime_key}')
    pt = pd.to_numeric(filtered.obs[pseudotime_key], errors='coerce')
    n_bins = int(config.get('trajectory_bins', 10))
    labels = [f'bin_{i+1}' for i in range(n_bins)]
    bins = pd.qcut(pt.rank(method='first'), q=min(n_bins, max(2, pt.notna().sum())), labels=labels[:min(n_bins, max(2, pt.notna().sum()))], duplicates='drop')
    filtered.obs = filtered.obs.copy()
    filtered.obs['_trajectory_bin'] = bins.astype(str)
    subsets=[]; subset_summaries=[]
    min_cells_per_subset = int(config.get('min_cells_per_subset', max(3, config.get('min_cells',3))))
    for label, sub_obs in filtered.obs.groupby('_trajectory_bin', dropna=False):
        mask = filtered.obs.index.isin(sub_obs.index)
        sub_ds = subset_dataset(filtered, mask)
        if sub_ds.n_cells < min_cells_per_subset:
            subset_summaries.append({'label': str(label), 'skipped': True, 'reason': 'too_few_cells', 'n_cells': int(sub_ds.n_cells)})
            continue
        sub_df, sub_summary = run_hvg_baseline(sub_ds, method=config.get('hvg_method','dispersion'), n_top_genes=config.get('n_top_genes',2000), n_bins=config.get('n_bins',20), loess_span=float(config.get('loess_span', 0.3)))
        sub_df['subset_key'] = '_trajectory_bin'
        sub_df['subset_value'] = str(label)
        subsets.append(sub_df)
        subset_summaries.append({'label': str(label), **sub_summary})
    subset_df = pd.concat(subsets, ignore_index=True) if subsets else pd.DataFrame()
    if subset_df.empty:
        raise ValueError('No valid trajectory bins available for trajectory_hvg')
    consensus = _aggregate_consensus(subset_df, config.get('n_top_genes',2000))
    consensus = merge_var_features(consensus, var_df)
    subset_df = merge_var_features(subset_df, var_df)
    mode_summary = {
        'analysis_mode': 'trajectory_hvg',
        'primary_label': 'trajectory_consensus',
        'pseudotime_key': pseudotime_key,
        'trajectory_bins': int(config.get('trajectory_bins', 10)),
        'filter_report': filter_report,
        'subset_summaries': subset_summaries,
        'auxiliary_outputs': ['trajectory_bin_hvg.csv'],
    }
    return consensus, mode_summary, {'trajectory_bin_hvg.csv': subset_df}
