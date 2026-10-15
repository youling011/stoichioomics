from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from backend.apps.stoichdb import phylogeny


class Command(BaseCommand):
    help = "Run or return controlled Pagel lambda signal results for a phylogeny release."

    def add_arguments(self, parser):
        parser.add_argument("--release-id", default="protist_phylogeny_v1")
        parser.add_argument("--features", nargs="*", default=[])

    def handle(self, *args, **options):
        try:
            payload = phylogeny.signal_payload(
                {
                    "release_id": options["release_id"],
                    "features": options["features"] or sorted(phylogeny.ALLOWED_P2_FEATURES),
                }
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
