from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

import pandas as pd


def _read_table(path: Path, nrows: int | None = None) -> pd.DataFrame:
    sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    return pd.read_csv(path, sep=sep, nrows=nrows)


def inspect_stoich_readiness(stoich_path: str | Path | None, expression_gene_ids: Iterable[str] | None = None) -> Dict[str, Any]:
    if not stoich_path:
        return {
            "status": "missing",
            "phase2_ready": False,
            "reason_code": "no_stoich_table",
            "message": "No stoich feature table was provided; Phase 2 will be skipped.",
        }
    p = Path(stoich_path)
    try:
        df = _read_table(p)
    except Exception as exc:
        return {
            "status": "invalid",
            "phase2_ready": False,
            "reason_code": "stoich_read_failed",
            "message": str(exc),
        }
    if "gene_id" not in df.columns:
        df = df.rename(columns={df.columns[0]: "gene_id"}) if len(df.columns) else df
    if "gene_id" not in df.columns:
        return {
            "status": "invalid",
            "phase2_ready": False,
            "reason_code": "missing_gene_id",
            "message": "Stoich table does not contain a gene_id column.",
        }
    numeric_features = [
        c for c in df.columns
        if c != "gene_id" and pd.to_numeric(df[c], errors="coerce").notna().mean() >= 0.5
    ]
    expr_ids = set(str(x) for x in expression_gene_ids) if expression_gene_ids is not None else set()
    stoich_ids = set(df["gene_id"].astype(str))
    matched = len(expr_ids.intersection(stoich_ids)) if expr_ids else 0
    match_rate = (matched / max(len(expr_ids), 1)) if expr_ids else None
    min_rate = 0.75
    ready = len(numeric_features) >= 5 and (match_rate is None or match_rate >= min_rate)
    reason = None
    if len(numeric_features) < 5:
        reason = "too_few_numeric_stoich_features"
    elif match_rate is not None and match_rate < min_rate:
        reason = "low_gene_id_match_rate"
    return {
        "status": "ready" if ready else "not_ready",
        "phase2_ready": bool(ready),
        "source_file": str(p),
        "n_rows": int(df.shape[0]),
        "numeric_feature_count": int(len(numeric_features)),
        "numeric_features": numeric_features[:50],
        "matched_gene_count": int(matched) if expr_ids else None,
        "expression_gene_count": int(len(expr_ids)) if expr_ids else None,
        "match_rate": float(match_rate) if match_rate is not None else None,
        "minimum_match_rate": min_rate,
        "reason_code": reason,
        "message": "Stoich table is ready for Phase 2." if ready else "Stoich table is not sufficient for Phase 2.",
    }
