from __future__ import annotations

import csv
import gc
import json
from pathlib import Path
from typing import Any

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, reset_queries, transaction
from django.utils import timezone

from backend.apps.common.json_safe import sanitize_for_json
from backend.apps.stoichdb import services
from backend.apps.stoichdb.models import (
    AnalysisArtifact,
    DataRelease,
    EntityRecord,
    FeatureFile,
    GeneIndex,
    OmicsDataset,
    ProteinIndex,
    Species,
    TranscriptIndex,
)


def load_json(path: Path) -> Any:
    return sanitize_for_json(json.loads(path.read_text(encoding='utf-8')))


def normalize_species_id(value: str) -> str:
    return str(value).strip().lower().replace('.', '_').replace('-', '_').replace('__', '_')


def pretty_species_name(species_id: str) -> str:
    parts = str(species_id).replace('_', ' ').split()
    if not parts:
        return species_id
    if len(parts) >= 2:
        first = parts[0].capitalize()
        rest = ' '.join(parts[1:])
        return f'{first} {rest}'
    return str(species_id)


def short_name(display_name: str) -> str:
    parts = display_name.split()
    if len(parts) >= 2:
        return parts[0][0] + '. ' + ' '.join(parts[1:])
    return display_name


def textify(*parts: Any) -> str:
    return ' '.join(str(p) for p in parts if p not in [None, '']).strip()


def positive_float_or_zero(*values: Any) -> float:
    for value in values:
        normalized = normalize_payload_value(value)
        if normalized in [None, '']:
            continue
        try:
            number = float(normalized)
        except Exception:
            continue
        if number > 0:
            return number
    return 0.0


def render_progress_bar(current: int, total: int, width: int = 24) -> str:
    if total <= 0:
        return '[' + ('-' * width) + ']'
    ratio = max(0.0, min(1.0, current / total))
    filled = int(round(width * ratio))
    return '[' + ('#' * filled) + ('-' * (width - filled)) + ']'


def normalize_payload_value(value: Any) -> Any:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value.item() if hasattr(value, 'item') else value


TEXT_FIELD_MARKERS = {
    'id',
    'name',
    'symbol',
    'description',
    'biotype',
    'seq',
    'strand',
    'source',
    'md5',
    'rule',
    'reason',
    'assembly',
    'db',
    'header',
    'cluster',
    'status',
    'tag',
}


def parse_number(value: Any) -> int | float | None:
    value = normalize_payload_value(value)
    if value in [None, '']:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if not text or text.lower() in {'nan', 'na', 'none', 'null'}:
        return None
    try:
        number = float(text)
    except Exception:
        return None
    if number.is_integer() and all(token not in text.lower() for token in ['.', 'e']):
        return int(number)
    return number


def normalize_csv_payload_value(key: str, value: Any) -> Any:
    value = normalize_payload_value(value)
    if value in [None, '']:
        return None
    text = str(value).strip()
    if not text or text.lower() in {'nan', 'na', 'none', 'null'}:
        return None
    key_lower = str(key).lower()
    if any(marker in key_lower for marker in TEXT_FIELD_MARKERS):
        return text
    number = parse_number(text)
    return number if number is not None else text


