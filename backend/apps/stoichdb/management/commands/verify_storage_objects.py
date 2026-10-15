from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from backend.apps.stoichdb.model_release_pipeline_utils import (
    count_csv_rows_fast,
    read_header,
    release_dataset_rows,
    sha256_file,
    storage_object_for,
    storage_path,
    write_csv,
    write_json,
)
from backend.apps.stoichdb.models import FileQCResult, ReleaseQCResult, SchemaRegistry


def upsert_file_qc(release, storage_object, check_name, status, reason_code, metrics, thresholds, details):
    obj = FileQCResult.objects.filter(release=release, storage_object=storage_object, check_name=check_name).order_by("-created_at").first()
    if obj is None:
        obj = FileQCResult(release=release, storage_object=storage_object, check_name=check_name)
    obj.status = status
    obj.reason_code = reason_code
    obj.metrics_json = metrics
    obj.threshold_json = thresholds
    obj.details_json = details
    obj.save()
    return obj


class Command(BaseCommand):
    help = "Verify model-organism StorageObject CSV files and write FileQCResult rows."

    def add_arguments(self, parser):
        parser.add_argument("--release", required=True)
        parser.add_argument("--checks", default="exists,size,header,row_count,schema,checksum")
        parser.add_argument("--products", default="core,full")
        parser.add_argument("--out", required=True)
        parser.add_argument("--resume", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        release, rows = release_dataset_rows(options["release"], scope="included")
        products = [x.strip() for x in options["products"].split(",") if x.strip()]
        checks = {x.strip() for x in options["checks"].split(",") if x.strip()}
        out_dir = Path(options["out"])
        out_dir.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(timezone.utc).isoformat()
        result_rows = []
        bad_rows = []
        status_counts = Counter()

        schema_headers = {}
        for schema in SchemaRegistry.objects.filter(schema_id__startswith=f"{release.release_id}:"):
            schema_headers[(schema.omics_type, schema.product_type)] = [col.get("name", "") for col in schema.columns_json]

        total_targets = 0
        for rd in rows:
            for product in products:
                if storage_object_for(rd, product):
                    total_targets += 1

        processed = 0
        for rd in rows:
            for product in products:
                storage = storage_object_for(rd, product)
                if storage is None:
                    continue
                processed += 1
                path = storage_path(storage)
                expected_rows = int(rd.row_count_core if product == "core" else rd.row_count_full)
                metrics = {
                    "species_id": rd.species_id_text,
                    "dataset_id": rd.dataset_id_text,
                    "omics_type": rd.omics_type,
                    "product_type": product,
                    "expected_rows": expected_rows,
                    "storage_size_bytes": storage.size_bytes,
                    "storage_sha256_present": bool(storage.sha256),
                    "path": str(path),
                }
                details = {}
                failures = []
                header = []
                actual_rows = None

                exists = path.exists()
                metrics["exists"] = exists
                if "exists" in checks and not exists:
                    failures.append("path_not_found")
                if exists:
                    size = path.stat().st_size
                    metrics["actual_size_bytes"] = size
                    if "size" in checks and size <= 0:
                        failures.append("empty_file")
                    if "header" in checks or "schema" in checks:
                        try:
                            header = read_header(path)
                            metrics["column_count"] = len(header)
                        except Exception as exc:
                            failures.append("header_read_failed")
                            details["header_error"] = str(exc)
                    if "row_count" in checks:
                        try:
                            actual_rows = count_csv_rows_fast(path)
                            metrics["actual_rows"] = actual_rows
                            metrics["row_count_delta"] = actual_rows - expected_rows
                            if expected_rows and actual_rows != expected_rows:
                                failures.append("row_count_mismatch")
                        except Exception as exc:
                            failures.append("row_count_failed")
                            details["row_count_error"] = str(exc)
                    if "checksum" in checks:
                        try:
                            actual_sha = sha256_file(path)
                            metrics["actual_sha256"] = actual_sha
                            if storage.sha256 and actual_sha != storage.sha256:
                                failures.append("sha256_mismatch")
                        except Exception as exc:
                            failures.append("sha256_failed")
                            details["sha256_error"] = str(exc)
                    if "schema" in checks:
                        expected_header = schema_headers.get((rd.omics_type, product), [])
                        metrics["schema_registered"] = bool(expected_header)
                        if not expected_header:
                            failures.append("schema_missing")
                        elif header != expected_header:
                            failures.append("schema_header_mismatch")
                            details["expected_header"] = expected_header
                            details["actual_header"] = header

                status = "pass" if not failures else "fail"
                reason_code = "ok" if not failures else ";".join(sorted(set(failures)))
                status_counts[status] += 1
                row = {
                    "species_id": rd.species_id_text,
                    "dataset_id": rd.dataset_id_text,
                    "omics_type": rd.omics_type,
                    "product_type": product,
                    "logical_key": storage.logical_key,
                    "path": str(path),
                    "status": status,
                    "reason_code": reason_code,
                    "expected_rows": expected_rows,
                    "actual_rows": actual_rows if actual_rows is not None else "",
                    "size_bytes": metrics.get("actual_size_bytes", ""),
                    "column_count": metrics.get("column_count", ""),
                }
                result_rows.append(row)
                if failures:
                    bad_rows.append(row)
                if not options["dry_run"]:
                    upsert_file_qc(
                        release,
                        storage,
                        "feature_csv_integrity",
                        status,
                        reason_code,
                        metrics,
                        {"row_count_must_match": True, "sha256_must_match": True, "schema_header_must_match": True},
                        details,
                    )
                if processed == 1 or processed % 250 == 0 or processed == total_targets:
                    self.stdout.write(f"File QC {processed}/{total_targets} pass={status_counts['pass']} fail={status_counts['fail']}")

        gate_status = "pass" if not bad_rows else "fail"
        summary = {
            "stage": "S4_file_qc",
            "release_id": release.release_id,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": bool(options["dry_run"]),
            "targets": total_targets,
            "pass": status_counts["pass"],
            "fail": status_counts["fail"],
            "bad_file_rows": len(bad_rows),
            "checks": sorted(checks),
        }
        if not options["dry_run"]:
            ReleaseQCResult.objects.update_or_create(
                release=release,
                gate="S4_file_qc",
                defaults={"status": gate_status, "summary_json": summary, "approved_by": ""},
            )
        write_csv(out_dir / "file_qc_results.csv", result_rows, ["species_id", "dataset_id", "omics_type", "product_type", "logical_key", "path", "status", "reason_code", "expected_rows", "actual_rows", "size_bytes", "column_count"])
        write_csv(out_dir / "bad_files.csv", bad_rows, ["species_id", "dataset_id", "omics_type", "product_type", "logical_key", "path", "status", "reason_code", "expected_rows", "actual_rows", "size_bytes", "column_count"])
        write_json(out_dir / "summary.json", summary)
        self.stdout.write(str(summary))
