from __future__ import annotations

import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from backend.apps.stoichdb.models import PhylogenyQCMetric, PhylogenyRelease, PhylogenyTipMap, Species


RANK_FIELDS = ["domain_or_realm", "kingdom", "phylum", "class", "order", "family", "genus", "species"]


def as_bool(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class Command(BaseCommand):
    help = "Import a generated P0/P1 phylogeny release into PostgreSQL-backed stoichdb tables."

    def add_arguments(self, parser):
        parser.add_argument("--release-id", default="protist_phylogeny_v1")
        parser.add_argument("--activate", action="store_true")

    def handle(self, *args, **options):
        release_id = options["release_id"]
        root = Path(settings.BASE_DIR) / "data" / "phylogeny" / release_id
        registry_path = root / "stage6_platform_registry" / "phylogeny_registry.json"
        release_csv = root / "stage4_catalog" / "phylogeny_release.csv"
        tip_map_csv = root / "stage1_standardized" / "tip_mapping.csv"
        qc_csv = root / "stage2_validation" / "phylogeny_qc_metrics.csv"
        for path in [registry_path, release_csv, tip_map_csv, qc_csv]:
            if not path.exists():
                raise CommandError(f"Missing phylogeny import input: {path}")

        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        with release_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            release_rows = list(csv.DictReader(handle))
        if not release_rows:
            raise CommandError(f"No release row in {release_csv}")
        release_row = release_rows[0]

        with tip_map_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            tip_rows = list(csv.DictReader(handle))
        with qc_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            qc_rows = list(csv.DictReader(handle))

        species_by_id = {row.species_id: row for row in Species.objects.filter(species_id__in=[item.get("species_id", "") for item in tip_rows])}

        with transaction.atomic():
            if options["activate"]:
                PhylogenyRelease.objects.filter(scope=release_row.get("scope") or "protists").update(is_active=False)
            release, _ = PhylogenyRelease.objects.update_or_create(
                release_id=release_id,
                defaults={
                    "label": release_row.get("label") or release_id,
                    "scope": release_row.get("scope") or "protists",
                    "tree_kind": release_row.get("tree_kind") or "taxonomy_reference_topology",
                    "source": release_row.get("source", ""),
                    "source_version": release_row.get("source_version", ""),
                    "method": release_row.get("method", ""),
                    "rooted": as_bool(release_row.get("rooted", "true")),
                    "branch_length_unit": release_row.get("branch_length_unit") or "none",
                    "tip_count": int(float(release_row.get("tip_count") or 0)),
                    "analysis_eligible": as_bool(release_row.get("analysis_eligible")),
                    "topology_eligible": bool(registry.get("summary", {}).get("topology_eligible", True)),
                    "tree_path": release_row.get("tree_path", ""),
                    "tree_sha256": release_row.get("tree_sha256", ""),
                    "tip_map_path": release_row.get("tip_map_path", ""),
                    "tip_map_sha256": release_row.get("tip_map_sha256", ""),
                    "metadata_json": registry,
                    "is_active": options["activate"] or as_bool(release_row.get("is_active")),
                },
            )

            PhylogenyTipMap.objects.filter(release=release).delete()
            PhylogenyQCMetric.objects.filter(release=release).delete()
            PhylogenyTipMap.objects.bulk_create(
                [
                    PhylogenyTipMap(
                        release=release,
                        species=species_by_id.get(row.get("species_id", "")),
                        species_id_text=row.get("species_id", ""),
                        tip_label=row.get("tip_label", ""),
                        display_name=row.get("display_name", ""),
                        tax_id=row.get("tax_id_current", ""),
                        full_lineage=row.get("full_lineage", ""),
                        rank_json={field: row.get(field, "") for field in RANK_FIELDS},
                        mapping_status=row.get("mapping_status") or "mapped",
                        topology_eligible=as_bool(row.get("topology_eligible")),
                        pgls_eligible=as_bool(row.get("pgls_eligible")),
                        pgls_blocker=row.get("pgls_blocker", ""),
                    )
                    for row in tip_rows
                ],
                batch_size=1000,
            )
            PhylogenyQCMetric.objects.bulk_create(
                [
                    PhylogenyQCMetric(
                        release=release,
                        metric=row.get("metric", ""),
                        value=str(row.get("value", "")),
                        status=row.get("status") or "pass",
                        detail=row.get("detail", ""),
                    )
                    for row in qc_rows
                ],
                batch_size=1000,
            )

        self.stdout.write(self.style.SUCCESS(f"Imported phylogeny release {release.release_id}: {len(tip_rows)} tips, {len(qc_rows)} QC metrics."))
