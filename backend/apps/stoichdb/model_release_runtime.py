from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings
from django.db.models import Count

from backend.apps.stoichdb.models import (
    DataRelease,
    FileQCResult,
    OmicsDataset,
    ReleaseDataset,
    ReleaseQCResult,
    ReleaseSpecies,
    SchemaRegistry,
    StorageObject,
)
from backend.apps.stoichdb.storage_objects import resolve_storage_object


MODEL_RELEASE_ID = "model_organisms_20260731_v1"
FORMAL_RELEASE_STATUSES = {"validated", "published", "release_ready"}
CHUNK_ROWS = 8192


def _path_exists(path: Path | str | None) -> bool:
    return isinstance(path, Path) and path.exists() and path.is_file()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


@lru_cache(maxsize=1)
def model_release() -> DataRelease | None:
    return DataRelease.objects.filter(release_id=MODEL_RELEASE_ID).first()


def release_dataset_for_dataset(dataset: OmicsDataset) -> ReleaseDataset | None:
    release = model_release()
    if release is None:
        return None
    return ReleaseDataset.objects.filter(release=release, dataset=dataset, membership_status="included").first()


def release_dataset_for_key(species_id: str, omics: str) -> ReleaseDataset | None:
    release = model_release()
    if release is None:
        return None
    return ReleaseDataset.objects.filter(
        release=release,
        species_id_text=species_id,
        omics_type=omics,
        membership_status="included",
    ).select_related("dataset", "species").first()


def release_species_for_key(species_id: str) -> ReleaseSpecies | None:
    release = model_release()
    if release is None:
        return None
    return ReleaseSpecies.objects.filter(release=release, species_id_text=species_id).select_related("species").first()


def is_model_release_dataset(dataset: OmicsDataset) -> bool:
    return release_dataset_for_dataset(dataset) is not None


def _storage_object_for_key(logical_key: str) -> StorageObject | None:
    if not logical_key:
        return None
    return StorageObject.objects.filter(logical_key=logical_key).first()


def _legacy_path(dataset: OmicsDataset, scope: str) -> Path | None:
    path_text = str((dataset.full_csv_path if scope == "full" else dataset.core_csv_path) or "").strip()
    if not path_text or path_text.lower() in {"nan", "none", "null"}:
        return None
    path = Path(path_text)
    return path if path.exists() and path.is_file() else None


def resolve_feature_table(dataset: OmicsDataset, scope: str = "core", *, prefer_parquet: bool = True) -> dict[str, Any]:
    scope = "full" if str(scope or "").lower() == "full" else "core"
    fallbacks: list[dict[str, str]] = []
    rd = release_dataset_for_dataset(dataset)
    if rd is not None:
        storage_map = (rd.metadata_json or {}).get("storage_objects") or {}
        candidates: list[tuple[str, str]] = []
        if prefer_parquet:
            candidates.append((f"parquet_{scope}", "parquet"))
        candidates.append((scope, "csv"))
        for product_key, table_format in candidates:
            logical_key = str(storage_map.get(product_key) or "")
            storage = _storage_object_for_key(logical_key)
            path = resolve_storage_object(storage) if storage is not None else None
            if _path_exists(path):
                return {
                    "available": True,
                    "path": path,
                    "format": table_format,
                    "source": f"{table_format}_storage_object",
                    "scope": scope,
                    "release_id": rd.release.release_id,
                    "release_dataset_id": rd.id,
                    "storage_object": storage,
                    "logical_key": storage.logical_key if storage else "",
                    "schema_version": storage.schema_version if storage else "",
                    "size_bytes": storage.size_bytes if storage else 0,
                    "sha256": storage.sha256 if storage else "",
                    "fallback_events": fallbacks,
                }
            fallbacks.append({"candidate": product_key, "reason": "missing_or_unregistered"})
    legacy = _legacy_path(dataset, scope)
    if legacy is not None:
        return {
            "available": True,
            "path": legacy,
            "format": "csv",
            "source": "legacy_dataset_path",
            "scope": scope,
            "release_id": "",
            "release_dataset_id": None,
            "storage_object": None,
            "logical_key": "",
            "schema_version": dataset.schema_version,
            "size_bytes": legacy.stat().st_size,
            "sha256": "",
            "fallback_events": fallbacks + [{"candidate": "legacy_path", "reason": "used"}],
        }
    return {
        "available": False,
        "path": None,
        "format": "",
        "source": "unavailable",
        "scope": scope,
        "release_id": rd.release.release_id if rd else "",
        "release_dataset_id": rd.id if rd else None,
        "storage_object": None,
        "logical_key": "",
        "schema_version": dataset.schema_version,
        "size_bytes": 0,
        "sha256": "",
        "fallback_events": fallbacks + [{"candidate": "legacy_path", "reason": "missing"}],
    }