class Command(BaseCommand):
    help = 'Import staged stoichdb pipeline outputs into ORM tables suitable for PostgreSQL-backed serving.'

    def add_arguments(self, parser):
        parser.add_argument('--pipeline-root', required=True, help='Root directory containing stage4_catalog, stage5_artifacts, and stage6_platform_registry')
        parser.add_argument('--flush', action='store_true', help='Delete current stoichdb records before import')
        parser.add_argument(
            '--entity-source',
            choices=['auto', 'platform', 'core', 'full'],
            default='auto',
            help=(
                'Which per-entity feature table to store in EntityRecord.payload_json. '
                'auto imports core rows into PostgreSQL and keeps full table paths registered; '
                'platform keeps the current lightweight rows_for_platform.csv behavior; '
                'core imports OmicsDataset.core_csv_path; full imports OmicsDataset.full_csv_path.'
            ),
        )
        parser.add_argument(
            '--entity-chunk-size',
            type=int,
            default=2000,
            help='CSV chunk size for importing EntityRecord rows. Use a smaller value such as 500 for full wide tables.',
        )
        parser.add_argument(
            '--entity-csv-engine',
            choices=['auto', 'c', 'python'],
            default='auto',
            help='CSV parser engine for EntityRecord rows. auto uses python for full wide tables and c otherwise.',
        )
        parser.add_argument(
            '--entity-batch-size',
            type=int,
            default=100,
            help='Database insert batch size for EntityRecord rows. Use 5-20 for full wide JSON payloads on low memory machines.',
        )
        parser.add_argument(
            '--entity-min-batch-size',
            type=int,
            default=10,
            help='Minimum adaptive EntityRecord insert batch size.',
        )
        parser.add_argument(
            '--entity-max-batch-size',
            type=int,
            default=500,
            help='Maximum adaptive EntityRecord insert batch size.',
        )
        parser.add_argument(
            '--no-adaptive-import',
            dest='adaptive_import',
            action='store_false',
            help='Disable memory-aware adaptive EntityRecord batch resizing.',
        )
        parser.add_argument(
            '--index-batch-size',
            type=int,
            default=2000,
            help='Database insert batch size for GeneIndex, TranscriptIndex, and ProteinIndex streaming imports.',
        )
        parser.add_argument(
            '--validate-stage-paths-only',
            action='store_true',
            help='Validate stage5/stage6 species artifact paths and exit without writing database records.',
        )
        parser.add_argument(
            '--skip-entity-records',
            action='store_true',
            help='Import species, datasets, feature files, entity indexes, artifacts, and release metadata without materializing EntityRecord rows.',
        )
        parser.set_defaults(adaptive_import=True)


    def _build_stage5_dir_lookup(self, stage5: Path) -> dict[str, Path]:
        lookup: dict[str, Path] = {}
        if not stage5.exists():
            return lookup
        for child in stage5.iterdir():
            if not child.is_dir() or child.name == 'compare':
                continue
            lookup.setdefault(child.name, child)
            lookup.setdefault(normalize_species_id(child.name), child)
        return lookup

    def _stage5_species_dir(self, lookup: dict[str, Path], *species_ids: Any) -> Path | None:
        for value in species_ids:
            text = str(value or '').strip()
            if not text or text.lower() in {'nan', 'none', 'null'}:
                continue
            direct = lookup.get(text)
            if direct is not None:
                return direct
            normalized = normalize_species_id(text)
            direct = lookup.get(normalized)
            if direct is not None:
                return direct
        return None

    def _require_stage5_species_dir(self, lookup: dict[str, Path], *species_ids: Any) -> Path:
        species_dir = self._stage5_species_dir(lookup, *species_ids)
        if species_dir is None:
            candidates = ', '.join(str(value) for value in species_ids if value not in [None, ''])
            raise CommandError(f'Missing stage5 artifact directory for species candidates: {candidates}')
        return species_dir
    def _progress_line(self, label: str, current: int, total: int, detail: str = '') -> str:
        total = max(total, current, 1)
        percent = (current / total) * 100.0
        suffix = f' | {detail}' if detail else ''
        return f'{label} {render_progress_bar(current, total)} {percent:6.2f}% ({current}/{total}){suffix}'

    def _progress_step(self, total: int, target_updates: int = 40) -> int:
        return max(1, total // max(1, target_updates))

    def handle(self, *args, **options):
        if settings.DEBUG:
            settings.DEBUG = False
            for connection in connections.all():
                connection.force_debug_cursor = False
            self.stdout.write('Disabled Django DEBUG SQL logging for this import command.')

        pipeline_root = Path(options['pipeline_root']).resolve()
        requested_entity_source = str(options.get('entity_source') or 'auto').lower()
        entity_source = 'core' if requested_entity_source == 'auto' else requested_entity_source
        entity_chunk_size = max(1, int(options.get('entity_chunk_size') or 2000))
        entity_batch_size = max(1, int(options.get('entity_batch_size') or 100))
        entity_min_batch_size = max(1, int(options.get('entity_min_batch_size') or 10))
        entity_max_batch_size = max(entity_min_batch_size, int(options.get('entity_max_batch_size') or 500))
        adaptive_import = bool(options.get('adaptive_import', True))
        index_batch_size = max(100, int(options.get('index_batch_size') or 2000))
        stage4 = pipeline_root / 'stage4_catalog' / 'db_seed'
        stage5 = pipeline_root / 'stage5_artifacts'
        stage6 = pipeline_root / 'stage6_platform_registry'
        if not stage4.exists() or not stage5.exists() or not stage6.exists():
            raise CommandError('pipeline-root must contain stage4_catalog/db_seed, stage5_artifacts, and stage6_platform_registry')

        if options['flush']:
            self.stdout.write('Flushing existing stoichdb tables...')
            with transaction.atomic():
                EntityRecord.objects.all().delete()
                ProteinIndex.objects.all().delete()
                TranscriptIndex.objects.all().delete()
                GeneIndex.objects.all().delete()
                AnalysisArtifact.objects.all().delete()
                FeatureFile.objects.all().delete()
                OmicsDataset.objects.all().delete()
                Species.objects.all().delete()
                DataRelease.objects.all().update(is_active=False)

        index_payload = load_json(stage6 / 'index.json')
        index_species = {}
        for index_row in index_payload.get('species', []):
            raw_index_sid = str(index_row.get('species_id') or '').strip()
            if raw_index_sid:
                index_species[raw_index_sid] = index_row
                index_species[normalize_species_id(raw_index_sid)] = index_row
        omics_meta = index_payload.get('omics_meta', {})
        stage5_dir_lookup = self._build_stage5_dir_lookup(stage5)

        species_df = pd.read_csv(stage4 / 'species.csv')
        species_records = []
        species_rows = species_df.to_dict(orient='records')
        if options.get('validate_stage_paths_only'):
            dataset_df = pd.read_csv(stage4 / 'omics_dataset.csv')
            missing: list[str] = []
            for row in species_rows:
                sid = normalize_species_id(row['species_id'])
                species_stage5_dir = self._stage5_species_dir(stage5_dir_lookup, row.get('species_id'), row.get('source_species_id'), sid)
                if species_stage5_dir is None:
                    missing.append(f"species_dir:{row.get('species_id')}")
                    if len(missing) >= 10:
                        break
                    continue
                for name in ['browse_meta.json', 'cross_omics.json']:
                    if not (species_stage5_dir / name).exists():
                        missing.append(f"{row.get('species_id')}:{name}")
                        if len(missing) >= 10:
                            break
                if len(missing) >= 10:
                    break
            if not missing:
                for row in dataset_df.to_dict(orient='records'):
                    sid = normalize_species_id(row['species_id'])
                    omics_type = str(row['omics_type']).lower()
                    species_stage5_dir = self._stage5_species_dir(stage5_dir_lookup, row.get('species_id'), sid)
                    if species_stage5_dir is None:
                        missing.append(f"dataset_dir:{row.get('species_id')}:{omics_type}")
                    else:
                        for name in ['summary.json', 'analysis.json']:
                            if not (species_stage5_dir / omics_type / name).exists():
                                missing.append(f"{row.get('species_id')}:{omics_type}:{name}")
                                break
                    if len(missing) >= 10:
                        break
            if missing:
                raise CommandError('Stage path validation failed: ' + '; '.join(missing))
            self.stdout.write(self.style.SUCCESS(f'Stage path validation passed: species={len(species_rows)}, datasets={len(dataset_df)}, stage5_dirs={len(stage5_dir_lookup)}'))
            return
        species_total = len(species_rows)
        species_step = self._progress_step(species_total, target_updates=50)
        self.stdout.write(self._progress_line('Import species', 0, species_total, 'starting'))
        for idx, row in enumerate(species_rows, start=1):
            sid = normalize_species_id(row['species_id'])
            idx_row = index_species.get(sid, {})
            display_name = idx_row.get('display_name') or row.get('display_name') or sid
            if str(display_name).lower() in {'core', 'full', '', 'nan'}:
                display_name = pretty_species_name(sid)
            short_name_value = idx_row.get('short_name') or row.get('short_name') or display_name
            if str(short_name_value).lower() in {'core', 'full', '', 'nan'}:
                short_name_value = short_name(str(display_name))
            source_species_id = idx_row.get('source_species_id') or row.get('source_species_id') or row.get('species_id') or sid
            stage5_species_dir = self._stage5_species_dir(stage5_dir_lookup, row.get('species_id'), source_species_id, sid)
            species_records.append(Species(
                species_id=sid,
                display_name=str(display_name),
                short_name=str(short_name_value),
                source_species_id=str(source_species_id),
                domain=str(idx_row.get('domain') or row.get('domain') or ''),
                kingdom=str(idx_row.get('kingdom') or ''),
                phylum=str(idx_row.get('phylum') or ''),
                clade=str(idx_row.get('clade') or row.get('clade') or ''),
                habitat=str(idx_row.get('habitat') or row.get('habitat') or ''),
                source_database=str(idx_row.get('source_database') or 'Feature-table case import'),
                assembly_version=str(idx_row.get('assembly_version') or ''),
                genome_size_mb=positive_float_or_zero(row.get('genome_size_mb'), idx_row.get('genome_size_mb')),
                has_genome=bool(row.get('has_genome')),
                has_transcriptome=bool(row.get('has_transcriptome')),
                has_proteome=bool(row.get('has_proteome')),
                fingerprint=idx_row.get('fingerprint') or {},
                cross_omics_payload=load_json(stage5_species_dir / 'cross_omics.json') if stage5_species_dir and (stage5_species_dir / 'cross_omics.json').exists() else {},
                searchable_text=textify(display_name, sid, row.get('domain'), row.get('clade'), row.get('habitat')),
                is_featured=True,
            ))
            if idx == 1 or idx == species_total or idx % species_step == 0:
                self.stdout.write(self._progress_line('Import species', idx, species_total, sid))
        species_update_fields = [
            'display_name',
            'short_name',
            'source_species_id',
            'domain',
            'kingdom',
            'phylum',
            'clade',
            'habitat',
            'source_database',
            'assembly_version',
            'genome_size_mb',
            'has_genome',
            'has_transcriptome',
            'has_proteome',
            'fingerprint',
            'cross_omics_payload',
            'searchable_text',
            'is_featured',
        ]
        with transaction.atomic():
            Species.objects.bulk_create(
                species_records,
                batch_size=500,
                update_conflicts=True,
                update_fields=species_update_fields,
                unique_fields=['species_id'],
            )
        species_map = {row.species_id: row for row in Species.objects.all()}
        self.stdout.write(f'Imported/updated species: {len(species_records)}; database species total: {len(species_map)}')

        dataset_df = pd.read_csv(stage4 / 'omics_dataset.csv')
        browse_meta_payloads = {}
        for row in species_rows:
            sid = normalize_species_id(row['species_id'])
            species = species_map.get(sid)
            source_species_id = species.source_species_id if species else row.get('source_species_id') or row.get('species_id')
            species_stage5_dir = self._stage5_species_dir(stage5_dir_lookup, row.get('species_id'), source_species_id, sid)
            browse_path = species_stage5_dir / 'browse_meta.json' if species_stage5_dir else None
            browse_meta_payloads[sid] = load_json(browse_path) if browse_path and browse_path.exists() else {}
        ds_records = []
        dataset_rows = dataset_df.to_dict(orient='records')
        dataset_total = len(dataset_rows)
        dataset_step = self._progress_step(dataset_total, target_updates=50)
        self.stdout.write(self._progress_line('Import datasets', 0, dataset_total, 'starting'))
        for idx, row in enumerate(dataset_rows, start=1):
            sid = normalize_species_id(row['species_id'])
            species = species_map[sid]
            omics_type = str(row['omics_type']).lower()
            species_stage5_dir = self._require_stage5_species_dir(stage5_dir_lookup, row.get('species_id'), species.source_species_id, sid)
            summary_payload = load_json(species_stage5_dir / omics_type / 'summary.json')
            analysis_payload = load_json(species_stage5_dir / omics_type / 'analysis.json')
            browse_meta = {**(omics_meta.get(omics_type) or {}), **(browse_meta_payloads.get(sid, {}).get(omics_type) or {})}
            ds_records.append(OmicsDataset(
                dataset_id=str(row['dataset_id']),
                species=species,
                omics_type=omics_type,
                schema_version=str(row.get('schema_version') or 'auto_v1'),
                row_count_core=int(row.get('row_count_core') or 0),
                row_count_full=int(row.get('row_count_full') or 0),
                core_csv_path=str(row.get('core_csv_path') or ''),
                full_csv_path=str(row.get('full_csv_path') or ''),
                status=str(row.get('status') or 'ready'),
                browse_meta=browse_meta,
                summary_payload=summary_payload,
                analysis_payload=analysis_payload,
                searchable_text=textify(species.display_name, species.species_id, omics_type, browse_meta.get('description')),
            ))
            if idx == 1 or idx == dataset_total or idx % dataset_step == 0:
                self.stdout.write(self._progress_line('Import datasets', idx, dataset_total, f'{sid}/{omics_type}'))
        dataset_update_fields = [
            'species',
            'omics_type',
            'schema_version',
            'row_count_core',
            'row_count_full',
            'core_csv_path',
            'full_csv_path',
            'status',
            'browse_meta',
            'summary_payload',
            'analysis_payload',
            'searchable_text',
        ]
        with transaction.atomic():
            OmicsDataset.objects.bulk_create(
                ds_records,
                batch_size=500,
                update_conflicts=True,
                update_fields=dataset_update_fields,
                unique_fields=['dataset_id'],
            )
        dataset_map = {row.dataset_id: row for row in OmicsDataset.objects.select_related('species').all()}
        self.stdout.write(f'Imported/updated datasets: {len(ds_records)}; database dataset total: {len(dataset_map)}')

        file_df = pd.read_csv(stage4 / 'feature_file.csv')
        feature_rows = [
            FeatureFile(
                file_id=str(row['file_id']),
                dataset=dataset_map[str(row['dataset_id'])],
                file_type=str(row.get('file_type') or ''),
                path=str(row.get('path') or ''),
                size_bytes=int(row.get('size_bytes') or 0),
            )
            for _, row in file_df.iterrows()
            if str(row['dataset_id']) in dataset_map
        ]
        self.stdout.write(self._progress_line('Import feature files', len(feature_rows), len(feature_rows), 'ready to bulk insert'))
        with transaction.atomic():
            FeatureFile.objects.bulk_create(
                feature_rows,
                batch_size=1000,
                update_conflicts=True,
                update_fields=['dataset', 'file_type', 'path', 'size_bytes'],
                unique_fields=['file_id'],
            )

        self._import_entity_indexes(stage4, species_map, batch_size=index_batch_size)
        if options['skip_entity_records']:
            self.stdout.write('Skipped EntityRecord import; core rows remain available through OmicsDataset.core_csv_path.')
        else:
            entity_csv_engine = str(options['entity_csv_engine'])
            self._import_entity_rows(
                stage5,
                dataset_map,
                entity_source=entity_source,
                chunksize=entity_chunk_size,
                csv_engine=entity_csv_engine,
                batch_size=entity_batch_size,
                min_batch_size=entity_min_batch_size,
                max_batch_size=entity_max_batch_size,
                adaptive_import=adaptive_import,
            )
        self._import_artifacts(stage5, species_map, dataset_map, stage5_dir_lookup)
        registered_entity_source = 'skipped' if options['skip_entity_records'] else entity_source
        self._register_release(pipeline_root, stage6, entity_source=registered_entity_source, requested_entity_source=requested_entity_source)
        services.clear_runtime_caches()
        self.stdout.write(self.style.SUCCESS('Stoichdb pipeline import completed.'))

    def _csv_dict_rows(self, path: Path):
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                yield row

    def _int_value(self, value: Any) -> int | None:
        number = parse_number(value)
        return int(number) if number is not None else None

    def _flush_bulk_records(self, records: list[Any], *, batch_size: int) -> int:
        if not records:
            return 0
        model = type(records[0])
        count = len(records)
        conflict_options = {
            GeneIndex: {
                'update_fields': ['gene_name', 'locus_tag', 'biotype', 'seqid', 'start_1', 'end_1', 'strand'],
                'unique_fields': ['species', 'gene_id'],
            },
            TranscriptIndex: {
                'update_fields': ['gene_id', 'gene_symbol', 'transcript_biotype', 'seq_region', 'start', 'end', 'strand'],
                'unique_fields': ['species', 'transcript_id'],
            },
            ProteinIndex: {
                'update_fields': ['ensembl_gene_id', 'gene_id', 'gene_symbol', 'description', 'length_aa'],
                'unique_fields': ['species', 'protein_id'],
            },
        }.get(model)
        kwargs = conflict_options or {}
        if kwargs:
            kwargs = {'update_conflicts': True, **kwargs}
        with transaction.atomic():
            model.objects.bulk_create(records, batch_size=batch_size, **kwargs)
        records.clear()
        reset_queries()
        return count

    def _import_entity_indexes(self, stage4: Path, species_map: dict[str, Species], batch_size: int = 2000) -> None:
        self._import_gene_index_stream(stage4 / 'gene_index.csv', species_map, batch_size=batch_size)
        self._import_transcript_index_stream(stage4 / 'transcript_index.csv', species_map, batch_size=batch_size)
        self._import_protein_index_stream(stage4 / 'protein_index.csv', species_map, batch_size=batch_size)
        gc.collect()
        self.stdout.write('Imported entity index tables.')

    def _existing_index_ids_for_species(self, model: type[Any], species: Species, id_field: str) -> set[str]:
        return set(model.objects.filter(species=species).values_list(id_field, flat=True))

    def _index_progress(self, label: str, scanned: int, inserted: int, skipped_existing: int, detail: str = '') -> None:
        suffix = f' | {detail}' if detail else ''
        self.stdout.write(f'{label}: scanned={scanned} inserted={inserted} skipped_existing={skipped_existing}{suffix}')

    def _import_gene_index_stream(self, path: Path, species_map: dict[str, Species], batch_size: int = 5000) -> None:
        records = []
        scanned = 0
        inserted = 0
        skipped_existing = 0
        current_species_id = None
        existing_ids: set[str] = set()
        report_step = 100000
        next_report = report_step
        for row in self._csv_dict_rows(path):
            scanned += 1
            sid = normalize_species_id(row.get('species_id') or '')
            species = species_map.get(sid)
            if not species:
                continue
            if current_species_id != species.id:
                current_species_id = species.id
                existing_ids = self._existing_index_ids_for_species(GeneIndex, species, 'gene_id')
            gene_id = str(row.get('gene_id') or '')
            if not gene_id:
                continue
            if gene_id in existing_ids:
                skipped_existing += 1
            else:
                existing_ids.add(gene_id)
                records.append(GeneIndex(
                    species=species,
                    gene_id=gene_id,
                    gene_name=str(row.get('gene_name') or ''),
                    locus_tag=str(row.get('locus_tag') or ''),
                    biotype=str(row.get('biotype') or ''),
                    seqid=str(row.get('seqid') or ''),
                    start_1=self._int_value(row.get('start_1')),
                    end_1=self._int_value(row.get('end_1')),
                    strand=str(row.get('strand') or ''),
                ))
            if len(records) >= batch_size:
                inserted += self._flush_bulk_records(records, batch_size=batch_size)
            if scanned >= next_report:
                self._index_progress('Import gene index', scanned, inserted, skipped_existing, sid)
                next_report += report_step
        inserted += self._flush_bulk_records(records, batch_size=batch_size)
        self._index_progress('Import gene index done', scanned, inserted, skipped_existing, 'streamed resumable bulk insert')

    def _import_transcript_index_stream(self, path: Path, species_map: dict[str, Species], batch_size: int = 5000) -> None:
        records = []
        scanned = 0
        inserted = 0
        skipped_existing = 0
        current_species_id = None
        existing_ids: set[str] = set()
        report_step = 100000
        next_report = report_step
        for row in self._csv_dict_rows(path):
            scanned += 1
            sid = normalize_species_id(row.get('species_id') or '')
            species = species_map.get(sid)
            if not species:
                continue
            if current_species_id != species.id:
                current_species_id = species.id
                existing_ids = self._existing_index_ids_for_species(TranscriptIndex, species, 'transcript_id')
            transcript_id = str(row.get('transcript_id') or '')
            if not transcript_id:
                continue
            if transcript_id in existing_ids:
                skipped_existing += 1
            else:
                existing_ids.add(transcript_id)
                records.append(TranscriptIndex(
                    species=species,
                    transcript_id=transcript_id,
                    gene_id=str(row.get('gene_id') or ''),
                    gene_symbol=str(row.get('gene_symbol') or ''),
                    transcript_biotype=str(row.get('transcript_biotype') or ''),
                    seq_region=str(row.get('seq_region') or ''),
                    start=self._int_value(row.get('start')),
                    end=self._int_value(row.get('end')),
                    strand=str(row.get('strand') or ''),
                ))
            if len(records) >= batch_size:
                inserted += self._flush_bulk_records(records, batch_size=batch_size)
            if scanned >= next_report:
                self._index_progress('Import transcript index', scanned, inserted, skipped_existing, sid)
                next_report += report_step
        inserted += self._flush_bulk_records(records, batch_size=batch_size)
        self._index_progress('Import transcript index done', scanned, inserted, skipped_existing, 'streamed resumable bulk insert')

    def _import_protein_index_stream(self, path: Path, species_map: dict[str, Species], batch_size: int = 5000) -> None:
        records = []
        scanned = 0
        inserted = 0
        skipped_existing = 0
        current_species_id = None
        existing_ids: set[str] = set()
        report_step = 100000
        next_report = report_step
        for row in self._csv_dict_rows(path):
            scanned += 1
            sid = normalize_species_id(row.get('species_id') or '')
            species = species_map.get(sid)
            if not species:
                continue
            if current_species_id != species.id:
                current_species_id = species.id
                existing_ids = self._existing_index_ids_for_species(ProteinIndex, species, 'protein_id')
            protein_id = str(row.get('protein_id') or '')
            if not protein_id:
                continue
            if protein_id in existing_ids:
                skipped_existing += 1
            else:
                existing_ids.add(protein_id)
                records.append(ProteinIndex(
                    species=species,
                    protein_id=protein_id,
                    ensembl_gene_id=str(row.get('ensembl_gene_id') or ''),
                    gene_id=str(row.get('gene_id') or ''),
                    gene_symbol=str(row.get('gene_symbol') or ''),
                    description=str(row.get('description') or ''),
                    length_aa=self._int_value(row.get('length_aa')),
                ))
            if len(records) >= batch_size:
                inserted += self._flush_bulk_records(records, batch_size=batch_size)
            if scanned >= next_report:
                self._index_progress('Import protein index', scanned, inserted, skipped_existing, sid)
                next_report += report_step
        inserted += self._flush_bulk_records(records, batch_size=batch_size)
        self._index_progress('Import protein index done', scanned, inserted, skipped_existing, 'streamed resumable bulk insert')

    def _entity_rows_path(self, stage5: Path, dataset: OmicsDataset, entity_source: str) -> Path:
        if entity_source == 'full':
            return Path(dataset.full_csv_path)
        if entity_source == 'core':
            return Path(dataset.core_csv_path)
        return stage5 / dataset.species.species_id / dataset.omics_type / 'rows_for_platform.csv'

    def _entity_expected_rows(self, dataset: OmicsDataset, entity_source: str) -> int:
        if entity_source == 'full':
            return int(dataset.row_count_full or dataset.row_count_core or 0)
        return int(dataset.row_count_core or dataset.row_count_full or 0)

    def _payload_value(self, payload: dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = normalize_payload_value(payload.get(key))
            if value in [None, '']:
                continue
            value_str = str(value).strip()
            if value_str and value_str.lower() not in {'nan', 'none', 'null'}:
                return value_str
        return ''

    def _entity_identity(self, dataset: OmicsDataset, payload: dict[str, Any]) -> tuple[str, str, str]:
        if dataset.omics_type == 'proteome':
            entity_id = self._payload_value(payload, [
                'entity_id',
                'protein_id',
                'ensembl_protein_id',
                'source_protein_id',
                'transcript_id',
                'gene_id',
                'ensembl_gene_id',
            ])
            canonical_gene_id = self._payload_value(payload, ['gene_id', 'ensembl_gene_id'])
            secondary_id = self._payload_value(payload, [
                'protein_id',
                'ensembl_protein_id',
                'source_protein_id',
                'transcript_id',
            ])
        elif dataset.omics_type == 'transcriptome':
            entity_id = self._payload_value(payload, ['entity_id', 'transcript_id', 'gene_id', 'ensembl_gene_id'])
            canonical_gene_id = self._payload_value(payload, ['gene_id', 'ensembl_gene_id', 'transcript_id'])
            secondary_id = self._payload_value(payload, ['transcript_id', 'gene_id'])
        else:
            entity_id = self._payload_value(payload, ['entity_id', 'gene_id', 'source_gene_id', 'locus_tag'])
            canonical_gene_id = self._payload_value(payload, ['gene_id', 'ensembl_gene_id', 'source_gene_id'])
            secondary_id = self._payload_value(payload, ['source_gene_id', 'locus_tag', 'gene_id'])
        return entity_id, canonical_gene_id or entity_id, secondary_id

    def _unique_entity_id(self, payload: dict[str, Any], base_entity_id: str, seen_entity_ids: set[str], row_number: int) -> str:
        entity_id = base_entity_id or f'row_{row_number}'
        if entity_id not in seen_entity_ids:
            return entity_id

        for key in ['protein_id', 'transcript_id', 'source_protein_id', 'source_gene_id', 'locus_tag']:
            candidate = self._payload_value(payload, [key])
            if candidate and candidate not in seen_entity_ids:
                payload['entity_id_original'] = entity_id
                return candidate

        payload['entity_id_original'] = entity_id
        suffix = 2
        while f'{entity_id}__dup{suffix}' in seen_entity_ids:
            suffix += 1
        return f'{entity_id}__dup{suffix}'

    def _entity_csv_reader(self, rows_path: Path, *, entity_source: str, chunksize: int, csv_engine: str):
        engine = 'python' if csv_engine == 'auto' and entity_source == 'full' else csv_engine
        if engine == 'auto':
            engine = 'c'
        kwargs: dict[str, Any] = {'chunksize': chunksize, 'engine': engine}
        if engine == 'c':
            kwargs['low_memory'] = False
        return pd.read_csv(rows_path, **kwargs)

    def _available_memory(self) -> tuple[int | None, float | None]:
        try:
            import psutil  # type: ignore

            memory = psutil.virtual_memory()
            return int(memory.available), float(memory.available / memory.total) if memory.total else None
        except Exception:
            return None, None

    def _tune_batch_size(self, current: int, *, minimum: int, maximum: int, adaptive: bool) -> int:
        if not adaptive:
            return current
        available_bytes, available_ratio = self._available_memory()
        if available_bytes is None or available_ratio is None:
            return current
        available_mb = available_bytes / (1024 * 1024)
        if available_ratio < 0.12 or available_mb < 512:
            return max(minimum, max(1, current // 2))
        if available_ratio > 0.35 and available_mb > 2048:
            return min(maximum, max(current + 1, int(current * 1.35)))
        return current

    def _bulk_create_entity_records_resilient(self, records: list[EntityRecord], batch_size: int) -> None:
        if not records:
            return
        try:
            with transaction.atomic():
                EntityRecord.objects.bulk_create(records, batch_size=batch_size)
            return
        except MemoryError:
            if len(records) <= 1 or batch_size <= 1:
                raise
            gc.collect()
            smaller = max(1, batch_size // 2)
            midpoint = max(1, len(records) // 2)
            self._bulk_create_entity_records_resilient(records[:midpoint], smaller)
            self._bulk_create_entity_records_resilient(records[midpoint:], smaller)

    def _flush_entity_records(self, records: list[EntityRecord], batch_size: int) -> int:
        if not records:
            return 0
        count = len(records)
        self._bulk_create_entity_records_resilient(records, batch_size)
        records.clear()
        reset_queries()
        gc.collect()
        return count

    def _import_entity_rows(
        self,
        stage5: Path,
        dataset_map: dict[str, OmicsDataset],
        *,
        entity_source: str,
        chunksize: int,
        csv_engine: str,
        batch_size: int,
        min_batch_size: int,
        max_batch_size: int,
        adaptive_import: bool,
    ) -> None:
        dataset_items = list(dataset_map.items())
        dataset_total = len(dataset_items)
        for dataset_idx, (dataset_id, dataset) in enumerate(dataset_items, start=1):
            rows_path = self._entity_rows_path(stage5, dataset, entity_source)
            if not rows_path.exists():
                if entity_source in {'core', 'full'}:
                    raise CommandError(f'Missing {entity_source} entity source for {dataset.dataset_id}: {rows_path}')
                continue
            expected_rows = self._entity_expected_rows(dataset, entity_source)
            imported_rows = 0
            report_step = max(2000, self._progress_step(expected_rows or 1, target_updates=40))
            next_report = report_step
            seen_entity_ids: set[str] = set()
            current_batch_size = max(min_batch_size, min(batch_size, max_batch_size, chunksize))
            max_buffer_size = max(current_batch_size, min(max_batch_size, chunksize))
            self.stdout.write(self._progress_line('Import entity rows', 0, max(expected_rows, 1), f'{dataset_idx}/{dataset_total} {dataset.dataset_id} source={entity_source} streaming file={rows_path.name} batch={current_batch_size} adaptive={adaptive_import}'))
            records: list[EntityRecord] = []
            for row in self._csv_dict_rows(rows_path):
                payload = {k: normalize_csv_payload_value(k, v) for k, v in row.items()}
                row_number = imported_rows + len(records) + 1
                base_entity_id, canonical_gene_id, secondary_id = self._entity_identity(dataset, payload)
                entity_id = self._unique_entity_id(payload, base_entity_id, seen_entity_ids, row_number)
                seen_entity_ids.add(entity_id)
                payload['entity_id'] = entity_id
                gene_name = self._payload_value(payload, ['gene_name', 'gene_symbol'])
                description = self._payload_value(payload, ['description', 'biotype', 'transcript_biotype'])
                seqid = self._payload_value(payload, ['seqid', 'seq_region'])
                start_pos = payload.get('start_1') if payload.get('start_1') is not None else payload.get('start')
                end_pos = payload.get('end_1') if payload.get('end_1') is not None else payload.get('end')
                search_text = textify(entity_id, canonical_gene_id, gene_name, description, dataset.species.display_name, dataset.omics_type, payload.get('strategy_cluster'))
                numeric_summary = {k: v for k, v in payload.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
                records.append(EntityRecord(
                    dataset=dataset,
                    species=dataset.species,
                    omics_type=dataset.omics_type,
                    entity_id=entity_id,
                    canonical_gene_id=canonical_gene_id,
                    secondary_id=secondary_id,
                    gene_name=gene_name,
                    description=description,
                    strategy_cluster=str(payload.get('strategy_cluster') or ''),
                    seqid=seqid,
                    start_pos=self._int_value(start_pos),
                    end_pos=self._int_value(end_pos),
                    payload_json=payload,
                    searchable_text=search_text,
                    numeric_summary=numeric_summary,
                ))
                if len(records) >= current_batch_size:
                    imported_rows += self._flush_entity_records(records, current_batch_size)
                    tuned_batch_size = self._tune_batch_size(current_batch_size, minimum=min_batch_size, maximum=max_buffer_size, adaptive=adaptive_import)
                    if tuned_batch_size != current_batch_size:
                        current_batch_size = tuned_batch_size
                        self.stdout.write(f'Adjusted entity import batch size to {current_batch_size}')
                progress_total = max(expected_rows, imported_rows, 1)
                if imported_rows >= next_report or imported_rows == progress_total:
                    self.stdout.write(
                        self._progress_line(
                            'Import entity rows',
                            imported_rows,
                            progress_total,
                            f'{dataset_idx}/{dataset_total} {dataset.dataset_id} source={entity_source}',
                        )
                    )
                    next_report += report_step
            imported_rows += self._flush_entity_records(records, current_batch_size)
            self.stdout.write(self._progress_line('Import entity rows', imported_rows, max(expected_rows, imported_rows, 1), f'completed {dataset.dataset_id} source={entity_source}'))

    def _flush_artifact_records(self, records: list[AnalysisArtifact], *, batch_size: int) -> int:
        if not records:
            return 0
        count = len(records)
        with transaction.atomic():
            AnalysisArtifact.objects.bulk_create(
                records,
                batch_size=batch_size,
                update_conflicts=True,
                update_fields=['species', 'dataset', 'omics_type', 'artifact_type', 'path', 'payload_json', 'version'],
                unique_fields=['artifact_id'],
            )
        records.clear()
        reset_queries()
        return count

    def _import_artifacts(self, stage5: Path, species_map: dict[str, Species], dataset_map: dict[str, OmicsDataset], stage5_dir_lookup: dict[str, Path], batch_size: int = 500) -> None:
        artifact_records: list[AnalysisArtifact] = []
        imported = 0
        species_items = [
            (species_id, species)
            for species_id, species in species_map.items()
            if self._stage5_species_dir(stage5_dir_lookup, species.source_species_id, species_id) is not None
        ]
        species_total = len(species_items)
        species_step = self._progress_step(species_total, target_updates=40)
        dataset_by_species_omics = {(dataset.species_id, dataset.omics_type): dataset for dataset in dataset_map.values()}
        self.stdout.write(self._progress_line('Import artifacts', 0, max(species_total, 1), 'starting'))
        for idx, (species_id, species) in enumerate(species_items, start=1):
            species_stage5_dir = self._stage5_species_dir(stage5_dir_lookup, species.source_species_id, species_id)
            if species_stage5_dir is None:
                continue
            cross_path = species_stage5_dir / 'cross_omics.json'
            if cross_path.exists():
                artifact_records.append(AnalysisArtifact(
                    artifact_id=f'{species_id}__cross_omics',
                    species=species,
                    dataset=None,
                    omics_type='all',
                    artifact_type='cross_omics',
                    path=str(cross_path),
                    payload_json=load_json(cross_path),
                    version='v1',
                ))
            for omics in ['genome', 'transcriptome', 'proteome']:
                ds = dataset_by_species_omics.get((species.id, omics))
                if not ds:
                    continue
                for artifact_type in ['profile', 'core_features', 'summary', 'analysis']:
                    path = species_stage5_dir / omics / f'{artifact_type}.json'
                    if path.exists():
                        artifact_records.append(AnalysisArtifact(
                            artifact_id=f'{species_id}__{omics}__{artifact_type}',
                            species=species,
                            dataset=ds,
                            omics_type=omics,
                            artifact_type=artifact_type,
                            path=str(path),
                            payload_json=load_json(path),
                            version='v1',
                        ))
                if len(artifact_records) >= batch_size:
                    imported += self._flush_artifact_records(artifact_records, batch_size=batch_size)
            if len(artifact_records) >= batch_size:
                imported += self._flush_artifact_records(artifact_records, batch_size=batch_size)
            if idx == 1 or idx == species_total or idx % species_step == 0:
                self.stdout.write(self._progress_line('Import artifacts', idx, species_total, f'{species_id}; imported={imported}'))
        imported += self._flush_artifact_records(artifact_records, batch_size=batch_size)
        self.stdout.write(f'Imported/updated artifacts: {imported}')

    def _register_release(self, pipeline_root: Path, stage6: Path, *, entity_source: str, requested_entity_source: str) -> None:
        manifest_path = pipeline_root / 'pipeline_manifest.json'
        manifest = load_json(manifest_path) if manifest_path.exists() else {}
        index_payload = load_json(stage6 / 'index.json')
        active_stamp = timezone.now()
        release_id = (
            str(manifest.get('release_id') or '').strip()
            or f"release_{active_stamp.strftime('%Y%m%d_%H%M%S')}"
        )
        label = (
            str(manifest.get('label') or '').strip()
            or f"Stoichioomics release {active_stamp.strftime('%Y-%m-%d %H:%M')}"
        )
        description = (
            str(manifest.get('description') or '').strip()
            or 'PostgreSQL-backed release imported from the staged stoichiometric feature-table pipeline.'
        )
        metadata_json = {
            'project': index_payload.get('project', {}),
            'omics_meta': index_payload.get('omics_meta', {}),
            'compare_pair_count': len(index_payload.get('compare_pairs', [])),
            'imported_via': 'import_stoichdb_pipeline',
            'active_database': 'postgresql',
            'entity_source': entity_source,
            'entity_source_requested': requested_entity_source,
            'full_tables_retained_as_files': entity_source != 'full',
            'import_strategy': (
                'entity_records_skipped_core_csv_paths_registered'
                if entity_source == 'skipped'
                else ('core_rows_in_postgresql_full_csv_paths_registered' if entity_source != 'full' else 'full_rows_in_postgresql')
            ),
        }
        with transaction.atomic():
            DataRelease.objects.all().update(is_active=False)
            DataRelease.objects.update_or_create(
                release_id=release_id,
                defaults={
                    'label': label,
                    'description': description,
                    'source_root': str(manifest.get('source_root') or ''),
                    'pipeline_root': str(pipeline_root),
                    'platform_registry_path': str(stage6),
                    'database_engine': 'postgresql',
                    'species_count': Species.objects.count(),
                    'dataset_count': OmicsDataset.objects.count(),
                    'entity_row_count': EntityRecord.objects.count(),
                    'artifact_count': AnalysisArtifact.objects.count(),
                    'feature_file_count': FeatureFile.objects.count(),
                    'metadata_json': metadata_json,
                    'manifest_json': manifest,
                    'is_active': True,
                },
            )
        self.stdout.write(f'Active release registered: {release_id}')






