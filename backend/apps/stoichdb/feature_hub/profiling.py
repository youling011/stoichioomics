from __future__ import annotations
from .cache_identity import read_cached,write_cache,calculation_lock
from backend.apps.stoichdb.feature_sources import io as feature_io

import csv
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any

from django.conf import settings

from .schemas import FeatureHubNotFound, normalize_omics, normalize_scope
from .sources import DatasetSourceResolver, iter_rows, read_header


PROFILE_ROOT = Path(getattr(settings, "STOICH_FEATURE_PROFILE_ROOT", Path(settings.BASE_DIR) / "runtime" / "feature_profiles"))


def _num(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    idx = (len(values) - 1) * q
    lower = int(math.floor(idx))
    upper = int(math.ceil(idx))
    if lower == upper:
        return values[lower]
    return values[lower] * (upper - idx) + values[upper] * (idx - lower)


def _histogram(values: list[float], bins: int = 32) -> dict[str, Any]:
    if not values:
        return {"bins": [], "counts": [], "n": 0}
    lo, hi = min(values), max(values)
    if lo == hi:
        return {"bins": [lo], "counts": [len(values)], "n": len(values)}
    step = (hi - lo) / bins
    counts = [0 for _ in range(bins)]
    for value in values:
        idx = min(bins - 1, int((value - lo) / step))
        counts[idx] += 1
    centers = [lo + step * (i + 0.5) for i in range(bins)]
    return {"bins": centers, "counts": counts, "n": len(values)}


def _iter_indexed_rows(source, fields: list[str]):
    selected = list(dict.fromkeys(fields))
    with feature_io.open_source(source.path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return
        positions = {name: idx for idx, name in enumerate(header)}
        missing = [field for field in selected if field not in positions]
        if missing:
            raise FeatureHubNotFound(f"Field {missing[0]} is not present in {source.species_id}/{source.omics}/{source.scope}")
        indexed = [(field, positions[field]) for field in selected]
        for values in reader:
            yield {field: values[idx] if idx < len(values) else "" for field, idx in indexed}


def _cache_path(fingerprint: str, field: str) -> Path:
    PROFILE_ROOT.mkdir(parents=True, exist_ok=True)
    return PROFILE_ROOT / f"{fingerprint}.{field}.json"


def _profile_result(source, target: str, values: list[float], valid_n: int, missing_n: int, ranked: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_values = sorted(values)
    avg = mean(values) if values else None
    std = (sum((v - avg) ** 2 for v in values) / max(1, len(values))) ** 0.5 if avg is not None else None
    return {
        "species_id": source.species_id,
        "omics": source.omics,
        "scope": source.scope,
        "field": target,
        "source_sha": source.fingerprint,
        "n_rows": valid_n + missing_n,
        "valid_n": valid_n,
        "missing_n": missing_n,
        "missing_rate": round(missing_n / max(1, valid_n + missing_n), 6),
        "numeric_n": len(values),
        "summary": {
            "min": min(values) if values else None,
            "p01": _percentile(sorted_values, 0.01),
            "p25": _percentile(sorted_values, 0.25),
            "median": _percentile(sorted_values, 0.5),
            "p75": _percentile(sorted_values, 0.75),
            "p99": _percentile(sorted_values, 0.99),
            "max": max(values) if values else None,
            "mean": avg,
            "std": std,
            "zero_rate": sum(1 for value in values if value == 0) / max(1, len(values)) if values else None,
            "is_constant": len(set(values)) <= 1 if values else False,
        },
        "distribution": _histogram(values),
        "top_rows": sorted(ranked, key=lambda item: item["value"], reverse=True)[:12],
        "bottom_rows": sorted(ranked, key=lambda item: item["value"])[:12],
        "warnings": source.warnings,
    }


@calculation_lock(lambda: PROFILE_ROOT)
def precompute_field_profiles(species_id: str, omics: str, scope: str, fields: list[str], *, force: bool = False) -> dict[str, dict[str, Any]]:
    source = DatasetSourceResolver().resolve(species_id, normalize_omics(omics), normalize_scope(scope))
    targets = [str(field or "").strip() for field in dict.fromkeys(fields) if str(field or "").strip()]
    cached: dict[str, dict[str, Any]] = {}
    pending: list[str] = []
    for target in targets:
        cache = _cache_path(source.fingerprint, target)
        result=read_cached('feature_profiles',cache,source,[f'{key}.{target}.json' for key in source.legacy_fingerprints],'profile',field=target) if not force else None
        if result is not None:cached[target]=result
        else:pending.append(target)
    if not pending:
        return cached
    with __import__('backend.apps.common.task_execution',fromlist=['heavy_compute_slot']).heavy_compute_slot():

        values: dict[str, list[float]] = {field: [] for field in pending}
        valid: dict[str, int] = {field: 0 for field in pending}
        missing: dict[str, int] = {field: 0 for field in pending}
        ranked: dict[str, list[dict[str, Any]]] = {field: [] for field in pending}
        header = set(read_header(source))
        selected = [field for field in ["gene_id", "transcript_id", "protein_id", *pending] if field in header]
        for row in _iter_indexed_rows(source, selected):
            entity_id = row.get("gene_id") or row.get("transcript_id") or row.get("protein_id") or ""
            for target in pending:
                raw = row.get(target)
                if raw is None or str(raw).strip() == "":
                    missing[target] += 1
                    continue
                valid[target] += 1
                num = _num(raw)
                if num is not None:
                    values[target].append(num)
                    ranked[target].append({"entity_id": entity_id, "value": num})
        for target in pending:
            result = _profile_result(source, target, values[target], valid[target], missing[target], ranked[target])
            try:
                write_cache(_cache_path(source.fingerprint,target),result)
            except OSError:
                pass
            cached[target] = result
        return cached


@calculation_lock(lambda: PROFILE_ROOT)
def field_profile(species_id: str, omics: str, scope: str, field: str, *, force: bool = False) -> dict[str, Any]:
    source = DatasetSourceResolver().resolve(species_id, normalize_omics(omics), normalize_scope(scope))
    target = str(field or "").strip()
    if not target:
        raise FeatureHubNotFound("Missing field")
    cache = _cache_path(source.fingerprint, target)
    result=read_cached('feature_profiles',cache,source,[f'{key}.{target}.json' for key in source.legacy_fingerprints],'profile',field=target) if not force else None
    if result is not None:return result
    with __import__('backend.apps.common.task_execution',fromlist=['heavy_compute_slot']).heavy_compute_slot():
        values: list[float] = []
        valid_n = 0
        missing_n = 0
        ranked: list[dict[str, Any]] = []
        header = set(read_header(source))
        id_fields = [field for field in ["species_id", "gene_id", "transcript_id", "protein_id", target] if field in header]
        for row in _iter_indexed_rows(source, id_fields):
            raw = row.get(target)
            if raw is None or str(raw).strip() == "":
                missing_n += 1
                continue
            valid_n += 1
            num = _num(raw)
            if num is not None:
                values.append(num)
                ranked.append({
                    "entity_id": row.get("gene_id") or row.get("transcript_id") or row.get("protein_id") or "",
                    "value": num,
                })
        result = _profile_result(source, target, values, valid_n, missing_n, ranked)
        try:
            write_cache(cache,result)
        except OSError:
            pass
        return result
