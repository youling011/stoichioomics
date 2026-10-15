from __future__ import annotations

import numpy as np
import pandas as pd

from .schemas import PLOT_FEATURES


def build_summary_json(
    df: pd.DataFrame,
    case_id: str,
    species_id: str,
    omics: str,
    model_info,
    phase1_summary=None,
    validation_summary=None,
    mapping_summary=None,
    feature_associations: pd.DataFrame | None = None,
):
    cls_counts = df['stoich_class'].value_counts(dropna=False).to_dict() if 'stoich_class' in df.columns else {}
    associated_features = (
        df['stoich_associated_feature'].fillna('NA').astype(str).value_counts().head(12).reset_index()
        if 'stoich_associated_feature' in df.columns else pd.DataFrame(columns=['index', 'stoich_associated_feature'])
    )
    if not associated_features.empty:
        associated_features.columns = ['feature', 'count']
    top_assoc = []
    if feature_associations is not None and not feature_associations.empty:
        top_assoc = feature_associations.head(20).replace([np.inf, -np.inf], np.nan).where(
            pd.notnull(feature_associations.head(20)),
            None,
        ).to_dict(orient='records')
    warnings = (validation_summary or {}).get('warnings', []) if isinstance(validation_summary, dict) else []
    return {
        'case_id': case_id,
        'species_id': species_id,
        'omics': omics,
        'total_genes': int(df.shape[0]),
        'total_hvgs': int(df['is_hvg'].fillna(False).astype(bool).sum()) if 'is_hvg' in df.columns else None,
        'class_counts': {str(k): int(v) for k, v in cls_counts.items()},
        'top_associated_feature_counts': associated_features.to_dict(orient='records'),
        'top_associated_features': top_assoc,
        'model_info': model_info,
        'phase1_context': phase1_summary or {},
        'validation_context': validation_summary or {},
        'mapping_summary': mapping_summary or {},
        'warnings': warnings,
        'evidence_labels': {
            'descriptive': 'Descriptive summary only',
            'statistical_association': 'Statistical association (non-causal)',
            'predictive': 'Predictive signal (non-causal)',
            'exploratory_hypothesis': 'Exploratory hypothesis',
        },
    }


