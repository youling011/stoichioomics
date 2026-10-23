
from __future__ import annotations
from typing import Dict, Any, List
import pandas as pd
import numpy as np
from backend.analysis_engine.phase1.hvg_core import run_configured_hvg
from backend.analysis_engine.phase1.utils import filter_low_quality_genes, merge_var_features, subset_dataset


def _aggregate_consensus(subset_df: pd.DataFrame, n_top_genes: int) -> pd.DataFrame:
    grouped = subset_df.groupby('gene_id', dropna=False)
    agg = grouped.agg({
        'gene_name': 'first',
        'mean_expr': 'mean',
        'variance': 'mean',
        'dispersion': 'mean',
        'normalized_dispersion': 'mean',
        'hvg_score': 'mean',
        'n_cells_detected': 'mean',
        'pct_cells_detected': 'mean',
        'is_hvg': 'mean',
        'subset_value': 'nunique',
    }).rename(columns={'is_hvg':'hvg_vote_fraction','subset_value':'n_subsets_seen'}).reset_index()
    rank_mean = grouped['hvg_rank'].mean().rename('mean_hvg_rank').reset_index()
    agg = agg.merge(rank_mean, on='gene_id', how='left')
    agg = agg.sort_values(['hvg_vote_fraction','mean_hvg_rank','hvg_score'], ascending=[False, True, False]).reset_index(drop=True)
    agg['hvg_rank'] = np.arange(1, len(agg)+1)
    max_rank = max(len(agg), 1)
    rank_component = 1.0 - ((agg['mean_hvg_rank'].fillna(max_rank) - 1.0) / max_rank)
    agg['stability_score'] = (agg['hvg_vote_fraction'].fillna(0.0) * rank_component.clip(lower=0.0, upper=1.0)).clip(lower=0.0, upper=1.0)
    vote_threshold = 0.5
    agg['is_hvg'] = agg['hvg_rank'] <= min(int(n_top_genes), len(agg))
    agg['consensus_strategy'] = 'vote_then_rank'
    agg['consensus_label'] = agg['hvg_vote_fraction'].apply(
        lambda v: 'high_consensus' if v >= 0.8 else ('moderate_consensus' if v >= 0.5 else 'low_consensus')
    )
    return agg


def run_sample_consensus_mode(dataset, var_df, config: Dict[str, Any], sample_key: str):
    filtered, filter_report = filter_low_quality_genes(dataset, min_cells=config.get('min_cells',3), min_counts=config.get('min_counts',1))
    subsets = []
    subset_summaries = []
    min_cells_per_subset = int(config.get('min_cells_per_subset', max(3, config.get('min_cells',3))))
    for label, sub_obs in filtered.obs.groupby(sample_key, dropna=False):
        mask = filtered.obs.index.isin(sub_obs.index)
        sub_ds = subset_dataset(filtered, mask)
        if sub_ds.n_cells < min_cells_per_subset:
            subset_summaries.append({'label': str(label), 'skipped': True, 'reason': 'too_few_cells', 'n_cells': int(sub_ds.n_cells)})
            continue
        sub_df, sub_summary = run_configured_hvg(sub_ds, config)
        sub_df['subset_key'] = sample_key
        sub_df['subset_value'] = str(label)
        subsets.append(sub_df)
        subset_summaries.append({'label': str(label), **sub_summary})
    subset_df = pd.concat(subsets, ignore_index=True) if subsets else pd.DataFrame()
    if subset_df.empty:
        raise ValueError(f'No valid subsets available for sample_consensus_hvg using key={sample_key}')
    consensus = _aggregate_consensus(subset_df, config.get('n_top_genes',2000))
    consensus = merge_var_features(consensus, var_df)
    subset_df = merge_var_features(subset_df, var_df)
    mode_summary = {
        'analysis_mode': 'sample_consensus_hvg',
        'primary_label': 'sample_consensus',
        'sample_key': sample_key,
        'filter_report': filter_report,
        'subset_summaries': subset_summaries,
        'auxiliary_outputs': ['sample_specific_hvg.csv'],
    }
    return consensus, mode_summary, {'sample_specific_hvg.csv': subset_df}
