from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd


GENE_ID_HINTS = {"gene_id", "gene", "genes", "gene_name", "symbol", "feature", "features"}
CELL_ID_HINTS = {"cell_id", "cell", "barcode", "barcodes", "cell_barcode"}


def detect_tabular_orientation(path: str | Path, max_rows: int = 40, max_cols: int = 40) -> Dict[str, Any]:
    p = Path(path)
    sep = "\t" if p.suffix.lower() in {".tsv", ".txt"} else ","
    try:
        df = pd.read_csv(p, sep=sep, nrows=max_rows)
    except Exception as exc:
        return {"orientation": "auto", "confidence": "low", "need_user_confirmation": True, "error": str(exc), "evidence": []}
    cols = [str(c).strip().lower() for c in df.columns]
    first_col = cols[0] if cols else ""
    n_rows_sample = int(df.shape[0])
    n_cols = int(df.shape[1])
    evidence = [f"sample_rows={n_rows_sample}", f"columns={n_cols}", f"first_col={first_col}"]
    if first_col in GENE_ID_HINTS or any(h in first_col for h in ("gene", "feature")):
        return {"orientation": "gene_by_cell", "confidence": "high", "need_user_confirmation": False, "evidence": evidence + ["first_column_gene_id_like"]}
    if first_col in CELL_ID_HINTS or any(h in first_col for h in ("cell", "barcode")):
        return {"orientation": "cell_by_gene", "confidence": "high", "need_user_confirmation": False, "evidence": evidence + ["first_column_cell_id_like"]}
    numeric_cols = 0
    for col in df.columns[1:max_cols]:
        if pd.to_numeric(df[col], errors="coerce").notna().mean() >= 0.8:
            numeric_cols += 1
    if numeric_cols >= max(2, min(10, n_cols - 1)):
        return {"orientation": "gene_by_cell", "confidence": "medium", "need_user_confirmation": False, "evidence": evidence + ["many_numeric_columns_after_first"]}
    return {"orientation": "auto", "confidence": "low", "need_user_confirmation": True, "evidence": evidence + ["ambiguous_tabular_shape"]}
