import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from backend.apps.stoichdb import entity_report
from backend.apps.stoichdb.models import Species


class Command(BaseCommand):
    help = 'Compute an on-demand entity feature-statistics QC file for core report fields.'

    def add_arguments(self, parser):
        parser.add_argument('--species', default='all')
        parser.add_argument('--omics', default='all')
        parser.add_argument('--export', default='workspace/entity_reports/entity_feature_stats_qc.csv')

    def handle(self, *args, **options):
        species_qs = Species.objects.all().order_by('species_id')
        if options['species'] != 'all':
            species_qs = species_qs.filter(species_id=options['species'])
        omics_list = list(entity_report.OMICS_ORDER) if options['omics'] == 'all' else [options['omics']]
        out = Path(settings.BASE_DIR) / options['export']
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=['species_id', 'omics', 'feature', 'valid_n', 'n_total', 'median', 'q05', 'q95', 'missing_rate'])
            writer.writeheader()
            for species in species_qs:
                for omics in omics_list:
                    stats = entity_report._bulk_stats_for_omics(species.species_id, omics, entity_report.CORE_FIELDS.get(omics, []))
                    for cfg in entity_report.CORE_FIELDS.get(omics, []):
                        if not cfg.get('numeric', True):
                            continue
                        row = stats.get(tuple(cfg['aliases']), {})
                        writer.writerow({
                            'species_id': species.species_id,
                            'omics': omics,
                            'feature': cfg['field'],
                            'valid_n': row.get('valid_n', 0),
                            'n_total': row.get('n_total', 0),
                            'median': row.get('median', ''),
                            'q05': row.get('q05', ''),
                            'q95': row.get('q95', ''),
                            'missing_rate': row.get('missing_rate', ''),
                        })
        self.stdout.write(self.style.SUCCESS(f'Entity feature stats QC exported: {out}'))

