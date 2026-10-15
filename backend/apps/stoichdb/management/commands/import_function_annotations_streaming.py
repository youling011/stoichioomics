from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from backend.apps.stoichdb import function_annotations
from backend.apps.stoichdb.models import (
    FunctionalAnnotationIngestionLog,
    FunctionalAnnotationRelease,
    GOAnnotation,
    GOTerm,
    KEGGAnnotationLink,
    KEGGGeneAnnotation,
    Species,
    SpeciesFunctionalAnnotationStatus,
)


DEFAULT_SUBDIRS = ['后生生物', '植物', '真菌', '细菌', '脊椎动物', '脊索动物']


def to_int(value: Any) -> int:
    try:
        return int(float(str(value or '0').strip() or 0))
    except (TypeError, ValueError):
        return 0


def to_bool(value: Any) -> bool:
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y'}


def csv_rows(path: Path) -> Iterable[dict[str, str]]:
    if not path.exists():
        return
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            yield {key: (value or '') for key, value in row.items()}


def count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        return max(0, sum(1 for _line in handle) - 1)


def bulk_flush(model, objects: list[Any], batch_size: int) -> int:
    if not objects:
        return 0
    model.objects.bulk_create(objects, batch_size=batch_size)
    count = len(objects)
    objects.clear()
    return count


