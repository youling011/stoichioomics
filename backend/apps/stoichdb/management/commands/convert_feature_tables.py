from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from django.core.management.base import BaseCommand, CommandError

from backend.apps.stoichdb.model_release_pipeline_utils import (
    count_csv_rows_fast,
    read_header,
    release_dataset_rows,
    sha256_file,
    storage_object_for,
    storage_path,
    upsert_storage_object_for_file,
    write_csv,
    write_json,
)
from backend.apps.stoichdb.models import FileQCResult, ReleaseQCResult


def csv_to_parquet_stream(source_path, parquet_path, header, compression, dry_run=False):
    reader = pacsv.open_csv(
        source_path,
        read_options=pacsv.ReadOptions(use_threads=True),
        convert_options=pacsv.ConvertOptions(column_types={col: pa.string() for col in header}),
    )
    rows = 0
    columns = len(header)
    writer = None
    try:
        for batch in reader:
            rows += batch.num_rows
            columns = batch.num_columns
            if dry_run:
                continue
            table = pa.Table.from_batches([batch])
            if writer is None:
                parquet_path.parent.mkdir(parents=True, exist_ok=True)
                writer = pq.ParquetWriter(parquet_path, table.schema, compression=compression)
            writer.write_table(table)
    finally:
        if writer is not None:
            writer.close()
    return rows, columns


def upsert_file_qc(release, storage_object, check_name, status, reason_code, metrics, details):
    obj = FileQCResult.objects.filter(release=release, storage_object=storage_object, check_name=check_name).order_by("-created_at").first()
    if obj is None:
        obj = FileQCResult(release=release, storage_object=storage_object, check_name=check_name)
    obj.status = status
    obj.reason_code = reason_code
    obj.metrics_json = metrics
    obj.threshold_json = {"parquet_rows_must_match_csv": True, "parquet_columns_must_match_csv": True}
    obj.details_json = details
    obj.save()
    return obj


