"""Read-only target inventory. No migrations, imports, path rewrites, or mkdir."""
from backend.apps.stoichdb.feature_sources import io as feature_io
import argparse
import importlib.metadata
import json
import os
from pathlib import PureWindowsPath
from backend.apps.common.host_paths import Path
import platform


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', action='store_true', help='Explicitly run read-only PostgreSQL probes')
    parser.add_argument('--sample-limit', type=int, default=20)
    parser.add_argument('--report', required=True, help='New local JSON evidence file; never a data path')
    args = parser.parse_args()
    if not 1 <= args.sample_limit <= 1000:
        parser.error('sample-limit must be 1..1000')
    target = Path(args.report)
    if feature_io.source_exists(target):
        parser.error('report already exists; choose a new evidence file')
    import django
    django.setup()
    from django.conf import settings
    from django.db import connection, transaction
    if settings.SETTINGS_MODULE not in {'backend.config.settings_production', 'deploy.local_settings'}:
        parser.error('Select the production settings or its explicit local overlay')
    report = {'environment': {'os': platform.system(), 'python': platform.python_version(), 'django': django.get_version()},
              'settings': settings.SETTINGS_MODULE, 'roots': [], 'path_samples': [],
              'database_checked': args.database,
              'limits': ['Samples do not prove all file paths are migrated.',
                         'Readiness does not prove scientific correctness or task durability.']}
    for name, root in settings.DEPLOYMENT_READINESS_ROOTS.items():
        path = Path(root)
        writable = name in settings.DEPLOYMENT_READINESS_WRITABLE_ROOTS
        mode = os.R_OK | os.X_OK | (os.W_OK if writable else 0)
        report['roots'].append({'name': name, 'path': str(path), 'requires_write': writable,
                                'ok': path.is_dir() and os.access(path, mode)})
    if args.database:
        if connection.vendor != 'postgresql':
            parser.error('PostgreSQL required for read-only database inventory')
        from django.db.migrations.executor import MigrationExecutor
        from backend.apps.stoichdb.models import OmicsDataset, FeatureFile, AnalysisArtifact, DataRelease, StorageObject, FunctionalAnnotationRelease
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
                cursor.execute('SET LOCAL statement_timeout = 10000')
                cursor.execute('SHOW server_version')
                report['postgresql_version'] = cursor.fetchone()[0]
                cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_trgm')")
                report['pg_trgm'] = cursor.fetchone()[0]
            executor = MigrationExecutor(connection)
            report['pending_migrations'] = [f'{m.app_label}.{m.name}' for m, backward in executor.migration_plan(executor.loader.graph.leaf_nodes())]
            for model, fields in [(OmicsDataset, ['core_csv_path', 'full_csv_path']),
                                  (FeatureFile, ['path']), (AnalysisArtifact, ['path']),
                                  (DataRelease, ['source_root', 'pipeline_root', 'platform_registry_path']),
                                  (StorageObject, ['object_uri']), (FunctionalAnnotationRelease, ['source_dir'])]:
                query = model.objects.order_by('pk')
                if model is FunctionalAnnotationRelease:
                    query = query.filter(is_active=True)
                for record in query.values('pk', *fields)[:args.sample_limit]:
                    for field in fields:
                        raw = record[field]
                        if not raw:
                            continue
                        path = Path(raw)
                        report['path_samples'].append({'model': model._meta.label, 'pk': record['pk'], 'field': field,
                            'path': raw, 'windows_absolute': PureWindowsPath(raw).is_absolute(),
                            'exists_on_target': feature_io.source_exists(path) if model is not DataRelease else None,
                            'filesystem_checked': model is not DataRelease, 'required_runtime': model is not DataRelease})
        report['database_ready'] = report['pg_trgm'] and not report['pending_migrations']
    report['ok'] = all(row['ok'] for row in report['roots']) and report.get('database_ready', True)
    if args.database:
        report['historical_path_warnings'] = [row for row in report['path_samples'] if not row['required_runtime'] and PureWindowsPath(row['path']).drive.casefold() == 'f:']
        report['ok'] = report['ok'] and all(row['exists_on_target'] for row in report['path_samples'] if row['required_runtime'])
    with target.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print('Read-only inventory written; ready=' + str(report['ok']))
    raise SystemExit(0 if report['ok'] else 1)


if __name__ == '__main__':
    main()
