from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from backend.apps.stoichdb.feature_hub.registry import fields_for
from backend.apps.stoichdb.models import AnalysisArtifact, OmicsDataset


ARTIFACT_TYPE = "species_atlas_core_completeness"
OMICS_KEYS = ("genome", "transcriptome", "proteome")


def _is_valid(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if text == "":
        return False
    lowered = text.lower()
    if lowered in {"nan", "na", "n/a", "null", "none", "inf", "+inf", "-inf", "infinity", "-infinity"}:
        return False
    try:
        number = float(text)
    except Exception:
        return True
    return math.isfinite(number)


def _model_fields(omics: str) -> list[dict[str, Any]]:
    rows = []
    for row in fields_for(omics, "core"):
        if row.get("ml_role") not in {"eligible", "conditional"}:
            continue
        if row.get("semantic_type") in {"identifier", "metadata_text", "coordinate"}:
            continue
        rows.append(row)
    return rows


def _source_signature(path_text: str, fast_token: str = "") -> str:
    if not path_text:
        return ""
    if fast_token:
        return hashlib.sha256(f"{path_text}|{fast_token}".encode("utf-8", errors="ignore")).hexdigest()
    path = Path(path_text)
    try:
        stat = path.stat()
    except Exception:
        return hashlib.sha256(path_text.encode("utf-8", errors="ignore")).hexdigest()
    token = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(token.encode("utf-8", errors="ignore")).hexdigest()


def _from_summary_payload(dataset: OmicsDataset, field_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    summary = dataset.summary_payload or {}
    missingness = summary.get("missingness")
    if not isinstance(missingness, list):
        return None
    row_count = int(dataset.row_count_core or summary.get("row_count") or 0)
    if row_count <= 0:
        return None
    missing_by_field = {}
    for item in missingness:
        if isinstance(item, dict) and item.get("field"):
            try:
                missing_by_field[str(item["field"])] = float(item.get("missing_fraction") or 0)
            except Exception:
                pass
    valid_cells = 0
    applicable_cells = 0
    missing_cells = 0
    observed = 0
    not_applicable = 0
    for field in field_rows:
        name = str(field.get("field") or "")
        if not name:
            continue
        applicability = str(field.get("applicability") or "all")
        if name not in missing_by_field and applicability != "all":
            not_applicable += 1
            continue
        missing_fraction = min(1.0, max(0.0, missing_by_field.get(name, 1.0)))
        observed += int(name in missing_by_field)
        applicable_cells += row_count
        field_missing = int(round(row_count * missing_fraction))
        missing_cells += field_missing
        valid_cells += max(0, row_count - field_missing)
    if applicable_cells <= 0:
        return None
    return {
        "source_method": "summary_payload.missingness_from_core",
        "valid_cells": valid_cells,
        "applicable_cells": applicable_cells,
        "missing_cells": missing_cells,
        "completeness_pct": round(valid_cells * 100.0 / applicable_cells, 6),
        "field_count_expected": len(field_rows),
        "field_count_observed": observed,
        "field_count_not_applicable": not_applicable,
    }


def _read_header(path_text: str) -> set[str]:
    path = Path(str(path_text or ""))
    if not path.exists():
        return set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return set(next(csv.reader(handle), []))
    except Exception:
        return set()


def _from_missingness_rows(missingness: Any, row_count: int, field_rows: list[dict[str, Any]], header: set[str] | None = None) -> dict[str, Any] | None:
    if not isinstance(missingness, list):
        return None
    if row_count <= 0:
        return None
    header = header or set()
    missing_by_field = {}
    for item in missingness:
        if isinstance(item, dict) and item.get("field"):
            try:
                missing_by_field[str(item["field"])] = float(item.get("missing_fraction") or 0)
            except Exception:
                pass
    valid_cells = 0
    applicable_cells = 0
    missing_cells = 0
    observed = 0
    not_applicable = 0
    for field in field_rows:
        name = str(field.get("field") or "")
        if not name:
            continue
        applicability = str(field.get("applicability") or "all")
        if name not in missing_by_field and header and name not in header and applicability != "all":
            not_applicable += 1
            continue
        if header and name not in header:
            missing_fraction = 1.0
        else:
            missing_fraction = min(1.0, max(0.0, missing_by_field.get(name, 0.0 if header and name in header else 1.0)))
        observed += int(name in missing_by_field or (header and name in header))
        applicable_cells += row_count
        field_missing = int(round(row_count * missing_fraction))
        missing_cells += field_missing
        valid_cells += max(0, row_count - field_missing)
    if applicable_cells <= 0:
        return None
    return {
        "source_method": "core_csv_header_plus_summary_missingness" if header else "summary_payload.missingness_from_core",
        "valid_cells": valid_cells,
        "applicable_cells": applicable_cells,
        "missing_cells": missing_cells,
        "completeness_pct": round(valid_cells * 100.0 / applicable_cells, 6),
        "field_count_expected": len(field_rows),
        "field_count_observed": observed,
        "field_count_not_applicable": not_applicable,
    }


def _scan_core_csv(dataset: OmicsDataset, field_rows: list[dict[str, Any]], max_rows: int = 0) -> dict[str, Any] | None:
    path = Path(str(dataset.core_csv_path or ""))
    if not path.exists():
        return None
    field_by_name = {str(row.get("field") or ""): row for row in field_rows if row.get("field")}
    valid_cells = 0
    applicable_cells = 0
    missing_cells = 0
    observed_fields: set[str] = set()
    scanned_rows = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = set(reader.fieldnames or [])
        active_fields = []
        not_applicable = 0
        for name, field in field_by_name.items():
            if name in header:
                active_fields.append(name)
                observed_fields.add(name)
            elif str(field.get("applicability") or "all") == "all":
                active_fields.append(name)
            else:
                not_applicable += 1
        for row in reader:
            scanned_rows += 1
            for name in active_fields:
                applicable_cells += 1
                if _is_valid(row.get(name)):
                    valid_cells += 1
                else:
                    missing_cells += 1
            if max_rows and scanned_rows >= max_rows:
                break
    if applicable_cells <= 0:
        return None
    return {
        "source_method": "core_csv_scan",
        "valid_cells": valid_cells,
        "applicable_cells": applicable_cells,
        "missing_cells": missing_cells,
        "completeness_pct": round(valid_cells * 100.0 / applicable_cells, 6),
        "field_count_expected": len(field_rows),
        "field_count_observed": len(observed_fields),
        "field_count_not_applicable": not_applicable,
        "scanned_rows": scanned_rows,
        "scan_is_sampled": bool(max_rows and scanned_rows >= max_rows),
    }


def _from_core_header(path_text: str, row_count: int, field_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if row_count <= 0:
        return None
    header = _read_header(path_text)
    if not header:
        return None
    valid_cells = 0
    applicable_cells = 0
    missing_cells = 0
    observed = 0
    not_applicable = 0
    for field in field_rows:
        name = str(field.get("field") or "")
        if not name:
            continue
        if name in header:
            observed += 1
            applicable_cells += row_count
            valid_cells += row_count
        elif str(field.get("applicability") or "all") != "all":
            not_applicable += 1
        else:
            applicable_cells += row_count
            missing_cells += row_count
    if applicable_cells <= 0:
        return None
    return {
        "source_method": "core_csv_header_presence_fallback",
        "valid_cells": valid_cells,
        "applicable_cells": applicable_cells,
        "missing_cells": missing_cells,
        "completeness_pct": round(valid_cells * 100.0 / applicable_cells, 6),
        "field_count_expected": len(field_rows),
        "field_count_observed": observed,
        "field_count_not_applicable": not_applicable,
    }


class Command(BaseCommand):
    help = "Precompute Species Atlas Core feature completeness into AnalysisArtifact rows."

    def add_arguments(self, parser):
        parser.add_argument("--omics", choices=OMICS_KEYS, default="", help="Optional omics layer.")
        parser.add_argument("--limit", type=int, default=0, help="Limit datasets for smoke testing.")
        parser.add_argument("--force", action="store_true", help="Delete existing atlas artifacts before writing.")
        parser.add_argument("--scan-files", action="store_true", help="Scan Core CSV files instead of reusing summary_payload missingness.")
        parser.add_argument("--max-rows", type=int, default=0, help="Optional row sampling limit when --scan-files is enabled.")
        parser.add_argument("--batch-size", type=int, default=1000)

    def handle(self, *args, **options):
        query = (
            OmicsDataset.objects
            .select_related("species")
            .exclude(core_csv_path="")
            .only("id", "species_id", "species__species_id", "omics_type", "row_count_core", "core_csv_path", "summary_payload")
        )
        if options["omics"]:
            query = query.filter(omics_type=options["omics"])
        query = query.order_by("id")
        if options["limit"]:
            query = query[: max(1, int(options["limit"]))]
        if options["force"]:
            delete_qs = AnalysisArtifact.objects.filter(artifact_type=ARTIFACT_TYPE)
            if options["omics"]:
                delete_qs = delete_qs.filter(omics_type=options["omics"])
            deleted, _ = delete_qs.delete()
            self.stdout.write(f"Deleted existing atlas artifacts: {deleted}")

        field_cache = {omics: _model_fields(omics) for omics in OMICS_KEYS}
        batch = []
        created = 0
        skipped = 0
        failed = 0

        def flush() -> None:
            nonlocal created, batch
            if not batch:
                return
            AnalysisArtifact.objects.bulk_create(batch, batch_size=max(1, int(options["batch_size"])), ignore_conflicts=True)
            created += len(batch)
            batch = []

        existing_dataset_ids = set()
        if not options["force"]:
            existing_dataset_ids = set(
                AnalysisArtifact.objects
                .filter(artifact_type=ARTIFACT_TYPE, dataset__isnull=False)
                .values_list("dataset_id", flat=True)
            )
        processed = 0
        if not options["scan_files"]:
            query = (
                OmicsDataset.objects
                .select_related("species")
                .exclude(core_csv_path="")
                .values(
                    "id",
                    "species_id",
                    "species__species_id",
                    "omics_type",
                    "row_count_core",
                    "core_csv_path",
                    "summary_payload__missingness",
                )
                .order_by("id")
            )
            if options["omics"]:
                query = query.filter(omics_type=options["omics"])
            if options["limit"]:
                query = query[: max(1, int(options["limit"]))]
            for dataset in query.iterator(chunk_size=1000):
                processed += 1
                dataset_id = int(dataset["id"])
                if not options["force"] and dataset_id in existing_dataset_ids:
                    skipped += 1
                    continue
                omics_type = str(dataset["omics_type"])
                field_rows = field_cache.get(omics_type) or []
                row_count = int(dataset.get("row_count_core") or 0)
                header = _read_header(dataset.get("core_csv_path") or "")
                metrics = _from_missingness_rows(dataset.get("summary_payload__missingness"), row_count, field_rows, header=header)
                if not metrics:
                    metrics = _from_core_header(dataset.get("core_csv_path") or "", row_count, field_rows)
                if not metrics:
                    failed += 1
                    continue
                species_id_text = str(dataset.get("species__species_id") or "")
                payload = {
                    "schema_version": "atlas_completeness_v1",
                    "species_id": species_id_text,
                    "omics": omics_type,
                    **metrics,
                    "source_object": dataset.get("core_csv_path") or "",
                    "source_sha256": _source_signature(dataset.get("core_csv_path") or "", fast_token=str(dataset.get("row_count_core") or "")),
                }
                batch.append(AnalysisArtifact(
                    artifact_id=f"atlas_core_complete:{dataset_id}",
                    species_id=int(dataset["species_id"]),
                    dataset_id=dataset_id,
                    omics_type=omics_type,
                    artifact_type=ARTIFACT_TYPE,
                    payload_json=payload,
                    version="atlas_completeness_v1",
                ))
                if len(batch) >= max(1, int(options["batch_size"])):
                    flush()
                    self.stdout.write(f"Processed {processed} datasets...")
            flush()
            self.stdout.write(self.style.SUCCESS(
                f"Species Atlas metrics completed. queued_created={created} skipped={skipped} failed={failed}"
            ))
            return

        for dataset in query.iterator(chunk_size=1000):
            processed += 1
            if not options["force"] and dataset.id in existing_dataset_ids:
                skipped += 1
                continue
            field_rows = field_cache.get(dataset.omics_type) or []
            if options["scan_files"]:
                metrics = _scan_core_csv(dataset, field_rows, max_rows=max(0, int(options["max_rows"] or 0)))
            else:
                metrics = _from_summary_payload(dataset, field_rows) or _scan_core_csv(dataset, field_rows, max_rows=max(0, int(options["max_rows"] or 0)))
            if not metrics:
                failed += 1
                continue
            payload = {
                "schema_version": "atlas_completeness_v1",
                "species_id": dataset.species.species_id,
                "omics": dataset.omics_type,
                **metrics,
                "source_object": dataset.core_csv_path,
                    "source_sha256": _source_signature(dataset.core_csv_path),
            }
            batch.append(AnalysisArtifact(
                artifact_id=f"atlas_core_complete:{dataset.id}",
                species_id=dataset.species_id,
                dataset_id=dataset.id,
                omics_type=dataset.omics_type,
                artifact_type=ARTIFACT_TYPE,
                payload_json=payload,
                version="atlas_completeness_v1",
            ))
            if len(batch) >= max(1, int(options["batch_size"])):
                flush()
                self.stdout.write(f"Processed {processed} datasets...")
        flush()

        self.stdout.write(self.style.SUCCESS(
            f"Species Atlas metrics completed. queued_created={created} skipped={skipped} failed={failed}"
        ))
