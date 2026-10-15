from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from backend.apps.stoichdb import services
from backend.apps.stoichdb.complete_core import METHOD_VERSION
from backend.apps.stoichdb.models import AnalysisArtifact, OmicsDataset, Species


class Command(BaseCommand):
    help = "Materialize Species Explorer complete_core_v2 artifacts for selected species/omics."

    def add_arguments(self, parser):
        parser.add_argument("--species-id", action="append", default=[])
        parser.add_argument("--omics", action="append", choices=["genome", "transcriptome", "proteome"], default=[])
        parser.add_argument("--output-dir", default="runtime/complete_core_v2")
        parser.add_argument("--write-db", action="store_true")
        parser.add_argument("--limit", type=int, default=0)

    def handle(self, *args, **options):
        species_ids = [item.strip() for item in options["species_id"] if item.strip()]
        if not species_ids:
            qs = Species.objects.order_by("species_id").values_list("species_id", flat=True)
            if options["limit"]:
                qs = qs[: options["limit"]]
            species_ids = list(qs)
        omics_list = options["omics"] or ["genome", "transcriptome", "proteome"]
        out_root = Path(options["output_dir"])
        written = 0
        for species_id in species_ids:
            for omics in omics_list:
                try:
                    bundle = services.get_omics_bundle(species_id, omics, scope="core", compute="complete_core")
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f"{species_id}/{omics}: skipped {type(exc).__name__}: {exc}"))
                    continue
                target = out_root / species_id / f"{omics}_complete_core_v2.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                payload = {"method_version": METHOD_VERSION, "species_id": species_id, "omics": omics, "bundle": bundle}
                text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
                target.write_text(text, encoding="utf-8")
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if options["write_db"]:
                    dataset = OmicsDataset.objects.filter(species__species_id=species_id, omics_type=omics).first()
                    species = Species.objects.get(species_id=species_id)
                    AnalysisArtifact.objects.update_or_create(
                        artifact_id=f"{species_id}_{omics}_complete_core_v2",
                        defaults={
                            "species": species,
                            "dataset": dataset,
                            "omics_type": omics,
                            "artifact_type": "complete_core_v2",
                            "path": str(target),
                            "payload_json": {"method_version": METHOD_VERSION, "sha256": digest},
                            "version": METHOD_VERSION,
                        },
                    )
                written += 1
                self.stdout.write(f"{species_id}/{omics}: {target} sha256={digest[:12]}")
        self.stdout.write(self.style.SUCCESS(f"Materialized {written} complete_core_v2 artifact files."))