class Command(BaseCommand):
    help = "Convert model-organism feature CSV files to Parquet and register StorageObject records."

    def add_arguments(self, parser):
        parser.add_argument("--release", required=True)
        parser.add_argument("--format", choices=["parquet"], default="parquet")
        parser.add_argument("--compression", default="zstd")
        parser.add_argument("--scope", choices=["included"], default="included")
        parser.add_argument("--products", default="core,full")
        parser.add_argument("--out", default="")
        parser.add_argument("--limit-species", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--resume", action="store_true")

    def handle(self, *args, **options):
        release, rows = release_dataset_rows(options["release"], scope=options["scope"])
        project_root = Path(__file__).resolve().parents[5]
        out_root = Path(options["out"]) if options["out"] else project_root / "data" / "features_parquet" / release.release_id
        report_root = project_root / "data" / "model_organism_release_hardening" / "S4_S5_schema_qc_parquet_20260801_010000" / ("parquet_dry_run" if options["dry_run"] else "parquet_formal")
        report_root.mkdir(parents=True, exist_ok=True)
        products = [x.strip() for x in options["products"].split(",") if x.strip()]
        started_at = datetime.now(timezone.utc).isoformat()

        allowed_species = None
        if options["limit_species"]:
            allowed_species = sorted({rd.species_id_text for rd in rows})[: options["limit_species"]]
            allowed_species = set(allowed_species)

        targets = []
        for rd in rows:
            if allowed_species is not None and rd.species_id_text not in allowed_species:
                continue
            for product in products:
                storage = storage_object_for(rd, product)
                if storage is not None:
                    targets.append((rd, product, storage))

        result_rows = []
        failures = []
        status_counts = Counter()
        for idx, (rd, product, storage) in enumerate(targets, 1):
            source_path = storage_path(storage)
            parquet_path = out_root / rd.species_id_text / rd.omics_type / f"{product}.parquet"
            status = "pass"
            reason = "ok"
            details = {}
            metrics = {
                "species_id": rd.species_id_text,
                "dataset_id": rd.dataset_id_text,
                "omics_type": rd.omics_type,
                "product_type": product,
                "source_storage_key": storage.logical_key,
                "source_path": str(source_path),
                "parquet_path": str(parquet_path),
                "compression": options["compression"],
            }
            parquet_object = None
            try:
                if not source_path.exists():
                    raise FileNotFoundError(str(source_path))
                header = read_header(source_path)
                if not header:
                    raise CommandError(f"empty header: {source_path}")
                csv_rows = count_csv_rows_fast(source_path)
                metrics["csv_rows"] = csv_rows
                metrics["csv_columns"] = len(header)
                metrics["source_sha256"] = storage.sha256
                if options["dry_run"]:
                    parquet_rows, parquet_columns = csv_to_parquet_stream(
                        source_path,
                        parquet_path,
                        header,
                        options["compression"],
                        dry_run=True,
                    )
                    metrics["dry_run_arrow_rows"] = parquet_rows
                    metrics["dry_run_arrow_columns"] = parquet_columns
                elif options["resume"] and parquet_path.exists():
                    parquet_file = pq.ParquetFile(parquet_path)
                    parquet_rows = parquet_file.metadata.num_rows
                    parquet_columns = parquet_file.metadata.num_columns
                else:
                    parquet_rows, parquet_columns = csv_to_parquet_stream(
                        source_path,
                        parquet_path,
                        header,
                        options["compression"],
                        dry_run=False,
                    )
                metrics["parquet_rows"] = parquet_rows
                metrics["parquet_columns"] = parquet_columns
                if parquet_rows != csv_rows:
                    status = "fail"
                    reason = "row_count_mismatch"
                elif parquet_columns != len(header):
                    status = "fail"
                    reason = "column_count_mismatch"
                if not options["dry_run"] and parquet_path.exists():
                    parquet_sha = sha256_file(parquet_path)
                    metrics["parquet_size_bytes"] = parquet_path.stat().st_size
                    metrics["parquet_sha256"] = parquet_sha
                    parquet_object = upsert_storage_object_for_file(
                        parquet_path,
                        project_root,
                        schema_version=f"{rd.omics_type}_{product}_parquet_v1",
                        status="registered" if status == "pass" else "qc_failed",
                        metadata={
                            "stage": "S5_parquet_conversion",
                            "release_id": release.release_id,
                            "species_id": rd.species_id_text,
                            "dataset_id": rd.dataset_id_text,
                            "omics_type": rd.omics_type,
                            "product_type": product,
                            "source_storage_key": storage.logical_key,
                            "csv_rows": csv_rows,
                            "parquet_rows": parquet_rows,
                            "compression": options["compression"],
                        },
                        sha256=parquet_sha,
                    )
                    metadata = dict(rd.metadata_json or {})
                    storage_meta = dict(metadata.get("storage_objects") or {})
                    storage_meta[f"parquet_{product}"] = parquet_object.logical_key
                    metadata["storage_objects"] = storage_meta
                    rd.metadata_json = metadata
                    rd.save(update_fields=["metadata_json", "updated_at"])
                    upsert_file_qc(release, parquet_object, "parquet_conversion", status, reason, metrics, details)
            except Exception as exc:
                status = "fail"
                reason = exc.__class__.__name__
                details["error"] = str(exc)
                failures.append({
                    "species_id": rd.species_id_text,
                    "dataset_id": rd.dataset_id_text,
                    "omics_type": rd.omics_type,
                    "product_type": product,
                    "source_path": str(source_path),
                    "parquet_path": str(parquet_path),
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                })
            status_counts[status] += 1
            result_rows.append({
                "species_id": rd.species_id_text,
                "dataset_id": rd.dataset_id_text,
                "omics_type": rd.omics_type,
                "product_type": product,
                "source_path": str(source_path),
                "parquet_path": str(parquet_path),
                "status": status,
                "reason_code": reason,
                "csv_rows": metrics.get("csv_rows", ""),
                "parquet_rows": metrics.get("parquet_rows", ""),
                "csv_columns": metrics.get("csv_columns", ""),
                "parquet_columns": metrics.get("parquet_columns", ""),
                "parquet_size_bytes": metrics.get("parquet_size_bytes", ""),
            })
            if idx == 1 or idx % 100 == 0 or idx == len(targets):
                self.stdout.write(f"Parquet convert {idx}/{len(targets)} pass={status_counts['pass']} fail={status_counts['fail']}")

        gate_status = "pass" if not failures and status_counts["fail"] == 0 else "fail"
        summary = {
            "stage": "S5_parquet_conversion",
            "release_id": release.release_id,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": bool(options["dry_run"]),
            "products": products,
            "limit_species": options["limit_species"],
            "targets": len(targets),
            "pass": status_counts["pass"],
            "fail": status_counts["fail"],
            "failure_rows": len(failures),
            "out_root": str(out_root),
            "compression": options["compression"],
        }
        if not options["dry_run"]:
            ReleaseQCResult.objects.update_or_create(
                release=release,
                gate="S5_parquet_conversion",
                defaults={"status": gate_status, "summary_json": summary, "approved_by": ""},
            )
        write_csv(report_root / "parquet_conversion_results.csv", result_rows, ["species_id", "dataset_id", "omics_type", "product_type", "source_path", "parquet_path", "status", "reason_code", "csv_rows", "parquet_rows", "csv_columns", "parquet_columns", "parquet_size_bytes"])
        write_csv(report_root / "parquet_conversion_failures.csv", failures, ["species_id", "dataset_id", "omics_type", "product_type", "source_path", "parquet_path", "error_type", "error"])
        write_json(report_root / "summary.json", summary)
        self.stdout.write(str(summary))
