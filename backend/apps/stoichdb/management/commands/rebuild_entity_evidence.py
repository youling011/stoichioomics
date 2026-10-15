import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from backend.apps.stoichdb import entity_report
from backend.apps.stoichdb.models import EntityRecord, Species


class Command(BaseCommand):
    help = 'Sample candidate-evidence aggregation for entities and export a QC report.'

    def add_arguments(self, parser):
        parser.add_argument('--species', default='all')
        parser.add_argument('--limit-per-species', type=int, default=25)
        parser.add_argument('--export', default='workspace/entity_reports/entity_evidence_qc.csv')

    def handle(self, *args, **options):
        species_qs = Species.objects.all().order_by('species_id')
        if options['species'] != 'all':
            species_qs = species_qs.filter(species_id=options['species'])
        out = Path(settings.BASE_DIR) / options['export']
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open('w', encoding='utf-8-sig', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=['species_id', 'entity_key', 'linked_rows', 'evidence_rows', 'module_count'])
            writer.writeheader()
            for species in species_qs:
                keys = (
                    EntityRecord.objects
                    .filter(species=species)
                    .exclude(canonical_gene_id='')
                    .values_list('canonical_gene_id', flat=True)
                    .distinct()[: max(1, options['limit_per_species'])]
                )
                for key in keys:
                    try:
                        records = entity_report._linked_records(species.species_id, key)
                        evidence = entity_report._candidate_evidence(species.species_id, records)
                    except Exception:
                        records, evidence = [], []
                    writer.writerow({
                        'species_id': species.species_id,
                        'entity_key': key,
                        'linked_rows': len(records),
                        'evidence_rows': len(evidence),
                        'module_count': len({item.get('module_id') for item in evidence}),
                    })
        self.stdout.write(self.style.SUCCESS(f'Entity evidence QC exported: {out}'))

