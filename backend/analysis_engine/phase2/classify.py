
from __future__ import annotations
import pandas as pd
from .schemas import ModelArtifacts


def _safe_quantile(series: pd.Series, q: float, fallback: float = 0.0) -> float:
    s = pd.to_numeric(series, errors='coerce').dropna()
    if s.empty:
        return float(fallback)
    return float(s.quantile(float(q)))


def classify_genes(df: pd.DataFrame, hvg_flag_col: str='is_hvg', artifacts: ModelArtifacts | None=None):
    out = df.copy()
    hvg_mask = out[hvg_flag_col].fillna(False).astype(bool)
    hvg_excess = pd.to_numeric(out.loc[hvg_mask, 'stoich_excess_var'], errors='coerce')
    hvg_frac = pd.to_numeric(out.loc[hvg_mask, 'stoich_explained_fraction'], errors='coerce')
    hvg_close = pd.to_numeric(out.loc[hvg_mask, 'stoich_fit_closeness'], errors='coerce')
    all_signal = pd.to_numeric(out['observed_hvg_signal'], errors='coerce')
    mean_expr = pd.to_numeric(out['mean_expr'], errors='coerce')
    cost_idx = pd.to_numeric(out['cost_index'], errors='coerce')
    thresholds = {
        'hvg_excess_q75': _safe_quantile(hvg_excess, 0.75, fallback=0.0),
        'hvg_excess_q50': _safe_quantile(hvg_excess, 0.50, fallback=0.0),
        'hvg_explained_fraction_q75': _safe_quantile(hvg_frac, 0.75, fallback=0.6),
        'hvg_fit_closeness_q75': _safe_quantile(hvg_close, 0.75, fallback=0.6),
        'stable_signal_q25': _safe_quantile(all_signal, 0.25, fallback=0.25),
        'stable_mean_expr_q50': _safe_quantile(mean_expr, 0.50, fallback=0.0),
        'stable_cost_q75': _safe_quantile(cost_idx, 0.75, fallback=0.0),
    }
    out['stoich_class'] = 'background_gene'
    mask_excess = hvg_mask & (pd.to_numeric(out['stoich_excess_var'], errors='coerce') >= thresholds['hvg_excess_q75'])
    out.loc[mask_excess, 'stoich_class'] = 'stoich_excess_hvg'
    mask_explained = (
        hvg_mask & ~mask_excess &
        (pd.to_numeric(out['stoich_explained_fraction'], errors='coerce') >= thresholds['hvg_explained_fraction_q75']) &
        (pd.to_numeric(out['stoich_fit_closeness'], errors='coerce') >= thresholds['hvg_fit_closeness_q75']) &
        (pd.to_numeric(out['stoich_excess_var'], errors='coerce') <= thresholds['hvg_excess_q50'])
    )
    out.loc[mask_explained, 'stoich_class'] = 'stoich_explained_hvg'
    mask_canonical = hvg_mask & ~(mask_excess | mask_explained)
    out.loc[mask_canonical, 'stoich_class'] = 'canonical_hvg'
    mask_stable = (~hvg_mask & (pd.to_numeric(out['observed_hvg_signal'], errors='coerce') <= thresholds['stable_signal_q25']) & (pd.to_numeric(out['mean_expr'], errors='coerce') >= thresholds['stable_mean_expr_q50']) & (pd.to_numeric(out['cost_index'], errors='coerce') >= thresholds['stable_cost_q75']))
    out.loc[mask_stable, 'stoich_class'] = 'stoich_constrained_stable'
    if artifacts is not None:
        artifacts.thresholds = thresholds
    return out, thresholds, artifacts
