from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pandas as pd


FIELD_SYNONYMS = {
    "cell_id": ["cell_id", "cell", "barcode", "cellid", "cell_barcode", "obs_name"],
    "sample_id": ["sample_id", "sample", "sampleid", "library", "sample_name", "run"],
    "batch": ["batch", "batch_id", "experiment", "library_prep", "lane", "platform"],
    "condition": ["condition", "treatment", "group", "status", "phenotype", "case_control", "stimulus"],
    "timepoint": ["timepoint", "time", "time_point", "day", "hour", "stage", "phase"],
    "cluster": ["cluster", "leiden", "louvain", "seurat_clusters", "cluster_id"],
    "cell_type": ["cell_type", "celltype", "annotation", "predicted_cell_type", "major_celltype"],
    "donor": ["donor", "subject", "patient", "individual", "animal_id"],
    "perturbation": ["perturbation", "perturb", "drug", "knockdown", "ko", "stimulation"],
    "pseudotime": ["pseudotime", "dpt_pseudotime", "monocle_pseudotime", "slingshot", "latent_time"],
}


def _norm(value: str) -> str:
    return "".join(ch for ch in str(value).strip().lower().replace("-", "_").replace(" ", "_") if ch.isalnum() or ch == "_")


def automap_metadata_fields(metadata_path: str | Path | None) -> Dict[str, Any]:
    if not metadata_path:
        return {
            "status": "missing",
            "standard_fields": {field: None for field in FIELD_SYNONYMS},
            "detected_fields": [],
            "unavailable_fields": list(FIELD_SYNONYMS),
            "warnings": [{"code": "NO_METADATA", "severity": "info", "message": "No metadata file was provided."}],
        }
    p = Path(metadata_path)
    sep = "\t" if p.suffix.lower() in {".tsv", ".txt"} else ","
    try:
        df = pd.read_csv(p, sep=sep, nrows=200)
    except Exception as exc:
        return {
            "status": "invalid",
            "standard_fields": {field: None for field in FIELD_SYNONYMS},
            "detected_fields": [],
            "unavailable_fields": list(FIELD_SYNONYMS),
            "warnings": [{"code": "METADATA_READ_FAILED", "severity": "warning", "message": str(exc)}],
        }
    norm_to_original = {_norm(c): c for c in df.columns}
    mapping: Dict[str, Any] = {}
    details = {}
    for field, synonyms in FIELD_SYNONYMS.items():
        matched = None
        matched_by = None
        for syn in synonyms:
            key = _norm(syn)
            if key in norm_to_original:
                matched = norm_to_original[key]
                matched_by = syn
                break
        mapping[field] = matched
        if matched is not None:
            series = df[matched]
            details[field] = {
                "source_column": matched,
                "matched_synonym": matched_by,
                "non_null_fraction": float(series.notna().mean()),
                "n_unique_sampled": int(series.nunique(dropna=True)),
            }
    detected = [field for field, col in mapping.items() if col]
    unavailable = [field for field, col in mapping.items() if not col]
    status = "ready" if detected else "unmapped"
    if detected and unavailable:
        status = "partial"
    return {
        "status": status,
        "source_file": str(p),
        "raw_columns": [str(c) for c in df.columns],
        "standard_fields": mapping,
        "field_details": details,
        "detected_fields": detected,
        "unavailable_fields": unavailable,
        "warnings": [] if detected else [{"code": "NO_RECOGNIZED_METADATA_FIELDS", "severity": "info", "message": "Metadata was provided but no standard fields were recognized."}],
    }
