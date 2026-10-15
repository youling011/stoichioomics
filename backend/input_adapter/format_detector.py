from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


EXPRESSION_HINTS = ("expression", "matrix", "counts", "count", "expr", "rna")
METADATA_HINTS = ("metadata", "meta", "obs", "cell_annotation", "cellinfo", "sample")
STOICH_HINTS = ("stoich", "feature", "features", "composition", "gene_features")


def _score_name(path: Path, hints: tuple[str, ...]) -> int:
    name = path.name.lower()
    return sum(1 for hint in hints if hint in name)


def _confidence(score: int, fallback: bool = False) -> str:
    if score >= 2:
        return "high"
    if score == 1:
        return "medium"
    return "low" if fallback else "medium"


def detect_uploaded_files(raw_dir: str | Path) -> Dict[str, Any]:
    base = Path(raw_dir)
    files = [p for p in base.iterdir() if p.is_file()] if base.exists() else []
    report: Dict[str, Any] = {
        "raw_dir": str(base.resolve()),
        "files": [{"name": p.name, "suffix": p.suffix.lower(), "size": int(p.stat().st_size)} for p in files],
        "expression": {"status": "missing", "detected_format": None, "file": None, "confidence": "low", "evidence": []},
        "metadata": {"status": "missing", "file": None, "confidence": "low", "evidence": []},
        "stoich": {"status": "missing", "file": None, "confidence": "low", "evidence": []},
        "warnings": [],
    }
    if not files:
        report["warnings"].append({"code": "NO_FILES_UPLOADED", "severity": "error", "message": "No uploaded files were found."})
        return report

    h5ad = [p for p in files if p.suffix.lower() == ".h5ad"]
    if h5ad:
        chosen = sorted(h5ad, key=lambda p: (-_score_name(p, EXPRESSION_HINTS), p.name))[0]
        report["expression"] = {
            "status": "ready",
            "detected_format": "h5ad",
            "file": chosen.name,
            "confidence": _confidence(_score_name(chosen, EXPRESSION_HINTS), fallback=True),
            "evidence": ["h5ad_extension"],
        }
    else:
        names = {p.name.lower() for p in files}
        has_tenx = any(n in names for n in {"matrix.mtx", "matrix.mtx.gz"}) and any(
            n in names for n in {"features.tsv", "features.tsv.gz", "genes.tsv", "genes.tsv.gz"}
        ) and any(n in names for n in {"barcodes.tsv", "barcodes.tsv.gz"})
        if has_tenx:
            report["expression"] = {
                "status": "ready",
                "detected_format": "tenx",
                "file": "matrix.mtx",
                "confidence": "high",
                "evidence": ["10x_matrix_features_barcodes_detected"],
            }
        else:
            tabular = [p for p in files if p.suffix.lower() in {".csv", ".tsv", ".txt"}]
            if tabular:
                ranked = sorted(tabular, key=lambda p: (-_score_name(p, EXPRESSION_HINTS), _score_name(p, METADATA_HINTS) + _score_name(p, STOICH_HINTS), p.name))
                chosen = ranked[0]
                report["expression"] = {
                    "status": "ready",
                    "detected_format": "csv" if chosen.suffix.lower() == ".csv" else "tsv",
                    "file": chosen.name,
                    "confidence": _confidence(_score_name(chosen, EXPRESSION_HINTS), fallback=(len(tabular) == 1)),
                    "evidence": ["tabular_expression_candidate", f"suffix={chosen.suffix.lower()}"],
                }

    tabular = [p for p in files if p.suffix.lower() in {".csv", ".tsv", ".txt"}]
    expression_file = report["expression"].get("file")
    meta_candidates = [p for p in tabular if p.name != expression_file and _score_name(p, METADATA_HINTS) > 0]
    if meta_candidates:
        chosen = sorted(meta_candidates, key=lambda p: (-_score_name(p, METADATA_HINTS), p.name))[0]
        report["metadata"] = {
            "status": "ready",
            "file": chosen.name,
            "confidence": _confidence(_score_name(chosen, METADATA_HINTS)),
            "evidence": ["metadata_filename_hint"],
        }
    stoich_candidates = [p for p in tabular if p.name != expression_file and _score_name(p, STOICH_HINTS) > 0]
    if stoich_candidates:
        chosen = sorted(stoich_candidates, key=lambda p: (-_score_name(p, STOICH_HINTS), p.name))[0]
        report["stoich"] = {
            "status": "ready",
            "file": chosen.name,
            "confidence": _confidence(_score_name(chosen, STOICH_HINTS)),
            "evidence": ["stoich_filename_hint"],
        }
    if report["expression"]["status"] != "ready":
        report["warnings"].append({"code": "NO_EXPRESSION_MATRIX", "severity": "error", "message": "Could not identify an expression matrix."})
    return report
