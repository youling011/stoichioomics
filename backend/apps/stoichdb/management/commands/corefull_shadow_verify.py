"""Compare registered Core and Full sources without changing data or bindings."""
import json
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from backend.apps.common.host_paths import Path
from backend.apps.stoichdb.feature_sources.verification import compare_csv_pair
from backend.apps.stoichdb.feature_sources import io as feature_io
from backend.apps.stoichdb.models import OmicsDataset


def _full_path(core_value, full_value):
    if full_value:
        path = Path(full_value)
        if not path.is_file():
            raise CommandError('Registered Full file is unavailable')
        return path
    if not core_value:
        raise CommandError('No Core path is registered for candidate derivation')
    core = Path(core_value)
    name = core.name
    candidates = [
        name.replace('.core.', '.full.'),
        name.replace('_features.core.csv', '_features.csv'),
    ]
    found = []
    for candidate in dict.fromkeys(candidates):
        path = core.with_name(candidate)
        if candidate != name and path.is_file() and path not in found:
            found.append(path)
    if len(found) != 1:
        raise CommandError('No unique Full candidate for unregistered path')
    return found[0]


class Command(BaseCommand):
    help = 'Read-only logical comparison; this command does not activate Full-backed storage.'

    def add_arguments(self, parser):
        parser.add_argument('--species-id', required=True)
        parser.add_argument('--omics', choices=['genome', 'transcriptome', 'proteome'], required=True)

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError('This inventory requires the configured PostgreSQL database')
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
                cursor.execute('SET LOCAL statement_timeout = 30000')
            try:
                dataset = OmicsDataset.objects.only('dataset_id', 'core_csv_path', 'full_csv_path').get(
                    species__species_id=options['species_id'], omics_type=options['omics'])
            except OmicsDataset.DoesNotExist as exc:
                raise CommandError('Dataset not registered') from exc
        try:
            logical=feature_io.logical_source(dataset.core_csv_path) if dataset.core_csv_path else None
            if logical is not None:
                actual=feature_io.source_sha256(dataset.core_csv_path)
                expected=logical.record['core_sha256'];receipt=logical.record['receipt_json']
                if not expected:
                    result={'dataset_id':dataset.dataset_id,'comparison_method':'runtime_projection_only_no_original_byte_baseline',
                        'baseline_kind':receipt.get('baseline_kind'),'verification_level':receipt.get('verification_level'),
                        'virtual_core_sha256':actual,'cells_compared':0,'logical_match':None,'binding_ready':False,
                        'physical_core_retained':Path(dataset.core_csv_path).is_file()}
                    self.stdout.write(json.dumps(result,ensure_ascii=False,sort_keys=True))
                    raise CommandError('Sampled acceptance has no original per-file byte baseline; explicit pair verification is required for an exact claim')
                rows=logical.record['row_count'];columns=len(logical.recipe.columns)
                result={'dataset_id':dataset.dataset_id,'omics':options['omics'],'core_path':dataset.core_csv_path,
                    'full_path':str(logical.full_path),'rows_core':rows,'rows_full':receipt.get('full_rows',rows),
                    'cells_compared':rows*columns,'different_cells':0,'id_order_mismatches':0,'duplicate_ids':0,
                    'empty_ids':0,'examples':[],'core_columns':columns,'full_columns':len(feature_io.source_header(logical.full_path)),
                    'core_sha256':actual,'full_sha256':logical.record['full_sha256'],'stable_stat':True,
                    'logical_match':actual==expected,'binding_ready':False,
                    'comparison_method':'virtual_core_bytes_against_frozen_baseline',
                    'baseline_kind':receipt.get('baseline_kind','verified_legacy_core'),
                    'physical_core_retained':Path(dataset.core_csv_path).is_file()}
                self.stdout.write(json.dumps(result,ensure_ascii=False,sort_keys=True))
                if actual!=expected:raise CommandError('Logical Core differs from its frozen baseline')
                return
        except (OSError,ValueError) as exc:raise CommandError('Bound source comparison failed: '+str(exc)) from exc
        if not dataset.core_csv_path or not Path(dataset.core_csv_path).is_file():
            raise CommandError('Registered Core oracle is unavailable')
        full = _full_path(dataset.core_csv_path, dataset.full_csv_path)
        try:
            result = compare_csv_pair(Path(dataset.core_csv_path), full, options['omics'])
        except (OSError, ValueError) as exc:
            raise CommandError('Source comparison failed: ' + str(exc)) from exc
        result['dataset_id'] = dataset.dataset_id
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if not result['logical_match']:
            raise CommandError('Core and projected Full differ; binding remains disabled')
