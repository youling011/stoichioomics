from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from django.conf import settings

from .profiling import field_profile, precompute_field_profiles
from .qc import qc_report
from .registry import catalog_payload
from .schemas import normalize_omics, normalize_scope
from .sources import DatasetSourceResolver, read_header

HOME_SPOTLIGHT_ROOT = Path(settings.BASE_DIR) / "runtime" / "feature_home_spotlight"
OMICS_LAYERS = ("genome", "transcriptome", "proteome")
FIELD_SETS = ("core", "full")


def _cache_token(value: str) -> str:
    text = str(value or "all").strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "_", text)
    return text.strip("_") or "all"


def _cache_path(source_fingerprint: str, species_id: str, omics: str, scope: str, family: str) -> Path:
    HOME_SPOTLIGHT_ROOT.mkdir(parents=True, exist_ok=True)
    key = "|".join([species_id, omics, scope, family or "all", source_fingerprint])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    name = f"{_cache_token(species_id)}.{omics}.{scope}.{_cache_token(family)}.{digest}.json"
    return HOME_SPOTLIGHT_ROOT / name


def _is_numeric_field(row: dict[str, Any]) -> bool:
    if row.get("ml_role") == "eligible":
        return True
    dtype = str(row.get("dtype") or "").lower()
    semantic = str(row.get("semantic_type") or "").lower()
    return (
        "float" in dtype
        or "double" in dtype
        or "int" in dtype
        or "number" in dtype
        or "numeric" in dtype
        or semantic in {"continuous", "count", "composition", "binary"}
    )


def pick_preview_rows(rows: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    numeric = [row for row in rows if _is_numeric_field(row)]
    rest = [row for row in rows if not _is_numeric_field(row)]
    return [dict(row) for row in [*numeric, *rest][: max(1, limit)]]


def _preview_row(row: dict[str, Any], species_id: str, omics: str, scope: str, *, force: bool = False, profiles: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    field = str(row.get("field") or "")
    item = {
        "field": field,
        "label": row.get("label"),
        "family": row.get("family"),
        "module": row.get("semantic_type") or row.get("ml_role"),
        "semantic_type": row.get("semantic_type"),
        "dtype": row.get("dtype"),
        "ml_role": row.get("ml_role"),
        "composition_group": row.get("composition_group"),
        "missingness": None,
        "iqr": None,
        "notes": row.get("description") or "",
    }
    profile = (profiles or {}).get(field) or field_profile(species_id, omics, scope, field, force=force)
    p25 = profile.get("summary", {}).get("p25")
    p75 = profile.get("summary", {}).get("p75")
    item["missingness"] = round(float(profile.get("missing_rate") or 0) * 100, 2)
    item["iqr"] = round(float(p75) - float(p25), 6) if p25 is not None and p75 is not None else None
    item["notes"] = f"{int(profile.get('numeric_n') or 0):,} numeric / {int(profile.get('n_rows') or 0):,} rows"
    return item


def _qc_summary(species_id: str, omics: str, scope: str, fields: list[str], fallback_rows: list[dict[str, Any]], *, force: bool = False) -> dict[str, Any]:
    if not fields:
        return {
            "profile_status": "no_applicable_fields",
            "missing_gt_20_count": 0 if scope == "core" else None,
            "constant_count": 0 if scope == "core" else None,
            "high_corr_pair_count": 0 if scope == "core" else None,
            "compositional_group_count": 0,
            "message": "No fields from this Feature Family are present in the selected species, omics layer, and field set.",
        }
    if scope != "core":
        return {
            "profile_status": "browse_only_full_scope",
            "missing_gt_20_count": None,
            "constant_count": None,
            "high_corr_pair_count": None,
            "compositional_group_count": len({row.get("composition_group") for row in fallback_rows if row.get("composition_group")}),
            "message": "Full feature sets are browse/download only; ML QC is computed for Core field sets.",
        }
    report = qc_report(species_id, omics, fields, force=force)
    missing = report.get("missingness") or {}
    return {
        "profile_status": "profiled_preview_fields",
        "missing_gt_20_count": sum(1 for item in missing.values() if float(item.get("missing_rate") or 0) > 0.2),
        "constant_count": len(report.get("constant") or []),
        "high_corr_pair_count": len(report.get("high_correlation_pairs") or []),
        "compositional_group_count": len(report.get("composition_groups") or {}),
        "message": f"Computed from {int(report.get('selected_features') or len(fields)):,} preview Core fields across {int(report.get('n_rows') or 0):,} {omics} rows.",
    }


def homepage_preview(species_id: str, omics: str = "proteome", scope: str = "core", family: str = "", *, force: bool = False) -> dict[str, Any]:
    omics = normalize_omics(omics)
    scope = normalize_scope(scope)
    family = str(family or "").strip()
    catalog = catalog_payload(omics=omics, scope=scope, family=family)
    source = DatasetSourceResolver().resolve(species_id, omics, scope)
    header = set(read_header(source))
    all_rows = [row for row in (catalog.get("items") or []) if row.get("field") in header]
    cache = _cache_path(source.fingerprint, species_id, omics, scope, family)
    if cache.exists() and not force:
        with cache.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    selected_rows = pick_preview_rows(all_rows)
    profile_map = precompute_field_profiles(species_id, omics, scope, [row.get("field") for row in selected_rows if row.get("field")], force=force) if selected_rows else {}
    feature_rows = [_preview_row(row, species_id, omics, scope, force=force, profiles=profile_map) for row in selected_rows]
    selected_fields = [row["field"] for row in feature_rows if row.get("field")]
    payload = {
        "status": "ready",
        "species_id": species_id,
        "omics": omics,
        "table_level": scope,
        "feature_family": family,
        "field_count": len(all_rows),
        "entity_count": int(source.row_count or 0),
        "source_sha": source.fingerprint,
        "dataset_id": source.dataset_id,
        "schema_version": source.schema_version,
        "feature_rows": feature_rows,
        "summary": catalog.get("summary") or {},
        "facets": catalog.get("facets") or {},
        "qc": _qc_summary(species_id, omics, scope, selected_fields, selected_rows, force=force),
        "cache": {
            "mode": "precomputed_homepage_combo",
            "path": str(cache),
        },
    }
    cache.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
