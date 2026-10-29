from backend.apps.stoichdb.feature_sources import io as feature_io
import csv
import gzip
from backend.apps.common.host_paths import Path
from collections import Counter
from django.core.management.base import BaseCommand
from backend.apps.stoichdb.models import OmicsDataset
from backend.apps.stoichdb.compare_core.catalog import catalog
from backend.apps.stoichdb.compare_core.contracts import atomic_json


class Command(BaseCommand):
    help = 'Read-only registered Core path/header audit. Never supplements from Full.'

    def add_arguments(self, parser):
        parser.add_argument('--species-ids', default='')
        parser.add_argument('--all', action='store_true')
        parser.add_argument('--header-only', action='store_true')
        parser.add_argument('--out', required=True)

    def handle(self, *args, **options):
        cat = catalog()
        expected = {o: {f['field'] for f in cat['fields'] if f['omics'] == o} for o in cat['counts']}
        qs = OmicsDataset.objects.select_related('species').order_by('id')
        if options['species_ids']:
            qs = qs.filter(species__species_id__in=options['species_ids'].split(','))
        elif not options['all']:
            qs = qs.none()
        rows = []
        for ds in qs.iterator(chunk_size=256):
            path = Path(ds.core_csv_path) if ds.core_csv_path else None
            row = {'dataset_id': ds.dataset_id, 'species_id': ds.species.species_id, 'omics': ds.omics_type,
                   'registered_rows': ds.row_count_core, 'status': 'source_unavailable', 'path': str(path or '')}
            if path and feature_io.source_available(path):
                try:
                    opener = gzip.open if path.suffix == '.gz' else feature_io.open_source
                    with opener(path, 'rt', encoding='utf-8-sig', newline='') as handle:
                        reader = csv.reader(handle)
                        header = next(reader, [])
                        row.update(header_count=len(header), missing_fields=sorted(expected.get(ds.omics_type, set()) - set(header)),
                                   status='ok' if expected.get(ds.omics_type, set()).issubset(header) else 'missing_fields')
                        if not options['header_only']:
                            row['actual_rows'] = sum(1 for _ in reader)
                            row['count_matches'] = row['actual_rows'] == ds.row_count_core
                except (OSError, UnicodeError, csv.Error) as exc:
                    row.update(status='unreadable', reason=str(exc))
            rows.append(row)
        report = {'scope': 'core', 'catalog_count': cat['field_count'], 'semantic_hash': cat['semantic_hash'],
                  'header_only': options['header_only'], 'datasets': len(rows), 'status_counts': dict(Counter(r['status'] for r in rows)),
                  'rows': rows, 'review_required': cat['review_required'], 'full_supplement_used': False}
        atomic_json(Path(options['out']), report)
        self.stdout.write(str({k: v for k, v in report.items() if k not in ('rows',)}))
