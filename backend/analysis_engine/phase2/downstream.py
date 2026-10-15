from __future__ import annotations

import numpy as np
import pandas as pd


def _minmax(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors='coerce')
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or pd.isna(hi) or hi <= lo:
        return pd.Series(0.0, index=s.index)
    return (s - lo) / (hi - lo)


def build_candidate_gene_table(df: pd.DataFrame, top_n: int = 300) -> pd.DataFrame:
    work = df.copy()
    work['is_hvg_num'] = work['is_hvg'].fillna(False).astype(bool).astype(float) if 'is_hvg' in work.columns else 0.0
    work['rank_score'] = 0.0
    if 'hvg_rank' in work.columns:
        rank = pd.to_numeric(work['hvg_rank'], errors='coerce')
        max_rank = np.nanmax(rank.to_numpy()) if rank.notna().any() else 1.0
        work['rank_score'] = 1.0 - ((rank - 1.0) / max(max_rank, 1.0))
        work['rank_score'] = work['rank_score'].replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0, upper=1.0)
    work['excess_score'] = _minmax(pd.to_numeric(work.get('stoich_excess_var'), errors='coerce').abs())
    work['explained_score'] = _minmax(pd.to_numeric(work.get('stoich_explained_fraction'), errors='coerce'))
    work['fit_score'] = _minmax(pd.to_numeric(work.get('stoich_fit_closeness'), errors='coerce'))
    work['priority_score'] = (
        0.35 * work['rank_score']
        + 0.20 * work['is_hvg_num']
        + 0.20 * work['excess_score']
        + 0.15 * work['explained_score']
        + 0.10 * work['fit_score']
    )
    keep = [
        c for c in [
            'gene_id',
            'gene_name',
            'is_hvg',
            'hvg_rank',
            'stoich_class',
            'stoich_associated_feature',
            'observed_hvg_signal',
            'stoich_expected_var',
            'stoich_excess_var',
            'stoich_explained_fraction',
            'stoich_fit_closeness',
            'priority_score',
        ] if c in work.columns
    ]
    out = work.sort_values('priority_score', ascending=False).head(int(top_n))[keep]
    return out.reset_index(drop=True)


def build_downstream_summary(df: pd.DataFrame, feature_associations: pd.DataFrame | None = None) -> dict:
    out = {
        'n_genes': int(df.shape[0]),
        'class_counts': df['stoich_class'].value_counts(dropna=False).to_dict() if 'stoich_class' in df.columns else {},
        'hvg_fraction': float(df['is_hvg'].fillna(False).astype(bool).mean()) if 'is_hvg' in df.columns else None,
    }
    if feature_associations is not None and not feature_associations.empty:
        sig = feature_associations.loc[
            pd.to_numeric(feature_associations.get('fdr_bh'), errors='coerce') <= 0.05
        ]
        out['significant_association_count_fdr_0_05'] = int(sig.shape[0])
        out['top_significant_features'] = sig.head(15).to_dict(orient='records')
    else:
        out['significant_association_count_fdr_0_05'] = 0
        out['top_significant_features'] = []
    return out
