
from __future__ import annotations
from typing import Dict, Any
import pandas as pd
from backend.analysis_engine.phase1.hvg_core import run_configured_hvg
from backend.analysis_engine.phase1.utils import filter_low_quality_genes, merge_var_features, subset_dataset


def _build_condition_patterns(subset_df: pd.DataFrame) -> pd.DataFrame:
    if subset_df.empty:
        return pd.DataFrame()
    tmp = subset_df[['gene_id', 'gene_name', 'subset_value', 'is_hvg', 'hvg_score']].copy()
    tmp['is_hvg'] = tmp['is_hvg'].fillna(False).astype(bool)
    grouped = tmp.groupby('gene_id', dropna=False)
    agg = grouped.agg({
        'gene_name': 'first',
        'subset_value': 'nunique',
        'is_hvg': 'sum',
        'hvg_score': ['mean', 'std', 'max', 'min'],
    })
    agg.columns = ['gene_name', 'n_conditions_seen', 'n_conditions_hvg', 'mean_hvg_score', 'std_hvg_score', 'max_hvg_score', 'min_hvg_score']
    agg = agg.reset_index()
    agg['differential_variability_score'] = agg['max_hvg_score'] - agg['min_hvg_score']
    agg['condition_pattern'] = 'non_hvg'
    all_seen = agg['n_conditions_seen'].fillna(0).astype(int)
    n_hvg = agg['n_conditions_hvg'].fillna(0).astype(int)
    agg.loc[(n_hvg > 0) & (n_hvg == all_seen), 'condition_pattern'] = 'shared_hvg'
    agg.loc[n_hvg == 1, 'condition_pattern'] = 'condition_specific_hvg'
    agg.loc[(n_hvg > 1) & (n_hvg < all_seen), 'condition_pattern'] = 'condition_enriched_hvg'
    top_cond = (
        tmp.sort_values('hvg_score', ascending=False)
        .groupby('gene_id', dropna=False)['subset_value']
        .first()
        .rename('top_condition_by_score')
        .reset_index()
    )
    return agg.merge(top_cond, on='gene_id', how='left')


def run_condition_mode(dataset, var_df, config: Dict[str, Any], condition_key: str):
    filtered, filter_report = filter_low_quality_genes(dataset, min_cells=config.get('min_cells',3), min_counts=config.get('min_counts',1))
    global_df, global_summary = run_configured_hvg(filtered, config)
    global_df = merge_var_features(global_df, var_df)
    subsets = []
    min_cells_per_subset = int(config.get('min_cells_per_subset', max(5, config.get('min_cells',3))))
    subset_summaries = []
    for label, sub_obs in filtered.obs.groupby(condition_key, dropna=False):
        mask = filtered.obs.index.isin(sub_obs.index)
        sub_ds = subset_dataset(filtered, mask)
        if sub_ds.n_cells < min_cells_per_subset:
            subset_summaries.append({'label': str(label), 'skipped': True, 'reason': 'too_few_cells', 'n_cells': int(sub_ds.n_cells)})
            continue
        sub_df, sub_summary = run_configured_hvg(sub_ds, config)
        sub_df['subset_key'] = condition_key
        sub_df['subset_value'] = str(label)
        subsets.append(sub_df)
        subset_summaries.append({'label': str(label), **sub_summary})
    subset_df = pd.concat(subsets, ignore_index=True) if subsets else pd.DataFrame()
    if not subset_df.empty:
        subset_df = merge_var_features(subset_df, var_df)
    pattern_df = _build_condition_patterns(subset_df) if not subset_df.empty else pd.DataFrame()
    if not pattern_df.empty:
        pattern_df = merge_var_features(pattern_df, var_df)

    mode_summary = {
        'analysis_mode': 'condition_aware_hvg',
        'primary_label': 'global',
        'condition_key': condition_key,
        'filter_report': filter_report,
        'subset_summaries': subset_summaries,
        'condition_pattern_counts': pattern_df['condition_pattern'].value_counts().to_dict() if not pattern_df.empty else {},
        'auxiliary_outputs': [f for f, enabled in [
            ('condition_specific_hvg.csv', not subset_df.empty),
            ('condition_hvg_patterns.csv', not pattern_df.empty),
        ] if enabled],
    }
    aux = {'condition_specific_hvg.csv': subset_df}
    if not pattern_df.empty:
        aux['condition_hvg_patterns.csv'] = pattern_df
    return global_df, mode_summary, aux
