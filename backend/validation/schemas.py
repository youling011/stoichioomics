from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import pandas as pd
from scipy import sparse

@dataclass
class StandardizedBundle:
    X: sparse.csr_matrix
    obs: pd.DataFrame
    var: pd.DataFrame
    uns: Dict[str, Any]
    input_manifest: Dict[str, Any]
    phase1_validation: Dict[str, Any]
    run_log: Dict[str, Any]
    input_dir: Path
    raw_stoich: Optional[pd.DataFrame] = None

    @property
    def n_cells(self) -> int:
        return int(self.X.shape[0])

    @property
    def n_genes(self) -> int:
        return int(self.X.shape[1])

    def to_basic_summary(self) -> Dict[str, Any]:
        return {
            'n_cells': self.n_cells,
            'n_genes': self.n_genes,
            'matrix_semantics': self.uns.get('matrix_semantics', self.phase1_validation.get('matrix_semantics', 'unknown')),
            'source_format': self.uns.get('source_format', self.phase1_validation.get('source_format', 'unknown')),
            'stoich_columns_present': [c for c in self.var.columns if c in {'gc_content','length_nt','nt_entropy','at_skew','gc_skew','c_per_nt','n_per_nt','p_per_nt'}],
        }
