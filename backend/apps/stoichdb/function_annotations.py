from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
import os
from functools import lru_cache
from backend.apps.common.host_paths import Path
from typing import Any

from django.conf import settings
from django.db import connection
from django.db.models import Count, Q
from django.db.utils import DatabaseError, OperationalError, ProgrammingError

from .models import (
    FunctionalAnnotationRelease,
    GOAnnotation,
    GOTerm,
    KEGGAnnotationLink,
    KEGGGeneAnnotation,
    Species,
    SpeciesFunctionalAnnotationStatus,
)


ANNOTATION_SCHEMA_VERSION = 'function_annotation_v1'

FILE_NAMES = {
    'status': 'species_function_annotation_status.csv',
    'go': 'go_annotations_all_species.with_terms.csv',
    'go_raw': 'go_annotations_all_species.csv',
    'go_terms': 'go_terms.csv',
    'kegg_genes': 'kegg_gene_annotations_from_xrefs.csv',
    'kegg_links': 'kegg_annotation_links_long.csv',
    'kegg_compact': 'kegg_annotations_all_species.csv',
    'manifest': 'function_annotation_download_manifest.json',
    'kegg_manifest': 'kegg_rest_from_existing_xrefs_manifest.json',
}

STATUS_INT_FIELDS = {
    'mapped_uniprot_rows',
    'unique_uniprot_accessions',
    'go_rows',
    'uniprot_kegg_xref_rows',
    'kegg_gene_rows',
    'kegg_ko_rows',
    'kegg_pathway_rows',
    'kegg_module_rows',
    'kegg_joined_rows',
}


class AnnotationNotFound(Exception):
    pass


def _base_dir() -> Path:
    return Path(settings.BASE_DIR)


def annotation_data_dir() -> Path:
    configured = os.environ.get('FUNCTION_ANNOTATION_SOURCE') or getattr(settings, 'FUNCTION_ANNOTATION_SOURCE', '')
    candidates = []
    if configured:
        candidates.append(Path(configured))
    base = _base_dir()
    workspace_root = base.parent.parent if base.parent.name else base.parent
    candidates.extend([
        base / 'data' / 'function_annotations',
        base / 'data' / 'external_annotations',
        workspace_root / 'gpt优化方案' / '项目平台完整归纳整理' / '功能注释下载',
        Path(getattr(settings, 'STOICHIOOMICS_ROOT', '') or 'G:/stoichioomics') / '项目平台数据' / '功能注释下载',
    ])
    for candidate in candidates:
        if candidate and (candidate / FILE_NAMES['status']).exists():
            return candidate
    return candidates[0] if candidates else base / 'data' / 'function_annotations'


def _annotation_path(kind: str) -> Path:
    return annotation_data_dir() / FILE_NAMES[kind]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        return [{key: (value or '') for key, value in row.items()} for row in csv.DictReader(handle)]


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or '0').strip() or 0))
    except (TypeError, ValueError):
        return 0


def _to_bool(value: Any) -> bool:
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'y'}


def _norm(value: Any) -> str:
    text = str(value or '').strip().lower()
    if not text:
        return ''
    if '.' in text and not text.startswith('go:') and not text.startswith('ko:') and not text.startswith('path:'):
        text = text.split('.', 1)[0]
    return text


def _split_terms(ids: str, names: str = '') -> list[dict[str, str]]:
    id_parts = [part.strip() for part in str(ids or '').split(';') if part.strip()]
    name_parts = [part.strip() for part in str(names or '').split(';')]
    return [
        {'id': term_id, 'name': name_parts[idx] if idx < len(name_parts) else ''}
        for idx, term_id in enumerate(id_parts)
    ]


@lru_cache(maxsize=1)
def status_rows_file() -> list[dict[str, Any]]:
    rows = []
    for row in _read_csv(_annotation_path('status')):
        normalized = dict(row)
        for field in STATUS_INT_FIELDS:
            normalized[field] = _to_int(normalized.get(field))
        rows.append(normalized)
    return rows


@lru_cache(maxsize=1)
def go_rows_file() -> list[dict[str, str]]:
    return _read_csv(_annotation_path('go'))


@lru_cache(maxsize=1)
def go_terms_file() -> list[dict[str, str]]:
    return _read_csv(_annotation_path('go_terms'))


@lru_cache(maxsize=1)
def kegg_gene_rows_file() -> list[dict[str, str]]:
    return _read_csv(_annotation_path('kegg_genes'))


@lru_cache(maxsize=1)
def kegg_link_rows_file() -> list[dict[str, str]]:
    return _read_csv(_annotation_path('kegg_links'))


@lru_cache(maxsize=1)
def _table_names() -> set[str]:
    try:
        return set(connection.introspection.table_names())
    except Exception:
        return set()


