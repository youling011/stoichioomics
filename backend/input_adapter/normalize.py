from __future__ import annotations
from typing import Dict, Iterable
import pandas as pd

CELL_SYNONYMS = {
    'barcode': 'cell_id',
    'cell': 'cell_id',
    'cellid': 'cell_id',
    'cell_id': 'cell_id',
    'sample': 'sample_id',
    'sampleid': 'sample_id',
    'sample_id': 'sample_id',
    'batch': 'batch',
    'condition': 'condition',
    'time': 'timepoint',
    'timepoint': 'timepoint',
    'cluster': 'cluster',
    'celltype': 'cell_type',
    'cell_type': 'cell_type',
    'donor': 'donor',
    'perturbation': 'perturbation',
    'pseudotime': 'pseudotime',
}

GENE_SYNONYMS = {
    'gene': 'gene_id',
    'geneid': 'gene_id',
    'gene_id': 'gene_id',
    'gene_name': 'gene_name',
    'symbol': 'gene_name',
    'feature_type': 'feature_type',
    'featuretype': 'feature_type',
    'gc_content': 'gc_content',
    'gc': 'gc_content',
    'sequence_length': 'length_nt',
    'length_bp': 'length_nt',
    'length_nt': 'length_nt',
    'nt_entropy': 'nt_entropy',
    'sequence_entropy': 'nt_entropy',
    'at_skew': 'at_skew',
    'gc_skew': 'gc_skew',
    'c_per_nt': 'c_per_nt',
    'n_per_nt': 'n_per_nt',
    'p_per_nt': 'p_per_nt',
}


def _norm_name(s: str) -> str:
    return s.strip().lower().replace(' ', '_').replace('-', '_')


def normalize_obs_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for c in df.columns:
        nc = _norm_name(str(c))
        rename[c] = CELL_SYNONYMS.get(nc, nc)
    out = df.rename(columns=rename).copy()
    if 'cell_id' not in out.columns:
        out.insert(0, 'cell_id', out.index.astype(str))
    out.index = out['cell_id'].astype(str)
    return out


def normalize_var_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for c in df.columns:
        nc = _norm_name(str(c))
        rename[c] = GENE_SYNONYMS.get(nc, nc)
    out = df.rename(columns=rename).copy()
    if 'gene_id' not in out.columns:
        out.insert(0, 'gene_id', out.index.astype(str))
    out.index = out['gene_id'].astype(str)
    return out


def coerce_numeric_columns(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df
