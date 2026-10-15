
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any
import pandas as pd
from scipy import sparse

from backend.validation.schemas import StandardizedBundle

@dataclass
class ExpressionDataset:
    matrix: sparse.csr_matrix  # cells x genes
    gene_ids: List[str]
    gene_names: List[str]
    cell_ids: List[str]
    obs: pd.DataFrame
    uns: Dict[str, Any]

    @property
    def n_cells(self) -> int:
        return int(self.matrix.shape[0])

    @property
    def n_genes(self) -> int:
        return int(self.matrix.shape[1])


def bundle_to_expression_dataset(bundle: StandardizedBundle) -> ExpressionDataset:
    var = bundle.var.copy()
    if 'gene_id' not in var.columns:
        var = var.copy()
        var.insert(0, 'gene_id', var.index.astype(str))
    if 'gene_name' in var.columns:
        gene_names = var['gene_name'].fillna(var['gene_id']).astype(str).tolist()
    elif 'gene_symbol' in var.columns:
        gene_names = var['gene_symbol'].fillna(var['gene_id']).astype(str).tolist()
    else:
        gene_names = var['gene_id'].astype(str).tolist()
    obs = bundle.obs.copy()
    if 'cell_id' not in obs.columns:
        obs = obs.copy()
        obs.insert(0, 'cell_id', obs.index.astype(str))
    return ExpressionDataset(
        matrix=bundle.X.tocsr(copy=False),
        gene_ids=var['gene_id'].astype(str).tolist(),
        gene_names=gene_names,
        cell_ids=obs['cell_id'].astype(str).tolist(),
        obs=obs,
        uns=bundle.uns.copy(),
    )
