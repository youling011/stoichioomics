import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from django.conf import settings

from backend.apps.stoichdb.models import EntityRecord, Species


class Command(BaseCommand):
    help = 'Build an entity-index quality report from the current EntityRecord table.'

    def add_arguments(self, parser):
        parser.add_argument('--species', default='all')
        parser.add_argument('--export', default='workspace/entity_reports/entity_index_qc.csv')

    def handle(self, *args, **options):
        species_arg = options['species']
        qs = Species.objects.all().order_by('species_id')
        if species_arg != 'all':
            qs = qs.filter(species_id=species_arg)
        out = Path(settings.BASE_DIR) / options['export']
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=['species_id', 'omics', 'rows', 'with_gene_id', 'with_gene_name'])
            writer.writeheader()
            for species in qs:
                for omics in ('genome', 'transcriptome', 'proteome'):
                    records = EntityRecord.objects.filter(species=species, omics_type=omics)
                    writer.writerow({
                        'species_id': species.species_id,
                        'omics': omics,
                        'rows': records.count(),
                        'with_gene_id': records.exclude(canonical_gene_id='').count(),
                        'with_gene_name': records.exclude(gene_name='').count(),
                    })
        self.stdout.write(self.style.SUCCESS(f'Entity index QC exported: {out}'))

