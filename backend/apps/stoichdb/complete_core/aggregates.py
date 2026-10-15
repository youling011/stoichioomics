from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

from . import METHOD_VERSION
from .contracts import all_contract_fields_for_omics, optional_full_fields_for_omics, required_core_fields_for_omics
from .datasource import CompleteCoreDataSource


def safe_num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "na", "none", "null", "inf", "-inf"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def percentile(sorted_values: list[float], ratio: float) -> float:
    if not sorted_values:
        return 0.0
    pos = max(0.0, min(1.0, ratio)) * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    weight = pos - lo
    return float(sorted_values[lo] * (1.0 - weight) + sorted_values[hi] * weight)


def distribution_stats(values: Iterable[float]) -> dict[str, float]:
    clean = sorted(float(v) for v in values if safe_num(v) is not None)
    if not clean:
        return {"min": 0.0, "p05": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p95": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0}
    mean = sum(clean) / len(clean)
    std = (sum((v - mean) ** 2 for v in clean) / max(1, len(clean))) ** 0.5
    return {
        "min": round(clean[0], 6),
        "p05": round(percentile(clean, 0.05), 6),
        "p25": round(percentile(clean, 0.25), 6),
        "p50": round(percentile(clean, 0.5), 6),
        "p75": round(percentile(clean, 0.75), 6),
        "p95": round(percentile(clean, 0.95), 6),
        "max": round(clean[-1], 6),
        "mean": round(mean, 6),
        "std": round(std, 6),
    }


def histogram(values: Iterable[float], bins: int = 42) -> dict[str, Any]:
    clean = [float(v) for v in values if safe_num(v) is not None]
    if not clean:
        return {"centers": [], "counts": [], "bin_edges": [], "bin_n": [], "n": 0, "n_valid": 0}
    lo = min(clean)
    hi = max(clean)
    if lo == hi:
        return {"centers": [round(lo, 6)], "counts": [len(clean)], "bin_edges": [round(lo, 6), round(hi, 6)], "bin_n": [len(clean)], "n": len(clean), "n_valid": len(clean)}
    width = (hi - lo) / bins
    counts = [0] * bins
    for value in clean:
        idx = min(bins - 1, max(0, int((value - lo) / width)))
        counts[idx] += 1
    edges = [round(lo + i * width, 6) for i in range(bins + 1)]
    centers = [round((edges[i] + edges[i + 1]) / 2.0, 6) for i in range(bins)]
    return {"centers": centers, "counts": counts, "bin_edges": edges, "bin_n": counts[:], "n": len(clean), "n_valid": len(clean)}


def complete_core_field_summary(species_id: str, omics: str, field: str) -> dict[str, Any]:
    source = CompleteCoreDataSource(species_id, omics)
    rows, meta = source.rows(fields=[field], optional_full_fields=[field])
    values_raw = [row.get(field) for row in rows]
    numeric = [float(v) for v in (safe_num(item) for item in values_raw) if v is not None]
    valid_n = sum(1 for item in values_raw if item not in (None, ""))
    missing_n = max(0, len(rows) - valid_n)
    ranked = [row for row in rows if safe_num(row.get(field)) is not None]
    ranked.sort(key=lambda row: safe_num(row.get(field)) or 0.0, reverse=True)
    return {
        "species_id": species_id,
        "omics": omics,
        "scope": "core",
        "compute_mode": "complete_core",
        "method_version": METHOD_VERSION,
        "field": field,
        "field_meta": {"field": field, "label": field.replace("_", " ")},
        "n_total": len(rows),
        "n_source_rows": len(rows),
        "valid_n": len(numeric),
        "missing_n": missing_n,
        "missing_rate": round(missing_n / max(1, len(rows)), 6),
        "summary": distribution_stats(numeric),
        "distribution": histogram(numeric, bins=42),
        "top_rows": ranked[:12],
        "bottom_rows": list(reversed(ranked[-12:])) if ranked else [],
        "method_metadata": {
            "aggregation_scope": "all_valid_core_rows",
            "sampling_policy": "none",
            **meta,
        },
    }


def complete_core_scatter_payload(species_id: str, omics: str, x_field: str, y_field: str, sample: int = 5000) -> dict[str, Any]:
    sample = max(200, min(5000, int(sample or 5000)))
    source = CompleteCoreDataSource(species_id, omics)
    rows, meta = source.rows(fields=[x_field, y_field], optional_full_fields=[x_field, y_field])
    pair_rows: list[dict[str, Any]] = []
    xs: list[float] = []
    ys: list[float] = []
    for row in rows:
        x = safe_num(row.get(x_field))
        y = safe_num(row.get(y_field))
        if x is None or y is None:
            continue
        point = {
            "entity_id": row.get("entity_id") or row.get("gene_id") or row.get("transcript_id") or row.get("protein_id"),
            "gene_id": row.get("gene_id") or row.get("canonical_gene_id") or "",
            "gene_name": row.get("gene_name") or row.get("gene_symbol") or row.get("description") or "",
            x_field: round(float(x), 6),
            y_field: round(float(y), 6),
        }
        pair_rows.append(point)
        xs.append(float(x))
        ys.append(float(y))
    total = len(pair_rows)
    display = deterministic_sample(pair_rows, sample)
    pearson = correlation(xs, ys)
    slope, intercept = linear_fit(xs, ys)
    return {
        "species_id": species_id,
        "omics": omics,
        "scope": "core",
        "compute_mode": "complete_core",
        "method_version": METHOD_VERSION,
        "x_field": x_field,
        "y_field": y_field,
        "x_meta": {"field": x_field, "label": x_field.replace("_", " ")},
        "y_meta": {"field": y_field, "label": y_field.replace("_", " ")},
        "n_total": total,
        "n_points": len(display),
        "n_source_rows": len(rows),
        "n_pair_valid": total,
        "display_n": len(display),
        "points": display,
        "statistics": {
            "pearson_r": pearson,
            "spearman_r": spearman(xs, ys),
            "slope": slope,
            "intercept": intercept,
        },
        "method_metadata": {
            "aggregation_scope": "all_pairwise_valid_core_rows",
            "sampling_policy": "deterministic_even_stride_display_sample" if total > len(display) else "none",
            "n_source_rows": len(rows),
            "n_pair_valid": total,
            "display_n": len(display),
            **meta,
        },
    }


def complete_core_summary_overlay(species_id: str, omics: str) -> dict[str, Any]:
    fields = all_contract_fields_for_omics(omics)
    source = CompleteCoreDataSource(species_id, omics)
    rows, meta = source.rows(fields=fields, optional_full_fields=optional_full_fields_for_omics(omics))
    if not rows:
        return {"summary": {}, "analysis": {}, "source": meta}
    header = set(source.header("core")) | set(source.header("full"))
    used_fields = [field for field in fields if field in header or any(field in row for row in rows[:50])]
    feature_cards = {}
    distributions = {}
    missingness = []
    for field in used_fields:
        values_raw = [row.get(field) for row in rows]
        values = [float(v) for v in (safe_num(item) for item in values_raw) if v is not None]
        if values:
            card = distribution_stats(values)
            card.update({"n_valid": len(values), "missing_rate": round(1.0 - len(values) / max(1, len(rows)), 6)})
            feature_cards[field] = card
            distributions[field] = histogram(values, bins=42)
        missing_n = max(0, len(rows) - len(values))
        missingness.append({"field": field, "valid_n": len(values), "missing_n": missing_n, "missing_rate": round(missing_n / max(1, len(rows)), 6)})
    corr_fields = [field for field in used_fields if field in feature_cards][:40]
    matrix, edges = correlation_matrix(rows, corr_fields)
    score_field = next((field for field in corr_fields if field in feature_cards), "")
    ranked = []
    if score_field:
        for row in rows:
            value = safe_num(row.get(score_field))
            if value is None:
                continue
            ranked.append({
                "entity_id": row.get("entity_id") or row.get("gene_id") or row.get("transcript_id") or row.get("protein_id"),
                "gene_id": row.get("gene_id") or row.get("canonical_gene_id") or "",
                "gene_name": row.get("gene_name") or row.get("gene_symbol") or "",
                score_field: round(float(value), 6),
                "value": round(float(value), 6),
            })
        ranked.sort(key=lambda item: item["value"], reverse=True)
    summary = {
        "compute_mode": "complete_core",
        "result_view": "complete_core",
        "precomputed_from_real_rows": True,
        "row_count": len(rows),
        "source_scope": "core",
        "feature_cards": feature_cards,
        "distributions": distributions,
        "missingness": missingness,
        "correlation_matrix": matrix,
        "correlation_matrices": {"pearson": matrix},
        "coupling_edges": edges[:50],
        "top_entities": {"top": ranked[:24], "bottom": list(reversed(ranked[-24:])) if ranked else []},
        "method_metadata": {
            "complete_core_v2": {
                "method_version": METHOD_VERSION,
                "aggregation_scope": "all_valid_core_rows_for_contract_fields",
                "used_fields": used_fields,
                "field_n_used": len(used_fields),
                **meta,
            }
        },
    }
    analysis = {
        "compute_mode": "complete_core",
        "scope": "core",
        "outliers": {"high": ranked[:24], "low": list(reversed(ranked[-24:])) if ranked else [], "multivariate": []},
        "coupling_edges": edges[:50],
        "method_metadata": {"complete_core_v2": summary["method_metadata"]["complete_core_v2"]},
    }
    return {"summary": summary, "analysis": analysis, "source": summary["method_metadata"]["complete_core_v2"]}


def deterministic_sample(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    stride = max(1, math.ceil(len(rows) / limit))
    return rows[::stride][:limit]


def correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(ys) < 2 or len(xs) != len(ys):
        return None
    if np is not None:
        try:
            arr_x = np.asarray(xs, dtype=float)
            arr_y = np.asarray(ys, dtype=float)
            if float(np.nanstd(arr_x)) == 0.0 or float(np.nanstd(arr_y)) == 0.0:
                return None
            value = float(np.corrcoef(arr_x, arr_y)[0, 1])
            return round(value, 6) if not math.isnan(value) else None
        except Exception:
            pass
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = sum((x - mx) ** 2 for x in xs) ** 0.5
    den_y = sum((y - my) ** 2 for y in ys) ** 0.5
    if not den_x or not den_y:
        return None
    return round(num / (den_x * den_y), 6)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) > 200000:
        return None
    return correlation(rank(xs), rank(ys))


def rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    for idx, original in enumerate(order, start=1):
        ranks[original] = float(idx)
    return ranks


def linear_fit(xs: list[float], ys: list[float]) -> tuple[float | None, float | None]:
    if len(xs) < 2 or len(xs) != len(ys):
        return None, None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if not den:
        return None, None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return round(slope, 6), round(my - slope * mx, 6)


def correlation_matrix(rows: list[dict[str, Any]], fields: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    labels = fields[:]
    values = []
    details = []
    edges = []
    for yi, fy in enumerate(labels):
        for xi, fx in enumerate(labels):
            xs: list[float] = []
            ys: list[float] = []
            for row in rows:
                x = safe_num(row.get(fx))
                y = safe_num(row.get(fy))
                if x is None or y is None:
                    continue
                xs.append(float(x))
                ys.append(float(y))
            r = correlation(xs, ys)
            cell = 0.0 if r is None else r
            values.append([xi, yi, cell])
            details.append({"x": fx, "y": fy, "r": cell, "pairwise_n": len(xs), "p_value": None, "fdr": None})
            if xi > yi and r is not None:
                edges.append({"source": fx, "target": fy, "weight": r, "n": len(xs), "p_value": None, "fdr": None, "method": "pearson"})
    edges.sort(key=lambda item: abs(float(item.get("weight") or 0.0)), reverse=True)
    return {"x_labels": labels, "y_labels": labels, "values": values, "details": details, "method": "pearson", "method_version": METHOD_VERSION}, edges
