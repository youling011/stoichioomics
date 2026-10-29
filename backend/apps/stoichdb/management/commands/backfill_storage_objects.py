from __future__ import annotations
from backend.apps.stoichdb.feature_sources import io as feature_io

import csv
import hashlib
import json
import mimetypes
from collections import defaultdict
from datetime import datetime, timezone
from backend.apps.common.host_paths import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone as django_timezone

from backend.apps.stoichdb.models import (
    AnalysisArtifact,
    DataRelease,
    FeatureFile,
    OmicsDataset,
    ReleaseDataset,
    ReleaseSpecies,
    Species,
    StorageObject,
)


DEFAULT_RELEASE_ID = "model_organisms_20260731_v1"
CHUNK_SIZE = 1024 * 1024 * 8
ROOT_ALIAS_ORDER = (
    "STOICH_FEATURE_ROOT",
    "STOICH_PROJECT_ROOT",
    "STOICH_PROJECT_DATA_ROOT",
    "STOICHIOOMICS_ROOT",
)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as f:
        return [{k: (v if v is not None else "") for k, v in row.items()} for row in csv.DictReader(f)]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def sha256_file(path: Path) -> str:
    return feature_io.source_sha256(path)

def _legacy_unused_sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with feature_io.open_source(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def safe_rel(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None
    except OSError:
        return None


def logical_key(root_alias: str, relative_path: str, object_uri: str = "") -> str:
    if root_alias and relative_path:
        key = f"local_fs/{root_alias}/{relative_path}"
    else:
        key = f"local_fs/absolute/{object_uri.replace(chr(92), '/')}"
    if len(key) <= 512:
        return key
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"local_fs/path_sha256/{digest}"


def media_for(path: Path) -> tuple[str, str]:
    suffixes = [s.lower() for s in path.suffixes]
    compression = ""
    if suffixes and suffixes[-1] in {".gz", ".zip", ".bz2", ".xz", ".zst"}:
        compression = suffixes[-1].lstrip(".")
    media_type = mimetypes.guess_type(str(path))[0] or ""
    if not media_type:
        if ".csv" in suffixes:
            media_type = "text/csv"
        elif ".json" in suffixes:
            media_type = "application/json"
        elif ".parquet" in suffixes:
            media_type = "application/vnd.apache.parquet"
        else:
            media_type = "application/octet-stream"
    return media_type, compression


class Command(BaseCommand):
    help = "Backfill StorageObject records for the model-organism release scope."

    def add_arguments(self, parser):
        parser.add_argument("--release", default=DEFAULT_RELEASE_ID)
        parser.add_argument("--scope", choices=["model"], default="model")
        parser.add_argument("--s1-dir", default="")
        parser.add_argument("--out", required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--checksum-mode", choices=["none", "sampled", "sha256"], default="none")
        parser.add_argument("--sample", type=int, default=100)
        parser.add_argument("--resume", action="store_true")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--no-artifacts", action="store_true")

    def handle(self, *args, **options):
        release_id = options["release"]
        project_root = Path(__file__).resolve().parents[5]
        s1_dir = Path(options["s1_dir"]) if options["s1_dir"] else project_root / "data" / "model_organism_release_hardening" / "S1_scope_inventory_20260731_041000"
        out_dir = Path(options["out"])
        out_dir.mkdir(parents=True, exist_ok=True)
        membership_path = s1_dir / "membership_seed.csv"
        dataset_seed_path = s1_dir / "omics_dataset_membership_seed.csv"
        if not feature_io.source_exists(membership_path) or not feature_io.source_exists(dataset_seed_path):
            raise CommandError(f"S1 seed files not found in {s1_dir}")

        started_at = datetime.now(timezone.utc).isoformat()
        membership_rows = read_csv_rows(membership_path)
        dataset_rows = read_csv_rows(dataset_seed_path)
        included_species_ids = sorted(
            row["species_id"] for row in membership_rows if row.get("inclusion_status") == "included"
        )
        species_map = {sp.species_id: sp for sp in Species.objects.filter(species_id__in=[r["species_id"] for r in membership_rows])}
        dataset_map = {
            ds.dataset_id: ds
            for ds in OmicsDataset.objects.select_related("species").filter(dataset_id__in=[r["dataset_id"] for r in dataset_rows])
        }

        roots = self._root_map(project_root)
        objects: dict[str, dict[str, Any]] = {}
        missing_refs: list[dict[str, Any]] = []

        for row in dataset_rows:
            if row.get("membership_status") != "included":
                continue
            for product_type, col in (("core", "core_csv_path"), ("full", "full_csv_path")):
                self._add_path_object(
                    objects,
                    missing_refs,
                    roots,
                    row.get(col, ""),
                    source={
                        "source_type": "omics_dataset",
                        "species_id": row.get("species_id", ""),
                        "dataset_id": row.get("dataset_id", ""),
                        "omics_type": row.get("omics_type", ""),
                        "product_type": product_type,
                        "row_count": int(row.get(f"row_count_{product_type}") or 0),
                    },
                )

        datasets_qs = OmicsDataset.objects.filter(species__species_id__in=included_species_ids)
        for ff in FeatureFile.objects.select_related("dataset", "dataset__species").filter(dataset__in=datasets_qs).iterator(chunk_size=options["batch_size"]):
            self._add_path_object(
                objects,
                missing_refs,
                roots,
                ff.path,
                source={
                    "source_type": "feature_file",
                    "species_id": ff.dataset.species.species_id,
                    "dataset_id": ff.dataset.dataset_id,
                    "omics_type": ff.dataset.omics_type,
                    "file_id": ff.file_id,
                    "file_type": ff.file_type,
                    "size_bytes_db": ff.size_bytes,
                },
            )

        if not options["no_artifacts"]:
            for artifact in AnalysisArtifact.objects.select_related("species", "dataset").filter(species__species_id__in=included_species_ids).exclude(path="").iterator(chunk_size=options["batch_size"]):
                self._add_path_object(
                    objects,
                    missing_refs,
                    roots,
                    artifact.path,
                    source={
                        "source_type": "analysis_artifact",
                        "species_id": artifact.species.species_id,
                        "dataset_id": artifact.dataset.dataset_id if artifact.dataset_id else "",
                        "omics_type": artifact.omics_type,
                        "artifact_id": artifact.artifact_id,
                        "artifact_type": artifact.artifact_type,
                        "version": artifact.version,
                    },
                )

        object_rows = list(objects.values())
        object_rows.sort(key=lambda r: r["logical_key"])
        selected_for_hash = self._selected_hash_keys(object_rows, options["checksum_mode"], options["sample"])

        existing_by_key = {}
        if options["resume"] and not options["dry_run"]:
            existing_by_key = {
                obj.logical_key: obj
                for obj in StorageObject.objects.filter(logical_key__in=[row["logical_key"] for row in object_rows])
            }

        hashed = 0
        hash_skipped_resume = 0
        for idx, row in enumerate(object_rows, 1):
            exists = bool(row["exists"])
            if exists and row["logical_key"] in selected_for_hash:
                existing = existing_by_key.get(row["logical_key"])
                if existing and existing.sha256 and int(existing.size_bytes) == int(row["size_bytes"]):
                    row["sha256"] = existing.sha256
                    row["status"] = existing.status
                    hash_skipped_resume += 1
                else:
                    row["sha256"] = sha256_file(Path(row["absolute_path"]))
                    row["status"] = "registered"
                    hashed += 1
            elif exists and options["checksum_mode"] == "none":
                row["status"] = "pending_checksum"
            elif exists:
                row["status"] = "pending_checksum"
            else:
                row["status"] = "missing"
            if idx == 1 or idx % 250 == 0 or idx == len(object_rows):
                self.stdout.write(f"StorageObject scan/hash {idx}/{len(object_rows)} hashed={hashed} missing={len([r for r in object_rows[:idx] if not r['exists']])}")

        summary = {
            "stage": "S3_storage_object_backfill",
            "release_id": release_id,
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "project_root": str(project_root),
            "s1_dir": str(s1_dir),
            "out_dir": str(out_dir),
            "dry_run": bool(options["dry_run"]),
            "checksum_mode": options["checksum_mode"],
            "sample": options["sample"],
            "resume": bool(options["resume"]),
            "included_species_count": len(included_species_ids),
            "membership_seed_rows": len(membership_rows),
            "dataset_seed_rows": len(dataset_rows),
            "storage_object_candidates": len(object_rows),
            "existing_file_objects": sum(1 for row in object_rows if row["exists"]),
            "missing_file_objects": sum(1 for row in object_rows if not row["exists"]),
            "hashed_objects": hashed,
            "hash_skipped_resume": hash_skipped_resume,
            "pending_checksum_objects": sum(1 for row in object_rows if row["status"] == "pending_checksum"),
            "missing_reference_rows": len(missing_refs),
            "root_alias_counts": dict(sorted(self._counter(row["root_alias"] for row in object_rows).items())),
            "status_counts": dict(sorted(self._counter(row["status"] for row in object_rows).items())),
        }

        write_csv(out_dir / "storage_objects_manifest.csv", object_rows, [
            "logical_key",
            "backend",
            "root_alias",
            "relative_path",
            "object_uri",
            "exists",
            "size_bytes",
            "sha256",
            "media_type",
            "compression",
            "schema_version",
            "status",
            "reference_count",
            "absolute_path",
        ])
        write_csv(out_dir / "missing_storage_references.csv", missing_refs, [
            "path",
            "reason",
            "source_type",
            "species_id",
            "dataset_id",
            "omics_type",
            "product_type",
            "file_id",
            "artifact_id",
            "artifact_type",
        ])
        write_json(out_dir / "storage_objects_manifest.json", object_rows)
        write_json(out_dir / "summary.json", summary)

        if not options["dry_run"]:
            release = self._upsert_release(release_id, len(included_species_ids), len(dataset_rows))
            self._upsert_membership(release, membership_rows, dataset_rows, species_map, dataset_map, options["batch_size"])
            created, updated = self._upsert_storage_objects(object_rows, options["batch_size"])
            self._attach_storage_keys_to_release_datasets(release, dataset_rows, object_rows, options["batch_size"])
            summary.update({
                "data_release_pk": release.pk,
                "storage_objects_created": created,
                "storage_objects_updated": updated,
                "release_species_rows_after": ReleaseSpecies.objects.filter(release=release).count(),
                "release_dataset_rows_after": ReleaseDataset.objects.filter(release=release).count(),
                "storage_object_rows_after": StorageObject.objects.count(),
                "storage_object_rows_for_s3_keys_after": StorageObject.objects.filter(logical_key__in=[row["logical_key"] for row in object_rows]).count(),
            })
            write_json(out_dir / "summary.json", summary)

        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        self.stdout.write(self.style.SUCCESS("S3 StorageObject backfill completed."))

    def _root_map(self, project_root: Path) -> dict[str, Path]:
        stoich_root = project_root.parents[2]
        return {
            "STOICH_FEATURE_ROOT": stoich_root / "\u5168\u7ec4\u5b66\u7279\u5f81\u6570\u636e",
            "STOICH_PROJECT_ROOT": project_root,
            "STOICH_PROJECT_DATA_ROOT": project_root / "data",
            "STOICHIOOMICS_ROOT": stoich_root,
        }

    def _add_path_object(self, objects, missing_refs, roots, path_value: str, source: dict[str, Any]) -> None:
        path_text = str(path_value or "").strip().strip('"')
        if not path_text:
            ref = {"path": path_text, "reason": "empty_path"}
            ref.update(source)
            missing_refs.append(ref)
            return
        path = Path(path_text)
        exists = feature_io.source_exists(path)
        root_alias, relative_path = self._relative_for(path, roots)
        media_type, compression = media_for(path)
        key = logical_key(root_alias, relative_path, path_text)
        row = objects.get(key)
        if row is None:
            stat = feature_io.source_metadata(path) if exists else None
            row = {
                "logical_key": key,
                "backend": "local_fs",
                "root_alias": root_alias,
                "relative_path": relative_path,
                "object_uri": "" if root_alias else path_text,
                "absolute_path": str(path),
                "exists": exists,
                "size_bytes": int(stat.size) if stat else 0,
                "mtime_utc": datetime.fromtimestamp(stat.mtime, timezone.utc).isoformat() if stat else "",
                "sha256": "",
                "media_type": media_type,
                "compression": compression,
                "schema_version": self._schema_version(source, path),
                "status": "registered" if exists else "missing",
                "reference_count": 0,
                "references": [],
            }
            objects[key] = row
        row["reference_count"] += 1
        if len(row["references"]) < 50:
            row["references"].append(source)
        if not exists:
            ref = {"path": path_text, "reason": "path_not_found"}
            ref.update(source)
            missing_refs.append(ref)

    def _relative_for(self, path: Path, roots: dict[str, Path]) -> tuple[str, str]:
        for alias in ROOT_ALIAS_ORDER:
            rel = safe_rel(path, roots[alias])
            if rel is not None:
                return alias, rel
        return "", ""

    def _schema_version(self, source: dict[str, Any], path: Path) -> str:
        source_type = source.get("source_type", "")
        if source_type in {"omics_dataset", "feature_file"}:
            product = source.get("product_type") or source.get("file_type") or ""
            omics = source.get("omics_type") or "omics"
            if product:
                return f"{omics}_{product}_legacy_csv_v1"
            return f"{omics}_legacy_csv_v1"
        if path.suffix.lower() == ".json":
            return "analysis_artifact_json_v1"
        return ""

    def _selected_hash_keys(self, rows, mode: str, sample: int) -> set[str]:
        if mode == "none":
            return set()
        existing = [row["logical_key"] for row in rows if row["exists"]]
        if mode == "sha256":
            return set(existing)
        return set(existing[: max(sample, 0)])

    def _counter(self, values):
        result = defaultdict(int)
        for value in values:
            result[value or ""] += 1
        return result

    def _upsert_release(self, release_id: str, species_count: int, dataset_count: int) -> DataRelease:
        release, _ = DataRelease.objects.update_or_create(
            release_id=release_id,
            defaults={
                "scope_kind": "model_organisms",
                "status": "candidate",
                "version": "v1",
                "schema_version": "s2_minimal_model_v1",
                "pipeline_version": "S3_storage_object_backfill_v1",
                "species_count": species_count,
                "dataset_count": dataset_count,
                "entity_row_count": 0,
                "is_active": False,
                "is_immutable": False,
                "published_at": None,
                "metadata_json": {
                    "stage": "S3",
                    "scope": "model_organisms",
                    "source": "S1 membership seed",
                },
            },
        )
        return release

    @transaction.atomic
    def _upsert_membership(self, release, membership_rows, dataset_rows, species_map, dataset_map, batch_size: int) -> None:
        for row in membership_rows:
            sid = row["species_id"]
            ReleaseSpecies.objects.update_or_create(
                release=release,
                species_id_text=sid,
                defaults={
                    "species": species_map.get(sid),
                    "inclusion_status": row.get("inclusion_status", ""),
                    "reason_code": row.get("reason_code", ""),
                    "qc_status": row.get("qc_status", "pending"),
                    "is_model_organism": truthy(row.get("is_model_organism", "")),
                    "model_group_latin": row.get("model_group_latin", ""),
                    "expected_model_group": row.get("expected_model_group", ""),
                    "source_division": row.get("source_division", ""),
                    "metadata_json": dict(row),
                },
            )
        for row in dataset_rows:
            ds = dataset_map.get(row["dataset_id"])
            sp = species_map.get(row["species_id"])
            ReleaseDataset.objects.update_or_create(
                release=release,
                species_id_text=row["species_id"],
                omics_type=row["omics_type"],
                defaults={
                    "species": sp,
                    "dataset": ds,
                    "dataset_id_text": row.get("dataset_id", ""),
                    "membership_status": row.get("membership_status", "included"),
                    "reason_code": "",
                    "row_count_core": int(row.get("row_count_core") or 0),
                    "row_count_full": int(row.get("row_count_full") or 0),
                    "metadata_json": dict(row),
                },
            )

    def _upsert_storage_objects(self, object_rows, batch_size: int) -> tuple[int, int]:
        created = 0
        updated = 0
        for row in object_rows:
            metadata = {
                "absolute_path": row["absolute_path"],
                "exists": row["exists"],
                "mtime_utc": row.get("mtime_utc", ""),
                "reference_count": row["reference_count"],
                "references": row["references"],
                "source_stage": "S3_storage_object_backfill",
            }
            _, was_created = StorageObject.objects.update_or_create(
                logical_key=row["logical_key"],
                defaults={
                    "backend": row["backend"],
                    "root_alias": row["root_alias"],
                    "relative_path": row["relative_path"],
                    "object_uri": row["object_uri"],
                    "size_bytes": int(row["size_bytes"]),
                    "sha256": row["sha256"],
                    "media_type": row["media_type"],
                    "compression": row["compression"],
                    "schema_version": row["schema_version"],
                    "status": row["status"],
                    "metadata_json": metadata,
                },
            )
            created += int(was_created)
            updated += int(not was_created)
            if (created + updated) % batch_size == 0:
                self.stdout.write(f"StorageObject upsert {created + updated}/{len(object_rows)}")
        return created, updated

    def _attach_storage_keys_to_release_datasets(self, release, dataset_rows, object_rows, batch_size: int) -> None:
        key_by_abs = {str(Path(row["absolute_path"])): row["logical_key"] for row in object_rows}
        updated = 0
        for row in dataset_rows:
            rd = ReleaseDataset.objects.filter(release=release, species_id_text=row["species_id"], omics_type=row["omics_type"]).first()
            if not rd:
                continue
            metadata = dict(rd.metadata_json or {})
            core_key = key_by_abs.get(str(Path(row.get("core_csv_path", "")))) if row.get("core_csv_path") else ""
            full_key = key_by_abs.get(str(Path(row.get("full_csv_path", "")))) if row.get("full_csv_path") else ""
            metadata["storage_objects"] = {
                "core": core_key,
                "full": full_key,
            }
            rd.metadata_json = metadata
            rd.save(update_fields=["metadata_json", "updated_at"])
            updated += 1
            if updated % batch_size == 0:
                self.stdout.write(f"ReleaseDataset storage metadata attach {updated}/{len(dataset_rows)}")
