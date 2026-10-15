from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from collections import defaultdict
from typing import Any

from django.conf import settings

from .registry import field_lookup
from .schemas import FeatureHubError, normalize_omics
from .sources import DatasetSourceResolver, iter_rows


QC_ROOT = Path(settings.BASE_DIR) / "runtime" / "feature_qc"


def _qc_cache_path(fingerprint: str, omics: str, fields: list[str]) -> Path:
    QC_ROOT.mkdir(parents=True, exist_ok=True)
    fields_key = hashlib.sha256("\n".join(fields).encode("utf-8")).hexdigest()[:16]
    return QC_ROOT / f"{fingerprint}.{omics}.{fields_key}.json"


def _iter_indexed_rows(source, fields: list[str]):
    selected = list(dict.fromkeys(fields))
    with source.path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return
        positions = {name: idx for idx, name in enumerate(header)}
        missing = [field for field in selected if field not in positions]
        if missing:
            raise FeatureHubError(f"Field {missing[0]} is not present in {source.species_id}/{source.omics}/core")
        indexed = [(field, positions[field]) for field in selected]
        for values in reader:
            yield {field: values[idx] if idx < len(values) else "" for field, idx in indexed}


def _num(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def qc_report(species_id: str, omics: str, fields: list[str], *, force: bool = False) -> dict[str, Any]:
    omics = normalize_omics(omics)
    if not fields:
        raise FeatureHubError("At least one Core field is required for QC")
    registry = field_lookup(omics, "core")
    selected = [field for field in fields if field in registry]
    if not selected:
        raise FeatureHubError("No selected fields are present in the Core registry")
    invalid = [field for field in fields if field not in registry]
    blocked = [field for field in selected if registry[field]["ml_role"] == "exclude"]
    source = DatasetSourceResolver().resolve(species_id, omics, "core")
    cache = _qc_cache_path(source.fingerprint, omics, selected)
    if cache.exists() and not force:
        with cache.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    missing = {field: 0 for field in selected}
    valid = {field: 0 for field in selected}
    non_finite = {field: 0 for field in selected}
    unique_values: dict[str, set[str]] = {field: set() for field in selected}
    hashes = {field: hashlib.sha256() for field in selected}
    numeric_values: dict[str, list[float]] = {field: [] for field in selected}
    n_rows = 0
    for row in _iter_indexed_rows(source, selected):
        n_rows += 1
        for field in selected:
            text = str(row.get(field, "")).strip()
            if text == "":
                missing[field] += 1
                hashes[field].update(b"<NA>\n")
                continue
            valid[field] += 1
            unique_values[field].add(text)
            hashes[field].update(text.encode("utf-8", errors="replace") + b"\n")
            num = _num(text)
            if num is None:
                non_finite[field] += 1
            else:
                numeric_values[field].append(num)
    constant = [field for field in selected if len(unique_values[field]) <= 1]
    groups_by_hash: dict[str, list[str]] = defaultdict(list)
    for field in selected:
        groups_by_hash[hashes[field].hexdigest()].append(field)
    duplicate_groups = [items for items in groups_by_hash.values() if len(items) > 1]
    composition_groups: dict[str, list[str]] = defaultdict(list)
    for field in selected:
        group = registry[field].get("composition_group") or ""
        if group:
            composition_groups[group].append(field)
    high_corr = []
    for i, left in enumerate(selected):
        lv = numeric_values[left]
        if len(lv) < 3:
            continue
        for right in selected[i + 1:]:
            rv = numeric_values[right]
            if len(rv) != len(lv) or len(rv) < 3:
                continue
            corr = _pearson(lv, rv)
            if corr is not None and abs(corr) >= 0.95:
                high_corr.append({"x": left, "y": right, "pearson": round(corr, 6)})
    result = {
        "species_id": species_id,
        "omics": omics,
        "scope": "core",
        "n_rows": n_rows,
        "selected_features": len(selected),
        "usable_features": len([field for field in selected if field not in constant and field not in blocked]),
        "invalid_fields": invalid,
        "metadata_or_excluded": blocked,
        "constant": constant,
        "exact_duplicate_groups": duplicate_groups,
        "high_correlation_pairs": high_corr[:200],
        "composition_groups": dict(composition_groups),
        "applicability_warnings": [
            {"field": field, "applicability": registry[field].get("applicability"), "zero_semantics": registry[field].get("zero_semantics")}
            for field in selected
            if registry[field].get("applicability") != "all"
        ],
        "missingness": {
            field: {
                "valid_n": valid[field],
                "missing_n": missing[field],
                "missing_rate": round(missing[field] / max(1, n_rows), 6),
                "non_finite_n": non_finite[field],
            }
            for field in selected
        },
        "scale_summary": {field: _scale_summary(numeric_values[field], registry[field]) for field in selected if numeric_values[field]},
        "recommendations": _recommendations(constant, duplicate_groups, composition_groups, high_corr),
        "leakage_policy": "No scaler, imputer, PCA, or supervised selector was fitted. Fit preprocessing inside train folds.",
        "warnings": source.warnings,
        "cache": {"mode": "precomputed_qc", "path": str(cache)},
    }
    try:
        cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return result


def _pearson(x: list[float], y: list[float]) -> float | None:
    mx = sum(x) / len(x)
    my = sum(y) / len(y)
    vx = sum((v - mx) ** 2 for v in x)
    vy = sum((v - my) ** 2 for v in y)
    if vx <= 0 or vy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (vx * vy) ** 0.5


def _scale_summary(values: list[float], meta: dict[str, Any]) -> dict[str, Any]:
    values = sorted(values)
    return {
        "min": values[0],
        "median": values[len(values) // 2],
        "max": values[-1],
        "scaling_hint": meta.get("scaling_hint", "standard"),
        "transform_hint": meta.get("transform_hint", "none"),
    }


def _recommendations(constants: list[str], duplicates: list[list[str]], compositions: dict[str, list[str]], correlations: list[dict[str, Any]]) -> list[str]:
    out = []
    if constants:
        out.append("Review constant fields before modeling; Clean Core can remove them only after user confirmation.")
    if duplicates:
        out.append("Exact duplicate groups detected; keep one representative per group for compact ML matrices.")
    if compositions:
        out.append("Composition fields are constrained; consider drop-one, CLR, or ILR transforms inside the training pipeline.")
    if correlations:
        out.append("Highly correlated pairs are warnings only; do not remove them without checking the downstream model and target.")
    return out or ["No blocking QC issue detected for the selected Core features."]