@lru_cache(maxsize=16)
def _table_has_rows(table_name: str) -> bool:
    if table_name not in _table_names():
        return False
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT 1 FROM "{table_name}" LIMIT 1')
            return cursor.fetchone() is not None
    except (DatabaseError, OperationalError, ProgrammingError):
        return False


def _use_db(model: type) -> bool:
    return _table_has_rows(model._meta.db_table)


def _row_from_status_model(obj: SpeciesFunctionalAnnotationStatus) -> dict[str, Any]:
    return {
        'species_id': obj.species_id_text,
        'tax_id': obj.tax_id,
        'tax_name': obj.tax_name,
        'assembly_accession': obj.assembly_accession,
        'ensembl_release': obj.ensembl_release,
        'mapped_uniprot_rows': obj.mapped_uniprot_rows,
        'unique_uniprot_accessions': obj.unique_uniprot_accessions,
        'go_rows': obj.go_rows,
        'uniprot_kegg_xref_rows': obj.uniprot_kegg_xref_rows,
        'kegg_code': obj.kegg_code,
        'kegg_t_number': obj.kegg_t_number,
        'kegg_name': obj.kegg_name,
        'kegg_match_status': obj.kegg_match_status,
        'kegg_gene_rows': obj.kegg_gene_rows,
        'kegg_ko_rows': obj.kegg_ko_rows,
        'kegg_pathway_rows': obj.kegg_pathway_rows,
        'kegg_module_rows': obj.kegg_module_rows,
        'kegg_joined_rows': obj.kegg_joined_rows,
        'status_note': obj.status_note,
    }


def _status_rows() -> list[dict[str, Any]]:
    if _use_db(SpeciesFunctionalAnnotationStatus):
        return [_row_from_status_model(row) for row in SpeciesFunctionalAnnotationStatus.objects.order_by('species_id_text')]
    return status_rows_file()


def _filter_page(rows: list[dict[str, Any]], *, page: Any = 1, page_size: Any = 50) -> dict[str, Any]:
    page_int = max(1, min(_to_int(page) or 1, 100000))
    page_size_int = max(1, min(_to_int(page_size) or 50, 500))
    start = (page_int - 1) * page_size_int
    end = start + page_size_int
    total = len(rows)
    return {
        'page': page_int,
        'page_size': page_size_int,
        'total': total,
        'total_pages': math.ceil(total / page_size_int) if total else 0,
        'rows': rows[start:end],
    }


def _status_label(row: dict[str, Any]) -> str:
    has_go = _to_int(row.get('go_rows')) > 0
    has_kegg = _to_int(row.get('kegg_joined_rows')) > 0 or _to_int(row.get('kegg_gene_rows')) > 0
    if has_go and has_kegg:
        return 'go_and_kegg_available'
    if has_go:
        return 'go_available'
    if has_kegg:
        return 'kegg_available'
    return 'no_standard_annotation'


def release_payload() -> dict[str, Any]:
    rows = _status_rows()
    release = None
    if _use_db(FunctionalAnnotationRelease):
        release = FunctionalAnnotationRelease.objects.filter(is_active=True).order_by('-created_at').first()
    if release:
        return {
            'release_id': release.release_id,
            'label': release.label,
            'source_dir': release.source_dir,
            'schema_version': ANNOTATION_SCHEMA_VERSION,
            'species_total': release.species_total,
            'go_species_count': release.go_species_count,
            'kegg_species_count': release.kegg_species_count,
            'go_annotation_count': release.go_annotation_count,
            'kegg_gene_count': release.kegg_gene_count,
            'kegg_link_count': release.kegg_link_count,
            'go_source': release.go_source,
            'kegg_source': release.kegg_source,
        }
    return {
        'release_id': 'functional_annotations_file_bundle',
        'label': 'Functional annotation file bundle',
        'source_dir': str(annotation_data_dir()),
        'schema_version': ANNOTATION_SCHEMA_VERSION,
        'species_total': len(rows),
        'go_species_count': sum(1 for row in rows if _to_int(row.get('go_rows')) > 0),
        'kegg_species_count': sum(1 for row in rows if _to_int(row.get('kegg_joined_rows')) > 0 or _to_int(row.get('kegg_gene_rows')) > 0),
        'go_annotation_count': sum(_to_int(row.get('go_rows')) for row in rows),
        'kegg_gene_count': sum(_to_int(row.get('kegg_gene_rows')) for row in rows),
        'kegg_link_count': sum(_to_int(row.get('kegg_joined_rows')) for row in rows),
        'go_source': 'UniProtKB GO annotations with GO term metadata',
        'kegg_source': 'KEGG REST annotations resolved from existing UniProtKB KEGG cross references',
    }


