from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu


def _cliffs_delta(x: np.ndarray, y: np.ndarray) -> float:
    if x.size == 0 or y.size == 0:
        return float('nan')
    ordered_y = np.sort(y)
    less = np.searchsorted(ordered_y, x, side='left').sum(dtype=np.int64)
    greater = (y.size - np.searchsorted(ordered_y, x, side='right')).sum(dtype=np.int64)
    return float((less - greater) / (x.size * y.size))


def _benjamini_hochberg(pvals: Iterable[float]) -> np.ndarray:
    arr = np.asarray([np.nan if p is None else float(p) for p in pvals], dtype=np.float64)
    out = np.full(arr.shape, np.nan, dtype=np.float64)
    valid = np.isfinite(arr)
    if valid.sum() == 0:
        return out
    idx = np.argsort(arr[valid])
    ordered = arr[valid][idx]
    n = ordered.size
    adjusted = np.empty(n, dtype=np.float64)
    prev = 1.0
    for i in range(n - 1, -1, -1):
        rank = i + 1
        val = (ordered[i] * n) / rank
        prev = min(prev, val)
        adjusted[i] = min(prev, 1.0)
    restored = np.empty(n, dtype=np.float64)
    restored[idx] = adjusted
    out[valid] = restored
    return out


def _evidence_level(fdr: float, cliffs: float) -> str:
    if not np.isfinite(fdr) or not np.isfinite(cliffs):
        return 'descriptive'
    abs_delta = abs(float(cliffs))
    if fdr < 0.01 and abs_delta >= 0.33:
        return 'statistical_association_strong'
    if fdr < 0.05 and abs_delta >= 0.20:
        return 'statistical_association_moderate'
    if fdr < 0.10 and abs_delta >= 0.10:
        return 'statistical_association_weak'
    return 'descriptive'


def compute_feature_associations(
    df: pd.DataFrame,
    feature_columns: list[str],
    hvg_flag_col: str = 'is_hvg',
    min_group_n: int = 8,
) -> pd.DataFrame:
    if hvg_flag_col not in df.columns:
        return pd.DataFrame(columns=[
            'feature', 'n_hvg', 'n_non_hvg', 'median_hvg', 'median_non_hvg', 'median_diff',
            'mean_hvg', 'mean_non_hvg', 'mean_diff', 'cliffs_delta', 'p_value', 'fdr_bh',
            'direction', 'evidence_level',
        ])

    hvg_mask = df[hvg_flag_col].fillna(False).astype(bool)
    rows = []
    for feat in feature_columns:
        if feat not in df.columns:
            continue
        sub = df[[feat, hvg_flag_col]].copy()
        sub[feat] = pd.to_numeric(sub[feat], errors='coerce')
        hvg_vals = sub.loc[hvg_mask, feat].dropna().to_numpy(dtype=np.float64)
        non_hvg_vals = sub.loc[~hvg_mask, feat].dropna().to_numpy(dtype=np.float64)

        if hvg_vals.size < min_group_n or non_hvg_vals.size < min_group_n:
            p_val = np.nan
            cliff = np.nan
        else:
            try:
                _, p_val = mannwhitneyu(hvg_vals, non_hvg_vals, alternative='two-sided')
            except Exception:
                p_val = np.nan
            cliff = _cliffs_delta(hvg_vals, non_hvg_vals)

        median_hvg = float(np.nanmedian(hvg_vals)) if hvg_vals.size else np.nan
        median_non = float(np.nanmedian(non_hvg_vals)) if non_hvg_vals.size else np.nan
        mean_hvg = float(np.nanmean(hvg_vals)) if hvg_vals.size else np.nan
        mean_non = float(np.nanmean(non_hvg_vals)) if non_hvg_vals.size else np.nan
        median_diff = median_hvg - median_non if np.isfinite(median_hvg) and np.isfinite(median_non) else np.nan
        mean_diff = mean_hvg - mean_non if np.isfinite(mean_hvg) and np.isfinite(mean_non) else np.nan
        direction = 'higher_in_hvg' if np.isfinite(median_diff) and median_diff > 0 else (
            'lower_in_hvg' if np.isfinite(median_diff) and median_diff < 0 else 'neutral'
        )

        rows.append({
            'feature': feat,
            'n_hvg': int(hvg_vals.size),
            'n_non_hvg': int(non_hvg_vals.size),
            'median_hvg': median_hvg,
            'median_non_hvg': median_non,
            'median_diff': median_diff,
            'mean_hvg': mean_hvg,
            'mean_non_hvg': mean_non,
            'mean_diff': mean_diff,
            'cliffs_delta': cliff,
            'p_value': float(p_val) if p_val is not None and np.isfinite(p_val) else np.nan,
            'direction': direction,
        })

    assoc = pd.DataFrame(rows)
    if assoc.empty:
        assoc['fdr_bh'] = []
        assoc['evidence_level'] = []
        return assoc

    assoc['fdr_bh'] = _benjamini_hochberg(assoc['p_value'].to_numpy(dtype=np.float64))
    assoc['evidence_level'] = [
        _evidence_level(fdr, cliff) for fdr, cliff in zip(assoc['fdr_bh'], assoc['cliffs_delta'])
    ]
    assoc = assoc.sort_values(
        by=['fdr_bh', 'p_value', 'cliffs_delta'],
        ascending=[True, True, False],
        na_position='last',
    ).reset_index(drop=True)
    assoc['association_rank'] = np.arange(1, len(assoc) + 1)
    return assoc
