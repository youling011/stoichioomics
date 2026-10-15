from __future__ import annotations
from typing import Dict, Any
import numpy as np

from .schemas import StandardizedBundle
from .utils import fraction, sample_nonzero_values


def build_matrix_check_report(bundle: StandardizedBundle) -> Dict[str, Any]:
    X = bundle.X.tocsr()
    n_cells, n_genes = X.shape
    nnz = int(X.nnz)
    zero_only_cells = int((X.getnnz(axis=1) == 0).sum())
    zero_only_genes = int((X.getnnz(axis=0) == 0).sum())

    sampled = sample_nonzero_values(X)
    matrix_min = float(sampled.min()) if sampled.size else 0.0
    matrix_max = float(sampled.max()) if sampled.size else 0.0
    matrix_mean_nonzero = float(sampled.mean()) if sampled.size else 0.0
    matrix_median_nonzero = float(np.median(sampled)) if sampled.size else 0.0

    report = {
        'shape': {'n_cells': int(n_cells), 'n_genes': int(n_genes)},
        'nnz': nnz,
        'density': fraction(nnz, n_cells * n_genes),
        'sparse': True,
        'zero_only_cells': zero_only_cells,
        'zero_only_genes': zero_only_genes,
        'zero_only_cell_fraction': fraction(zero_only_cells, n_cells),
        'zero_only_gene_fraction': fraction(zero_only_genes, n_genes),
        'min_nonzero_value': matrix_min,
        'max_nonzero_value': matrix_max,
        'mean_nonzero_value': matrix_mean_nonzero,
        'median_nonzero_value': matrix_median_nonzero,
        'has_negative_values': bool(X.data.min() < 0) if nnz > 0 else False,
    }
    report['ready_for_hvg'] = bool(not report['has_negative_values'] and report['zero_only_gene_fraction'] < 0.5)
    return report