def _scatter_records(df: pd.DataFrame, cols, limit: int = 5000):
    cols = [c for c in cols if c in df.columns]
    if len(cols) < 2:
        return []
    sub = df[cols].copy()
    if len(sub) > limit:
        step = max(1, len(sub) // limit)
        sub = sub.iloc[::step, :]
    sub = sub.replace([np.inf, -np.inf], np.nan).dropna()
    return sub.to_dict(orient='records')


def _metric_pairs(model_info: dict) -> list[dict]:
    model_info = model_info or {}
    baseline = model_info.get('baseline_metrics') or {}
    augmented = model_info.get('model_metrics') or {}
    delta = model_info.get('delta_metrics') or {}
    rows = []
    delta_key_map = {
        'cv_r2_mean': 'delta_cv_r2',
        'cv_mae_mean': 'delta_cv_mae',
        'cv_roc_auc_mean': 'delta_cv_roc_auc',
        'cv_pr_auc_mean': 'delta_cv_pr_auc',
        'cv_balanced_accuracy_mean': 'delta_cv_balanced_accuracy',
        'cv_f1_mean': 'delta_cv_f1',
    }
    for metric in delta_key_map:
        if metric in baseline or metric in augmented:
            rows.append({
                'metric': metric,
                'baseline': baseline.get(metric),
                'augmented': augmented.get(metric),
                'delta': delta.get(delta_key_map[metric]),
            })
    return rows


def build_plot_payload(df: pd.DataFrame, model_info=None, feature_associations: pd.DataFrame | None = None):
    mean_var = _scatter_records(df, ['gene_id', 'mean_expr', 'normalized_dispersion', 'is_hvg', 'stoich_class'], limit=6000)
    expected_obs = _scatter_records(df, ['gene_id', 'stoich_expected_var', 'observed_hvg_signal', 'stoich_class', 'stoich_associated_feature'], limit=6000)
    residual = _scatter_records(df, ['gene_id', 'stoich_excess_var', 'observed_hvg_signal', 'stoich_class'], limit=6000)
    cost_vol = _scatter_records(df, ['gene_id', 'cost_index', 'observed_hvg_signal', 'mean_expr', 'stoich_class', 'stoich_associated_feature'], limit=6000)
    class_bar = (
        df['stoich_class'].value_counts().rename_axis('stoich_class').reset_index(name='count').to_dict(orient='records')
        if 'stoich_class' in df.columns else []
    )
    feature_boxplots = {}
    for feat in [c for c in PLOT_FEATURES if c in df.columns]:
        temp = df[['stoich_class', feat]].copy()
        temp[feat] = pd.to_numeric(temp[feat], errors='coerce')
        feature_boxplots[feat] = []
        for cls, sub in temp.groupby('stoich_class'):
            vals = sub[feat].dropna()
            if vals.empty:
                continue
            feature_boxplots[feat].append({
                'stoich_class': cls,
                'q1': float(vals.quantile(0.25)),
                'median': float(vals.quantile(0.50)),
                'q3': float(vals.quantile(0.75)),
                'min': float(vals.min()),
                'max': float(vals.max()),
            })
    top_tables = {}
    keep_cols = [
        c
        for c in [
            'gene_id',
            'gene_name',
            'stoich_class',
            'stoich_associated_feature',
            'is_hvg',
            'mean_expr',
            'hvg_rank',
            'stoich_excess_var',
            'stoich_explained_fraction',
            'stoich_fit_closeness',
            'cost_volatility_index',
        ]
        if c in df.columns
    ]
    for cls in ['stoich_excess_hvg', 'stoich_explained_hvg', 'stoich_constrained_stable']:
        sort_col = 'stoich_excess_var' if cls != 'stoich_constrained_stable' else 'cost_volatility_index'
        if sort_col not in df.columns:
            continue
        sub = df.loc[df['stoich_class'] == cls, keep_cols].sort_values(sort_col, ascending=False).head(50)
        top_tables[cls] = sub.replace([np.inf, -np.inf], np.nan).fillna('').to_dict(orient='records')
    assoc_top = []
    if feature_associations is not None and not feature_associations.empty:
        assoc_top = feature_associations.head(30).replace([np.inf, -np.inf], np.nan).where(
            pd.notnull(feature_associations.head(30)),
            None,
        ).to_dict(orient='records')
    return {
        'mean_var_scatter': mean_var,
        'expected_observed_scatter': expected_obs,
        'residual_scatter': residual,
        'cost_volatility_bubble': cost_vol,
        'class_bar': class_bar,
        'feature_boxplots': feature_boxplots,
        'top_tables': top_tables,
        'feature_association_top': assoc_top,
        'baseline_vs_augmented': _metric_pairs(model_info or {}),
    }


def build_gene_detail_payload(df: pd.DataFrame, top_n: int = 60):
    sort_cols = [c for c in ['stoich_excess_var', 'cost_volatility_index'] if c in df.columns]
    pieces = []
    if 'stoich_excess_var' in df.columns:
        pieces += [
            df.sort_values('stoich_excess_var', ascending=False).head(top_n),
            df.sort_values('stoich_excess_var', ascending=True).head(max(1, top_n // 2)),
        ]
    if 'cost_volatility_index' in df.columns:
        pieces += [df.sort_values('cost_volatility_index', ascending=False).head(top_n)]
    selected = pd.concat(pieces, axis=0).drop_duplicates(subset=['gene_id']) if pieces else df.head(top_n)
    keep_cols = [c for c in df.columns if c not in {'observed_target_raw', 'stoich_expected_raw'}]
    selected = selected[keep_cols]
    selected = selected.replace([np.inf, -np.inf], np.nan).where(pd.notnull(selected), None)
    rows = selected.to_dict(orient='records')
    by_gene_id = {str(r.get('gene_id')): r for r in rows if r.get('gene_id') is not None}
    return {'n_records': len(rows), 'rows': rows, 'by_gene_id': by_gene_id}
