from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from backend.apps.stoichdb import phylogeny


class Command(BaseCommand):
    help = "Return Case 1 phylogeny readiness payload for the active protist release."

    def add_arguments(self, parser):
        parser.add_argument("--release-id", default="protist_phylogeny_v1")

    def handle(self, *args, **options):
        try:
            payload = phylogeny.case1_phylogeny_payload(options["release_id"])
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
