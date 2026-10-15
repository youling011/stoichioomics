from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from backend.analysis_engine.common import ExpressionDataset


def _scanpy_flavor(method: str) -> str:
    m = (method or "seurat_v3").lower()
    if m in {"cell_ranger"}:
        return "cell_ranger"
    if m in {"seurat", "dispersion"}:
        return "seurat"
    return "seurat_v3"


def run_scanpy_backend(dataset: ExpressionDataset, config: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(config.get("enable_scanpy_backend", False)):
        return {
            "backend": "scanpy",
            "status": "disabled",
            "result": None,
            "summary": {
                "n_genes": int(dataset.n_genes),
                "reason": "Scanpy backend is available as an optional adapter but is disabled by default to avoid slow runtime imports in interactive jobs.",
            },
            "error": None,
        }
    try:
        import anndata as ad
        import scanpy as sc
    except Exception as exc:
        return {"backend": "scanpy", "status": "unavailable", "result": None, "summary": {}, "error": str(exc)}

    method = str(config.get("scanpy_hvg_method") or config.get("hvg_method") or "seurat_v3")
    flavor = _scanpy_flavor(method)
    n_top = min(int(config.get("n_top_genes", 2000)), dataset.n_genes)
    try:
        var = pd.DataFrame(index=pd.Index(dataset.gene_ids, name="gene_id"))
        obs = dataset.obs.copy()
        if "cell_id" in obs.columns:
            obs.index = obs["cell_id"].astype(str)
        adata = ad.AnnData(X=dataset.matrix.tocsr(), obs=obs, var=var)
        kwargs: Dict[str, Any] = {"flavor": flavor, "n_top_genes": n_top, "inplace": False}
        if flavor in {"seurat", "cell_ranger"}:
            kwargs["n_bins"] = int(config.get("n_bins", 20))
        if flavor == "seurat_v3":
            kwargs["span"] = float(config.get("loess_span", 0.3))
        hv = sc.pp.highly_variable_genes(adata, **kwargs)
        score_col = "variances_norm" if "variances_norm" in hv.columns else "dispersions_norm" if "dispersions_norm" in hv.columns else None
        score = pd.to_numeric(hv[score_col], errors="coerce") if score_col else pd.Series(np.nan, index=hv.index)
        order = np.argsort(np.nan_to_num(score.to_numpy(dtype=float), nan=-np.inf))[::-1]
        ranks = np.empty_like(order)
        ranks[order] = np.arange(1, len(order) + 1)
        out = pd.DataFrame({
            "gene_id": dataset.gene_ids,
            "gene_name": dataset.gene_names,
            "scanpy_mean": pd.to_numeric(hv.get("means"), errors="coerce") if "means" in hv else np.nan,
            "scanpy_score": score.to_numpy(dtype=float),
            "hvg_score": score.to_numpy(dtype=float),
            "hvg_rank": ranks,
            "is_hvg": pd.Series(hv.get("highly_variable", ranks <= n_top)).fillna(False).astype(bool).to_numpy(),
            "hvg_method": f"scanpy_{flavor}",
            "hvg_score_semantics": score_col or "scanpy_highly_variable_rank",
            "hvg_backend": "scanpy",
        })
        return {
            "backend": "scanpy",
            "status": "success",
            "result": out,
            "summary": {"method": flavor, "n_hvgs": int(out["is_hvg"].sum()), "n_top_genes": int(n_top), "loess_span": float(config.get("loess_span", 0.3))},
            "error": None,
        }
    except Exception as exc:
        return {"backend": "scanpy", "status": "failed", "result": None, "summary": {"method": flavor}, "error": str(exc)}
