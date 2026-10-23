from django.core.management.base import BaseCommand
from backend.apps.stoichdb.compare_core.worker import drain


class Command(BaseCommand):
    help = 'Process durable Core comparison jobs and exit when drained.'
    # Deployment runs Django checks explicitly. A short-lived worker need not
    # import every unrelated URL/analysis module before processing a queued job.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--drain', action='store_true')
        parser.add_argument('--run-id')
        parser.add_argument('--poll-seconds', type=float, default=1)

    def handle(self, *args, **options):
        drain(once=options['once'], run_id=options['run_id'])
        self.stdout.write('Compare worker finished; all owned database connections closed.')
