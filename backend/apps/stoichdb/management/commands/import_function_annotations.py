from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

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


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise CommandError(f'Missing required file: {path}')
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        return [{key: (value or '') for key, value in row.items()} for row in csv.DictReader(handle)]


def to_int(value: Any) -> int:
    try:
        return int(float(str(value or '0').strip() or 0))
    except (TypeError, ValueError):
        return 0


def to_bool(value: Any) -> bool:
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y'}


def bulk_create(model, objects, batch_size: int) -> int:
    count = len(objects)
    if objects:
        model.objects.bulk_create(objects, batch_size=batch_size)
    return count


class Command(BaseCommand):
    help = 'Import official GO and KEGG functional annotation tables for supported protist species.'

    def add_arguments(self, parser):
        parser.add_argument('--source', default='', help='Directory containing function annotation CSV/JSON files.')
        parser.add_argument('--annotation-release', default='functional_annotations_v1', help='Functional annotation release ID.')
        parser.add_argument('--label', default='Functional annotations v1', help='Human-readable release label.')
        parser.add_argument('--batch-size', type=int, default=5000)
        parser.add_argument('--flush', action='store_true', help='Delete existing functional annotation records before import.')
        parser.add_argument('--dry-run', action='store_true', help='Validate files and print counts without writing records.')
        parser.add_argument('--limit', type=int, default=0, help='Optional row limit per large annotation table for smoke tests.')

    def handle(self, *args, **options):
        source = Path(options['source']) if options['source'] else function_annotations.annotation_data_dir()
        batch_size = max(100, int(options['batch_size'] or 5000))
        limit = max(0, int(options['limit'] or 0))

        files = {
            kind: source / name
            for kind, name in function_annotations.FILE_NAMES.items()
            if kind in {'status', 'go', 'go_terms', 'kegg_genes', 'kegg_links', 'manifest', 'kegg_manifest'}
        }
        status_rows = read_csv(files['status'])
        go_term_rows = read_csv(files['go_terms'])
        go_rows = read_csv(files['go'])
        kegg_gene_rows = read_csv(files['kegg_genes'])
        kegg_link_rows = read_csv(files['kegg_links'])
        if limit:
            go_rows = go_rows[:limit]
            kegg_gene_rows = kegg_gene_rows[:limit]
            kegg_link_rows = kegg_link_rows[:limit]

        counts = {
            'status_rows': len(status_rows),
            'go_terms': len(go_term_rows),
            'go_annotations': len(go_rows),
            'kegg_gene_annotations': len(kegg_gene_rows),
            'kegg_annotation_links': len(kegg_link_rows),
        }
        if options['dry_run']:
            self.stdout.write(json.dumps({'source': str(source), 'counts': counts}, ensure_ascii=False, indent=2))
            return

        species_map = {row.species_id: row for row in Species.objects.only('id', 'species_id')}
        log = None
        try:
            with transaction.atomic():
                if options['flush']:
                    FunctionalAnnotationIngestionLog.objects.all().delete()
                    GOAnnotation.objects.all().delete()
                    KEGGAnnotationLink.objects.all().delete()
                    KEGGGeneAnnotation.objects.all().delete()
                    SpeciesFunctionalAnnotationStatus.objects.all().delete()
                    GOTerm.objects.all().delete()
                    FunctionalAnnotationRelease.objects.all().delete()

                FunctionalAnnotationRelease.objects.filter(is_active=True).update(is_active=False)
                release, _created = FunctionalAnnotationRelease.objects.update_or_create(
                    release_id=options['annotation_release'],
                    defaults={
                        'label': options['label'],
                        'source_dir': str(source),
                        'species_total': len(status_rows),
                        'go_species_count': sum(1 for row in status_rows if to_int(row.get('go_rows')) > 0),
                        'kegg_species_count': sum(1 for row in status_rows if to_int(row.get('kegg_joined_rows')) > 0 or to_int(row.get('kegg_gene_rows')) > 0),
                        'go_annotation_count': len(go_rows),
                        'kegg_gene_count': len(kegg_gene_rows),
                        'kegg_link_count': len(kegg_link_rows),
                        'manifest_json': self._manifest_payload(files),
                        'is_active': True,
                    },
                )
                log = FunctionalAnnotationIngestionLog.objects.create(
                    release=release,
                    source_dir=str(source),
                    status='started',
                    rows_json=counts,
                )

                status_objects = []
                for row in status_rows:
                    sid = row.get('species_id') or ''
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
                bulk_create(SpeciesFunctionalAnnotationStatus, status_objects, batch_size)

                term_objects = [
                    GOTerm(
                        go_id=row.get('go_id', ''),
                        go_name=row.get('go_name', ''),
                        namespace=row.get('namespace', ''),
                        definition=row.get('definition', ''),
                        is_obsolete=to_bool(row.get('is_obsolete')),
                    )
                    for row in go_term_rows
                    if row.get('go_id')
                ]
                bulk_create(GOTerm, term_objects, batch_size)
                term_map = {row.go_id: row for row in GOTerm.objects.only('id', 'go_id')}

                go_objects = []
                for row in go_rows:
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
                bulk_create(GOAnnotation, go_objects, batch_size)

                kegg_gene_objects = []
                for row in kegg_gene_rows:
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
                bulk_create(KEGGGeneAnnotation, kegg_gene_objects, batch_size)

                kegg_link_objects = []
                for row in kegg_link_rows:
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
                bulk_create(KEGGAnnotationLink, kegg_link_objects, batch_size)

                log.status = 'succeeded'
                log.finished_at = timezone.now()
                log.rows_json = counts
                log.message = 'Functional annotation import completed.'
                log.save(update_fields=['status', 'finished_at', 'rows_json', 'message'])
        except Exception as exc:
            if log:
                FunctionalAnnotationIngestionLog.objects.filter(id=log.id).update(
                    status='failed',
                    finished_at=timezone.now(),
                    message=str(exc),
                )
            raise

        self.stdout.write(self.style.SUCCESS(json.dumps({'source': str(source), 'release': options['annotation_release'], 'counts': counts}, ensure_ascii=False, indent=2)))

    def _manifest_payload(self, files: dict[str, Path]) -> dict[str, Any]:
        payload = {}
        for kind, path in files.items():
            if not path.exists():
                continue
            if path.suffix.lower() == '.json':
                try:
                    payload[kind] = json.loads(path.read_text(encoding='utf-8'))
                    continue
                except Exception:
                    pass
            payload[kind] = {'path': str(path), 'size_bytes': path.stat().st_size}
        return payload
