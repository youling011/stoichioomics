from __future__ import annotations

from typing import Any, Dict, Iterable, List

import numpy as np
import pandas as pd


def _method_row(backend_result: Dict[str, Any]) -> Dict[str, Any]:
    df = backend_result.get("result")
    status = backend_result.get("status")
    row = {
        "backend": backend_result.get("backend"),
        "status": status,
        "error": backend_result.get("error"),
    }
    summary = backend_result.get("summary") or {}
    for key, value in summary.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            row[key] = value
    if isinstance(df, pd.DataFrame) and not df.empty:
        row["n_genes"] = int(df.shape[0])
        row["n_hvgs"] = int(df["is_hvg"].fillna(False).astype(bool).sum()) if "is_hvg" in df.columns else None
        row["median_hvg_rank"] = float(pd.to_numeric(df.get("hvg_rank"), errors="coerce").median())
    return row


def build_method_benchmark(backend_results: Iterable[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([_method_row(result) for result in backend_results])


def build_hvg_consensus(backend_results: List[Dict[str, Any]], n_top_genes: int) -> pd.DataFrame:
    frames = []
    for result in backend_results:
        df = result.get("result")
        if result.get("status") != "success" or not isinstance(df, pd.DataFrame) or df.empty:
            continue
        keep = df[["gene_id", "gene_name", "is_hvg", "hvg_rank", "hvg_score"]].copy()
        keep["backend"] = result.get("backend")
        keep["is_hvg"] = keep["is_hvg"].fillna(False).astype(bool)
        keep["hvg_rank"] = pd.to_numeric(keep["hvg_rank"], errors="coerce")
        keep["hvg_score"] = pd.to_numeric(keep["hvg_score"], errors="coerce")
        frames.append(keep)
    if not frames:
        return pd.DataFrame(columns=[
            "gene_id", "gene_name", "consensus_hvg_vote_count", "consensus_backend_count",
            "consensus_vote_fraction", "mean_rank", "min_rank", "consensus_rank", "is_consensus_hvg",
        ])
    combined = pd.concat(frames, ignore_index=True)
    grouped = combined.groupby("gene_id", dropna=False)
    consensus = grouped.agg(
        gene_name=("gene_name", "first"),
        consensus_hvg_vote_count=("is_hvg", "sum"),
        consensus_backend_count=("backend", "nunique"),
        mean_rank=("hvg_rank", "mean"),
        min_rank=("hvg_rank", "min"),
        mean_hvg_score=("hvg_score", "mean"),
    ).reset_index()
    consensus["consensus_vote_fraction"] = consensus["consensus_hvg_vote_count"] / consensus["consensus_backend_count"].clip(lower=1)
    consensus = consensus.sort_values(
        ["consensus_hvg_vote_count", "mean_rank", "mean_hvg_score", "gene_id"],
        ascending=[False, True, False, True],
    ).reset_index(drop=True)
    consensus["consensus_rank"] = np.arange(1, consensus.shape[0] + 1)
    consensus["is_consensus_hvg"] = consensus["consensus_rank"] <= min(int(n_top_genes), consensus.shape[0])
    return consensus


def backend_report(backend_results: List[Dict[str, Any]], consensus: pd.DataFrame) -> Dict[str, Any]:
    return {
        "backend_count": int(len(backend_results)),
        "successful_backend_count": int(sum(1 for r in backend_results if r.get("status") == "success")),
        "backends": [
            {
                "backend": r.get("backend"),
                "status": r.get("status"),
                "summary": r.get("summary") or {},
                "error": r.get("error"),
            }
            for r in backend_results
        ],
        "consensus": {
            "n_genes": int(consensus.shape[0]),
            "n_consensus_hvgs": int(consensus["is_consensus_hvg"].fillna(False).astype(bool).sum()) if "is_consensus_hvg" in consensus else 0,
        },
    }
