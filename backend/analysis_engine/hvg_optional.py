from __future__ import annotations

from importlib.util import find_spec
from shutil import which
from typing import Any, Dict


PYTHON_PACKAGES = {
    "anndata": "standardized.h5ad export and Scanpy backend",
    "scanpy": "Scanpy HVG backend",
    "skmisc": "Scanpy Seurat v3 LOESS acceleration",
    "statsmodels": "multiple testing and statistical diagnostics",
    "mygene": "external gene identifier annotation",
    "gprofiler": "g:Profiler enrichment",
    "gseapy": "GSEA prerank enrichment",
    "goatools": "GO ORA enrichment",
    "networkx": "local gene network/module summaries",
    "community": "Louvain community detection",
    "shap": "model interpretability diagnostics",
    "plotly": "interactive plot payload support",
    "kaleido": "static Plotly export",
}


def optional_dependency_report() -> Dict[str, Any]:
    packages = {}
    for module, purpose in PYTHON_PACKAGES.items():
        packages[module] = {
            "available": find_spec(module) is not None,
            "purpose": purpose,
        }
    external = {
        "Rscript": {
            "available": which("Rscript") is not None,
            "purpose": "optional Seurat R backend bridge",
        }
    }
    status = "ready" if all(v["available"] for v in packages.values()) else "degraded"
    return {
        "status": status,
        "python_packages": packages,
        "external_tools": external,
    }


def has_module(module: str) -> bool:
    return find_spec(module) is not None
