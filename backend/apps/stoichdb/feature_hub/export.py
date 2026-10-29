from __future__ import annotations
from backend.apps.common.maintenance import guarded_submission
from backend.apps.common.task_execution import enqueue as enqueue_executor
import re
from backend.apps.common.artifact_locations import locate

import csv
import hashlib
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from django.conf import settings
from backend.apps.common.atomic_json import atomic_write_json, read_json

from .builder import split_x_metadata
from .qc import qc_report
from .registry import catalog_payload
from .schemas import FeatureHubError, normalize_omics, normalize_scope
from .sources import DatasetSourceResolver, iter_rows


EXPORT_ROOT = Path(getattr(settings, "STOICH_FEATURE_EXPORT_ROOT", Path(settings.BASE_DIR) / "runtime" / "feature_exports"))
X_MATRIX_FILENAME_TEMPLATE = "X_{omics}.csv"
METADATA_FILENAME = "metadata.csv"
FEATURE_DICTIONARY_FILENAME = "feature_dictionary.csv"


def _job_dir(export_id: str) -> Path:
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',export_id):raise FeatureHubError('Invalid export id')
    return EXPORT_ROOT/export_id

def _read_job_dir(export_id):
    _job_dir(export_id)
    found=locate('feature_exports',EXPORT_ROOT,export_id,required=False)
    return found.target if found else _job_dir(export_id)


def _status_path(export_id: str) -> Path:
    return _job_dir(export_id) / "status.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def _set_status(export_id: str, payload: dict[str, Any]) -> None:
    root=_job_dir(export_id);root.mkdir(parents=True,exist_ok=True);path=_status_path(export_id)
    previous=read_json(path) if path.is_file() else {}
    _write_json(path,{**previous,**payload})


@guarded_submission
def create_export(payload: dict[str, Any]) -> dict[str, Any]:
    species_ids = [str(item).strip() for item in payload.get("species_ids") or [] if str(item).strip()]
    if not species_ids and payload.get("species_id"):
        species_ids = [str(payload.get("species_id")).strip()]
    if not species_ids:
        raise FeatureHubError("At least one species_id is required")
    omics = normalize_omics(payload.get("omics", "genome"))
    scope = normalize_scope(payload.get("scope", "core"))
    mode = str(payload.get("mode") or ("ml_package" if scope == "core" else "selected_columns")).strip()
    fields = [str(item).strip() for item in payload.get("fields") or [] if str(item).strip()]
    include_metadata = [str(item).strip() for item in payload.get("metadata_fields") or [] if str(item).strip()]
    if mode == "ml_package" and scope != "core":
        raise FeatureHubError("ML packages can only be built from Core feature tables")
    export_id = f"fh_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    request_payload = {
        "export_id": export_id,
        "species_ids": species_ids,
        "omics": omics,
        "scope": scope,
        "mode": mode,
        "fields": fields,
        "metadata_fields": include_metadata,
    }
    _set_status(export_id, {
        "export_id": export_id,
        "status": "queued",
        "request": request_payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    })
    try:enqueue_executor('feature_export',export_id,request_payload)
    except Exception as exc:
        _set_status(export_id,{'status':'failed','error':'executor_start_failed: '+str(exc)})
        raise
    return export_status(export_id)


