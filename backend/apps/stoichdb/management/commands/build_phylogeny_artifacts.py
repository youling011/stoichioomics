from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Build P2 phylogeny analysis-readiness artifacts for the active protist release."

    def add_arguments(self, parser):
        parser.add_argument("--release-id", default="protist_phylogeny_v1")

    def handle(self, *args, **options):
        if options["release_id"] != "protist_phylogeny_v1":
            raise CommandError("Only protist_phylogeny_v1 is supported by the current P2 builder.")
        script = Path(settings.BASE_DIR) / "scripts" / "build_protist_phylogeny_p2.py"
        if not script.exists():
            raise CommandError(f"Missing builder script: {script}")
        completed = subprocess.run([sys.executable, str(script)], cwd=str(settings.BASE_DIR), text=True, capture_output=True)
        if completed.returncode != 0:
            raise CommandError(completed.stderr or completed.stdout)
        self.stdout.write(completed.stdout.strip())
        self.stdout.write(self.style.SUCCESS("P2 phylogeny artifacts built."))
