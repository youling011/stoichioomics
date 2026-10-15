from __future__ import annotations
from pathlib import Path
from typing import Dict, Iterable, List
import json
import numpy as np
import pandas as pd

CORE_STOICH_FIELDS = [
    'gc_content','length_nt','nt_entropy','at_skew','gc_skew','c_per_nt','n_per_nt','p_per_nt'
]
RECOMMENDED_METADATA_FIELDS = [
    'sample_id','batch','condition','timepoint','cluster','cell_type','donor','perturbation','pseudotime'
]

def read_json(path: Path) -> Dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json(obj: Dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def safe_float(x, default=None):
    try:
        if x is None:
            return default
        v = float(x)
        if np.isnan(v):
            return default
        return v
    except Exception:
        return default


def fraction(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def sample_nonzero_values(X, max_values: int = 50000) -> np.ndarray:
    data = X.data
    if data.size == 0:
        return np.array([], dtype=float)
    if data.size <= max_values:
        return np.asarray(data)
    idx = np.linspace(0, data.size - 1, num=max_values, dtype=int)
    return np.asarray(data[idx])


def is_integer_like(values: np.ndarray, atol: float = 1e-8) -> float:
    if values.size == 0:
        return 1.0
    return float(np.mean(np.isclose(values, np.round(values), atol=atol)))


def non_null_fraction(series: pd.Series) -> float:
    return fraction(int(series.notna().sum()), int(series.shape[0]))


def top_value_counts(series: pd.Series, k: int = 10) -> Dict[str, int]:
    vc = series.astype(str).value_counts(dropna=False).head(k)
    return {str(k_): int(v) for k_, v in vc.items()}


def infer_presence(df: pd.DataFrame, fields: Iterable[str]) -> Dict[str, bool]:
    return {f: (f in df.columns) for f in fields}
