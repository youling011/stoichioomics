from __future__ import annotations
from pathlib import Path
import pandas as pd
from scipy import sparse
from ..schemas import InternalDataset
from ..normalize import normalize_obs_columns, normalize_var_columns


def read_matrix_csv(path: str | Path, sep: str | None = None, orientation: str = 'auto', value_semantics: str = 'unknown', gene_id_col: str = 'gene_id') -> InternalDataset:
    path = Path(path)
    if sep is None:
        sep = '	' if path.suffix.lower() in {'.tsv','.txt'} else ','
    df = pd.read_csv(path, sep=sep)
    if gene_id_col not in df.columns:
        # maybe first column is genes
        gene_id_col = df.columns[0]
    df[gene_id_col] = df[gene_id_col].astype(str)
    first = gene_id_col

    def looks_like_gene_ids(vals):
        vals = [str(v) for v in vals[: min(10, len(vals))]]
        hits = sum(any(ch.isalpha() for ch in v) for v in vals)
        return hits >= max(3, len(vals)//2)

    if orientation == 'auto':
        row_gene_like = looks_like_gene_ids(df[first].tolist())
        col_gene_like = looks_like_gene_ids([c for c in df.columns[1:]])
        orientation = 'gene_by_cell' if row_gene_like or not col_gene_like else 'cell_by_gene'

    if orientation == 'gene_by_cell':
        gene_ids = df[first].astype(str).tolist()
        mat = df.drop(columns=[first]).apply(pd.to_numeric, errors='coerce').fillna(0.0)
        cell_ids = [str(c) for c in mat.columns]
        X = sparse.csr_matrix(mat.to_numpy().T)  # cells x genes
        obs = pd.DataFrame({'cell_id': cell_ids})
        var = pd.DataFrame({'gene_id': gene_ids})
    elif orientation == 'cell_by_gene':
        cell_ids = df[first].astype(str).tolist()
        mat = df.drop(columns=[first])
        gene_ids = [str(c) for c in mat.columns]
        X = sparse.csr_matrix(mat.apply(pd.to_numeric, errors='coerce').fillna(0.0).to_numpy())
        obs = pd.DataFrame({'cell_id': cell_ids})
        var = pd.DataFrame({'gene_id': gene_ids})
    else:
        raise ValueError(f'Unsupported orientation: {orientation}')

    obs = normalize_obs_columns(obs)
    var = normalize_var_columns(var)
    uns = {'source_format':'csv_matrix', 'matrix_semantics': value_semantics, 'n_cells': int(X.shape[0]), 'n_genes': int(X.shape[1]), 'orientation_detected': orientation}
    return InternalDataset(X=X, obs=obs, var=var, uns=uns, source_format='csv_matrix', matrix_semantics=value_semantics)
