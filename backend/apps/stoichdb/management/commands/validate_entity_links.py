import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count

from backend.apps.stoichdb.models import EntityRecord, Species


class Command(BaseCommand):
    help = 'Validate gene-transcript-protein link coverage by canonical gene ID.'

    def add_arguments(self, parser):
        parser.add_argument('--species', default='all')
        parser.add_argument('--export', default='workspace/entity_reports/entity_link_qc.csv')

    def handle(self, *args, **options):
        species_qs = Species.objects.all().order_by('species_id')
        if options['species'] != 'all':
            species_qs = species_qs.filter(species_id=options['species'])
        out = Path(settings.BASE_DIR) / options['export']
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=['species_id', 'gene_id', 'genome_rows', 'transcriptome_rows', 'proteome_rows', 'link_confidence'])
            writer.writeheader()
            for species in species_qs:
                grouped = (
                    EntityRecord.objects
                    .filter(species=species)
                    .exclude(canonical_gene_id='')
                    .values('canonical_gene_id', 'omics_type')
                    .annotate(n=Count('id'))
                )
                by_gene = {}
                for row in grouped:
                    by_gene.setdefault(row['canonical_gene_id'], {'genome': 0, 'transcriptome': 0, 'proteome': 0})
                    by_gene[row['canonical_gene_id']][row['omics_type']] = row['n']
                for gene_id, counts in by_gene.items():
                    linked_layers = sum(1 for value in counts.values() if value)
                    writer.writerow({
                        'species_id': species.species_id,
                        'gene_id': gene_id,
                        'genome_rows': counts['genome'],
                        'transcriptome_rows': counts['transcriptome'],
                        'proteome_rows': counts['proteome'],
                        'link_confidence': 'high' if linked_layers >= 2 else 'low',
                    })
        self.stdout.write(self.style.SUCCESS(f'Entity link QC exported: {out}'))
