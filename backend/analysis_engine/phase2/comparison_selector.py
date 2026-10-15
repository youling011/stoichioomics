from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from backend.apps.stoichdb.feature_hub.field_resolution import resolve_field, resolve_registry_fields

from .comparison_schema import COMPARISON_SCHEMA_VERSION


ALLOWED_COMPARISON_OMICS = ("genome", "transcriptome", "proteome")


def load_registry_payload() -> dict[str, Any]:
    """Load the pinned registry snapshot used by comparison v2."""
    project_root = Path(__file__).resolve().parents[3]
    snapshot = project_root / "shared" / "schemas" / "stoich_ml_feature_registry_v1.json"
    if snapshot.exists():
        return json.loads(snapshot.read_text(encoding="utf-8"))
    from backend.apps.stoichdb.feature_hub.registry import load_registry
    return load_registry()


def _requested_omics(config: dict[str, Any]) -> list[str]:
    raw = config.get("comparison_omics") or config.get("omics") or ALLOWED_COMPARISON_OMICS
    if isinstance(raw, str):
        values = [item.strip().lower() for item in raw.replace("+", ",").split(",") if item.strip()]
    else:
        values = [str(item).strip().lower() for item in raw if str(item).strip()]
    if "all" in values:
        values = list(ALLOWED_COMPARISON_OMICS)
    return [item for item in ALLOWED_COMPARISON_OMICS if item in dict.fromkeys(values)]


def _read_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, (str, Path)):
        path = Path(value)
        if not path.exists():
            return []
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return [payload]
            return [row for row in payload if isinstance(row, dict)]
        try:
            return pd.read_csv(path).fillna("").to_dict(orient="records")
        except Exception:
            return []
    if isinstance(value, dict):
        return [value]
    return [row for row in value or [] if isinstance(row, dict)]


def _provenance_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    value = config.get("comparison_feature_provenance_path")
    if not value:
        value = config.get("comparison_feature_provenance")
    return _read_rows(value)


def _provenance_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = _provenance_rows(config)
    out: dict[str, dict[str, Any]] = {}
    raw = config.get("comparison_feature_provenance")
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                out[str(key)] = dict(value)
            elif value:
                out[str(key)] = {"output_column": str(value), "source_column": str(value), "source_present": True}
    for row in rows:
        key = row.get("feature_key") or (
            f"{row.get('omics')}::{row.get('registry_name') or row.get('feature_name')}"
            if row.get("omics") and (row.get("registry_name") or row.get("feature_name")) else ""
        )
        if key:
            out[str(key)] = dict(row)
    return out


def _block_status_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    value = config.get("comparison_block_status")
    if not value:
        value = config.get("comparison_mapping_summary") or config.get("comparison_mapping_summary_path")
    rows = _read_rows(value)
    if isinstance(value, dict):
        source = value.get("blocks") if isinstance(value.get("blocks"), dict) else value
        if isinstance(source, dict):
            return {str(key): dict(item) for key, item in source.items() if isinstance(item, dict)}
    mapped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        nested = row.get("blocks")
        if isinstance(nested, dict):
            for key, item in nested.items():
                if isinstance(item, dict):
                    mapped[str(key)] = dict(item)
        elif row.get("omics"):
            mapped[str(row.get("omics"))] = dict(row)
    return mapped


def _resolution_for_context(
    df: pd.DataFrame,
    fields_by_omics: dict[str, list[dict[str, Any]]],
    requested: list[str],
    explicit: dict[str, dict[str, Any]],
) -> tuple[dict[tuple[str, str], tuple[str, str]], bool]:
    headers = [str(column) for column in df.columns]
    owners: dict[str, set[str]] = {}
    candidate_resolutions: dict[tuple[str, str], Any] = {}
    for omics in requested:
        for meta in fields_by_omics[omics]:
            field = str(meta.get("field") or "")
            resolution = resolve_field(headers, omics=omics, field=field, metadata=meta, allow_unprefixed=True)
            candidate_resolutions[(omics, field)] = resolution
            if resolution.present and "__" not in resolution.source_column and not resolution.source_column.casefold().startswith(
                tuple(prefix.casefold() for prefix in (f"{omics}_", "transcript_", "protein_"))
            ):
                owners.setdefault(resolution.source_column.casefold(), set()).add(omics)

    resolved: dict[tuple[str, str], tuple[str, str]] = {}
    cross_omics_collision = False
    for omics in requested:
        for meta in fields_by_omics[omics]:
            field = str(meta.get("field") or "")
            key = f"{omics}::{field}"
            configured = explicit.get(key) or {}
            configured_column = str(configured.get("output_column") or configured.get("source_column") or "")
            if configured_column:
                candidate = next((header for header in headers if header.casefold() == configured_column.casefold()), "")
                if candidate:
                    resolved[(omics, field)] = (candidate, "explicit_provenance")
                    continue
            resolution = candidate_resolutions[(omics, field)]
            if not resolution.present:
                continue
            # A bare column is safe only when it belongs to one requested
            # block. Namespaced columns are always safe.
            is_namespaced = "__" in resolution.source_column or resolution.source_column.casefold().startswith((f"{omics}_", "transcript_", "protein_"))
            if not is_namespaced:
                if len(owners.get(resolution.source_column.casefold(), set())) > 1:
                    cross_omics_collision = True
                    continue
            resolved[(omics, field)] = (resolution.source_column, resolution.method)
    return resolved, cross_omics_collision


