from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from backend.analysis_engine.common import ExpressionDataset
from backend.analysis_engine.phase1.hvg_core import run_hvg_baseline


def run_internal_backend(dataset: ExpressionDataset, config: Dict[str, Any]) -> Dict[str, Any]:
    df, summary = run_hvg_baseline(
        dataset,
        method=config.get("hvg_method", "seurat_v3"),
        n_top_genes=int(config.get("n_top_genes", 2000)),
        n_bins=int(config.get("n_bins", 20)),
        loess_span=float(config.get("loess_span", 0.3)),
    )
    df = df.copy()
    df["hvg_backend"] = "internal"
    return {
        "backend": "internal",
        "status": "success",
        "result": df,
        "summary": summary,
        "error": None,
    }


def coerce_existing_baseline(df: pd.DataFrame, config: Dict[str, Any]) -> Dict[str, Any]:
    work = df.copy()
    work["hvg_backend"] = "internal"
    return {
        "backend": "internal",
        "status": "success",
        "result": work,
        "summary": {
            "n_genes": int(work.shape[0]),
            "n_hvgs": int(work["is_hvg"].fillna(False).astype(bool).sum()) if "is_hvg" in work.columns else None,
            "method": config.get("hvg_method", "seurat_v3"),
            "n_top_genes": int(config.get("n_top_genes", 2000)),
            "loess_span": float(config.get("loess_span", 0.3)),
        },
        "error": None,
    }