class Command(BaseCommand):
    help = 'Stream-import multi-directory GO/KEGG functional annotations without loading all CSV rows into memory.'

    def add_arguments(self, parser):
        parser.add_argument('--source-root', required=True, help='Root directory containing the six annotation subdirectories.')
        parser.add_argument('--include-root', action='store_true', help='Also include CSV files directly under --source-root.')
        parser.add_argument('--subdirs', default=','.join(DEFAULT_SUBDIRS), help='Comma-separated annotation subdirectories to import.')
        parser.add_argument('--annotation-release', default='functional_annotations_six_group_streaming_v1')
        parser.add_argument('--label', default='Functional annotations six-group streaming import')
        parser.add_argument('--batch-size', type=int, default=5000)
        parser.add_argument('--flush', action='store_true', help='Delete existing functional annotation rows before importing this release.')
        parser.add_argument('--dry-run', action='store_true', help='Count input rows and exit without writing records.')

    def handle(self, *args, **options):
        source_root = Path(options['source_root'])
        if not source_root.exists():
            raise CommandError(f'Missing source root: {source_root}')
        batch_size = max(500, int(options['batch_size'] or 5000))
        source_dirs: list[Path] = []
        if options['include_root']:
            source_dirs.append(source_root)
        for name in [item.strip() for item in str(options['subdirs'] or '').split(',') if item.strip()]:
            path = source_root / name
            if path.exists():
                source_dirs.append(path)
        if not source_dirs:
            raise CommandError('No readable annotation source directories were found.')

        names = function_annotations.FILE_NAMES
        counts = {
            'source_dirs': [str(path) for path in source_dirs],
            'status_rows': sum(count_csv_rows(path / names['status']) for path in source_dirs),
            'go_terms': sum(count_csv_rows(path / names['go_terms']) for path in source_dirs),
            'go_annotations': sum(count_csv_rows(path / names['go']) for path in source_dirs),
            'kegg_gene_annotations': sum(count_csv_rows(path / names['kegg_genes']) for path in source_dirs),
            'kegg_annotation_links': sum(count_csv_rows(path / names['kegg_links']) for path in source_dirs),
        }
        if options['dry_run']:
            self.stdout.write(json.dumps({'source_root': str(source_root), 'counts': counts}, ensure_ascii=False, indent=2))
            return

        species_map = {row.species_id: row for row in Species.objects.only('id', 'species_id')}
        with transaction.atomic():
            FunctionalAnnotationRelease.objects.filter(is_active=True).update(is_active=False)
            release, _created = FunctionalAnnotationRelease.objects.update_or_create(
                release_id=options['annotation_release'],
                defaults={
                    'label': options['label'],
                    'source_dir': str(source_root),
                    'species_total': 0,
                    'go_species_count': 0,
                    'kegg_species_count': 0,
                    'go_annotation_count': counts['go_annotations'],
                    'kegg_gene_count': counts['kegg_gene_annotations'],
                    'kegg_link_count': counts['kegg_annotation_links'],
                    'manifest_json': counts,
                    'is_active': True,
                },
            )
            log = FunctionalAnnotationIngestionLog.objects.create(
                release=release,
                source_dir=str(source_root),
                status='started',
                rows_json=counts,
            )

        if options['flush']:
            self.stdout.write('Flushing existing functional annotation records...')
            FunctionalAnnotationIngestionLog.objects.exclude(id=log.id).delete()
            GOAnnotation.objects.all().delete()
            KEGGAnnotationLink.objects.all().delete()
            KEGGGeneAnnotation.objects.all().delete()
            SpeciesFunctionalAnnotationStatus.objects.all().delete()
            GOTerm.objects.all().delete()
            FunctionalAnnotationRelease.objects.exclude(id=release.id).delete()

        imported = {
            'status_rows': 0,
            'go_terms': 0,
            'go_annotations': 0,
            'kegg_gene_annotations': 0,
            'kegg_annotation_links': 0,
        }

        status_seen: set[str] = set()
        status_objects: list[SpeciesFunctionalAnnotationStatus] = []
        go_species: set[str] = set()
        kegg_species: set[str] = set()
        for directory in source_dirs:
            for row in csv_rows(directory / names['status']):
                sid = row.get('species_id') or ''
                if not sid or sid in status_seen:
                    continue
                status_seen.add(sid)
                if to_int(row.get('go_rows')) > 0:
                    go_species.add(sid)
                if to_int(row.get('kegg_joined_rows')) > 0 or to_int(row.get('kegg_gene_rows')) > 0:
                    kegg_species.add(sid)
                status_objects.append(SpeciesFunctionalAnnotationStatus(
                    release=release,
                    species=species_map.get(sid),
                    species_id_text=sid,
                    tax_id=row.get('tax_id', ''),
                    tax_name=row.get('tax_name', ''),
                    assembly_accession=row.get('assembly_accession', ''),
                    ensembl_release=row.get('ensembl_release', ''),
                    mapped_uniprot_rows=to_int(row.get('mapped_uniprot_rows')),
                    unique_uniprot_accessions=to_int(row.get('unique_uniprot_accessions')),
                    go_rows=to_int(row.get('go_rows')),
                    uniprot_kegg_xref_rows=to_int(row.get('uniprot_kegg_xref_rows')),
                    kegg_code=row.get('kegg_code', ''),
                    kegg_t_number=row.get('kegg_t_number', ''),
                    kegg_name=row.get('kegg_name', ''),
                    kegg_match_status=row.get('kegg_match_status', '') or 'not_matched',
                    kegg_gene_rows=to_int(row.get('kegg_gene_rows')),
                    kegg_ko_rows=to_int(row.get('kegg_ko_rows')),
                    kegg_pathway_rows=to_int(row.get('kegg_pathway_rows')),
                    kegg_module_rows=to_int(row.get('kegg_module_rows')),
                    kegg_joined_rows=to_int(row.get('kegg_joined_rows')),
                    status_note=row.get('status_note', ''),
                ))
                if len(status_objects) >= batch_size:
                    imported['status_rows'] += bulk_flush(SpeciesFunctionalAnnotationStatus, status_objects, batch_size)
        imported['status_rows'] += bulk_flush(SpeciesFunctionalAnnotationStatus, status_objects, batch_size)

        term_objects: list[GOTerm] = []
        term_seen: set[str] = set(GOTerm.objects.values_list('go_id', flat=True))
        for directory in source_dirs:
            for row in csv_rows(directory / names['go_terms']):
                go_id = row.get('go_id', '')
                if not go_id or go_id in term_seen:
                    continue
                term_seen.add(go_id)
                term_objects.append(GOTerm(
                    go_id=go_id,
                    go_name=row.get('go_name', ''),
                    namespace=row.get('namespace', ''),
                    definition=row.get('definition', ''),
                    is_obsolete=to_bool(row.get('is_obsolete')),
                ))
                if len(term_objects) >= batch_size:
                    imported['go_terms'] += bulk_flush(GOTerm, term_objects, batch_size)
        imported['go_terms'] += bulk_flush(GOTerm, term_objects, batch_size)
        term_map = {row.go_id: row for row in GOTerm.objects.only('id', 'go_id')}

        go_objects: list[GOAnnotation] = []
        for directory in source_dirs:
            self.stdout.write(f'Importing GO annotations from {directory}...')
            for row in csv_rows(directory / names['go']):
                sid = row.get('species_id') or ''
                go_objects.append(GOAnnotation(
                    release=release,
                    species=species_map.get(sid),
                    species_id_text=sid,
                    tax_id=row.get('tax_id', ''),
                    tax_name=row.get('tax_name', ''),
                    gene_id=row.get('gene_id', ''),
                    transcript_id=row.get('transcript_id', ''),
                    protein_id=row.get('protein_id', ''),
                    source_protein_id=row.get('source_protein_id', ''),
                    mapping_confidence=row.get('mapping_confidence', ''),
                    mapping_evidence=row.get('mapping_evidence', ''),
                    uniprot_accession=row.get('uniprot_accession', ''),
                    go_term=term_map.get(row.get('go_id', '')),
                    go_id=row.get('go_id', ''),
                    go_name=row.get('go_name', ''),
                    go_namespace=row.get('go_namespace', ''),
                    go_is_obsolete=to_bool(row.get('go_is_obsolete')),
                    source=row.get('source', ''),
                    annotation_status=row.get('annotation_status', ''),
                ))
                if len(go_objects) >= batch_size:
                    imported['go_annotations'] += bulk_flush(GOAnnotation, go_objects, batch_size)
        imported['go_annotations'] += bulk_flush(GOAnnotation, go_objects, batch_size)

        kegg_gene_objects: list[KEGGGeneAnnotation] = []
        for directory in source_dirs:
            self.stdout.write(f'Importing KEGG gene annotations from {directory}...')
            for row in csv_rows(directory / names['kegg_genes']):
                sid = row.get('species_id') or ''
                kegg_gene_objects.append(KEGGGeneAnnotation(
                    release=release,
                    species=species_map.get(sid),
                    species_id_text=sid,
                    tax_id=row.get('tax_id', ''),
                    tax_name=row.get('tax_name', ''),
                    gene_id=row.get('gene_id', ''),
                    transcript_id=row.get('transcript_id', ''),
                    protein_id=row.get('protein_id', ''),
                    source_protein_id=row.get('source_protein_id', ''),
                    mapping_confidence=row.get('mapping_confidence', ''),
                    mapping_evidence=row.get('mapping_evidence', ''),
                    uniprot_accession=row.get('uniprot_accession', ''),
                    kegg_gene_id=row.get('kegg_gene_id', ''),
                    kegg_org_code=row.get('kegg_org_code', ''),
                    kegg_gene_description=row.get('kegg_gene_description', ''),
                    ko_ids=row.get('ko_ids', ''),
                    ko_names=row.get('ko_names', ''),
                    pathway_ids=row.get('pathway_ids', ''),
                    pathway_names=row.get('pathway_names', ''),
                    module_ids=row.get('module_ids', ''),
                    module_names=row.get('module_names', ''),
                    source=row.get('source', ''),
                    annotation_status=row.get('annotation_status', ''),
                ))
                if len(kegg_gene_objects) >= batch_size:
                    imported['kegg_gene_annotations'] += bulk_flush(KEGGGeneAnnotation, kegg_gene_objects, batch_size)
        imported['kegg_gene_annotations'] += bulk_flush(KEGGGeneAnnotation, kegg_gene_objects, batch_size)

        kegg_link_objects: list[KEGGAnnotationLink] = []
        for directory in source_dirs:
            self.stdout.write(f'Importing KEGG links from {directory}...')
            for row in csv_rows(directory / names['kegg_links']):
                sid = row.get('species_id') or ''
                kegg_link_objects.append(KEGGAnnotationLink(
                    release=release,
                    species=species_map.get(sid),
                    species_id_text=sid,
                    tax_id=row.get('tax_id', ''),
                    tax_name=row.get('tax_name', ''),
                    gene_id=row.get('gene_id', ''),
                    transcript_id=row.get('transcript_id', ''),
                    protein_id=row.get('protein_id', ''),
                    uniprot_accession=row.get('uniprot_accession', ''),
                    kegg_gene_id=row.get('kegg_gene_id', ''),
                    kegg_org_code=row.get('kegg_org_code', ''),
                    kegg_gene_description=row.get('kegg_gene_description', ''),
                    annotation_type=row.get('annotation_type', ''),
                    annotation_id=row.get('annotation_id', ''),
                    annotation_name=row.get('annotation_name', ''),
                    source=row.get('source', ''),
                    annotation_status=row.get('annotation_status', ''),
                ))
                if len(kegg_link_objects) >= batch_size:
                    imported['kegg_annotation_links'] += bulk_flush(KEGGAnnotationLink, kegg_link_objects, batch_size)
        imported['kegg_annotation_links'] += bulk_flush(KEGGAnnotationLink, kegg_link_objects, batch_size)

        release.species_total = len(status_seen)
        release.go_species_count = len(go_species)
        release.kegg_species_count = len(kegg_species)
        release.go_annotation_count = imported['go_annotations']
        release.kegg_gene_count = imported['kegg_gene_annotations']
        release.kegg_link_count = imported['kegg_annotation_links']
        release.manifest_json = {'input_counts': counts, 'imported_counts': imported, 'source_dirs': counts['source_dirs']}
        release.is_active = True
        release.save()
        log.status = 'succeeded'
        log.finished_at = timezone.now()
        log.rows_json = {'input_counts': counts, 'imported_counts': imported}
        log.message = 'Streaming functional annotation import completed.'
        log.save(update_fields=['status', 'finished_at', 'rows_json', 'message'])
        self.stdout.write(json.dumps({'release': release.release_id, 'imported': imported}, ensure_ascii=False, indent=2))
