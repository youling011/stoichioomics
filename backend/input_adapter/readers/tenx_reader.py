from __future__ import annotations
from pathlib import Path
import gzip
import pandas as pd
from scipy import io, sparse
from ..schemas import InternalDataset
from ..normalize import normalize_obs_columns, normalize_var_columns


def _open_text(path: Path):
    if str(path).endswith('.gz'):
        return gzip.open(path, 'rt')
    return open(path, 'r', encoding='utf-8')


def _resolve(base: Path, name: str, fallbacks):
    candidates = [name, *fallbacks]
    for c in candidates:
        p = base / c
        if p.exists():
            return p
    raise FileNotFoundError(f'Could not find any of {candidates} in {base}')


def read_tenx(input_dir: str | Path, matrix_file='matrix.mtx', features_file='features.tsv', barcodes_file='barcodes.tsv', value_semantics='raw_counts') -> InternalDataset:
    base = Path(input_dir)
    mtx = _resolve(base, matrix_file, ['matrix.mtx.gz','matrix.mtx'])
    feat = _resolve(base, features_file, ['features.tsv.gz','features.tsv','genes.tsv.gz','genes.tsv'])
    bc = _resolve(base, barcodes_file, ['barcodes.tsv.gz','barcodes.tsv'])

    X = io.mmread(str(mtx)).tocsr().T  # cells x genes
    with _open_text(bc) as fh:
        cell_ids = [line.strip().split('	')[0] for line in fh if line.strip()]
    with _open_text(feat) as fh:
        rows = [line.strip().split('	') for line in fh if line.strip()]
    if rows and len(rows[0]) >= 3:
        var = pd.DataFrame({'gene_id':[r[0] for r in rows], 'gene_name':[r[1] for r in rows], 'feature_type':[r[2] for r in rows]})
    elif rows and len(rows[0]) >= 2:
        var = pd.DataFrame({'gene_id':[r[0] for r in rows], 'gene_name':[r[1] for r in rows]})
    else:
        var = pd.DataFrame({'gene_id':[r[0] for r in rows]})
    obs = pd.DataFrame({'cell_id': cell_ids})
    obs = normalize_obs_columns(obs)
    var = normalize_var_columns(var)
    uns = {'source_format':'tenx', 'matrix_semantics': value_semantics, 'n_cells': int(X.shape[0]), 'n_genes': int(X.shape[1])}
    return InternalDataset(X=X, obs=obs, var=var, uns=uns, source_format='tenx', matrix_semantics=value_semantics)