def resolve_comparison_features(
    df: pd.DataFrame,
    config: dict[str, Any],
    registry_payload: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], pd.DataFrame, list[str], str]:
    registry = registry_payload or load_registry_payload()
    registry_version = str(registry.get("registry_version") or "unknown")
    schema_version = str(config.get("comparison_schema_version") or COMPARISON_SCHEMA_VERSION)
    requested = _requested_omics(config)
    include_conditional = bool(config.get("comparison_include_conditional", False))
    block_statuses = _block_status_map(config)
    explicit = _provenance_map(config)
    fields_by_omics = {
        omics: [
            dict(row) for row in registry.get("fields", [])
            if row.get("scope") == "core" and str(row.get("omics") or "").lower() == omics
        ]
        for omics in requested
    }
    resolved_sources, cross_omics_collision = _resolution_for_context(df, fields_by_omics, requested, explicit)
    # Preserve the compact return behavior for callers of the pre-v2 selector
    # API. The v2 pipeline always supplies a schema/context flag and therefore
    # receives the required full registry audit, including unavailable blocks.
    if cross_omics_collision and not resolved_sources and "comparison_schema_version" not in config and "comparison_context_enabled" not in config:
        return [], pd.DataFrame(), [], registry_version
    resolved_blocks: list[str] = []
    block_metadata: dict[str, dict[str, Any]] = {}
    for omics in requested:
        meta = dict(block_statuses.get(omics) or {})
        if meta:
            status = str(meta.get("block_status") or meta.get("status") or "unavailable")
            meta["block_status"] = status
            block_metadata[omics] = meta
            if status in {"ready", "partial"}:
                resolved_blocks.append(omics)
        elif any(key[0] == omics for key in resolved_sources):
            block_metadata[omics] = {"block_status": "ready"}
            resolved_blocks.append(omics)
        else:
            block_metadata[omics] = {"block_status": "unavailable"}

    audit_rows: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    for omics in requested:
        block = block_metadata[omics]
        block_state = str(block.get("block_status") or "unavailable")
        for meta in fields_by_omics[omics]:
            field = str(meta.get("field") or "")
            feature_key = f"{omics}::{field}"
            source, resolution = resolved_sources.get((omics, field), ("", "unresolved"))
            provenance = explicit.get(feature_key) or {}
            if provenance.get("output_column"):
                source = str(provenance["output_column"])
            source_present = bool(provenance.get("source_present", bool(source))) and bool(source)
            if provenance.get("source_present") is False:
                source_present = False
            role = str(meta.get("ml_role") or "exclude")
            status = "discovered"
            reason = ""
            if role == "exclude":
                status, reason = "excluded", "registry_exclude"
            elif role == "conditional" and not include_conditional:
                status, reason = "excluded", "conditional_not_enabled"
            elif block_state == "unavailable":
                status, reason = "skipped", "block_unavailable"
            elif block_state == "failed":
                block_reason = str(block.get("status_reason") or "")
                status, reason = "skipped", "mapping_below_threshold" if "mapping_below_threshold" in block_reason else "block_failed"
            elif not source_present:
                status, reason = "skipped", "missing_source_column"

            row = {
                "registry_version": registry_version,
                "schema_id": meta.get("schema_id"),
                "schema_version": meta.get("schema_version"),
                "comparison_schema_version": schema_version,
                "omics_layer": omics,
                "scope": "core",
                "feature_name": field,
                "feature_key": feature_key,
                "display_name": meta.get("label") or field.replace("_", " "),
                "family": meta.get("family") or "other",
                "unit": meta.get("unit") or "",
                "description": meta.get("description") or "",
                "scaling_hint": meta.get("scaling_hint") or "none",
                "transform_hint": meta.get("transform_hint") or "none",
                "bounded_min": meta.get("bounded_min"),
                "bounded_max": meta.get("bounded_max"),
                "semantic_type": meta.get("semantic_type") or "continuous",
                "ml_role": role,
                "applicability": meta.get("applicability") or "all",
                "zero_semantics": meta.get("zero_semantics") or "true_zero",
                "composition_group": meta.get("composition_group") or "",
                "redundancy_group": meta.get("redundancy_group") or "",
                "source_block": omics,
                "provenance_resolution": str(provenance.get("resolution_method") or resolution),
                "source_column": source,
                "status": status,
                "reason": reason,
                "duplicate_of": "",
                "warnings": "",
                "registered": True,
                "source_resolved": bool(source_present and block_state in {"ready", "partial"}),
                "source_dataset_id": provenance.get("source_dataset_id") or block.get("dataset_id") or "",
                "source_schema_version": provenance.get("source_schema_version") or block.get("schema_version") or "",
                "materialized": bool(provenance.get("materialized", source_present)),
                "discovered": bool(source_present),
                "block_status": block_state,
                "raw_match_rate": block.get("raw_match_rate"),
                "applicable_match_rate": block.get("applicable_match_rate"),
                "analysis_status": status,
                "analysis_reason": reason,
                "n_applicable_total": None,
                "n_applicable_hvg": None,
                "n_applicable_non_hvg": None,
                "n_valid_hvg": None,
                "n_valid_non_hvg": None,
            }
            same_group = [
                str(item.get("field")) for item in fields_by_omics[omics]
                if str(item.get("composition_group") or "") == str(meta.get("composition_group") or "")
                and str(meta.get("composition_group") or "")
            ]
            row["composition_components"] = same_group
            audit_rows.append(row)
            if status == "discovered" and role == "eligible":
                selected.append(dict(row))
            elif status == "discovered" and role == "conditional" and include_conditional:
                selected.append(dict(row))

    return selected, pd.DataFrame(audit_rows), resolved_blocks, registry_version
