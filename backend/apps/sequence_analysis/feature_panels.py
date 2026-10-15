from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .feature_panel_registry import get_core_fields, get_core_panel_registry


IDENTITY_COLUMNS = [
    "entity_id", "gene_id", "gene_name", "gene_symbol", "transcript_id", "protein_id",
    "sample_id", "group", "condition", "species_id", "seqid", "strand", "source_db",
    "biotype", "transcript_biotype", "file_name",
]


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    if isinstance(value, tuple):
        return [_safe_json(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _numeric_values(df: pd.DataFrame, field: str) -> pd.Series:
    if field not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[field], errors="coerce").replace([np.inf, -np.inf], np.nan)


def _field_stats(df: pd.DataFrame, field: str) -> dict[str, Any]:
    if field not in df.columns:
        return {
            "field": field,
            "present": False,
            "n": int(len(df)),
            "valid_n": 0,
            "missing_n": int(len(df)),
            "missing_rate": 1.0 if len(df) else 0.0,
            "min": None,
            "q1": None,
            "median": None,
            "mean": None,
            "q3": None,
            "max": None,
            "std": None,
        }
    values = _numeric_values(df, field)
    valid = values.dropna()
    if valid.empty:
        return {
            "field": field,
            "present": True,
            "n": int(len(df)),
            "valid_n": 0,
            "missing_n": int(len(df)),
            "missing_rate": 1.0 if len(df) else 0.0,
            "min": None,
            "q1": None,
            "median": None,
            "mean": None,
            "q3": None,
            "max": None,
            "std": None,
        }
    return {
        "field": field,
        "present": True,
        "n": int(len(df)),
        "valid_n": int(valid.shape[0]),
        "missing_n": int(len(df) - valid.shape[0]),
        "missing_rate": float(1 - valid.shape[0] / max(1, len(df))),
        "min": float(valid.min()),
        "q1": float(valid.quantile(0.25)),
        "median": float(valid.median()),
        "mean": float(valid.mean()),
        "q3": float(valid.quantile(0.75)),
        "max": float(valid.max()),
        "std": None if valid.shape[0] < 2 else float(valid.std()),
    }


def _row_identity(row: pd.Series) -> dict[str, Any]:
    return {col: row.get(col) for col in IDENTITY_COLUMNS if col in row.index}


def _top_low(df: pd.DataFrame, field: str, n: int = 10) -> dict[str, list[dict[str, Any]]]:
    values = _numeric_values(df, field)
    if values.empty or values.dropna().empty:
        return {"top10": [], "low10": []}
    work = df.copy()
    work["_value"] = values
    work = work.dropna(subset=["_value"])

    def rows(part: pd.DataFrame, rank_type: str) -> list[dict[str, Any]]:
        output = []
        for rank, (_, row) in enumerate(part.iterrows(), start=1):
            item = {
                "rank_type": rank_type,
                "rank": rank,
                "field": field,
                "value": _safe_json(row.get("_value")),
            }
            item.update(_row_identity(row))
            output.append(item)
        return output

    return {
        "top10": rows(work.sort_values("_value", ascending=False).head(n), "Top10"),
        "low10": rows(work.sort_values("_value", ascending=True).head(n), "Low10"),
    }


def _histogram(values: pd.Series, bins: int = 18) -> dict[str, Any]:
    valid = values.dropna().astype(float)
    if valid.empty:
        return {"bins": [], "counts": []}
    if valid.nunique() == 1:
        value = float(valid.iloc[0])
        return {"bins": [value], "counts": [int(len(valid))]}
    counts, edges = np.histogram(valid.to_numpy(), bins=bins)
    centers = ((edges[:-1] + edges[1:]) / 2).tolist()
    return {"bins": [float(item) for item in centers], "counts": [int(item) for item in counts.tolist()]}


def _group_boxplots(df: pd.DataFrame, fields: list[str]) -> list[dict[str, Any]]:
    rows = []
    group_col = "group" if "group" in df.columns else None
    groups = df.groupby(group_col, dropna=False) if group_col else [("all", df)]
    for field in fields:
        if field not in df.columns:
            continue
        for group, part in groups:
            stats = _field_stats(part, field)
            if stats["valid_n"] == 0:
                continue
            rows.append({
                "field": field,
                "group": str(group),
                "n": stats["n"],
                "valid_n": stats["valid_n"],
                "missing_rate": stats["missing_rate"],
                "min": stats["min"],
                "q1": stats["q1"],
                "median": stats["median"],
                "q3": stats["q3"],
                "max": stats["max"],
            })
    return rows


def _composition_matrix(panel: dict[str, Any], stats: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    matrix = panel.get("matrix") or {}
    kind = matrix.get("type")
    prefix = matrix.get("field_prefix", "")
    output = []
    if kind == "dinucleotide":
        alphabet = matrix.get("alphabet") or []
        for row_base in alphabet:
            for col_base in alphabet:
                field = f"{prefix}_{row_base}{col_base}_freq"
                output.append({
                    "row": row_base,
                    "column": col_base,
                    "field": field,
                    "median": stats.get(field, {}).get("median"),
                    "mean": stats.get(field, {}).get("mean"),
                    "valid_n": stats.get(field, {}).get("valid_n", 0),
                })
    elif kind == "codon":
        alphabet = matrix.get("alphabet") or []
        for first in alphabet:
            for second in alphabet:
                for third in alphabet:
                    codon = f"{first}{second}{third}"
                    field = f"{prefix}_{codon}_freq"
                    output.append({
                        "first": first,
                        "second": second,
                        "third": third,
                        "codon": codon,
                        "field": field,
                        "median": stats.get(field, {}).get("median"),
                        "mean": stats.get(field, {}).get("mean"),
                        "valid_n": stats.get(field, {}).get("valid_n", 0),
                    })
    elif kind == "amino_acid":
        suffix = matrix.get("suffix", "_freq")
        alphabet = matrix.get("alphabet") or []
        for aa in alphabet:
            field = f"{prefix}_{aa}{suffix}" if aa != "other" else "AA_other_pct"
            output.append({
                "residue": aa,
                "field": field,
                "median": stats.get(field, {}).get("median"),
                "mean": stats.get(field, {}).get("mean"),
                "valid_n": stats.get(field, {}).get("valid_n", 0),
            })
    return output


def _categorical_counts(df: pd.DataFrame, fields: list[str]) -> list[dict[str, Any]]:
    rows = []
    for field in fields:
        if field not in df.columns:
            continue
        if pd.api.types.is_numeric_dtype(df[field]):
            continue
        for value, count in df[field].fillna("missing").astype(str).value_counts().head(30).items():
            rows.append({"field": field, "value": value, "count": int(count)})
    return rows


def _filter_df(df: pd.DataFrame, filters: dict[str, str] | None) -> pd.DataFrame:
    work = df.copy()
    for field, value in (filters or {}).items():
        if not value or field not in work.columns:
            continue
        values = {item.strip() for item in str(value).split(",") if item.strip()}
        if not values:
            continue
        work = work[work[field].astype(str).isin(values)]
    return work


def build_core_feature_panels(df: pd.DataFrame, omics_type: str, filters: dict[str, str] | None = None) -> dict[str, Any]:
    omics = str(omics_type or "").lower()
    registry = get_core_panel_registry(omics)
    filtered = _filter_df(df, filters)
    expected_fields = get_core_fields(omics)
    assigned_unique = list(dict.fromkeys(expected_fields))
    present_fields = [field for field in assigned_unique if field in filtered.columns]
    missing_fields = [field for field in assigned_unique if field not in filtered.columns]
    duplicate_fields = sorted({field for field in expected_fields if expected_fields.count(field) > 1})
    panels = []
    for panel in registry:
        fields = list(panel.get("fields") or [])
        stats = {field: _field_stats(filtered, field) for field in fields}
        numeric_fields = [field for field in fields if stats[field]["present"] and stats[field]["valid_n"] > 0]
        panel_payload = {
            **panel,
            "fields_present": [field for field in fields if field in filtered.columns],
            "missing_fields": [field for field in fields if field not in filtered.columns],
            "field_coverage": {
                "field_total": len(fields),
                "field_present": sum(1 for field in fields if field in filtered.columns),
                "missing_count": sum(1 for field in fields if field not in filtered.columns),
            },
            "field_stats": stats,
            "chart_data": {
                "group_boxplots": _group_boxplots(filtered, numeric_fields),
                "histograms": {field: _histogram(_numeric_values(filtered, field)) for field in numeric_fields[:24]},
                "composition_matrix": _composition_matrix(panel, stats),
                "categorical_counts": _categorical_counts(filtered, fields),
            },
            "top_low": {field: _top_low(filtered, field) for field in numeric_fields},
            "method_note": "median/IQR; missing and non-finite values excluded; Top/Low uses raw values.",
            "warnings": [],
        }
        if not numeric_fields and panel.get("unit") != "metadata":
            panel_payload["warnings"].append("No numeric core fields with valid values are available for this panel.")
        panels.append(panel_payload)

    return _safe_json({
        "omics_type": omics,
        "feature_set": "core",
        "row_count": int(len(filtered)),
        "unfiltered_row_count": int(len(df)),
        "filters": filters or {},
        "core_field_total": len(assigned_unique),
        "core_field_assigned": len(assigned_unique),
        "core_field_present": len(present_fields),
        "core_field_missing_count": len(missing_fields),
        "core_field_coverage": 1.0 if not assigned_unique else len(present_fields) / len(assigned_unique),
        "registry_coverage": {
            "expected_total": len(assigned_unique),
            "assigned_total": len(assigned_unique),
            "assigned_unique_total": len(assigned_unique),
            "duplicate_fields": duplicate_fields,
            "is_registry_complete": len(assigned_unique) == {"genome": 160, "transcriptome": 86, "proteome": 63}.get(omics, len(assigned_unique)),
        },
        "missing_fields": missing_fields,
        "present_fields": present_fields,
        "filter_options": {
            field: sorted([str(item) for item in df[field].dropna().astype(str).unique()])[:200]
            for field in ["group", "sample_id", "species_id", "condition", "seqid", "strand", "source_db", "biotype", "transcript_biotype"]
            if field in df.columns
        },
        "panels": panels,
        "method_metadata": {
            "method": "core_feature_panel_registry_v1",
            "source": "uploaded sequence core feature table",
            "aggregation": "median/IQR by default",
            "top_low": "raw field value ranking after current filters",
            "evidence_level": "descriptive/exploratory",
        },
    })
