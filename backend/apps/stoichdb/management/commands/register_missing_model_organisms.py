from __future__ import annotations
from backend.apps.stoichdb.feature_sources import io as feature_io

import csv
import json
from backend.apps.common.host_paths import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from backend.apps.stoichdb.models import OmicsDataset, Species


RELEASE_ID = 'model_organisms_20260731_v1'
GROUP_LABELS = {'bacteria': 'Bacteria', 'fungi': 'Fungi', 'metazoa': 'Metazoa', 'plants': 'Plants', 'protists': 'Protists', 'vertebrates': 'Vertebrates'}
OMICS = ('genome', 'transcriptome', 'proteome')


def _workspace_root() -> Path:
    return Path(settings.BASE_DIR).resolve().parent.parent


def _model_list() -> Path:
    root = _workspace_root()
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        for candidate in feature_io.logical_glob(directory, '*.csv'):
            try:
                with feature_io.open_source(candidate, 'r', encoding='utf-8-sig', newline='') as handle:
                    fields = set(next(csv.reader(handle), []))
            except (OSError, UnicodeError):
                continue
            if {'species_id', 'expected_model_group'}.issubset(fields):
                return candidate
    raise CommandError('Could not locate the model-organism whitelist CSV.')


def _feature_dirs() -> dict[str, Path]:
    """Infer the six-group feature directories from existing DB paths."""
    result: dict[str, Path] = {}
    for omics in OMICS:
        dataset = (
            OmicsDataset.objects
            .filter(omics_type=omics)
            .filter(species__domain__iexact='Bacteria')
            .exclude(core_csv_path='')
            .only('core_csv_path')
            .first()
        )
        if not dataset:
            continue
        path = Path(dataset.core_csv_path)
        if omics in {'genome', 'transcriptome'}:
            result[omics] = path.parent
        else:
            result[omics] = path.parent.parent
    if set(result) != set(OMICS):
        raise CommandError(f'Could not infer all feature directories from existing OmicsDataset paths: {result}')
    return result


def _stems(species_id: str) -> list[str]:
    values = [species_id, species_id.replace('subsp.', 'subsp_'), species_id.replace('.', '_')]
    return list(dict.fromkeys(values))


def _source_paths(dirs: dict[str, Path], species_id: str) -> dict[str, tuple[Path, Path]]:
    for stem in _stems(species_id):
        genome_dir = dirs['genome']
        transcript_dir = dirs['transcriptome']
        proteome_root = dirs['proteome']
        candidates = {
            'genome': (
                genome_dir / f'{stem}.genome_features.core.csv',
                genome_dir / f'{stem}.genome_features.csv',
            ),
            'transcriptome': (
                transcript_dir / f'{stem}.transcriptome.core.v5.csv',
                transcript_dir / f'{stem}.transcriptome.full.v5.csv',
            ),
            'proteome': (
                proteome_root / stem / f'{stem}.proteome_features.core.csv',
                proteome_root / stem / f'{stem}.proteome_features.full.csv',
            ),
        }
        if all(feature_io.source_exists(core) and feature_io.source_exists(full) for core, full in candidates.values()):
            return candidates
    raise FileNotFoundError(f'Could not find complete core/full feature paths for {species_id}')


def _species_from_existing_dataset(species_id: str) -> Species | None:
    dataset_ids = [f'{species_id}__{omics}' for omics in OMICS]
    dataset = (
        OmicsDataset.objects
        .filter(dataset_id__in=dataset_ids)
        .select_related('species')
        .first()
    )
    return dataset.species if dataset else None


def _upsert_dataset(species: Species, omics: str, core_path: Path, full_path: Path, display_name: str, group_label: str) -> None:
    dataset_id = f'{species.species_id}__{omics}'
    dataset = OmicsDataset.objects.filter(dataset_id=dataset_id).first()
    if dataset is None:
        dataset = OmicsDataset.objects.filter(species=species, omics_type=omics).first()
    if dataset is None:
        dataset = OmicsDataset(dataset_id=dataset_id, species=species, omics_type=omics)

    dataset.dataset_id = dataset_id
    dataset.species = species
    dataset.omics_type = omics
    dataset.schema_version = 'real_feature_model_scope_v1'
    dataset.core_csv_path = str(core_path)
    dataset.full_csv_path = str(full_path)
    dataset.status = 'ready'
    dataset.browse_meta = {
        'available_scopes': ['core', 'full'],
        'source_scope': 'full',
        'phylogeny_in_scope': False,
    }
    dataset.searchable_text = f'{display_name} {omics} {group_label}'
    dataset.save()


class Command(BaseCommand):
    help = 'Register model-organism whitelist species whose real three-omics files exist but are absent from the Species registry.'

    def add_arguments(self, parser):
        parser.add_argument('--model-list', default='')
        parser.add_argument('--release-id', default=RELEASE_ID)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        model_list = Path(options['model_list']).resolve() if options.get('model_list') else _model_list()
        with model_list.open('r', encoding='utf-8-sig', newline='') as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
        selected = {
            str(row.get('species_id') or '').strip(): row
            for row in rows
            if str(row.get('species_id') or '').strip()
            and str(row.get('hard_fail') or '').strip().lower() not in {'true', '1', 'yes', 'y'}
            and not str(row.get('exclude_reason') or '').strip()
        }
        missing = sorted(set(selected) - set(Species.objects.filter(species_id__in=list(selected)).values_list('species_id', flat=True)))
        dirs = _feature_dirs()
        created: list[str] = []
        skipped: list[dict[str, str]] = []
        for species_id in missing:
            row = selected[species_id]
            try:
                paths = _source_paths(dirs, species_id)
            except FileNotFoundError as exc:
                skipped.append({'species_id': species_id, 'reason': str(exc)})
                continue
            group = str(row.get('expected_model_group') or row.get('source_division') or '').strip().lower()
            group_label = GROUP_LABELS.get(group, group.title())
            display_name = str(row.get('display_name') or species_id).strip()
            short_name = str(row.get('short_name') or row.get('model_group_latin') or display_name).strip()
            if options.get('dry_run'):
                created.append(species_id)
                continue
            with transaction.atomic():
                species = Species.objects.filter(species_id=species_id).first()
                if species is None:
                    species = _species_from_existing_dataset(species_id) or Species(species_id=species_id)
                species.species_id = species_id
                species.display_name = display_name
                species.short_name = short_name[:128]
                species.source_species_id = species_id
                species.taxonomy_id = str(row.get('taxon_id') or '')
                species.domain = group_label
                species.kingdom = group_label
                species.source_database = f'model_organism_release:{options["release_id"]}'
                species.assembly_version = str(row.get('assembly_accession') or '')
                species.has_genome = True
                species.has_transcriptome = True
                species.has_proteome = True
                species.is_featured = True
                species.searchable_text = ' '.join([species_id, display_name, short_name, group_label])
                species.save()
                for omics, (core_path, full_path) in paths.items():
                    _upsert_dataset(species, omics, core_path, full_path, display_name, group_label)
            created.append(species_id)
        payload = {
            'release_id': options['release_id'],
            'model_list': str(model_list),
            'missing_before_registration': missing,
            'registered': created,
            'skipped': skipped,
            'phylogeny': 'excluded',
        }
        report = _workspace_root() / 'data' / 'model_organism_release_hardening' / str(options['release_id']) / 'missing_species_registration_report.json'
        report.parent.mkdir(parents=True, exist_ok=True)
        if not options.get('dry_run'):
            report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(json.dumps(payload, ensure_ascii=False, indent=2)))
