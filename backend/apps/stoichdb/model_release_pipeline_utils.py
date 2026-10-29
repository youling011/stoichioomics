from __future__ import annotations
from backend.apps.stoichdb.feature_sources import io as feature_io

import csv
import hashlib
import json
import math
import mimetypes
from pathlib import Path
from typing import Any

from backend.apps.stoichdb.models import DataRelease, ReleaseDataset, StorageObject
from backend.apps.stoichdb.storage_objects import resolve_storage_object


CHUNK_SIZE = 1024 * 1024 * 8


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with feature_io.open_source(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def media_for(path: Path) -> tuple[str, str]:
    suffixes = [s.lower() for s in path.suffixes]
    compression = ""
    if suffixes and suffixes[-1] in {".gz", ".zip", ".bz2", ".xz", ".zst"}:
        compression = suffixes[-1].lstrip(".")
    media_type = mimetypes.guess_type(str(path))[0] or ""
    if not media_type:
        if ".parquet" in suffixes:
            media_type = "application/vnd.apache.parquet"
        elif ".csv" in suffixes:
            media_type = "text/csv"
        elif ".json" in suffixes:
            media_type = "application/json"
        else:
            media_type = "application/octet-stream"
    return media_type, compression


def release_dataset_rows(release_id: str, scope: str = "included"):
    release = DataRelease.objects.get(release_id=release_id)
    qs = ReleaseDataset.objects.select_related("dataset", "species").filter(release=release).order_by("species_id_text", "omics_type")
    if scope == "included":
        qs = qs.filter(membership_status="included")
    return release, list(qs)


def storage_key_for(rd: ReleaseDataset, product: str) -> str:
    metadata = rd.metadata_json or {}
    return (metadata.get("storage_objects") or {}).get(product, "") or ""


def storage_object_for(rd: ReleaseDataset, product: str) -> StorageObject | None:
    key = storage_key_for(rd, product)
    if not key:
        return None
    return StorageObject.objects.filter(logical_key=key).first()


def storage_path(storage_object: StorageObject) -> Path:
    resolved = resolve_storage_object(storage_object)
    return Path(resolved) if not isinstance(resolved, Path) else resolved


def read_header(path: Path) -> list[str]:
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        return next(reader, [])


def count_csv_rows_fast(path: Path) -> int:
    source=feature_io.logical_source(path)
    if source:return int(source.record['row_count'])
    # Count CSV records, including quoted multiline values, rather than physical
    # LF bytes. This also matches Arrow conversion and the logical Core contract.
    with feature_io.open_source(path,'r',encoding='utf-8-sig',newline='') as handle:
        reader=csv.reader(handle);next(reader,None)
        return sum(1 for _ in reader)


def sample_column_stats(path: Path, sample_rows: int = 2000) -> dict[str, dict[str, Any]]:
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        stats = {col: {"non_null": 0, "null": 0, "numeric": 0, "min": None, "max": None, "examples": []} for col in columns}
        for idx, row in enumerate(reader):
            if idx >= sample_rows:
                break
            for col in columns:
                value = (row.get(col) or "").strip()
                if value == "":
                    stats[col]["null"] += 1
                    continue
                stats[col]["non_null"] += 1
                if len(stats[col]["examples"]) < 3 and value not in stats[col]["examples"]:
                    stats[col]["examples"].append(value[:120])
                try:
                    numeric = float(value)
                except ValueError:
                    continue
                if not math.isfinite(numeric):
                    continue
                stats[col]["numeric"] += 1
                stats[col]["min"] = numeric if stats[col]["min"] is None else min(stats[col]["min"], numeric)
                stats[col]["max"] = numeric if stats[col]["max"] is None else max(stats[col]["max"], numeric)
    return stats


def root_alias_relative_for_project(project_root: Path, path: Path) -> tuple[str, str]:
    root = project_root
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        return "STOICH_PROJECT_ROOT", rel
    except ValueError:
        return "", path.as_posix()


def storage_logical_key(root_alias: str, relative_path: str, object_uri: str = "") -> str:
    if root_alias and relative_path:
        key = f"local_fs/{root_alias}/{relative_path}"
    else:
        key = f"local_fs/absolute/{object_uri.replace(chr(92), '/')}"
    if len(key) <= 512:
        return key
    return f"local_fs/path_sha256/{hashlib.sha256(key.encode('utf-8')).hexdigest()}"


def upsert_storage_object_for_file(
    path: Path,
    project_root: Path,
    schema_version: str,
    status: str,
    metadata: dict[str, Any],
    sha256: str | None = None,
) -> StorageObject:
    root_alias, relative_path = root_alias_relative_for_project(project_root, path)
    media_type, compression = media_for(path)
    digest = sha256 if sha256 is not None else sha256_file(path)
    obj, _ = StorageObject.objects.update_or_create(
        logical_key=storage_logical_key(root_alias, relative_path, str(path)),
        defaults={
            "backend": "local_fs",
            "root_alias": root_alias,
            "relative_path": relative_path,
            "object_uri": "" if root_alias else str(path),
            "size_bytes": feature_io.source_metadata(path).size if feature_io.source_exists(path) else 0,
            "sha256": digest,
            "media_type": media_type,
            "compression": compression,
            "schema_version": schema_version,
            "status": status,
            "metadata_json": metadata,
        },
    )
    return obj
