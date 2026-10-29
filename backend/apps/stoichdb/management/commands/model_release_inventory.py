from __future__ import annotations
from backend.apps.stoichdb.feature_sources import io as feature_io

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from backend.apps.common.host_paths import Path
from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from django.utils import timezone as django_timezone

from backend.apps.stoichdb.models import DataRelease, OmicsDataset, Species


REQUIRED_COLUMNS = {
    "species_id",
    "model_group_latin",
    "expected_model_group",
    "source_division",
    "source_division_cn",
    "qc_grade",
    "has_genome",
    "has_transcriptome",
    "has_proteome",
    "hard_fail",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with feature_io.open_source(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise CommandError(f"Model list missing required columns: {sorted(missing)}")
        return [{k: (v if v is not None else "") for k, v in row.items()} for row in reader]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def stable_canonical_row(rows: list[dict[str, str]]) -> dict[str, str]:
    def score(row: dict[str, str]) -> tuple[int, int, int, str]:
        expected_match = int((row.get("source_division") or "") == (row.get("expected_model_group") or ""))
        no_warning = int("source_division_differs" not in (row.get("notes") or ""))
        grade = 1 if (row.get("qc_grade") or "").upper() == "A" else 0
        return (-expected_match, -no_warning, -grade, row.get("source_division") or "")

    return sorted(rows, key=score)[0]


class Command(BaseCommand):
    help = "Build model-organism release scope inventory and membership seed from the curated model organism list."

    def add_arguments(self, parser):
        parser.add_argument("--model-list", required=True, help="Path to 六类群白名单_模式生物清单.csv")
        parser.add_argument("--release-id", default="", help="Scoped model-organism release id.")
        parser.add_argument("--out", required=True, help="Output directory for S1 inventory artifacts.")
        parser.add_argument("--s0-work-root", default="", help="Optional S0 work root used as provenance input.")
        parser.add_argument("--dry-run", action="store_true", help="Generate files only; do not write membership tables.")
        parser.add_argument("--write-membership", action="store_true", help="Write ReleaseSpecies/ReleaseDataset if models exist. Not available before S2.")

    def handle(self, *args, **options):
        model_list = Path(options["model_list"]).resolve()
        out_dir = Path(options["out"]).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        release_id = options["release_id"] or f"model_organisms_{django_timezone.now().strftime('%Y%m%d')}_v1"
        started_at = datetime.now(timezone.utc).isoformat()

        rows = read_csv_rows(model_list)
        by_species: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            by_species[str(row["species_id"]).strip()].append(row)
        canonical_rows = [stable_canonical_row(group) for _, group in sorted(by_species.items())]
        duplicate_rows = [row for group in by_species.values() if len(group) > 1 for row in group]
        cross_rows = [row for row in rows if "source_division_differs_from_expected_model_group" in (row.get("notes") or "")]

        species_ids = sorted(by_species)
        species_qs = Species.objects.filter(species_id__in=species_ids)
        species_map = {sp.species_id: sp for sp in species_qs}
        omics_counts = dict(
            OmicsDataset.objects.filter(species__species_id__in=species_ids)
            .values("species__species_id")
            .annotate(c=Count("id"))
            .values_list("species__species_id", "c")
        )
        omics_by_species: dict[str, set[str]] = defaultdict(set)
        for sid, omics_type in OmicsDataset.objects.filter(species__species_id__in=species_ids).values_list("species__species_id", "omics_type"):
            omics_by_species[sid].add(omics_type)

        inventory: list[dict[str, Any]] = []
        included: list[dict[str, Any]] = []
        non_included: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        membership_seed: list[dict[str, Any]] = []

        for row in canonical_rows:
            sid = str(row["species_id"]).strip()
            sp = species_map.get(sid)
            source_hard_fail = truthy(row.get("hard_fail", ""))
            source_omics_ok = all(truthy(row.get(col, "")) for col in ("has_genome", "has_transcriptome", "has_proteome"))
            db_omics = omics_by_species.get(sid, set())
            db_complete = {"genome", "transcriptome", "proteome"}.issubset(db_omics)
            has_duplicate_warning = len(by_species[sid]) > 1
            has_cross_warning = any("source_division_differs" in (r.get("notes") or "") for r in by_species[sid])

            if source_hard_fail:
                inclusion_status = "excluded"
                reason_code = "source_hard_fail"
                qc_status = "fail"
            elif sp is None:
                inclusion_status = "missing"
                reason_code = "missing_in_current_db"
                qc_status = "pending_source_or_import"
            elif not source_omics_ok:
                inclusion_status = "excluded"
                reason_code = "source_list_incomplete_omics"
                qc_status = "fail"
            elif not db_complete:
                inclusion_status = "excluded"
                reason_code = "current_db_incomplete_omics"
                qc_status = "fail"
            else:
                inclusion_status = "included"
                reason_code = "included_current_db_3omics"
                qc_status = "pass_with_warning" if has_duplicate_warning or has_cross_warning else "pass"

            payload = {
                "release_id": release_id,
                "species_id": sid,
                "display_name": sp.display_name if sp else row.get("display_name", ""),
                "taxonomy_id_db": sp.taxonomy_id if sp else "",
                "domain_db": sp.domain if sp else "",
                "model_group_cn": row.get("model_group_cn", ""),
                "model_group_latin": row.get("model_group_latin", ""),
                "expected_model_group": row.get("expected_model_group", ""),
                "source_division": row.get("source_division", ""),
                "source_division_cn": row.get("source_division_cn", ""),
                "taxon_id_source": row.get("taxon_id", ""),
                "assembly_accession": row.get("assembly_accession", ""),
                "assembly_level": row.get("assembly_level", ""),
                "qc_grade": row.get("qc_grade", ""),
                "quality_score": row.get("quality_score", ""),
                "source_has_genome": row.get("has_genome", ""),
                "source_has_transcriptome": row.get("has_transcriptome", ""),
                "source_has_proteome": row.get("has_proteome", ""),
                "db_has_genome_dataset": "genome" in db_omics,
                "db_has_transcriptome_dataset": "transcriptome" in db_omics,
                "db_has_proteome_dataset": "proteome" in db_omics,
                "omics_dataset_count": int(omics_counts.get(sid, 0)),
                "inclusion_status": inclusion_status,
                "reason_code": reason_code,
                "qc_status": qc_status,
                "duplicate_species_id_warning": has_duplicate_warning,
                "cross_division_warning": has_cross_warning,
                "notes": row.get("notes", ""),
            }
            inventory.append(payload)
            if inclusion_status == "included":
                included.append(payload)
            else:
                non_included.append(payload)
                if inclusion_status == "missing":
                    missing.append(payload)
                else:
                    excluded.append(payload)
            membership_seed.append({
                "release_id": release_id,
                "species_id": sid,
                "species_pk_exists": sp is not None,
                "inclusion_status": inclusion_status,
                "reason_code": reason_code,
                "qc_status": qc_status,
                "is_model_organism": True,
                "model_group_latin": row.get("model_group_latin", ""),
                "expected_model_group": row.get("expected_model_group", ""),
                "source_division": row.get("source_division", ""),
            })

        dataset_seed = []
        included_ids = [row["species_id"] for row in included]
        for ds in OmicsDataset.objects.select_related("species").filter(species__species_id__in=included_ids).order_by("species__species_id", "omics_type"):
            dataset_seed.append({
                "release_id": release_id,
                "species_id": ds.species.species_id,
                "dataset_id": ds.dataset_id,
                "omics_type": ds.omics_type,
                "row_count_core": ds.row_count_core,
                "row_count_full": ds.row_count_full,
                "core_csv_path": ds.core_csv_path,
                "full_csv_path": ds.full_csv_path,
                "membership_status": "included",
            })

        inventory_fields = list(inventory[0].keys()) if inventory else []
        write_csv(out_dir / "model_release_inventory.csv", inventory, inventory_fields)
        write_csv(out_dir / "included_species.csv", included, inventory_fields)
        write_csv(out_dir / "non_included_species.csv", non_included, inventory_fields)
        write_csv(out_dir / "excluded_species.csv", excluded, inventory_fields)
        write_csv(out_dir / "missing_in_current_db.csv", missing, inventory_fields)
        write_csv(out_dir / "duplicate_or_cross_division_records.csv", duplicate_rows + cross_rows, list(rows[0].keys()) if rows else [])
        write_csv(out_dir / "membership_seed.csv", membership_seed, list(membership_seed[0].keys()) if membership_seed else [])
        write_csv(out_dir / "omics_dataset_membership_seed.csv", dataset_seed, list(dataset_seed[0].keys()) if dataset_seed else [])

        with (out_dir / "membership_seed.jsonl").open("w", encoding="utf-8") as f:
            for row in membership_seed:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        division_summary = []
        for division in sorted({row.get("source_division", "") for row in inventory}):
            rows_for_div = [row for row in inventory if row.get("source_division") == division]
            division_summary.append({
                "source_division": division,
                "unique_species": len(rows_for_div),
                "included": sum(row["inclusion_status"] == "included" for row in rows_for_div),
                "missing": sum(row["inclusion_status"] == "missing" for row in rows_for_div),
                "excluded": sum(row["inclusion_status"] == "excluded" for row in rows_for_div),
                "qc_A": sum(str(row.get("qc_grade", "")).upper() == "A" for row in rows_for_div),
                "qc_B": sum(str(row.get("qc_grade", "")).upper() == "B" for row in rows_for_div),
            })
        write_csv(out_dir / "division_summary.csv", division_summary, list(division_summary[0].keys()) if division_summary else [])

        group_summary = []
        for group in sorted({row.get("model_group_latin", "") for row in inventory}):
            rows_for_group = [row for row in inventory if row.get("model_group_latin") == group]
            group_summary.append({
                "model_group_latin": group,
                "unique_species": len(rows_for_group),
                "included": sum(row["inclusion_status"] == "included" for row in rows_for_group),
                "missing": sum(row["inclusion_status"] == "missing" for row in rows_for_group),
                "excluded": sum(row["inclusion_status"] == "excluded" for row in rows_for_group),
            })
        write_csv(out_dir / "model_group_summary.csv", group_summary, list(group_summary[0].keys()) if group_summary else [])

        status_counts = Counter(row["inclusion_status"] for row in inventory)
        reason_counts = Counter(row["reason_code"] for row in inventory)
        manifest = {
            "stage": "S1_model_organism_scope_inventory",
            "release_id": release_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "started_at": started_at,
            "model_list": str(model_list),
            "model_list_sha256": sha256_file(model_list),
            "s0_work_root": options.get("s0_work_root") or "",
            "out_dir": str(out_dir),
            "dry_run": bool(options["dry_run"]),
            "write_membership_requested": bool(options["write_membership"]),
            "model_list_rows": len(rows),
            "unique_species_ids": len(species_ids),
            "included_species_count": len(included),
            "non_included_species_count": len(non_included),
            "missing_species_count": len(missing),
            "excluded_species_count": len(excluded),
            "dataset_membership_rows": len(dataset_seed),
            "duplicate_input_records": len(duplicate_rows),
            "cross_division_warning_records": len(cross_rows),
            "status_counts": dict(status_counts),
            "reason_counts": dict(reason_counts),
            "division_summary": division_summary,
            "database_models_available": {
                "ReleaseSpecies": apps.is_installed("backend.apps.stoichdb") and apps.get_app_config("stoichdb").models.get("releasespecies") is not None,
                "ReleaseDataset": apps.is_installed("backend.apps.stoichdb") and apps.get_app_config("stoichdb").models.get("releasedataset") is not None,
            },
            "active_data_release": list(DataRelease.objects.filter(is_active=True).order_by("-created_at").values("release_id", "species_count", "dataset_count", "entity_row_count")[:1]),
            "outputs": {
                "inventory_csv": str(out_dir / "model_release_inventory.csv"),
                "included_species_csv": str(out_dir / "included_species.csv"),
                "non_included_species_csv": str(out_dir / "non_included_species.csv"),
                "excluded_species_csv": str(out_dir / "excluded_species.csv"),
                "missing_csv": str(out_dir / "missing_in_current_db.csv"),
                "membership_seed_csv": str(out_dir / "membership_seed.csv"),
                "dataset_membership_seed_csv": str(out_dir / "omics_dataset_membership_seed.csv"),
                "division_summary_csv": str(out_dir / "division_summary.csv"),
                "model_group_summary_csv": str(out_dir / "model_group_summary.csv"),
            },
        }
        write_json(out_dir / "manifest.json", manifest)
        write_json(out_dir / "summary.json", {
            "release_id": release_id,
            "unique_species_ids": len(species_ids),
            "included_species_count": len(included),
            "non_included_species_count": len(non_included),
            "missing_species_count": len(missing),
            "excluded_species_count": len(excluded),
            "dataset_membership_rows": len(dataset_seed),
            "status_counts": dict(status_counts),
            "reason_counts": dict(reason_counts),
        })

        lines = [
            f"# S1 模式生物 scope 盘点结果",
            "",
            f"- release_id: `{release_id}`",
            f"- unique_species_ids: `{len(species_ids)}`",
            f"- included_species_count: `{len(included)}`",
            f"- non_included_species_count: `{len(non_included)}`",
            f"- missing_species_count: `{len(missing)}`",
            f"- excluded_species_count: `{len(excluded)}`",
            f"- dataset_membership_rows: `{len(dataset_seed)}`",
            f"- duplicate_input_records: `{len(duplicate_rows)}`",
            f"- cross_division_warning_records: `{len(cross_rows)}`",
            "",
            "## 说明",
            "- 当前项目尚未创建 ReleaseSpecies / ReleaseDataset 模型，本阶段不写数据库 membership 表。",
            "- `membership_seed.csv` 和 `omics_dataset_membership_seed.csv` 是 S2 新增模型后的直接导入依据。",
        ]
        (out_dir / "S1_result_summary.md").write_text("\n".join(lines), encoding="utf-8")

        if options["write_membership"]:
            available = manifest["database_models_available"]
            if not available["ReleaseSpecies"] or not available["ReleaseDataset"]:
                write_json(out_dir / "write_membership_status.json", {
                    "status": "not_supported_before_S2",
                    "reason": "ReleaseSpecies/ReleaseDataset models do not exist in current project. Run S2 minimal model migration first.",
                })
                raise CommandError("ReleaseSpecies/ReleaseDataset models do not exist; S1 wrote membership seed files only.")

        self.stdout.write(json.dumps({
            "release_id": release_id,
            "out_dir": str(out_dir),
            "unique_species_ids": len(species_ids),
            "included_species_count": len(included),
            "non_included_species_count": len(non_included),
            "missing_species_count": len(missing),
            "excluded_species_count": len(excluded),
            "dataset_membership_rows": len(dataset_seed),
        }, ensure_ascii=False, indent=2))
        self.stdout.write(self.style.SUCCESS("S1 model organism scope inventory completed."))
