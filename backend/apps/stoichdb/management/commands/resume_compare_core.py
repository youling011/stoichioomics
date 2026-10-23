from django.core.management.base import BaseCommand
from backend.apps.stoichdb.compare_core.models import CompareRun
from backend.apps.stoichdb.compare_core.runs import resume


class Command(BaseCommand):
    help = 'Resume a failed or interrupted Core comparison using a new recorded attempt.'

    def add_arguments(self, parser):
        parser.add_argument('--run-id', required=True)

    def handle(self, *args, **options):
        run = resume(CompareRun.objects.get(pk=options['run_id']))
        self.stdout.write(f'{run.run_id}: {run.status}')
