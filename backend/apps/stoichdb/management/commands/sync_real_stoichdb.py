from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from scripts.build_feature_table_case_pipeline import run_pipeline


class Command(BaseCommand):
    help = (
        'Build a staged stoichdb registry directly from nested raw omics feature tables '
        'and import the result into the configured database.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--source-root', required=True, help='Root directory containing raw genome/transcriptome/proteome feature tables.')
        parser.add_argument(
            '--pipeline-root',
            default=str(Path(settings.BASE_DIR) / 'data' / 'real_stoichdb_pipeline'),
            help='Output directory for generated stage0-stage6 pipeline artifacts.',
        )
        parser.add_argument(
            '--platform-data-root',
            default=str(getattr(settings, 'STOICHDB_DATA_ROOT', Path(settings.BASE_DIR) / 'data' / 'stoichdb_demo')),
            help='Registry folder to refresh for file-backed fallback mode and local inspection.',
        )
        parser.add_argument('--flush', action='store_true', help='Delete existing stoichdb ORM records before import.')
        parser.add_argument(
            '--full-pipeline',
            action='store_true',
            help='Also run stage0 copy, stage2 validation, and stage3 parquet generation. By default the command uses a faster registry-only path.',
        )

    def handle(self, *args, **options):
        source_root = Path(options['source_root']).resolve()
        pipeline_root = Path(options['pipeline_root']).resolve()
        platform_data_root = Path(options['platform_data_root']).resolve()

        if not source_root.exists():
            raise CommandError(f'source-root does not exist: {source_root}')
        if not source_root.is_dir():
            raise CommandError(f'source-root must be a directory: {source_root}')

        self.stdout.write(f'Building staged registry from raw feature tables: {source_root}')
        result = run_pipeline(
            source_root,
            pipeline_root,
            platform_data_root=platform_data_root,
            fast_mode=not bool(options.get('full_pipeline')),
            progress=lambda message: self.stdout.write(message),
        )
        self.stdout.write(
            f'Pipeline build complete: {result["species_count"]} species from {result["dataset_count"]} dataset files'
        )

        self.stdout.write('Importing staged registry into the configured Django database...')
        call_command(
            'import_stoichdb_pipeline',
            pipeline_root=str(pipeline_root),
            flush=bool(options.get('flush')),
        )
        self.stdout.write(self.style.SUCCESS(f'Stoichdb sync finished. Registry refreshed at: {platform_data_root}'))
