from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from backend.apps.stoichdb import services
from backend.apps.stoichdb.models import (
    AnalysisArtifact,
    DataRelease,
    EntityRecord,
    FeatureFile,
    OmicsDataset,
    Species,
)


class Command(BaseCommand):
    help = 'Register the current stoichdb PostgreSQL contents as an active formal release.'

    def add_arguments(self, parser):
        parser.add_argument('--release-id', default='', help='Explicit release identifier. Defaults to a timestamped identifier.')
        parser.add_argument('--label', default='Stoichioomics PostgreSQL Release', help='Human-readable release label.')
        parser.add_argument('--description', default='Registered from the current PostgreSQL-backed stoichdb contents.', help='Release description.')
        parser.add_argument('--source-root', default='', help='Original raw-data root path.')
        parser.add_argument('--pipeline-root', default='', help='Pipeline output root path.')
        parser.add_argument('--platform-registry-path', default='data/stoichdb_demo', help='Platform registry fallback path.')

    def handle(self, *args, **options):
        release_id = options['release_id'] or timezone.now().strftime('release_%Y%m%d_%H%M%S')
        platform_registry_path = str(Path(options['platform_registry_path']))

        with transaction.atomic():
            DataRelease.objects.all().update(is_active=False)
            record, _ = DataRelease.objects.update_or_create(
                release_id=release_id,
                defaults={
                    'label': options['label'],
                    'description': options['description'],
                    'source_root': options['source_root'],
                    'pipeline_root': options['pipeline_root'],
                    'platform_registry_path': platform_registry_path,
                    'database_engine': 'postgresql',
                    'species_count': Species.objects.count(),
                    'dataset_count': OmicsDataset.objects.count(),
                    'entity_row_count': EntityRecord.objects.count(),
                    'artifact_count': AnalysisArtifact.objects.count(),
                    'feature_file_count': FeatureFile.objects.count(),
                    'metadata_json': {},
                    'manifest_json': {},
                    'is_active': True,
                },
            )

        services.clear_runtime_caches()
        self.stdout.write(self.style.SUCCESS(f'Active stoichdb release registered: {record.release_id}'))
