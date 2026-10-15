from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd


def _classify(values: np.ndarray) -> tuple[str, str, list[str]]:
    if values.size == 0:
        return "unknown", "low", ["no_numeric_values"]
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return "unknown", "low", ["no_finite_values"]
    min_v = float(np.min(finite))
    max_v = float(np.max(finite))
    mean_v = float(np.mean(finite))
    integer_fraction = float(np.mean(np.isclose(finite, np.round(finite), atol=1e-8)))
    negative_fraction = float(np.mean(finite < 0))
    zero_fraction = float(np.mean(finite == 0))
    evidence = [
        f"min={min_v:.4g}",
        f"max={max_v:.4g}",
        f"mean={mean_v:.4g}",
        f"integer_fraction={integer_fraction:.4f}",
        f"negative_fraction={negative_fraction:.4f}",
        f"zero_fraction={zero_fraction:.4f}",
    ]
    if negative_fraction > 0.01:
        return "scaled_zscore", "high", evidence + ["negative_values_present"]
    if integer_fraction >= 0.98 and min_v >= 0 and max_v > 20:
        return "raw_counts", "high", evidence + ["integer_nonnegative_large_range"]
    if min_v >= 0 and max_v <= 30 and integer_fraction < 0.95 and zero_fraction > 0.05:
        return "log_normalized", "medium", evidence + ["noninteger_nonnegative_with_zeros"]
    if min_v >= 0:
        return "normalized_counts", "medium", evidence + ["nonnegative_numeric_matrix"]
    return "unknown", "low", evidence


def detect_tabular_matrix_semantics(path: str | Path, max_rows: int = 80, max_cols: int = 80) -> Dict[str, Any]:
    p = Path(path)
    sep = "\t" if p.suffix.lower() in {".tsv", ".txt"} else ","
    try:
        df = pd.read_csv(p, sep=sep, nrows=max_rows)
        values = []
        for col in df.columns[:max_cols]:
            vals = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)
            if vals.size:
                values.append(vals)
        arr = np.concatenate(values) if values else np.array([], dtype=float)
        semantics, confidence, evidence = _classify(arr)
        return {
            "matrix_semantics": semantics,
            "confidence": confidence,
            "need_user_confirmation": confidence == "low",
            "evidence": evidence,
        }
    except Exception as exc:
        return {"matrix_semantics": "unknown", "confidence": "low", "need_user_confirmation": True, "error": str(exc), "evidence": []}
