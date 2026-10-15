
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Tuple
import json
import numpy as np
import pandas as pd
from scipy import sparse

from backend.analysis_engine.common import ExpressionDataset


def write_json(obj: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def subset_dataset(dataset: ExpressionDataset, mask: np.ndarray) -> ExpressionDataset:
    mask = np.asarray(mask).astype(bool)
    sub_obs = dataset.obs.loc[mask].reset_index(drop=True)
    return ExpressionDataset(
        matrix=dataset.matrix[mask, :].tocsr(),
        gene_ids=list(dataset.gene_ids),
        gene_names=list(dataset.gene_names),
        cell_ids=sub_obs['cell_id'].astype(str).tolist() if 'cell_id' in sub_obs.columns else [str(i) for i in range(sub_obs.shape[0])],
        obs=sub_obs,
        uns=dict(dataset.uns),
    )


def filter_low_quality_genes(dataset: ExpressionDataset, min_cells: int = 3, min_counts: int = 1) -> Tuple[ExpressionDataset, Dict[str, int]]:
    matrix = dataset.matrix.tocsc(copy=False)
    nonzero_cells = np.diff(matrix.indptr)
    total_counts = np.asarray(matrix.sum(axis=0)).ravel()
    keep_mask = (nonzero_cells >= int(min_cells)) & (total_counts >= int(min_counts))
    filtered = ExpressionDataset(
        matrix=dataset.matrix[:, keep_mask].tocsr(),
        gene_ids=[g for g, k in zip(dataset.gene_ids, keep_mask) if k],
        gene_names=[g for g, k in zip(dataset.gene_names, keep_mask) if k],
        cell_ids=list(dataset.cell_ids),
        obs=dataset.obs.copy(),
        uns=dict(dataset.uns),
    )
    report = {
        'n_genes_before_filter': int(dataset.n_genes),
        'n_genes_after_filter': int(filtered.n_genes),
        'n_genes_removed': int(dataset.n_genes - filtered.n_genes),
    }
    return filtered, report


def merge_var_features(df: pd.DataFrame, var_df: pd.DataFrame) -> pd.DataFrame:
    var_df = var_df.copy()
    if 'gene_id' in getattr(var_df.index, 'names', []):
        var_df = var_df.reset_index(drop=True)
    if 'gene_id' not in var_df.columns:
        var_df.insert(0, 'gene_id', var_df.index.astype(str))
    var_df['gene_id'] = var_df['gene_id'].astype(str)
    drop_cols = [c for c in ['gene_name'] if c in var_df.columns and c in df.columns]
    if drop_cols:
        var_df = var_df.drop(columns=drop_cols)
    validate = 'one_to_one' if not df['gene_id'].astype(str).duplicated().any() else 'many_to_one'
    return df.merge(var_df, on='gene_id', how='left', validate=validate)


def summarize_obs_fields(obs: pd.DataFrame, fields: List[str]) -> Dict[str, Dict[str, int]]:
    out = {}
    for field in fields:
        if field in obs.columns:
            vc = obs[field].astype(str).value_counts(dropna=False).to_dict()
            out[field] = {str(k): int(v) for k, v in vc.items()}
    return out


def order_categories(series: pd.Series) -> List[str]:
    uniq = series.dropna().astype(str).unique().tolist()
    def sort_key(x: str):
        import re
        m = re.match(r'^(.*?)(\d+(?:\.\d+)?)h$', x.lower())
        if m:
            try:
                return (0, float(m.group(2)), x)
            except Exception:
                pass
        try:
            return (0, float(x), x)
        except Exception:
            return (1, x)
    return sorted(uniq, key=sort_key)