def available_scopes_for_dataset(dataset: OmicsDataset) -> list[str]:
    scopes: list[str] = []
    for scope in ("core", "full"):
        resolved = resolve_feature_table(dataset, scope)
        if resolved.get("available"):
            scopes.append(scope)
    return scopes or ["core"]


def _rows_from_csv(path: Path, *, offset: int = 0, limit: int = 0, columns: list[str] | None = None) -> list[dict[str, Any]]:
    wanted = set(columns or [])
    rows: list[dict[str, Any]] = []
    skipped = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not isinstance(row, dict):
                continue
            if skipped < max(0, offset):
                skipped += 1
                continue
            if wanted:
                row = {key: row.get(key) for key in columns or []}
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def _rows_from_parquet(path: Path, *, offset: int = 0, limit: int = 0, columns: list[str] | None = None) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except Exception:
        return []
    parquet_file = pq.ParquetFile(path)
    schema_names = set(parquet_file.schema.names)
    if columns is not None:
        selected = [col for col in columns if col in schema_names]
        if not selected:
            return []
    else:
        selected = None
    rows: list[dict[str, Any]] = []
    skipped = 0
    for batch in parquet_file.iter_batches(batch_size=CHUNK_ROWS, columns=selected):
        batch_rows = batch.to_pylist()
        if skipped < max(0, offset):
            batch_skip = min(len(batch_rows), max(0, offset) - skipped)
            skipped += batch_skip
            batch_rows = batch_rows[batch_skip:]
        if batch_rows:
            rows.extend(batch_rows)
        if limit and len(rows) >= limit:
            return rows[:limit]
    return rows


def read_feature_rows(dataset: OmicsDataset, scope: str = "core", *, offset: int = 0, limit: int = 0, columns: list[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved = resolve_feature_table(dataset, scope)
    if not resolved.get("available") or not isinstance(resolved.get("path"), Path):
        return [], resolved
    path = resolved["path"]
    if resolved.get("format") == "parquet":
        rows = _rows_from_parquet(path, offset=offset, limit=limit, columns=columns)
        if rows:
            return rows, resolved
        fallback = resolve_feature_table(dataset, scope, prefer_parquet=False)
        fallback["fallback_events"] = list(resolved.get("fallback_events") or []) + [{"candidate": "parquet_read", "reason": "failed_or_empty"}]
        if fallback.get("available") and isinstance(fallback.get("path"), Path):
            return _rows_from_csv(fallback["path"], offset=offset, limit=limit, columns=columns), fallback
        return [], fallback
    return _rows_from_csv(path, offset=offset, limit=limit, columns=columns), resolved


def feature_columns(dataset: OmicsDataset, scope: str = "core") -> list[str]:
    resolved = resolve_feature_table(dataset, scope)
    path = resolved.get("path")
    if not resolved.get("available") or not isinstance(path, Path):
        return []
    if resolved.get("format") == "parquet":
        try:
            import pyarrow.parquet as pq
            return list(pq.ParquetFile(path).schema.names)
        except Exception:
            return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle), [])
    except Exception:
        return []


def feature_row_count(dataset: OmicsDataset, scope: str = "core") -> int:
    resolved = resolve_feature_table(dataset, scope)
    path = resolved.get("path")
    if not resolved.get("available") or not isinstance(path, Path):
        return 0
    if resolved.get("format") == "parquet":
        try:
            import pyarrow.parquet as pq
            return int(pq.ParquetFile(path).metadata.num_rows)
        except Exception:
            return 0
    count = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            next(handle, None)
            for _ in handle:
                count += 1
    except Exception:
        return 0
    return count


def dataset_runtime_payload(dataset: OmicsDataset) -> dict[str, Any]:
    scopes = {}
    for scope in ("core", "full"):
        resolved = resolve_feature_table(dataset, scope)
        scopes[scope] = {
            "available": bool(resolved.get("available")),
            "source": resolved.get("source", ""),
            "format": resolved.get("format", ""),
            "logical_key": resolved.get("logical_key", ""),
            "schema_version": resolved.get("schema_version", ""),
            "size_bytes": resolved.get("size_bytes", 0),
            "sha256_present": bool(resolved.get("sha256")),
            "fallback_events": resolved.get("fallback_events") or [],
        }
    return {
        "is_model_release_dataset": release_dataset_for_dataset(dataset) is not None,
        "available_scopes": available_scopes_for_dataset(dataset),
        "scopes": scopes,
    }


