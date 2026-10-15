from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from backend.apps.stoichdb.models import OmicsDataset, Species
from backend.apps.stoichdb.services import build_on_demand_omics_payload


class Command(BaseCommand):
    help = (
        "Build on-demand full/core omics summary and analysis payloads for selected species. "
        "The command writes JSON artifacts only and never imports or updates database rows."
    )

    def add_arguments(self, parser):
        parser.add_argument("--species-id", action="append", default=[], help="Species ID. Can be repeated.")
        parser.add_argument("--query", default="", help="Optional display-name/species-id search when --species-id is not supplied.")
        parser.add_argument("--omics", default="", choices=["", "genome", "transcriptome", "proteome"])
        parser.add_argument("--scope", default="core", choices=["core", "full"])
        parser.add_argument("--output-root", required=True)
        parser.add_argument("--scatter-limit", type=int, default=5000, help="Point cap for scatter-like payloads. Use 0 to emit all valid points.")

    def handle(self, *args, **options):
        species_ids = [item.strip() for item in options["species_id"] if item.strip()]
        if not species_ids:
            query = str(options["query"] or "").strip()
            if not query:
                raise SystemExit("Provide --species-id or --query.")
            species_ids = list(
                Species.objects
                .filter(display_name__icontains=query)
                .values_list("species_id", flat=True)[:25]
            )
        if not species_ids:
            raise SystemExit("No matching species found.")

        omics_list = [options["omics"]] if options["omics"] else ["genome", "transcriptome", "proteome"]
        scope = options["scope"]
        output_root = Path(options["output_root"])
        output_root.mkdir(parents=True, exist_ok=True)
        manifest = {
            "mode": "on_demand_full_omics_analysis",
            "scope": scope,
            "writes_database": False,
            "species": [],
            "errors": [],
        }

        for species_id in species_ids:
            species_dir = output_root / species_id
            species_dir.mkdir(parents=True, exist_ok=True)
            species_record = {"species_id": species_id, "omics": []}
            for omics in omics_list:
                if not OmicsDataset.objects.filter(species__species_id=species_id, omics_type=omics).exists():
                    manifest["errors"].append({"species_id": species_id, "omics": omics, "error": "dataset_not_registered"})
                    continue
                try:
                    payload = build_on_demand_omics_payload(
                        species_id,
                        omics,
                        scope,
                        scatter_limit=options["scatter_limit"],
                    )
                except Exception as exc:
                    manifest["errors"].append({"species_id": species_id, "omics": omics, "error": str(exc)})
                    self.stdout.write(self.style.WARNING(f"skip {species_id}/{omics}/{scope}: {exc}"))
                    continue
                omics_dir = species_dir / omics / scope
                omics_dir.mkdir(parents=True, exist_ok=True)
                (omics_dir / "summary.json").write_text(json.dumps(payload["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
                (omics_dir / "analysis.json").write_text(json.dumps(payload["analysis"], ensure_ascii=False, indent=2), encoding="utf-8")
                (omics_dir / "source.json").write_text(json.dumps(payload["source"], ensure_ascii=False, indent=2), encoding="utf-8")
                species_record["omics"].append({
                    "omics": omics,
                    "scope": scope,
                    "summary": str((omics_dir / "summary.json").resolve()),
                    "analysis": str((omics_dir / "analysis.json").resolve()),
                    "source": payload["source"],
                    "row_count": payload["summary"].get("row_count", 0),
                })
                self.stdout.write(
                    f"{species_id}/{omics}/{scope}: rows={payload['summary'].get('row_count', 0)} "
                    f"features={len(payload['summary'].get('feature_cards') or {})}"
                )
            manifest["species"].append(species_record)

        (output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"On-demand omics analysis artifacts written to {output_root}"))
