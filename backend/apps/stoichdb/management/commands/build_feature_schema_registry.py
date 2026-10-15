from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from backend.apps.stoichdb.model_release_pipeline_utils import (
    read_header,
    release_dataset_rows,
    sample_column_stats,
    storage_object_for,
    storage_path,
    write_csv,
    write_json,
)
from backend.apps.stoichdb.models import SchemaRegistry


class Command(BaseCommand):
    help = "Build SchemaRegistry entries for model-organism feature CSV files."

    def add_arguments(self, parser):
        parser.add_argument("--release", required=True)
        parser.add_argument("--omics", default="all", help="all or comma-separated genome,transcriptome,proteome")
        parser.add_argument("--products", default="core,full")
        parser.add_argument("--out", required=True)
        parser.add_argument("--sample-rows", type=int, default=2000)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        release, rows = release_dataset_rows(options["release"], scope="included")
        products = [x.strip() for x in options["products"].split(",") if x.strip()]
        omics_filter = None if options["omics"] == "all" else {x.strip() for x in options["omics"].split(",") if x.strip()}
        out_dir = Path(options["out"])
        out_dir.mkdir(parents=True, exist_ok=True)

        groups: dict[tuple[str, str], dict] = {}
        file_rows: list[dict] = []
        drift_rows: list[dict] = []
        started_at = datetime.now(timezone.utc).isoformat()

        for idx, rd in enumerate(rows, 1):
            if omics_filter and rd.omics_type not in omics_filter:
                continue
            for product in products:
                storage = storage_object_for(rd, product)
                if storage is None:
                    continue
                path = storage_path(storage)
                if not path.exists():
                    continue
                key = (rd.omics_type, product)
                group = groups.setdefault(
                    key,
                    {
                        "headers": Counter(),
                        "files": 0,
                        "rows_expected": 0,
                        "columns_seen": defaultdict(lambda: {"files": 0, "non_null": 0, "null": 0, "numeric": 0, "min": None, "max": None, "examples": []}),
                        "sample_files": [],
                    },
                )
                header = read_header(path)
                header_key = "\t".join(header)
                group["headers"][header_key] += 1
                group["files"] += 1
                group["rows_expected"] += int(rd.row_count_core if product == "core" else rd.row_count_full)
                if len(group["sample_files"]) < 10:
                    group["sample_files"].append(str(path))
                stats = sample_column_stats(path, options["sample_rows"])
                for col, col_stats in stats.items():
                    target = group["columns_seen"][col]
                    target["files"] += 1
                    target["non_null"] += int(col_stats["non_null"])
                    target["null"] += int(col_stats["null"])
                    target["numeric"] += int(col_stats["numeric"])
                    if col_stats["min"] is not None:
                        target["min"] = col_stats["min"] if target["min"] is None else min(target["min"], col_stats["min"])
                    if col_stats["max"] is not None:
                        target["max"] = col_stats["max"] if target["max"] is None else max(target["max"], col_stats["max"])
                    for example in col_stats["examples"]:
                        if len(target["examples"]) < 5 and example not in target["examples"]:
                            target["examples"].append(example)
                file_rows.append({
                    "species_id": rd.species_id_text,
                    "dataset_id": rd.dataset_id_text,
                    "omics_type": rd.omics_type,
                    "product_type": product,
                    "path": str(path),
                    "column_count": len(header),
                    "header_signature": header_key,
                })
                if idx == 1 or idx % 250 == 0:
                    self.stdout.write(f"Schema profiling dataset {idx}/{len(rows)}")

        registry_rows = []
        for (omics_type, product), group in sorted(groups.items()):
            canonical_header, canonical_count = group["headers"].most_common(1)[0]
            canonical_columns = canonical_header.split("\t") if canonical_header else []
            for signature, count in group["headers"].items():
                if signature != canonical_header:
                    drift_rows.append({
                        "omics_type": omics_type,
                        "product_type": product,
                        "header_count": count,
                        "canonical_count": canonical_count,
                        "header_signature": signature,
                    })
            columns_json = []
            for pos, col in enumerate(canonical_columns):
                stat = group["columns_seen"].get(col, {})
                observed = int(stat.get("files", 0))
                sampled_non_null = int(stat.get("non_null", 0))
                sampled_null = int(stat.get("null", 0))
                numeric = int(stat.get("numeric", 0))
                inferred = "number" if sampled_non_null and numeric / max(sampled_non_null, 1) >= 0.95 else "string"
                columns_json.append({
                    "name": col,
                    "position": pos,
                    "inferred_type": inferred,
                    "nullable": sampled_null > 0 or observed < group["files"],
                    "observed_files": observed,
                    "sampled_non_null": sampled_non_null,
                    "sampled_null": sampled_null,
                    "numeric_observations": numeric,
                    "min": stat.get("min"),
                    "max": stat.get("max"),
                    "examples": stat.get("examples", []),
                })
            schema_id = f"{release.release_id}:{omics_type}:{product}:csv:v1"
            rules_json = {
                "release_id": release.release_id,
                "canonical_header_count": canonical_count,
                "header_variant_count": len(group["headers"]),
                "file_count": group["files"],
                "rows_expected": group["rows_expected"],
                "sample_rows_per_file": options["sample_rows"],
                "sample_files": group["sample_files"],
            }
            status = "active" if not drift_rows else "active_with_drift_report"
            if not options["dry_run"]:
                SchemaRegistry.objects.update_or_create(
                    schema_id=schema_id,
                    defaults={
                        "omics_type": omics_type,
                        "product_type": product,
                        "version": "v1",
                        "status": status,
                        "columns_json": columns_json,
                        "rules_json": rules_json,
                        "metadata_json": {"stage": "S4_schema_profiling", "generated_at": datetime.now(timezone.utc).isoformat()},
                    },
                )
            registry_rows.append({
                "schema_id": schema_id,
                "omics_type": omics_type,
                "product_type": product,
                "status": status,
                "file_count": group["files"],
                "column_count": len(canonical_columns),
                "header_variant_count": len(group["headers"]),
                "rows_expected": group["rows_expected"],
            })

        write_csv(out_dir / "schema_registry_summary.csv", registry_rows, ["schema_id", "omics_type", "product_type", "status", "file_count", "column_count", "header_variant_count", "rows_expected"])
        write_csv(out_dir / "schema_file_profiles.csv", file_rows, ["species_id", "dataset_id", "omics_type", "product_type", "path", "column_count", "header_signature"])
        write_csv(out_dir / "schema_header_drift.csv", drift_rows, ["omics_type", "product_type", "header_count", "canonical_count", "header_signature"])
        summary = {
            "stage": "S4_schema_profiling",
            "release_id": release.release_id,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": bool(options["dry_run"]),
            "schema_entries": len(registry_rows),
            "profiled_files": len(file_rows),
            "header_drift_rows": len(drift_rows),
            "outputs": {
                "schema_registry_summary": str(out_dir / "schema_registry_summary.csv"),
                "schema_file_profiles": str(out_dir / "schema_file_profiles.csv"),
                "schema_header_drift": str(out_dir / "schema_header_drift.csv"),
            },
        }
        write_json(out_dir / "summary.json", summary)
        self.stdout.write(str(summary))
