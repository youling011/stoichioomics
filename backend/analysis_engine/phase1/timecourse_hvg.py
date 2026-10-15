
from __future__ import annotations
from typing import Dict, Any
import pandas as pd
import numpy as np
from backend.analysis_engine.phase1.hvg_core import run_hvg_baseline
from backend.analysis_engine.phase1.utils import filter_low_quality_genes, merge_var_features, subset_dataset, order_categories


def _build_timecourse_patterns(subset_df: pd.DataFrame, ordered_labels: list[str]) -> pd.DataFrame:
    if subset_df.empty:
        return pd.DataFrame()
    tmp = subset_df[['gene_id', 'gene_name', 'subset_value', 'is_hvg', 'hvg_score']].copy()
    tmp['is_hvg'] = tmp['is_hvg'].fillna(False).astype(bool)
    label_to_idx = {str(v): i for i, v in enumerate(ordered_labels)}
    tmp['time_order'] = tmp['subset_value'].astype(str).map(label_to_idx).fillna(len(label_to_idx)).astype(float)
    grouped = tmp.groupby('gene_id', dropna=False)
    agg = grouped.agg({
        'gene_name': 'first',
        'subset_value': 'nunique',
        'is_hvg': 'sum',
        'hvg_score': ['mean', 'std', 'max', 'min'],
    })
    agg.columns = ['gene_name', 'n_timepoints_seen', 'n_timepoints_hvg', 'mean_hvg_score', 'std_hvg_score', 'max_hvg_score', 'min_hvg_score']
    agg = agg.reset_index()
    agg['temporal_variability_score'] = agg['max_hvg_score'] - agg['min_hvg_score']
    agg['timecourse_pattern'] = 'non_hvg'
    seen = agg['n_timepoints_seen'].fillna(0).astype(int)
    n_hvg = agg['n_timepoints_hvg'].fillna(0).astype(int)
    agg.loc[(n_hvg > 0) & (n_hvg == seen), 'timecourse_pattern'] = 'persistent_hvg'
    agg.loc[n_hvg == 1, 'timecourse_pattern'] = 'transient_hvg'
    agg.loc[(n_hvg > 1) & (n_hvg < seen), 'timecourse_pattern'] = 'phase_specific_hvg'
    top_tp = (
        tmp.sort_values('hvg_score', ascending=False)
        .groupby('gene_id', dropna=False)['subset_value']
        .first()
        .rename('top_timepoint_by_score')
        .reset_index()
    )

    trends = []
    for gene_id, sub in tmp.groupby('gene_id', dropna=False):
        sub = sub[['time_order', 'hvg_score']].dropna()
        if sub.shape[0] < 3:
            trends.append({'gene_id': gene_id, 'temporal_trend_r': np.nan})
            continue
        r = sub['time_order'].corr(sub['hvg_score'], method='spearman')
        trends.append({'gene_id': gene_id, 'temporal_trend_r': float(r) if pd.notna(r) else np.nan})
    trend_df = pd.DataFrame(trends)
    out = agg.merge(top_tp, on='gene_id', how='left').merge(trend_df, on='gene_id', how='left')
    out['temporal_trend_label'] = out['temporal_trend_r'].apply(
        lambda v: 'increasing' if pd.notna(v) and v >= 0.35 else ('decreasing' if pd.notna(v) and v <= -0.35 else 'stable_or_weak')
    )
    return out


def run_timecourse_mode(dataset, var_df, config: Dict[str, Any], timepoint_key: str):
    filtered, filter_report = filter_low_quality_genes(dataset, min_cells=config.get('min_cells',3), min_counts=config.get('min_counts',1))
    global_df, global_summary = run_hvg_baseline(filtered, method=config.get('hvg_method','dispersion'), n_top_genes=config.get('n_top_genes',2000), n_bins=config.get('n_bins',20), loess_span=float(config.get('loess_span', 0.3)))
    global_df = merge_var_features(global_df, var_df)
    subsets = []
    subset_summaries = []
    min_cells_per_subset = int(config.get('min_cells_per_subset', max(5, config.get('min_cells',3))))
    order = order_categories(filtered.obs[timepoint_key].astype(str)) if timepoint_key in filtered.obs.columns else []
    grouped = filtered.obs.groupby(timepoint_key, dropna=False)
    items = list(grouped)
    items = sorted(items, key=lambda kv: order.index(str(kv[0])) if str(kv[0]) in order else len(order))
    for label, sub_obs in items:
        mask = filtered.obs.index.isin(sub_obs.index)
        sub_ds = subset_dataset(filtered, mask)
        if sub_ds.n_cells < min_cells_per_subset:
            subset_summaries.append({'label': str(label), 'skipped': True, 'reason': 'too_few_cells', 'n_cells': int(sub_ds.n_cells)})
            continue
        sub_df, sub_summary = run_hvg_baseline(sub_ds, method=config.get('hvg_method','dispersion'), n_top_genes=config.get('n_top_genes',2000), n_bins=config.get('n_bins',20), loess_span=float(config.get('loess_span', 0.3)))
        sub_df['subset_key'] = timepoint_key
        sub_df['subset_value'] = str(label)
        subsets.append(sub_df)
        subset_summaries.append({'label': str(label), **sub_summary})
    subset_df = pd.concat(subsets, ignore_index=True) if subsets else pd.DataFrame()
    if not subset_df.empty:
        subset_df = merge_var_features(subset_df, var_df)
    pattern_df = _build_timecourse_patterns(subset_df, order) if not subset_df.empty else pd.DataFrame()
    if not pattern_df.empty:
        pattern_df = merge_var_features(pattern_df, var_df)

    mode_summary = {
        'analysis_mode': 'timecourse_hvg',
        'primary_label': 'across_time',
        'timepoint_key': timepoint_key,
        'timepoint_order': order,
        'filter_report': filter_report,
        'subset_summaries': subset_summaries,
        'timecourse_pattern_counts': pattern_df['timecourse_pattern'].value_counts().to_dict() if not pattern_df.empty else {},
        'auxiliary_outputs': [f for f, enabled in [
            ('within_timepoint_hvg.csv', not subset_df.empty),
            ('timecourse_hvg_patterns.csv', not pattern_df.empty),
        ] if enabled],
    }
    aux = {'within_timepoint_hvg.csv': subset_df}
    if not pattern_df.empty:
        aux['timecourse_hvg_patterns.csv'] = pattern_df
    return global_df, mode_summary, aux
