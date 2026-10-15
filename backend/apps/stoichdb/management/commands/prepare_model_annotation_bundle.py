from __future__ import annotations

import csv
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backend.apps.stoichdb.models import Species


RELEASE_ID_DEFAULT = 'model_organisms_20260731_v1'
FILES = {
    'status': 'species_function_annotation_status.csv',
    'go': 'go_annotations_all_species.with_terms.csv',
    'go_terms': 'go_terms.csv',
    'kegg_genes': 'kegg_gene_annotations_from_xrefs.csv',
    'kegg_links': 'kegg_annotation_links_long.csv',
}
GROUP_DIRS = {
    'bacteria': ['细菌'],
    'fungi': ['真菌'],
    'metazoa': ['后生生物'],
    'plants': ['植物'],
    'protists': [''],
    'vertebrates': ['脊椎动物', '脊索动物'],
}


def _workspace_root() -> Path:
    return Path(settings.BASE_DIR).resolve().parent.parent


def _default_model_list() -> Path:
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


def _default_source_root() -> Path:
    return _workspace_root() / 'gpt优化方案' / '项目平台完整归纳整理' / '功能注释下载'


def _selected_ids(model_list: Path) -> set[str]:
    if not model_list.exists():
        raise CommandError(f'Model organism list does not exist: {model_list}')
    with model_list.open('r', encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    whitelist = {
        str(row.get('species_id') or '').strip()
        for row in rows
        if str(row.get('hard_fail') or '').strip().lower() not in {'true', '1', 'yes', 'y'}
        and not str(row.get('exclude_reason') or '').strip()
    }
    # Only materialize annotations for species registered in the current
    # platform.  The eight missing whitelist IDs remain explicitly reported.
    registered = set(Species.objects.filter(species_id__in=whitelist).values_list('species_id', flat=True))
    return whitelist & registered


def _source_files(source_root: Path, kind: str) -> list[Path]:
    paths = []
    for dirs in GROUP_DIRS.values():
        for directory in dirs:
            path = source_root / directory / FILES[kind] if directory else source_root / FILES[kind]
            if path.exists() and path not in paths:
                paths.append(path)
    return paths


def _iter_selected(path: Path, selected: set[str]) -> tuple[list[str], Iterable[dict[str, str]], int]:
    handle = path.open('r', encoding='utf-8-sig', newline='')
    reader = csv.DictReader(handle)
    fieldnames = list(reader.fieldnames or [])
    if 'species_id' not in fieldnames:
        handle.close()
        return fieldnames, iter(()), 0

    def generator():
        try:
            for row in reader:
                species_id = str(row.get('species_id') or '').strip()
                if species_id in selected:
                    yield {key: (value or '') for key, value in row.items()}
        finally:
            handle.close()

    return fieldnames, generator(), 0


class Command(BaseCommand):
    help = 'Filter the six-group GO/KEGG source bundles to the registered model-organism release.'

    def add_arguments(self, parser):
        parser.add_argument('--source', default='', help='Root directory containing the six-group annotation bundles.')
        parser.add_argument('--model-list', default='')
        parser.add_argument('--output', default='', help='Output bundle directory.')
        parser.add_argument('--release-id', default=RELEASE_ID_DEFAULT)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        source = Path(options['source']).resolve() if options.get('source') else _default_source_root()
        model_list = Path(options['model_list']).resolve() if options.get('model_list') else _default_model_list()
        output = Path(options['output']).resolve() if options.get('output') else Path(settings.BASE_DIR) / 'data' / 'function_annotations' / str(options['release_id'])
        if not source.exists():
            raise CommandError(f'Annotation source directory does not exist: {source}')
        selected = _selected_ids(model_list)
        self.stdout.write(f'Annotation bundle source={source}; registered model species={len(selected)}')
        if options.get('dry_run'):
            for kind in FILES:
                paths = _source_files(source, kind)
                self.stdout.write(f'{kind}: source_files={len(paths)}')
            return

        output.mkdir(parents=True, exist_ok=True)
        counts: dict[str, Any] = {}
        source_manifest: dict[str, Any] = {}
        for kind, filename in FILES.items():
            paths = _source_files(source, kind)
            source_manifest[kind] = [str(path) for path in paths]
            if kind == 'go_terms':
                count = self._write_go_terms(paths, output / filename)
                counts[kind] = {'rows': count, 'selected_species': len(selected), 'source_files': len(paths)}
                continue
            count, species_seen, fieldnames = self._write_selected_rows(paths, selected, output / filename)
            counts[kind] = {'rows': count, 'selected_species': len(species_seen), 'source_files': len(paths), 'columns': fieldnames}
            self.stdout.write(f'{kind}: rows={count}; species={len(species_seen)}')

        manifest = {
            'release_id': options['release_id'],
            'schema_version': 'functional_annotation_model_scope_v1',
            'source_root': str(source),
            'model_list': str(model_list),
            'output_root': str(output),
            'scope': 'six_group_model_organisms_without_phylogeny',
            'registered_species_count': len(selected),
            'selected_species_ids': sorted(selected),
            'files': source_manifest,
            'counts': counts,
            'missing_policy': 'status rows are retained for registered species; GO/KEGG rows remain absent when the source has no standard annotation.',
        }
        (output / 'model_annotation_bundle_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        (output / 'function_annotation_download_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(json.dumps({'output': str(output), 'registered_species_count': len(selected), 'counts': counts}, ensure_ascii=False, indent=2)))

    def _write_selected_rows(self, paths: list[Path], selected: set[str], target: Path) -> tuple[int, set[str], list[str]]:
        if not paths:
            raise CommandError(f'No source files found for {target.name}')
        fieldnames: list[str] = []
        all_fields: OrderedDict[str, None] = OrderedDict()
        total = 0
        seen_species: set[str] = set()
        # Source bundles are modest after scope filtering; stream rows while
        # preserving the source headers and tolerating group-specific extras.
        rows_buffer: list[dict[str, str]] = []
        status_by_species: OrderedDict[str, dict[str, str]] = OrderedDict()
        for path in paths:
            with path.open('r', encoding='utf-8-sig', newline='') as handle:
                reader = csv.DictReader(handle)
                for field in reader.fieldnames or []:
                    all_fields.setdefault(field, None)
                for row in reader:
                    species_id = str(row.get('species_id') or '').strip()
                    if species_id not in selected:
                        continue
                    normalized = {key: (value or '') for key, value in row.items()}
                    if target.name == FILES['status']:
                        previous = status_by_species.get(species_id)
                        if previous is None:
                            status_by_species[species_id] = normalized
                        else:
                            previous_score = sum(int(float(previous.get(field) or 0)) for field in ('go_rows', 'kegg_gene_rows', 'kegg_joined_rows'))
                            current_score = sum(int(float(normalized.get(field) or 0)) for field in ('go_rows', 'kegg_gene_rows', 'kegg_joined_rows'))
                            if current_score > previous_score:
                                status_by_species[species_id] = normalized
                    else:
                        rows_buffer.append(normalized)
                    total += 1
                    seen_species.add(species_id)
        fieldnames = list(all_fields)
        if target.name == FILES['status']:
            rows_buffer = list(status_by_species.values())
            total = len(rows_buffer)
        with target.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows_buffer)
        return total, seen_species, fieldnames

    def _write_go_terms(self, paths: list[Path], target: Path) -> int:
        if not paths:
            raise CommandError(f'No GO term source files found for {target.name}')
        all_fields: OrderedDict[str, None] = OrderedDict()
        rows: OrderedDict[str, dict[str, str]] = OrderedDict()
        for path in paths:
            with path.open('r', encoding='utf-8-sig', newline='') as handle:
                reader = csv.DictReader(handle)
                for field in reader.fieldnames or []:
                    all_fields.setdefault(field, None)
                for row in reader:
                    go_id = str(row.get('go_id') or '').strip()
                    if go_id and go_id not in rows:
                        rows[go_id] = {key: (value or '') for key, value in row.items()}
        fieldnames = list(all_fields)
        with target.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows.values())
        return len(rows)
