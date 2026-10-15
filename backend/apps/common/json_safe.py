from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _safe_scalar(v: Any) -> Any:
    if v is None:
        return None

    if isinstance(v, Path):
        return str(v)

    if isinstance(v, (np.integer,)):
        return int(v)

    if isinstance(v, (np.floating, float)):
        x = float(v)
        if not math.isfinite(x):
            return None
        return x

    if isinstance(v, (np.bool_,)):
        return bool(v)

    if isinstance(v, pd.Timestamp):
        return v.isoformat()

    try:
        if pd.isna(v):
            return None
    except Exception:
        pass

    return v


def sanitize_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]

    if isinstance(obj, pd.DataFrame):
        safe_df = obj.replace([np.inf, -np.inf], np.nan)
        records = safe_df.to_dict(orient="records")
        return [{k: sanitize_for_json(v) for k, v in rec.items()} for rec in records]

    if isinstance(obj, pd.Series):
        safe_ser = obj.replace([np.inf, -np.inf], np.nan)
        raw = safe_ser.to_dict()
        return {str(k): sanitize_for_json(v) for k, v in raw.items()}

    if isinstance(obj, np.ndarray):
        return [sanitize_for_json(v) for v in obj.tolist()]

    return _safe_scalar(obj)