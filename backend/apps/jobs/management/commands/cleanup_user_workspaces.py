from django.core.management.base import BaseCommand

from backend.apps.jobs.services import cleanup_expired_analysis_jobs
from backend.apps.sequence_analysis.services import cleanup_expired_jobs as cleanup_sequence_jobs


class Command(BaseCommand):
    help = "Remove expired user-upload workspaces and derived runtime sequence results."

    def handle(self, *args, **options):
        analysis = cleanup_expired_analysis_jobs()
        sequence_removed = cleanup_sequence_jobs()
        self.stdout.write(self.style.SUCCESS(
            f"analysis_removed={analysis['removed_count']} sequence_removed={sequence_removed}"
        ))
