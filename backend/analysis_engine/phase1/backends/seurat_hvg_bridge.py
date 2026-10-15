from __future__ import annotations

from shutil import which
from typing import Any, Dict

from backend.analysis_engine.common import ExpressionDataset


def run_seurat_backend(dataset: ExpressionDataset, config: Dict[str, Any]) -> Dict[str, Any]:
    rscript = which("Rscript")
    if not rscript:
        return {
            "backend": "seurat_r",
            "status": "unavailable",
            "result": None,
            "summary": {"n_genes": int(dataset.n_genes), "reason": "Rscript not found"},
            "error": "Rscript executable is not available on PATH.",
        }
    return {
        "backend": "seurat_r",
        "status": "unimplemented_bridge",
        "result": None,
        "summary": {
            "n_genes": int(dataset.n_genes),
            "reason": "R bridge is discoverable but not invoked by default to keep the Python pipeline deterministic.",
            "rscript": rscript,
        },
        "error": None,
    }
