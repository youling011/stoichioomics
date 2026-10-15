from __future__ import annotations

import csv
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Validate a generated P0/P1 phylogeny release registry, tree file, and tip map."

    def add_arguments(self, parser):
        parser.add_argument("--release-id", default="protist_phylogeny_v1")

    def handle(self, *args, **options):
        release_id = options["release_id"]
        root = Path(settings.BASE_DIR) / "data" / "phylogeny" / release_id
        registry_path = root / "stage6_platform_registry" / "phylogeny_registry.json"
        if not registry_path.exists():
            raise CommandError(f"Missing registry: {registry_path}")

        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        tree_path = Path(settings.BASE_DIR) / registry["tree"]["newick_path"]
        tip_map_path = Path(settings.BASE_DIR) / registry["tree"]["tip_map_path"]
        report_path = Path(settings.BASE_DIR) / registry["qc"]["validation_report_path"]
        for path in [tree_path, tip_map_path, report_path]:
            if not path.exists():
                raise CommandError(f"Missing phylogeny artifact: {path}")

        newick = tree_path.read_text(encoding="utf-8")
        if not newick.strip().endswith(";"):
            raise CommandError("Newick tree does not end with a semicolon.")

        with tip_map_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        species_ids = [row.get("species_id", "") for row in rows]
        tip_labels = [row.get("tip_label", "") for row in rows]
        if len(species_ids) != len(set(species_ids)):
            raise CommandError("Duplicate species_id values in tip map.")
        if len(tip_labels) != len(set(tip_labels)):
            raise CommandError("Duplicate tip_label values in tip map.")
        missing_tips = [tip for tip in tip_labels if tip and tip not in newick]
        if missing_tips:
            raise CommandError(f"Tip labels missing from Newick: {missing_tips[:5]}")

        summary = registry.get("summary") or {}
        expected = int(summary.get("whitelist_species_count") or 0)
        if expected and expected != len(rows):
            raise CommandError(f"Tip map row count {len(rows)} != whitelist species count {expected}.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Validated {release_id}: {len(rows)} tips, coverage={summary.get('topology_coverage_pct')}%, "
                f"pgls_eligible={summary.get('pgls_eligible')}"
            )
        )
