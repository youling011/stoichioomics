from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import pandas as pd
from scipy import sparse

@dataclass
class InternalDataset:
    X: sparse.csr_matrix
    obs: pd.DataFrame
    var: pd.DataFrame
    uns: Dict[str, Any] = field(default_factory=dict)
    source_format: Optional[str] = None
    matrix_semantics: str = "unknown"

    @property
    def n_cells(self) -> int:
        return int(self.X.shape[0])

    @property
    def n_genes(self) -> int:
        return int(self.X.shape[1])
