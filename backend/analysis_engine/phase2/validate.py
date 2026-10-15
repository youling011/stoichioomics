
from __future__ import annotations
import pandas as pd
from .schemas import CORE_MODEL_FEATURES, EXTENDED_MODEL_FEATURES


def choose_feature_columns(df: pd.DataFrame, feature_set: str = 'core'):
    feature_set = feature_set.lower()
    candidates = CORE_MODEL_FEATURES if feature_set == 'core' else EXTENDED_MODEL_FEATURES
    present = [c for c in candidates if c in df.columns]
    if len(present) < 5:
        raise ValueError(f'Too few model features available in baseline CSV: found {len(present)} columns -> {present}')
    return present


def choose_confounder_columns(df: pd.DataFrame, explicit_columns=None):
    if explicit_columns:
        chosen = [c for c in explicit_columns if c in df.columns]
        if chosen:
            return chosen

    fallback = [
        'mean_expr',
        'pct_cells_detected',
        'n_cells_detected',
        'dropout_rate',
        'length_nt',
        'gc_content',
        'mean_nonzero_expr',
    ]
    return [c for c in fallback if c in df.columns]


def validate_required_columns(df: pd.DataFrame, target_col: str, hvg_flag_col: str):
    missing = [c for c in ['gene_id', target_col, hvg_flag_col] if c not in df.columns]
    if missing:
        raise ValueError(f'Baseline CSV missing required columns: {missing}')
    dup_gene = int(df['gene_id'].astype(str).duplicated().sum())
    if dup_gene > 0:
        raise ValueError(f'Baseline CSV contains duplicated gene_id rows: {dup_gene}')
    has_mean_expr = 'mean_expr' in df.columns
    return {
        'n_rows': int(df.shape[0]),
        'n_columns': int(df.shape[1]),
        'target_col': target_col,
        'hvg_flag_col': hvg_flag_col,
        'has_mean_expr': bool(has_mean_expr),
        'n_missing_target': int(df[target_col].isna().sum()),
        'n_missing_hvg_flag': int(df[hvg_flag_col].isna().sum()),
    }
