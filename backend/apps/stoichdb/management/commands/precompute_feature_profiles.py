from django.core.management.base import BaseCommand
from django.db.models import Q

from backend.apps.stoichdb.feature_hub.homepage_cache import FIELD_SETS, OMICS_LAYERS, homepage_preview, pick_preview_rows
from backend.apps.stoichdb.feature_hub.profiling import field_profile, precompute_field_profiles
from backend.apps.stoichdb.feature_hub.registry import catalog_payload, fields_for
from backend.apps.stoichdb.feature_hub.sources import DatasetSourceResolver, read_header
from backend.apps.stoichdb.models import Species
from backend.apps.stoichdb.services import HOME_REPRESENTATIVE_SPECIES


class Command(BaseCommand):
    help = "Precompute Feature Hub field profile and homepage spotlight sidecars."

    def add_arguments(self, parser):
        parser.add_argument("--species-id", default="")
        parser.add_argument("--omics", default="", choices=["", "genome", "transcriptome", "proteome"])
        parser.add_argument("--scope", default="core", choices=["core", "full"])
        parser.add_argument("--fields", default="", help="Comma-separated fields. Defaults to first ten registry fields.")
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--home-feature-hub", action="store_true", help="Precompute all homepage Feature Hub combinations for the eight representative species.")

    def handle(self, *args, **options):
        if options["home_feature_hub"]:
            self._precompute_home_feature_hub(force=options["force"])
            return
        if not options["species_id"] or not options["omics"]:
            raise SystemExit("--species-id and --omics are required unless --home-feature-hub is used.")
        fields = [item.strip() for item in options["fields"].split(",") if item.strip()]
        if not fields:
            fields = [row["field"] for row in fields_for(options["omics"], options["scope"])[: max(1, options["limit"])]]
        for field in fields[: max(1, options["limit"])]:
            payload = field_profile(options["species_id"], options["omics"], options["scope"], field, force=options["force"])
            self.stdout.write(f"{field}: n={payload['n_rows']} missing={payload['missing_n']}")
        self.stdout.write(self.style.SUCCESS("Feature profile precompute completed."))

    def _representative_species_ids(self) -> list[str]:
        selected = []
        seen = set()
        for spec in HOME_REPRESENTATIVE_SPECIES:
            row = None
            for species_id in spec["preferred_ids"]:
                row = Species.objects.filter(species_id=species_id).first()
                if row:
                    break
            if row is None:
                query_filter = Q()
                for query in spec["queries"]:
                    query_filter |= Q(display_name__icontains=query) | Q(species_id__icontains=query.lower().replace(" ", "_"))
                row = Species.objects.filter(query_filter).order_by("display_name", "species_id").first()
            if row and row.species_id not in seen:
                selected.append(row.species_id)
                seen.add(row.species_id)
        return selected

    def _precompute_home_feature_hub(self, *, force: bool = False) -> None:
        species_ids = self._representative_species_ids()
        if not species_ids:
            raise SystemExit("No representative species were found in the database.")
        completed = 0
        skipped = 0
        for species_id in species_ids:
            for omics in OMICS_LAYERS:
                for scope in FIELD_SETS:
                    try:
                        families = [""] + list(catalog_payload(omics=omics, scope=scope).get("facets", {}).get("families") or [])
                    except Exception as exc:
                        skipped += 1
                        self.stdout.write(self.style.WARNING(f"skip {species_id}/{omics}/{scope}: catalog error {exc}"))
                        continue
                    try:
                        source = DatasetSourceResolver().resolve(species_id, omics, scope)
                        header = set(read_header(source))
                    except Exception as exc:
                        skipped += 1
                        self.stdout.write(self.style.WARNING(f"skip {species_id}/{omics}/{scope}: {exc}"))
                        continue
                    preview_fields = []
                    for family in dict.fromkeys(families):
                        try:
                            rows = [row for row in (catalog_payload(omics=omics, scope=scope, family=family).get("items") or []) if row.get("field") in header]
                            preview_fields.extend(row.get("field") for row in pick_preview_rows(rows) if row.get("field"))
                        except Exception:
                            continue
                    if preview_fields:
                        try:
                            precompute_field_profiles(species_id, omics, scope, list(dict.fromkeys(preview_fields)), force=force)
                        except Exception as exc:
                            self.stdout.write(self.style.WARNING(f"profile batch skip {species_id}/{omics}/{scope}: {exc}"))
                    for family in dict.fromkeys(families):
                        try:
                            payload = homepage_preview(species_id, omics, scope, family, force=force)
                        except Exception as exc:
                            skipped += 1
                            self.stdout.write(self.style.WARNING(f"skip {species_id}/{omics}/{scope}/{family or 'all'}: {exc}"))
                            continue
                        completed += 1
                        self.stdout.write(
                            f"{species_id}/{omics}/{scope}/{family or 'all'}: "
                            f"features={payload.get('field_count', 0)} rows={payload.get('entity_count', 0)}"
                        )
        self.stdout.write(self.style.SUCCESS(f"Homepage Feature Hub precompute completed: {completed} combinations, {skipped} skipped."))