def species_model_release_payload(species_id: str) -> dict[str, Any]:
    release = model_release()
    membership = release_species_for_key(species_id)
    if release is None or membership is None:
        return {
            "available": False,
            "is_model_organism": False,
            "quality_tier": "legacy-current",
            "release_id": "",
            "release_status": "",
            "schema_version": "",
            "qc_summary": {},
            "download_manifest": [],
        }
    datasets = list(ReleaseDataset.objects.filter(release=release, species_id_text=species_id).select_related("dataset"))
    dataset_payloads = []
    download_manifest = []
    parquet_available = 0
    csv_available = 0
    for rd in datasets:
        dataset = rd.dataset
        if dataset is None:
            continue
        runtime = dataset_runtime_payload(dataset)
        dataset_payloads.append({
            "omics": rd.omics_type,
            "dataset_id": rd.dataset_id_text,
            "membership_status": rd.membership_status,
            "row_count_core": rd.row_count_core,
            "row_count_full": rd.row_count_full,
            "runtime": runtime,
        })
        for scope, item in runtime["scopes"].items():
            if item["available"]:
                if item["format"] == "parquet":
                    parquet_available += 1
                if item["format"] == "csv":
                    csv_available += 1
                download_manifest.append({
                    "omics": rd.omics_type,
                    "scope": scope,
                    "format": item["format"],
                    "logical_key": item["logical_key"],
                    "size_bytes": item["size_bytes"],
                    "sha256_present": item["sha256_present"],
                })
    qc_counts = {
        "file_qc_pass": FileQCResult.objects.filter(release=release, status="pass").count(),
        "file_qc_fail": FileQCResult.objects.filter(release=release, status="fail").count(),
        "release_gates_pass": ReleaseQCResult.objects.filter(release=release, status="pass").count(),
        "release_gates_fail": ReleaseQCResult.objects.filter(release=release, status="fail").count(),
    }
    formal = release.status in FORMAL_RELEASE_STATUSES and membership.inclusion_status == "included" and membership.qc_status.startswith("pass")
    return {
        "available": True,
        "release_id": release.release_id,
        "release_status": release.status,
        "schema_version": release.schema_version,
        "published_at": release.published_at.isoformat() if release.published_at else "",
        "manifest_sha256": release.manifest_sha256,
        "is_model_organism": membership.is_model_organism,
        "inclusion_status": membership.inclusion_status,
        "qc_status": membership.qc_status,
        "reason_code": membership.reason_code,
        "quality_tier": "release-grade" if formal else ("candidate-grade" if membership.inclusion_status == "included" else "not-in-scope"),
        "model_group_latin": membership.model_group_latin,
        "source_division": membership.source_division,
        "datasets": dataset_payloads,
        "qc_summary": qc_counts,
        "download_manifest": download_manifest,
        "parquet_objects_available": parquet_available,
        "csv_objects_available": csv_available,
    }


def model_release_overview_payload() -> dict[str, Any]:
    release = model_release()
    if release is None:
        return {"available": False}
    gates = list(ReleaseQCResult.objects.filter(release=release).order_by("gate"))
    return {
        "available": True,
        "release": {
            "release_id": release.release_id,
            "label": release.label,
            "status": release.status,
            "scope_kind": release.scope_kind,
            "version": release.version,
            "schema_version": release.schema_version,
            "pipeline_version": release.pipeline_version,
            "published_at": release.published_at.isoformat() if release.published_at else "",
            "manifest_sha256": release.manifest_sha256,
            "is_immutable": release.is_immutable,
            "species_count": release.species_count,
            "dataset_count": release.dataset_count,
            "metadata": release.metadata_json or {},
            "manifest": release.manifest_json or {},
        },
        "species_status": list(
            ReleaseSpecies.objects.filter(release=release)
            .values("inclusion_status", "qc_status")
            .annotate(count=Count("id"))
            .order_by("inclusion_status", "qc_status")
        ),
        "dataset_status": list(
            ReleaseDataset.objects.filter(release=release)
            .values("membership_status", "omics_type")
            .annotate(count=Count("id"))
            .order_by("membership_status", "omics_type")
        ),
        "schema_registry": {
            "active": SchemaRegistry.objects.filter(schema_id__startswith=f"{release.release_id}:", status="active").count(),
            "total": SchemaRegistry.objects.filter(schema_id__startswith=f"{release.release_id}:").count(),
        },
        "qc_gates": [
            {"gate": gate.gate, "status": gate.status, "summary": gate.summary_json or {}}
            for gate in gates
        ],
    }
