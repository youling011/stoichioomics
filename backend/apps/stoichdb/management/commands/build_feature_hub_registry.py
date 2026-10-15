from django.core.management.base import BaseCommand

from backend.apps.stoichdb.feature_hub.registry import load_registry, write_registry_file


class Command(BaseCommand):
    help = "Build the complete Stoichioomics Feature Hub ML feature registry JSON."

    def handle(self, *args, **options):
        path = write_registry_file()
        summary = load_registry()["summary"]
        self.stdout.write(self.style.SUCCESS(f"Wrote {path}"))
        self.stdout.write(str(summary))