def annotation_status_payload(query: str = '', species_id: str = '', page: Any = 1, page_size: Any = 50) -> dict[str, Any]:
    if _use_db(SpeciesFunctionalAnnotationStatus):
        q = str(query or '').strip()
        qs = SpeciesFunctionalAnnotationStatus.objects.order_by('species_id_text')
        if species_id:
            qs = qs.filter(species_id_text=species_id)
        if q:
            qs = qs.filter(
                Q(species_id_text__icontains=q)
                | Q(tax_name__icontains=q)
                | Q(tax_id__icontains=q)
                | Q(kegg_code__icontains=q)
                | Q(kegg_name__icontains=q)
            )
        page_int = max(1, min(_to_int(page) or 1, 100000))
        page_size_int = max(1, min(_to_int(page_size) or 50, 500))
        total = qs.count()
        start = (page_int - 1) * page_size_int
        page_rows = [
            _row_from_status_model(row)
            for row in qs[start:start + page_size_int]
        ]
        rows = [
            {
                **row,
                'status': _status_label(row),
                'has_go': _to_int(row.get('go_rows')) > 0,
                'has_kegg': _to_int(row.get('kegg_joined_rows')) > 0 or _to_int(row.get('kegg_gene_rows')) > 0,
            }
            for row in page_rows
        ]
        count_rows = qs.values('go_rows', 'kegg_gene_rows', 'kegg_joined_rows')
        counts = Counter(
            _status_label({
                'go_rows': row.get('go_rows'),
                'kegg_gene_rows': row.get('kegg_gene_rows'),
                'kegg_joined_rows': row.get('kegg_joined_rows'),
            })
            for row in count_rows
        )
        release = release_payload()
        return {
            'release': release,
            'summary': {
                'species_total': SpeciesFunctionalAnnotationStatus.objects.count(),
                'go_species_count': release.get('go_species_count') or SpeciesFunctionalAnnotationStatus.objects.filter(go_rows__gt=0).count(),
                'kegg_species_count': release.get('kegg_species_count') or SpeciesFunctionalAnnotationStatus.objects.filter(Q(kegg_joined_rows__gt=0) | Q(kegg_gene_rows__gt=0)).count(),
                'status_counts': dict(counts),
                'unsupported_policy': 'Species without official GO/KEGG records are retained in status output and are not predicted.',
            },
            'filters': {'query': query, 'species_id': species_id},
            'page': page_int,
            'page_size': page_size_int,
            'total': total,
            'total_pages': math.ceil(total / page_size_int) if total else 0,
            'rows': rows,
        }
    rows = _status_rows()
    q = str(query or '').strip().lower()
    if species_id:
        rows = [row for row in rows if row.get('species_id') == species_id]
    if q:
        rows = [
            row for row in rows
            if q in ' '.join(str(row.get(key, '')) for key in ('species_id', 'tax_name', 'tax_id', 'kegg_code', 'kegg_name')).lower()
        ]
    rows = [{**row, 'status': _status_label(row), 'has_go': _to_int(row.get('go_rows')) > 0, 'has_kegg': _to_int(row.get('kegg_joined_rows')) > 0 or _to_int(row.get('kegg_gene_rows')) > 0} for row in rows]
    counts = Counter(row['status'] for row in rows)
    return {
        'release': release_payload(),
        'summary': {
            'species_total': len(_status_rows()),
            'go_species_count': sum(1 for row in _status_rows() if _to_int(row.get('go_rows')) > 0),
            'kegg_species_count': sum(1 for row in _status_rows() if _to_int(row.get('kegg_joined_rows')) > 0 or _to_int(row.get('kegg_gene_rows')) > 0),
            'status_counts': dict(counts),
            'unsupported_policy': 'Species without official GO/KEGG records are retained in status output and are not predicted.',
        },
        'filters': {'query': query, 'species_id': species_id},
        **_filter_page(rows, page=page, page_size=page_size),
    }


def _status_for_species(species_id: str) -> dict[str, Any]:
    for row in _status_rows():
        if row.get('species_id') == species_id:
            return {**row, 'status': _status_label(row)}
    return {
        'species_id': species_id,
        'status': 'no_standard_annotation',
        'go_rows': 0,
        'kegg_gene_rows': 0,
        'kegg_joined_rows': 0,
        'status_note': 'Species is not present in the functional annotation status table.',
    }


def _go_rows_for_species(species_id: str) -> list[dict[str, Any]]:
    if _use_db(GOAnnotation):
        fields = [
            'species_id_text', 'tax_id', 'tax_name', 'gene_id', 'transcript_id', 'protein_id', 'source_protein_id',
            'mapping_confidence', 'mapping_evidence', 'uniprot_accession', 'go_id', 'source', 'annotation_status',
            'go_name', 'go_namespace', 'go_is_obsolete',
        ]
        return [
            {
                'species_id': row['species_id_text'],
                **{key: row[key] for key in fields if key != 'species_id_text'},
            }
            for row in GOAnnotation.objects.filter(species_id_text=species_id).values(*fields)
        ]
    return [row for row in go_rows_file() if row.get('species_id') == species_id]


