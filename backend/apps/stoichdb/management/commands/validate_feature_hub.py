from django.core.management.base import BaseCommand, CommandError

from backend.apps.stoichdb.feature_hub.registry import load_registry


EXPECTED = {
    ("genome", "core"): 160,
    ("genome", "full"): 368,
    ("transcriptome", "core"): 86,
    ("transcriptome", "full"): 278,
    ("proteome", "core"): 63,
    ("proteome", "full"): 130,
}


class Command(BaseCommand):
    help = "Validate Feature Hub schema counts and Core/Full ML policy."

    def handle(self, *args, **options):
        registry = load_registry()
        by_key = {(row["omics"], row["scope"]): row["column_count"] for row in registry["schemas"]}
        errors = []
        for key, expected in EXPECTED.items():
            actual = by_key.get(key)
            if actual != expected:
                errors.append(f"{key}: expected {expected}, got {actual}")
        full_eligible = [row["field"] for row in registry["fields"] if row["scope"] == "full" and row["ml_role"] != "exclude"]
        if full_eligible:
            errors.append(f"Full fields incorrectly ML-enabled: {full_eligible[:10]}")
        if errors:
            raise CommandError("; ".join(errors))
        self.stdout.write(self.style.SUCCESS("Feature Hub registry validation passed."))
        self.stdout.write(str(registry["summary"]))

