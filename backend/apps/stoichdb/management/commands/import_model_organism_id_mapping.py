from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backend.apps.stoichdb.models import Species


RELEASE_ID_DEFAULT = 'model_organisms_20260731_v1'


def _workspace_root() -> Path:
    return Path(settings.BASE_DIR).resolve().parent.parent


def _model_list() -> Path:
    root = _workspace_root()
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        for candidate in directory.glob('*.csv'):
            try:
                with candidate.open('r', encoding='utf-8-sig', newline='') as handle:
                    fields = set(next(csv.reader(handle), []))
            except (OSError, UnicodeError):
                continue
            if {'species_id', 'expected_model_group'}.issubset(fields):
                return candidate
    raise FileNotFoundError('Could not locate the model-organism whitelist CSV.')


def _find_source_project() -> Path | None:
    root = Path('G:/stoichioomics')
    if not root.exists():
        return None
    for parent in root.iterdir():
        if not parent.is_dir():
            continue
        for project in parent.iterdir():
            if project.is_dir() and project.name.startswith('stoich_platform_postgres_open_search_v6_2_perf_fix'):
                candidate = project / 'proj'
                if (candidate / 'data' / 'id_mapping' / 'id_mapping.sqlite').exists():
                    return candidate
    return None


class Command(BaseCommand):
    help = 'Register the six-group model-organism ID mapping runtime and copy the existing protist SQLite base index.'

    def add_arguments(self, parser):
        parser.add_argument('--source-project', default='', help='Source project containing final_whitelist and id_mapping.sqlite.')
        parser.add_argument('--model-list', default='')
        parser.add_argument('--release-id', default=RELEASE_ID_DEFAULT)
        parser.add_argument('--no-copy-base', action='store_true', help='Only write the model-scope manifest; keep the local SQLite base unchanged.')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        source_project = Path(options['source_project']).resolve() if options.get('source_project') else _find_source_project()
        if source_project is None or not source_project.exists():
            raise CommandError('Could not locate the G: source project containing the ID-mapping data.')
        model_list = Path(options['model_list']).resolve() if options.get('model_list') else _model_list()
        if not model_list.exists():
            raise CommandError(f'Model organism list does not exist: {model_list}')
        with model_list.open('r', encoding='utf-8-sig', newline='') as handle:
            whitelist = [row for row in csv.DictReader(handle) if str(row.get('hard_fail') or '').strip().lower() not in {'true', '1', 'yes', 'y'} and not str(row.get('exclude_reason') or '').strip()]
        selected = {str(row.get('species_id') or '').strip(): row for row in whitelist if str(row.get('species_id') or '').strip()}
        registered = set(Species.objects.filter(species_id__in=list(selected)).values_list('species_id', flat=True))
        group_counts = Counter(str(row.get('expected_model_group') or row.get('source_division') or '').strip().lower() for sid, row in selected.items() if sid in registered)

        source_mapping = source_project / 'data' / 'id_mapping'
        source_final = source_mapping / 'final_whitelist'
        local_mapping = Path(settings.BASE_DIR) / 'data' / 'id_mapping'
        local_mapping.mkdir(parents=True, exist_ok=True)
        local_sqlite = local_mapping / 'id_mapping.sqlite'
        source_sqlite = source_mapping / 'id_mapping.sqlite'
        if not options.get('dry_run') and not options.get('no_copy_base'):
            if not source_sqlite.exists() or source_sqlite.stat().st_size == 0:
                raise CommandError(f'Source SQLite base index is missing or empty: {source_sqlite}')
            if not local_sqlite.exists() or local_sqlite.stat().st_size != source_sqlite.stat().st_size:
                shutil.copy2(source_sqlite, local_sqlite)

        manifest = {
            'release_id': options['release_id'],
            'schema_version': 'model_organism_id_mapping_runtime_v1',
            'scope': 'six_group_model_organisms_without_phylogeny',
            'model_list': str(model_list),
            'source_project': str(source_project),
            'source_final_whitelist_root': str(source_final),
            'local_runtime_sqlite': str(local_sqlite),
            'whitelist_species_count': len(selected),
            'registered_species_count': len(registered),
            'missing_from_database': sorted(set(selected) - registered),
            'group_counts': dict(sorted(group_counts.items())),
            'runtime_strategy': 'species-scoped byte-range reads over final_whitelist CSV plus local protist/base SQLite index; no 50GB raw CSV duplication',
            'phylogeny': 'excluded',
        }
        target = local_mapping / 'model_organism_scope_manifest.json'
        if not options.get('dry_run'):
            target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(json.dumps(manifest, ensure_ascii=False, indent=2)))