def _kegg_gene_rows_for_species(species_id: str) -> list[dict[str, Any]]:
    if _use_db(KEGGGeneAnnotation):
        fields = [
            'species_id_text', 'tax_id', 'tax_name', 'gene_id', 'transcript_id', 'protein_id', 'source_protein_id',
            'mapping_confidence', 'mapping_evidence', 'uniprot_accession', 'kegg_gene_id', 'kegg_org_code',
            'kegg_gene_description', 'ko_ids', 'ko_names', 'pathway_ids', 'pathway_names', 'module_ids', 'module_names',
            'source', 'annotation_status',
        ]
        return [
            {'species_id': row['species_id_text'], **{key: row[key] for key in fields if key != 'species_id_text'}}
            for row in KEGGGeneAnnotation.objects.filter(species_id_text=species_id).values(*fields)
        ]
    return [row for row in kegg_gene_rows_file() if row.get('species_id') == species_id]


def _kegg_link_rows_for_species(species_id: str) -> list[dict[str, Any]]:
    if _use_db(KEGGAnnotationLink):
        fields = [
            'species_id_text', 'tax_id', 'tax_name', 'gene_id', 'transcript_id', 'protein_id', 'uniprot_accession',
            'kegg_gene_id', 'kegg_org_code', 'kegg_gene_description', 'annotation_type', 'annotation_id',
            'annotation_name', 'source', 'annotation_status',
        ]
        return [
            {'species_id': row['species_id_text'], **{key: row[key] for key in fields if key != 'species_id_text'}}
            for row in KEGGAnnotationLink.objects.filter(species_id_text=species_id).values(*fields)
        ]
    return [row for row in kegg_link_rows_file() if row.get('species_id') == species_id]


def _entity_identifiers(row: dict[str, Any]) -> set[str]:
    keys = {
        row.get('gene_id'),
        row.get('transcript_id'),
        row.get('protein_id'),
        row.get('source_protein_id'),
        row.get('uniprot_accession'),
        row.get('kegg_gene_id'),
    }
    return {_norm(value) for value in keys if _norm(value)}


def _matches_entity(row: dict[str, Any], entity_key: str) -> bool:
    return _norm(entity_key) in _entity_identifiers(row)


