from django.core.management.base import BaseCommand, CommandError
from backend.apps.stoichdb.models import Species
from backend.apps.stoichdb.compare_core.catalog import catalog
from backend.apps.stoichdb.compare_core.contracts import OMICS
from backend.apps.stoichdb.compare_core.profiles import get_profile


class Command(BaseCommand):
    help = 'Build exact, all-field, strict-Core profiles; completed profiles are resumed/reused.'

    def add_arguments(self, parser):
        parser.add_argument('--species-ids', default='')
        parser.add_argument('--omics', default=','.join(OMICS))
        parser.add_argument('--all', action='store_true')
        parser.add_argument('--resume', action='store_true')
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        ids = [x for x in options['species_ids'].split(',') if x]
        if options['all']:
            ids = Species.objects.order_by('species_id').values_list('species_id', flat=True).iterator()
        elif not ids:
            raise CommandError('Specify --species-ids or explicitly use --all.')
        omics = options['omics'].split(',')
        if any(o not in OMICS for o in omics):
            raise CommandError('Invalid omics scope.')
        cat = catalog()
        for sid in ids:
            for o in omics:
                profile = get_profile(sid, o, cat, force=options['force'])
                self.stdout.write(f"{sid}/{o}: {profile['n_source']} rows; {len(profile['fields'])} fields; {profile['content_sha256'][:12]}")