def _run_export_job(request_payload: dict[str, Any]) -> None:
    export_id = request_payload["export_id"]
    try:
        current = export_status(export_id)
        _set_status(export_id, {**current, "status": "running"})
        root = _job_dir(export_id)
        resolver = DatasetSourceResolver()
        omics = request_payload["omics"]
        scope = request_payload["scope"]
        mode = request_payload["mode"]
        fields = request_payload["fields"]
        split = split_x_metadata(omics, fields, include_metadata=request_payload.get("metadata_fields")) if scope == "core" else {
            "x_fields": fields,
            "metadata_fields": ["species_id", "gene_id", "transcript_id", "protein_id"],
            "excluded_from_x": [],
            "preprocessing_recipe": {},
        }
        x_fields = split["x_fields"] or fields
        metadata_fields = split["metadata_fields"]
        if not x_fields:
            raise FeatureHubError("No exportable fields selected")
        x_path = root / X_MATRIX_FILENAME_TEMPLATE.format(omics=omics)
        metadata_path = root / METADATA_FILENAME
        source_files: list[dict[str, Any]] = []
        row_count = 0
        with x_path.open("w", encoding="utf-8", newline="") as x_handle, metadata_path.open("w", encoding="utf-8", newline="") as meta_handle:
            x_writer = csv.DictWriter(x_handle, fieldnames=["species_id"] + x_fields)
            meta_fields = list(dict.fromkeys(["species_id"] + metadata_fields))
            meta_writer = csv.DictWriter(meta_handle, fieldnames=meta_fields)
            x_writer.writeheader()
            meta_writer.writeheader()
            for species_id in request_payload["species_ids"]:
                source = resolver.resolve(species_id, omics, scope)
                needed = list(dict.fromkeys(["species_id"] + x_fields + metadata_fields))
                source_files.append({
                    "species_id": species_id,
                    "dataset_id": source.dataset_id,
                    "path": str(source.path),
                    "size": source.file_size,
                    "schema_version": source.schema_version,
                    "fingerprint": source.fingerprint,
                })
                for row in iter_rows(source, needed):
                    x_writer.writerow({"species_id": species_id, **{field: row.get(field, "") for field in x_fields}})
                    meta_writer.writerow({field: row.get(field, species_id if field == "species_id" else "") for field in meta_fields})
                    row_count += 1
        _write_feature_dictionary(root / FEATURE_DICTIONARY_FILENAME, omics, scope, x_fields)
        qc_payload = qc_report(request_payload["species_ids"][0], omics, x_fields) if scope == "core" and request_payload["species_ids"] else {}
        _write_json(root / "qc_report.json", qc_payload)
        (root / "preprocessing_recipe.yaml").write_text(_yamlish(split.get("preprocessing_recipe") or {}), encoding="utf-8")
        manifest = {
            "export_id": export_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "software": "Stoichioomics Feature Hub",
            "scope": scope,
            "mode": mode,
            "species_list": request_payload["species_ids"],
            "omics": omics,
            "selected_features": x_fields,
            "metadata_fields": metadata_fields,
            "tabular_format": "plain_csv",
            "primary_feature_file": x_path.name,
            "metadata_file": metadata_path.name,
            "feature_dictionary_file": FEATURE_DICTIONARY_FILENAME,
            "row_count": row_count,
            "source_files": source_files,
            "clean_operations": ["type-safe plain CSV serialization", "X/metadata separation", "non-finite values preserved as NA/text for user pipeline handling"],
            "leakage_policy": "No scaler, imputer, PCA, or supervised selector was fitted on the full export.",
        }
        _write_json(root / "manifest.json", manifest)
        (root / "README.md").write_text(_readme(manifest), encoding="utf-8")
        (root / "checksums.sha256").write_text(_checksums(root), encoding="utf-8")
        zip_path = root / f"{export_id}.zip"
        with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
            for path in root.iterdir():
                if path.is_file() and path.name not in {zip_path.name, "status.json"}:
                    zf.write(path, path.name)
        _set_status(export_id, {
            "export_id": export_id,
            "status": "completed",
            "request": request_payload,
            "row_count": row_count,
            "files": [path.name for path in root.iterdir() if path.is_file()],
            "download_url": f"/api/stoichdb/feature-hub/exports/{export_id}/download/",
            "manifest": manifest,
        })
    except Exception as exc:  # noqa: BLE001
        _set_status(export_id, {**export_status(export_id), "status": "failed", "error": str(exc)})


def _write_feature_dictionary(path: Path, omics: str, scope: str, fields: list[str]) -> None:
    rows = {row["field"]: row for row in catalog_payload(omics=omics, scope=scope)["items"]}
    with path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["field", "label", "family", "dtype", "semantic_type", "unit", "ml_role", "applicability", "composition_group"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for field in fields:
            row = rows.get(field, {"field": field})
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _yamlish(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _readme(manifest: dict[str, Any]) -> str:
    return "\n".join([
        "# Stoichioomics Feature Hub export",
        "",
        f"Export ID: {manifest['export_id']}",
        f"Omics: {manifest['omics']}",
        f"Scope: {manifest['scope']}",
        "",
        f"Primary feature matrix: {manifest.get('primary_feature_file', 'X_<omics>.csv')}",
        f"Metadata table: {manifest.get('metadata_file', 'metadata.csv')}",
        "",
        "Core features are reusable handcrafted molecular descriptors. Full tables are browse/download resources and are not default ML inputs.",
        "Identifiers and annotations are exported separately from the numeric X matrix.",
        "Fit scalers, imputers, PCA, or target-dependent selectors inside the training fold or cross-validation loop.",
    ])


def _checksums(root: Path) -> str:
    rows = []
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.name in {"checksums.sha256", "status.json"}:
            continue
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        rows.append(f"{h.hexdigest()}  {path.name}")
    return "\n".join(rows) + "\n"


def export_status(export_id: str) -> dict[str, Any]:
    folder=_read_job_dir(export_id);path=folder/'status.json'
    if not path.exists():return {'export_id':export_id,'status':'missing'}
    value=read_json(path)
    if folder.resolve()!=_job_dir(export_id).resolve() and value.get('status') in ['running','queued']:
        return {**value,'status':'interrupted','saved_status':value['status'],'reason':'historical_orphan_not_scheduled'}
    return value


def export_download_path(export_id: str) -> Path:
    status = export_status(export_id)
    if status.get("status") != "completed":
        raise FeatureHubError("Export is not completed")
    path = _read_job_dir(export_id) / f"{export_id}.zip"
    if not path.exists():
        raise FeatureHubError("Export ZIP is missing")
    if path.parent.resolve()!=_job_dir(export_id).resolve() and getattr(settings,'DEPLOYMENT_INTEGRITY_INDEX',None):
        from backend.apps.common.artifact_integrity import verify_file
        verify_file(path,required=True)
    return path