def species_functional_summary(species_id: str) -> dict[str, Any]:
    status = _status_for_species(species_id)
    go_rows = _go_rows_for_species(species_id)
    kegg_genes = _kegg_gene_rows_for_species(species_id)
    kegg_links = _kegg_link_rows_for_species(species_id)
    namespace_counts = Counter(row.get('go_namespace') or row.get('namespace') or 'unknown' for row in go_rows)
    kegg_type_counts = Counter(row.get('annotation_type') or 'gene' for row in kegg_links)
    go_entities = {_norm(row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession')) for row in go_rows}
    kegg_entities = {_norm(row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession')) for row in kegg_genes}
    return {
        'species_id': species_id,
        'status': status,
        'available': bool(go_rows or kegg_genes or kegg_links),
        'go': {
            'available': bool(go_rows),
            'row_count': len(go_rows),
            'unique_terms': len({row.get('go_id') for row in go_rows if row.get('go_id')}),
            'unique_entities': len({item for item in go_entities if item}),
            'namespace_counts': [{'namespace': key, 'count': value} for key, value in namespace_counts.most_common()],
            'top_terms': _top_go_terms(go_rows, limit=12),
        },
        'kegg': {
            'available': bool(kegg_genes or kegg_links),
            'gene_row_count': len(kegg_genes),
            'link_row_count': len(kegg_links),
            'unique_entities': len({item for item in kegg_entities if item}),
            'annotation_type_counts': [{'annotation_type': key, 'count': value} for key, value in kegg_type_counts.most_common()],
            'top_annotations': _top_kegg_links(kegg_links, limit=12),
        },
        'unsupported_policy': 'No prediction is generated for species without official standard annotations.',
    }


def _top_go_terms(rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        go_id = row.get('go_id') or ''
        if not go_id:
            continue
        item = grouped.setdefault(go_id, {
            'go_id': go_id,
            'go_name': row.get('go_name') or '',
            'go_namespace': row.get('go_namespace') or '',
            'entity_count': 0,
            'entities': set(),
        })
        key = _norm(row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession'))
        if key and key not in item['entities']:
            item['entities'].add(key)
            item['entity_count'] += 1
    values = sorted(grouped.values(), key=lambda item: item['entity_count'], reverse=True)[:limit]
    return [{key: value for key, value in item.items() if key != 'entities'} for item in values]


def _top_kegg_links(rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        annotation_id = row.get('annotation_id') or ''
        annotation_type = row.get('annotation_type') or ''
        if not annotation_id:
            continue
        key = (annotation_type, annotation_id)
        item = grouped.setdefault(key, {
            'annotation_type': annotation_type,
            'annotation_id': annotation_id,
            'annotation_name': row.get('annotation_name') or '',
            'entity_count': 0,
            'entities': set(),
        })
        entity = _norm(row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession'))
        if entity and entity not in item['entities']:
            item['entities'].add(entity)
            item['entity_count'] += 1
    values = sorted(grouped.values(), key=lambda item: item['entity_count'], reverse=True)[:limit]
    return [{key: value for key, value in item.items() if key != 'entities'} for item in values]


def go_annotations_payload(species_id: str, namespace: str = '', query: str = '', page: Any = 1, page_size: Any = 50) -> dict[str, Any]:
    rows = _go_rows_for_species(species_id)
    if namespace:
        rows = [row for row in rows if (row.get('go_namespace') or '').lower() == namespace.lower()]
    q = str(query or '').strip().lower()
    if q:
        rows = [
            row for row in rows
            if q in ' '.join(str(row.get(key, '')) for key in ('gene_id', 'transcript_id', 'protein_id', 'uniprot_accession', 'go_id', 'go_name')).lower()
        ]
    return {
        'species_id': species_id,
        'status': _status_for_species(species_id),
        'filters': {'namespace': namespace, 'query': query},
        'summary': {
            'row_count': len(rows),
            'unique_terms': len({row.get('go_id') for row in rows if row.get('go_id')}),
            'unique_entities': len({_norm(row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession')) for row in rows if _norm(row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession'))}),
        },
        **_filter_page(rows, page=page, page_size=page_size),
    }


def kegg_annotations_payload(species_id: str, annotation_type: str = '', query: str = '', page: Any = 1, page_size: Any = 50) -> dict[str, Any]:
    gene_rows = _kegg_gene_rows_for_species(species_id)
    link_rows = _kegg_link_rows_for_species(species_id)
    if annotation_type:
        link_rows = [row for row in link_rows if (row.get('annotation_type') or '').lower() == annotation_type.lower()]
    q = str(query or '').strip().lower()
    if q:
        gene_rows = [
            row for row in gene_rows
            if q in ' '.join(str(row.get(key, '')) for key in ('gene_id', 'transcript_id', 'protein_id', 'uniprot_accession', 'kegg_gene_id', 'kegg_gene_description', 'ko_ids', 'ko_names', 'pathway_ids', 'pathway_names', 'module_ids', 'module_names')).lower()
        ]
        link_rows = [
            row for row in link_rows
            if q in ' '.join(str(row.get(key, '')) for key in ('gene_id', 'transcript_id', 'protein_id', 'uniprot_accession', 'kegg_gene_id', 'annotation_id', 'annotation_name')).lower()
        ]
    rows = link_rows if annotation_type else gene_rows
    return {
        'species_id': species_id,
        'status': _status_for_species(species_id),
        'filters': {'annotation_type': annotation_type, 'query': query},
        'summary': {
            'gene_row_count': len(gene_rows),
            'link_row_count': len(link_rows),
            'unique_entities': len({_norm(row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession')) for row in gene_rows if _norm(row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession'))}),
            'annotation_type_counts': dict(Counter(row.get('annotation_type') or 'gene' for row in link_rows)),
        },
        **_filter_page(rows, page=page, page_size=page_size),
    }


def entity_function_payload(species_id: str, entity_key: str) -> dict[str, Any]:
    go_matches = [row for row in _go_rows_for_species(species_id) if _matches_entity(row, entity_key)]
    kegg_gene_matches = [row for row in _kegg_gene_rows_for_species(species_id) if _matches_entity(row, entity_key)]
    kegg_link_matches = [row for row in _kegg_link_rows_for_species(species_id) if _matches_entity(row, entity_key)]
    go_terms = _top_go_terms(go_matches, limit=100)
    kegg_terms = _top_kegg_links(kegg_link_matches, limit=100)
    identifiers = set()
    for row in go_matches + kegg_gene_matches + kegg_link_matches:
        identifiers.update(_entity_identifiers(row))
    return {
        'species_id': species_id,
        'entity_key': entity_key,
        'available': bool(go_matches or kegg_gene_matches or kegg_link_matches),
        'status': _status_for_species(species_id),
        'matched_identifiers': sorted(identifiers),
        'go': {
            'available': bool(go_matches),
            'row_count': len(go_matches),
            'terms': go_terms,
            'rows': go_matches[:200],
        },
        'kegg': {
            'available': bool(kegg_gene_matches or kegg_link_matches),
            'gene_row_count': len(kegg_gene_matches),
            'link_row_count': len(kegg_link_matches),
            'genes': kegg_gene_matches[:100],
            'annotations': kegg_terms,
            'links': kegg_link_matches[:200],
        },
        'method_metadata': {
            'method': 'Exact normalized match across gene_id, transcript_id, protein_id, source_protein_id, UniProt accession, and KEGG gene ID.',
            'source': 'Standard GO and KEGG records only; no predicted annotation is generated.',
        },
    }


def annotation_search_payload(query: str, species_id: str = '', limit: Any = 25) -> dict[str, Any]:
    q = str(query or '').strip().lower()
    limit_int = max(1, min(_to_int(limit) or 25, 100))
    if not q:
        return {'query': query, 'species_id': species_id, 'results': []}
    species_ids = [species_id] if species_id else [row.get('species_id') for row in _status_rows()]
    results: list[dict[str, Any]] = []
    for sid in species_ids:
        if not sid or len(results) >= limit_int:
            continue
        for row in _go_rows_for_species(sid):
            if q not in ' '.join(str(row.get(key, '')) for key in ('go_id', 'go_name', 'gene_id', 'protein_id', 'uniprot_accession')).lower():
                continue
            results.append({
                'kind': 'go_annotation',
                'species_id': sid,
                'entity_key': row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession'),
                'annotation_id': row.get('go_id'),
                'annotation_name': row.get('go_name'),
                'namespace': row.get('go_namespace'),
                'route': f"/species/{sid}/entity/{row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession')}",
            })
            if len(results) >= limit_int:
                break
        if len(results) >= limit_int:
            break
        for row in _kegg_link_rows_for_species(sid):
            if q not in ' '.join(str(row.get(key, '')) for key in ('annotation_id', 'annotation_name', 'gene_id', 'protein_id', 'uniprot_accession', 'kegg_gene_id')).lower():
                continue
            results.append({
                'kind': 'kegg_annotation',
                'species_id': sid,
                'entity_key': row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession'),
                'annotation_type': row.get('annotation_type'),
                'annotation_id': row.get('annotation_id'),
                'annotation_name': row.get('annotation_name'),
                'route': f"/species/{sid}/entity/{row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession')}",
            })
            if len(results) >= limit_int:
                break
    return {'query': query, 'species_id': species_id, 'results': results}


def _term_gene_sets(species_id: str, annotation_type: str, namespace: str = '', kegg_type: str = '') -> tuple[dict[str, set[str]], dict[str, dict[str, str]], dict[str, set[str]]]:
    term_to_genes: dict[str, set[str]] = defaultdict(set)
    term_meta: dict[str, dict[str, str]] = {}
    identifier_to_gene: dict[str, set[str]] = defaultdict(set)
    if annotation_type == 'go':
        rows = _go_rows_for_species(species_id)
        for row in rows:
            if namespace and (row.get('go_namespace') or '').lower() != namespace.lower():
                continue
            gene = _norm(row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession'))
            term = row.get('go_id') or ''
            if not gene or not term:
                continue
            term_to_genes[term].add(gene)
            term_meta.setdefault(term, {'annotation_id': term, 'annotation_name': row.get('go_name') or '', 'annotation_type': row.get('go_namespace') or 'go'})
            for identifier in _entity_identifiers(row):
                identifier_to_gene[identifier].add(gene)
    else:
        rows = _kegg_link_rows_for_species(species_id)
        for row in rows:
            if kegg_type and (row.get('annotation_type') or '').lower() != kegg_type.lower():
                continue
            gene = _norm(row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession'))
            term = row.get('annotation_id') or ''
            if not gene or not term:
                continue
            term_to_genes[term].add(gene)
            term_meta.setdefault(term, {'annotation_id': term, 'annotation_name': row.get('annotation_name') or '', 'annotation_type': row.get('annotation_type') or 'kegg'})
            for identifier in _entity_identifiers(row):
                identifier_to_gene[identifier].add(gene)
    return term_to_genes, term_meta, identifier_to_gene


def _hypergeom_sf(k: int, population_size: int, success_states: int, draws: int) -> float:
    if k <= 0:
        return 1.0
    max_k = min(success_states, draws)
    min_k = max(k, draws - (population_size - success_states))
    denom = math.comb(population_size, draws)
    total = 0
    for i in range(min_k, max_k + 1):
        total += math.comb(success_states, i) * math.comb(population_size - success_states, draws - i)
    return min(1.0, total / denom) if denom else 1.0


def _bh_fdr(rows: list[dict[str, Any]]) -> None:
    ordered = sorted(rows, key=lambda item: item['pvalue'])
    n = len(ordered)
    best = 1.0
    for rank_from_end, item in enumerate(reversed(ordered), start=1):
        rank = n - rank_from_end + 1
        adjusted = min(best, item['pvalue'] * n / rank)
        item['fdr'] = adjusted
        best = adjusted


def enrichment_payload(payload: dict[str, Any]) -> dict[str, Any]:
    species_id = str(payload.get('species_id') or '').strip()
    annotation_type = str(payload.get('annotation_type') or payload.get('kind') or 'go').strip().lower()
    namespace = str(payload.get('namespace') or '').strip()
    kegg_type = str(payload.get('kegg_type') or payload.get('annotation_subtype') or '').strip()
    raw_entities = payload.get('entities') or payload.get('entity_ids') or payload.get('ids') or []
    if isinstance(raw_entities, str):
        raw_entities = [item.strip() for item in raw_entities.replace(',', '\n').splitlines() if item.strip()]
    if not species_id:
        raise AnnotationNotFound('species_id is required for enrichment.')
    if annotation_type not in {'go', 'kegg'}:
        raise AnnotationNotFound('annotation_type must be go or kegg.')
    term_to_genes, term_meta, identifier_to_gene = _term_gene_sets(species_id, annotation_type, namespace=namespace, kegg_type=kegg_type)
    universe = set().union(*term_to_genes.values()) if term_to_genes else set()
    query_genes: set[str] = set()
    unmatched = []
    for item in raw_entities:
        normalized = _norm(item)
        matched = identifier_to_gene.get(normalized) or ({normalized} if normalized in universe else set())
        if matched:
            query_genes.update(matched)
        else:
            unmatched.append(item)
    population_size = len(universe)
    draws = len(query_genes)
    rows = []
    if population_size and draws:
        for term, genes in term_to_genes.items():
            overlap = sorted(query_genes & genes)
            if not overlap:
                continue
            pvalue = _hypergeom_sf(len(overlap), population_size, len(genes), draws)
            rows.append({
                **term_meta.get(term, {'annotation_id': term, 'annotation_name': '', 'annotation_type': annotation_type}),
                'overlap_count': len(overlap),
                'term_entity_count': len(genes),
                'query_size': draws,
                'universe_size': population_size,
                'pvalue': pvalue,
                'fold_enrichment': (len(overlap) / draws) / (len(genes) / population_size) if draws and genes and population_size else 0,
                'overlap_entities': overlap[:200],
            })
        _bh_fdr(rows)
        rows.sort(key=lambda item: (item.get('fdr', 1.0), item.get('pvalue', 1.0), -item.get('overlap_count', 0)))
    query_hash = hashlib.sha256(json.dumps(sorted(str(item) for item in raw_entities), ensure_ascii=False).encode('utf-8')).hexdigest()[:16]
    return {
        'analysis_id': f'{species_id}:{annotation_type}:{query_hash}',
        'species_id': species_id,
        'annotation_type': annotation_type,
        'filters': {'namespace': namespace, 'kegg_type': kegg_type},
        'query_size_input': len(raw_entities),
        'query_size_matched': draws,
        'universe_size': population_size,
        'unmatched_entities': unmatched[:200],
        'results': rows[: int(payload.get('limit') or 100)],
        'method_metadata': {
            'test': 'one-sided hypergeometric/Fisher exact over-representation',
            'multiple_testing': 'Benjamini-Hochberg FDR',
            'universe': 'same-species entities with the selected official standard annotation type',
            'namespace_policy': 'GO namespaces are analyzed separately when namespace is provided.',
            'prediction_policy': 'No inferred GO or KEGG annotation is generated.',
        },
    }


def downloads_payload() -> list[dict[str, Any]]:
    rows = []
    labels = {
        'status': 'Species functional annotation status',
        'go': 'All species GO annotations with terms',
        'go_raw': 'All species GO annotations',
        'go_terms': 'GO term dictionary',
        'kegg_genes': 'KEGG gene annotations from UniProt cross references',
        'kegg_links': 'Long KEGG KO/pathway/module links',
        'kegg_compact': 'Compatibility KEGG annotation table',
        'manifest': 'Functional annotation download manifest',
        'kegg_manifest': 'KEGG retrieval manifest',
    }
    for kind, name in FILE_NAMES.items():
        path = annotation_data_dir() / name
        if not path.exists():
            continue
        rows.append({
            'kind': kind,
            'label': labels.get(kind, kind),
            'description': 'Official standard annotation file; absent species are represented in the status table rather than predicted.',
            'url': f'/api/stoichdb/downloads/annotations/{kind}/',
            'size_bytes': path.stat().st_size,
            'filename': path.name,
        })
    return rows


def download_path(kind: str) -> Path:
    if kind not in FILE_NAMES:
        raise AnnotationNotFound(f'Unknown annotation download kind: {kind}')
    path = annotation_data_dir() / FILE_NAMES[kind]
    if not path.exists():
        raise AnnotationNotFound(f'Annotation file is missing: {FILE_NAMES[kind]}')
    return path


def quality_payload() -> dict[str, Any]:
    status = annotation_status_payload(page=1, page_size=20)
    return {
        'release': release_payload(),
        'coverage_summary': status['summary'],
        'top_species': status['rows'],
        'downloads': downloads_payload(),
        'method_metadata': {
            'status_table': FILE_NAMES['status'],
            'go_table': FILE_NAMES['go'],
            'kegg_gene_table': FILE_NAMES['kegg_genes'],
            'kegg_link_table': FILE_NAMES['kegg_links'],
            'unsupported_policy': 'Species without official GO/KEGG records are retained as no_standard_annotation and excluded from enrichment universes.',
        },
    }


def docs_payload() -> dict[str, Any]:
    return {
        'release': release_payload(),
        'files': downloads_payload(),
        'endpoints': [
            {'method': 'GET', 'path': '/api/stoichdb/annotations/status/', 'purpose': 'Species-level GO/KEGG availability, including explicit no-standard-annotation status.'},
            {'method': 'GET', 'path': '/api/stoichdb/annotations/search/', 'params': 'query, species_id, limit', 'purpose': 'Search GO and KEGG annotation records.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/{species_id}/functional-summary/', 'purpose': 'Species-level functional annotation summary.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/{species_id}/annotations/go/', 'params': 'namespace, query, page, page_size', 'purpose': 'Paged GO annotations.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/{species_id}/annotations/kegg/', 'params': 'annotation_type, query, page, page_size', 'purpose': 'Paged KEGG genes or long KO/pathway/module links.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/{species_id}/entities/{entity_key}/function/', 'purpose': 'Entity-level GO/KEGG evidence chain.'},
            {'method': 'POST', 'path': '/api/stoichdb/analysis/enrichment/', 'purpose': 'Same-species GO/KEGG over-representation with BH FDR.'},
            {'method': 'GET', 'path': '/api/stoichdb/case-studies/case2/function-chain/', 'purpose': 'ID mapping to standard function annotation case payload.'},
            {'method': 'GET', 'path': '/api/stoichdb/case-studies/case3/function-evidence/', 'purpose': 'Candidate entity report enriched with GO/KEGG evidence.'},
            {'method': 'GET', 'path': '/api/stoichdb/downloads/annotations/{kind}/', 'purpose': 'Download standard functional annotation CSV/JSON files.'},
        ],
        'enrichment_contract': {
            'required': ['species_id', 'entities'],
            'annotation_type': 'go or kegg',
            'optional': ['namespace', 'kegg_type', 'limit'],
            'statistics': 'one-sided hypergeometric/Fisher exact test with Benjamini-Hochberg FDR',
        },
    }


def case2_function_chain_payload() -> dict[str, Any]:
    ranked = sorted(_status_rows(), key=lambda row: (_to_int(row.get('kegg_joined_rows')), _to_int(row.get('go_rows'))), reverse=True)
    selected = next((row for row in ranked if _to_int(row.get('kegg_joined_rows')) > 0 and _to_int(row.get('go_rows')) > 0), ranked[0] if ranked else {})
    species_id = selected.get('species_id') or ''
    genes = _kegg_gene_rows_for_species(species_id)[:20]
    chain_rows = []
    for row in genes:
        function = entity_function_payload(species_id, row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession'))
        chain_rows.append({
            'species_id': species_id,
            'gene_id': row.get('gene_id'),
            'transcript_id': row.get('transcript_id'),
            'protein_id': row.get('protein_id'),
            'uniprot_accession': row.get('uniprot_accession'),
            'kegg_gene_id': row.get('kegg_gene_id'),
            'go_term_count': function['go']['row_count'],
            'kegg_link_count': function['kegg']['link_row_count'],
            'top_go_terms': function['go']['terms'][:3],
            'top_kegg_annotations': function['kegg']['annotations'][:3],
        })
    return {
        'id': 'case2_function_chain',
        'title': 'Case 2 functional ID chain',
        'selected_species': selected,
        'chain_table': chain_rows,
        'method': 'Shows how internal gene/transcript/protein IDs connect to UniProt, GO, and KEGG standard records.',
        'limitations': ['Only species with official GO/KEGG records are included; no annotation is predicted for unsupported species.'],
    }


def case3_function_evidence_payload() -> dict[str, Any]:
    ranked = sorted(_status_rows(), key=lambda row: (_to_int(row.get('go_rows')) + _to_int(row.get('kegg_joined_rows'))), reverse=True)
    for status in ranked:
        species_id = status.get('species_id') or ''
        for row in _kegg_gene_rows_for_species(species_id):
            key = row.get('gene_id') or row.get('protein_id') or row.get('uniprot_accession')
            evidence = entity_function_payload(species_id, key)
            if evidence['go']['row_count'] and evidence['kegg']['link_row_count']:
                return {
                    'id': 'case3_function_evidence',
                    'title': 'Case 3 candidate functional evidence',
                    'selected_entity': {
                        'species_id': species_id,
                        'tax_name': status.get('tax_name'),
                        'entity_key': key,
                        'gene_id': row.get('gene_id'),
                        'protein_id': row.get('protein_id'),
                        'uniprot_accession': row.get('uniprot_accession'),
                    },
                    'functional_evidence': evidence,
                    'method': 'Combines entity-level platform IDs with official GO and KEGG annotations.',
                    'limitations': ['Evidence is descriptive and depends on existing standard database records.'],
                }
    raise AnnotationNotFound('No entity with both GO and KEGG evidence was found in the annotation bundle.')
