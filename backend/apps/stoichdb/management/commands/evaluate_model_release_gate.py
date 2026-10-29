from __future__ import annotations
from backend.apps.stoichdb.feature_sources import io as feature_io

from collections import Counter, defaultdict
from datetime import datetime, timezone
from backend.apps.common.host_paths import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from backend.apps.stoichdb import model_release_runtime
from backend.apps.stoichdb.model_release_pipeline_utils import (
    sha256_file,
    upsert_storage_object_for_file,
    write_json,
)
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


PASSISH_SPECIES_QC = {"pass", "pass_with_warning"}


def status_summary(queryset, *fields: str) -> list[dict[str, Any]]:
    counts = Counter()
    for row in queryset.values(*fields):
        key = tuple(str(row.get(field) or "") for field in fields)
        counts[key] += 1
    return [
        {**{field: key[idx] for idx, field in enumerate(fields)}, "count": count}
        for key, count in sorted(counts.items())
    ]


def gate(status: bool, summary: dict[str, Any], *, required: bool = True) -> dict[str, Any]:
    return {"status": "pass" if status else ("warning" if not required else "fail"), "required": required, **summary}


class Command(BaseCommand):
    help = "Evaluate S6-S8 runtime, release-gate and platform-display readiness for the model-organism release."

    def add_arguments(self, parser):
        parser.add_argument("--release", default=model_release_runtime.MODEL_RELEASE_ID)
        parser.add_argument("--out", default="")
        parser.add_argument("--publish", action="store_true", help="Mark the scoped model release as published when all required gates pass.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        release_id = options["release"]
        try:
            release = DataRelease.objects.get(release_id=release_id)
        except DataRelease.DoesNotExist as exc:
            raise CommandError(f"Unknown release: {release_id}") from exc

        project_root = Path(__file__).resolve().parents[5]
        out_dir = Path(options["out"]) if options["out"] else project_root / "data" / "model_organism_release_hardening" / "S6_S8_runtime_gate_platform_20260801_013000"
        out_dir.mkdir(parents=True, exist_ok=True)

        started_at = datetime.now(timezone.utc).isoformat()
        included_species = ReleaseSpecies.objects.filter(release=release, inclusion_status="included")
        missing_species = ReleaseSpecies.objects.filter(release=release, inclusion_status="missing")
        included_datasets = ReleaseDataset.objects.filter(release=release, membership_status="included")
        schema_qs = SchemaRegistry.objects.filter(schema_id__startswith=f"{release.release_id}:")

        storage_keys = []
        storage_by_product = Counter()
        for rd in included_datasets.only("metadata_json"):
            for product, key in ((rd.metadata_json or {}).get("storage_objects") or {}).items():
                if key:
                    storage_keys.append(key)
                    storage_by_product[product] += 1
        storage_qs = StorageObject.objects.filter(logical_key__in=storage_keys)
        storage_present = storage_qs.count()
        storage_sha = storage_qs.exclude(sha256="").count()

        csv_qc = FileQCResult.objects.filter(release=release, check_name="feature_csv_integrity")
        parquet_qc = FileQCResult.objects.filter(release=release, check_name="parquet_conversion")
        release_qc = ReleaseQCResult.objects.filter(release=release)

        runtime_smoke = []
        smoke_failures = []
        for omics in ("genome", "transcriptome", "proteome"):
            rd = included_datasets.filter(omics_type=omics, dataset__isnull=False).select_related("dataset").first()
            if not rd or not rd.dataset:
                smoke_failures.append({"omics": omics, "reason": "no_dataset"})
                continue
            rows, resolved = model_release_runtime.read_feature_rows(rd.dataset, "core", limit=3)
            item = {
                "species_id": rd.species_id_text,
                "omics": omics,
                "source": resolved.get("source"),
                "format": resolved.get("format"),
                "logical_key": resolved.get("logical_key"),
                "rows_read": len(rows),
                "fallback_events": resolved.get("fallback_events") or [],
            }
            runtime_smoke.append(item)
            logical = feature_io.logical_source(resolved.get("path")) if resolved.get("path") else None
            verified_logical = logical is not None and logical.record["row_count"] > 0
            if len(rows) == 0 or (resolved.get("format") != "parquet" and not verified_logical):
                smoke_failures.append({**item, "reason": "parquet_smoke_failed"})

        required_gates = {
            "G1_scope_membership": gate(
                included_species.count() == release.species_count
                and not included_species.exclude(qc_status__in=PASSISH_SPECIES_QC).exists()
                and missing_species.count() >= 0,
                {
                    "included_species": included_species.count(),
                    "release_species_count": release.species_count,
                    "missing_species_retained_for_traceability": missing_species.count(),
                    "species_status": status_summary(ReleaseSpecies.objects.filter(release=release), "inclusion_status", "qc_status"),
                },
            ),
            "G2_dataset_membership": gate(
                included_datasets.count() == release.dataset_count
                and included_datasets.filter(dataset__isnull=True).count() == 0,
                {
                    "included_datasets": included_datasets.count(),
                    "release_dataset_count": release.dataset_count,
                    "dataset_status": status_summary(ReleaseDataset.objects.filter(release=release), "membership_status", "omics_type"),
                },
            ),
            "G3_schema_registry": gate(
                schema_qs.filter(status="active").count() >= 6,
                {
                    "active_schema_count": schema_qs.filter(status="active").count(),
                    "total_schema_count": schema_qs.count(),
                    "required_products": ["genome/core", "genome/full", "transcriptome/core", "transcriptome/full", "proteome/core", "proteome/full"],
                },
            ),
            "G4_storage_checksums": gate(
                storage_present == len(set(storage_keys)) and storage_sha == storage_present,
                {
                    "storage_keys_referenced": len(set(storage_keys)),
                    "storage_objects_present": storage_present,
                    "storage_objects_with_sha256": storage_sha,
                    "storage_by_product": dict(storage_by_product),
                },
            ),
            "G5_file_qc": gate(
                csv_qc.filter(status="fail").count() == 0
                and parquet_qc.filter(status="fail").count() == 0
                and csv_qc.filter(status="pass").count() > 0
                and parquet_qc.filter(status="pass").count() > 0,
                {
                    "feature_csv_pass": csv_qc.filter(status="pass").count(),
                    "feature_csv_fail": csv_qc.filter(status="fail").count(),
                    "parquet_pass": parquet_qc.filter(status="pass").count(),
                    "parquet_fail": parquet_qc.filter(status="fail").count(),
                },
            ),
            "G6_runtime_parquet_read": gate(
                not smoke_failures,
                {"runtime_smoke": runtime_smoke, "failures": smoke_failures},
            ),
            "G7_previous_release_gates": gate(
                release_qc.filter(gate__in=["S4_file_qc", "S5_parquet_conversion"], status="fail").count() == 0
                and release_qc.filter(gate="S4_file_qc", status="pass").exists()
                and release_qc.filter(gate="S5_parquet_conversion", status="pass").exists(),
                {
                    "release_qc": [
                        {"gate": item.gate, "status": item.status, "summary": item.summary_json or {}}
                        for item in release_qc.order_by("gate")
                    ],
                },
            ),
        }

        all_required_pass = all(item["status"] == "pass" for item in required_gates.values() if item.get("required"))
        manifest = {
            "stage": "S6_S8_runtime_gate_platform",
            "release_id": release.release_id,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": bool(options["dry_run"]),
            "publish_requested": bool(options["publish"]),
            "all_required_gates_pass": all_required_pass,
            "gate_summary": required_gates,
            "database_counts": {
                "species": release.species_count,
                "datasets": release.dataset_count,
                "omics_dataset_rows_global": OmicsDataset.objects.count(),
                "storage_objects_global": StorageObject.objects.count(),
            },
        }
        manifest_path = out_dir / "S6_S8_release_gate_manifest.json"
        write_json(manifest_path, manifest)
        manifest_sha = sha256_file(manifest_path)
        report_object = None
        if not options["dry_run"]:
            report_object = upsert_storage_object_for_file(
                manifest_path,
                project_root,
                schema_version="S6_S8_release_gate_manifest_v1",
                status="registered" if all_required_pass else "qc_failed",
                metadata={"stage": "S6_S8_runtime_gate_platform", "release_id": release.release_id},
                sha256=manifest_sha,
            )
            ReleaseQCResult.objects.update_or_create(
                release=release,
                gate="S7_release_gate",
                defaults={
                    "status": "pass" if all_required_pass else "fail",
                    "summary_json": manifest,
                    "report_object": report_object,
                    "approved_by": "automated_gate",
                },
            )
            metadata = dict(release.metadata_json or {})
            metadata["S6_S8_release_gate"] = {
                "status": "pass" if all_required_pass else "fail",
                "manifest_path": str(manifest_path),
                "manifest_sha256": manifest_sha,
                "published_by_command": bool(options["publish"] and all_required_pass),
            }
            release.metadata_json = metadata
            release.manifest_json = {**(release.manifest_json or {}), "S6_S8_release_gate": manifest}
            release.manifest_sha256 = manifest_sha
            if options["publish"] and all_required_pass:
                release.status = "published"
                release.is_immutable = True
                release.published_at = datetime.now(timezone.utc)
                release.version = release.version or "2026.08.model"
                release.schema_version = release.schema_version or "model_feature_schema_v1"
                release.pipeline_version = release.pipeline_version or "S0-S8_model_release_pipeline_v1"
            elif all_required_pass and release.status == "candidate":
                release.status = "validated"
            release.save()

        self.stdout.write(f"S6-S8 gates {'PASS' if all_required_pass else 'FAIL'} for {release.release_id}")
        self.stdout.write(f"Manifest: {manifest_path}")
        self.stdout.write(f"Manifest SHA256: {manifest_sha}")
        if report_object is not None:
            self.stdout.write(f"Report StorageObject: {report_object.logical_key}")
        if not all_required_pass:
            for name, payload in required_gates.items():
                if payload["status"] != "pass":
                    self.stdout.write(f"Gate {name}: {payload['status']}")
