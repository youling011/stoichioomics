from __future__ import annotations
from pathlib import Path
from typing import Dict, List


def _exists_any(base: Path, names: List[str]) -> str | None:
    for name in names:
        if not name:
            continue
        p = base / name
        if p.exists():
            return name
    return None


def detect_input_bundle(input_dir: str | Path, config: Dict) -> Dict:
    base = Path(input_dir)
    manifest = {
        "input_dir": str(base.resolve()),
        "expression": {"detected_format": None, "files": [], "sample_sheet": None},
        "metadata": {"present": False, "file": None},
        "stoich": {"present": False, "file": None},
        "sequence_mode": {"requested": False, "external_command": None},
        "workspace": config.get('workspace', {}),
        "warnings": [],
    }

    exp_cfg = config.get("expression", {})
    fmt = (exp_cfg.get("format") or "auto").lower()

    if fmt == "auto":
        if _exists_any(base, [exp_cfg.get("file", "")]) and str(exp_cfg.get("file", "")).endswith('.h5ad'):
            fmt = 'h5ad'
        elif _exists_any(base, [exp_cfg.get("matrix_file", "matrix.mtx"), "matrix.mtx", "matrix.mtx.gz"]):
            fmt = 'tenx'
        elif _exists_any(base, [exp_cfg.get("file", "expression.csv"), "expression.csv", "expression.tsv", "matrix.csv", "matrix.tsv"]):
            fmt = 'csv'
        else:
            raise FileNotFoundError(f"Could not auto-detect expression input in {base}")

    manifest["expression"]["detected_format"] = fmt

    if fmt == 'h5ad':
        f = exp_cfg.get("file", "expression.h5ad")
        manifest["expression"]["files"] = [f]
    elif fmt == 'tenx':
        manifest["expression"]["files"] = [
            exp_cfg.get("matrix_file", "matrix.mtx"),
            exp_cfg.get("features_file", "features.tsv"),
            exp_cfg.get("barcodes_file", "barcodes.tsv"),
        ]
    elif fmt in {'csv', 'tsv'}:
        manifest["expression"]["files"] = [exp_cfg.get("file", "expression.csv")]
    elif fmt in {'h5ad_multi', 'tenx_multi'}:
        ss = exp_cfg.get('sample_sheet')
        if not ss:
            raise ValueError(f'expression.sample_sheet is required for {fmt}')
        manifest['expression']['sample_sheet'] = ss
        manifest['expression']['files'] = [ss]
    else:
        raise ValueError(f"Unsupported expression format: {fmt}")

    meta_cfg = config.get("metadata", {}) or {}
    if meta_cfg.get("file"):
        manifest["metadata"] = {"present": True, "file": meta_cfg["file"]}

    stoich_cfg = config.get("stoich", {}) or {}
    if stoich_cfg.get("file"):
        manifest["stoich"] = {"present": True, "file": stoich_cfg["file"]}
    if stoich_cfg.get("external_command"):
        manifest["sequence_mode"] = {"requested": True, "external_command": stoich_cfg.get("external_command")}

    return manifest
