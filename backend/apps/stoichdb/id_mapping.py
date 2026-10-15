from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import services
from .models import Species


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / 'data' / 'id_mapping'
SQLITE_PATH = DATA_DIR / 'id_mapping.sqlite'
MANIFEST_PATH = DATA_DIR / 'id_mapping_manifest.json'
SCHEMA_PATH = DATA_DIR / 'id_mapping_schema.json'
QC_PATH = DATA_DIR / 'id_mapping_qc_summary.json'
CASE2_PATH = DATA_DIR / 'case2_id_mapping_advanced_payload.json'
FULL_OMICS_CSV = DATA_DIR / 'protist_omics_id_mapping_all_species.csv'
FULL_EXTERNAL_CSV = DATA_DIR / 'protist_external_id_mapping_all_species.csv'
FINAL_ROOT = DATA_DIR / 'final_whitelist'
FINAL_MANIFEST_PATH = FINAL_ROOT / 'final_whitelist_id_mapping_manifest.json'
FINAL_OFFSETS_PATH = FINAL_ROOT / 'final_whitelist_external_offsets.json'
FINAL_ONLINE_ROOT = FINAL_ROOT / 'online_external'
FINAL_ONLINE_MANIFEST_PATH = FINAL_ONLINE_ROOT / 'final_whitelist_online_external_id_mapping_manifest.json'
FINAL_GROUPS = {'bacteria', 'fungi', 'metazoa', 'plants', 'vertebrates'}
STANDARD_OVERLAY_ROOT = DATA_DIR / 'standard_external_id_overlay'
STANDARD_OVERLAY_MANIFEST_PATH = STANDARD_OVERLAY_ROOT / 'standard_external_id_overlay_manifest.json'


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding='utf-8'))


@lru_cache(maxsize=1)
def _final_offsets() -> dict[str, Any]:
    return _read_json(FINAL_OFFSETS_PATH, default={})


@lru_cache(maxsize=1)
def _final_species_qc() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for group in FINAL_GROUPS:
        path = FINAL_ROOT / group / f'{group}_id_mapping_species_qc.csv'
        if not path.exists():
            continue
        with path.open('r', encoding='utf-8-sig', newline='') as fh:
            for row in csv.DictReader(fh):
                species_id = clean_value(row.get('species_id'))
                if species_id:
                    rows[species_id] = {key: clean_value(value) for key, value in row.items()}
    return rows


def clean_value(value: object) -> str:
    text = str(value or '').strip()
    if text.lower() in {'nan', 'none', 'null'}:
        return ''
    return text


def _final_species_offset(species_id: str) -> dict[str, Any]:
    return ((_final_offsets().get('species') or {}).get(species_id) or {})


def _is_final_species(species_id: str) -> bool:
    return bool(_final_species_offset(species_id) or species_id in _final_species_qc())


@lru_cache(maxsize=8)
def _final_online_accession_map(group: str) -> dict[str, dict[str, list[str]]]:
    if group not in FINAL_GROUPS:
        return {}
    path = FINAL_ONLINE_ROOT / group / f'{group}_uniprot_online_accession_map.csv'
    if not path.exists():
        return {}
    mapping: dict[str, dict[str, set[str]]] = {}
    with path.open('r', encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            accession = clean_value(row.get('uniprot_accession'))
            database = clean_value(row.get('target_database'))
            external_id = clean_value(row.get('external_id'))
            if not accession or not database or not external_id:
                continue
            if database == 'NCBI Gene':
                key = 'ncbi_gene'
            elif database == 'NCBI Protein':
                key = 'refseq_protein'
            else:
                key = database.lower().replace(' ', '_')
            mapping.setdefault(accession, {}).setdefault(key, set()).add(external_id)
    return {acc: {key: sorted(values) for key, values in dbs.items()} for acc, dbs in mapping.items()}


def _final_online_external_ids(row: dict[str, Any]) -> dict[str, list[str]]:
    group = clean_value(row.get('division'))
    result = {'ncbi_gene': [], 'refseq_protein': []}
    if not group:
        return result
    accession_map = _final_online_accession_map(group)
    if not accession_map:
        return result
    for accession in _split(row.get('uniprot_accessions', '')):
        mapped = accession_map.get(accession) or {}
        for key, values in mapped.items():
            result.setdefault(key, [])
            result[key].extend(values)
    return {key: sorted(set(values)) for key, values in result.items() if values}


def _merge_ids(*items: list[str]) -> list[str]:
    merged: set[str] = set()
    for values in items:
        merged.update(value for value in values if value)
    return sorted(merged)


def _conn() -> sqlite3.Connection:
    if not SQLITE_PATH.exists():
        raise services.NotFoundError('ID mapping runtime index is missing. Run scripts/build_id_mapping_layer.py first.')
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row else {}


def _split(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in str(value).replace('|', ';').replace(',', ';').split(';') if item.strip()]


def _species_file_stem(species_id: str) -> str:
    candidate = re.sub(r'[^A-Za-z0-9_.-]+', '_', clean_value(species_id))
    if len(candidate) <= 56:
        return candidate
    digest = hashlib.sha1(clean_value(species_id).encode('utf-8')).hexdigest()[:16]
    return f'{candidate[:48]}_{digest}'


def _overlay_group_for_species(species_id: str, row: dict[str, Any] | None = None) -> str:
    division = clean_value((row or {}).get('division'))
    if division in FINAL_GROUPS:
        return division
    offset = _final_species_offset(species_id)
    division = clean_value(offset.get('division'))
    if division in FINAL_GROUPS:
        return division
    return 'protists'


def _overlay_paths(group: str, species_id: str) -> list[Path]:
    group_dir = STANDARD_OVERLAY_ROOT / group
    stem = _species_file_stem(species_id)
    paths = [group_dir / f'{stem}.standard_id_overlay.csv']
    raw = group_dir / f'{species_id}.standard_id_overlay.csv'
    if raw not in paths:
        paths.append(raw)
    return paths


@lru_cache(maxsize=2048)
def _standard_overlay_for_species(group: str, species_id: str) -> dict[str, dict[str, list[str]]]:
    rows: dict[str, dict[str, set[str]]] = {}
    path = next((item for item in _overlay_paths(group, species_id) if item.exists()), None)
    if not path:
        return {}
    with path.open('r', encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            internal_id = clean_value(row.get('internal_id'))
            if not internal_id:
                continue
            item = rows.setdefault(
                internal_id,
                {
                    'uniprot': set(),
                    'ncbi_gene': set(),
                    'refseq_protein': set(),
                    'refseq_transcript': set(),
                    'insdc_protein': set(),
                },
            )
            item['uniprot'].update(_split(row.get('uniprot_accessions', '')))
            item['ncbi_gene'].update(_split(row.get('ncbi_gene_ids', '')))
            item['refseq_protein'].update(_split(row.get('refseq_protein_accessions', '')))
            item['refseq_transcript'].update(_split(row.get('refseq_transcript_accessions', '')))
            item['insdc_protein'].update(_split(row.get('insdc_protein_accessions', '')))
    return {key: {field: sorted(values) for field, values in value.items() if values} for key, value in rows.items()}


@lru_cache(maxsize=8)
def _standard_overlay_accession_map(group: str) -> dict[str, dict[str, list[str]]]:
    path = STANDARD_OVERLAY_ROOT / group / f'{group}_uniprot_online_accession_map.csv'
    if not path.exists():
        return {}
    mapping: dict[str, dict[str, set[str]]] = {}
    with path.open('r', encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            accession = clean_value(row.get('uniprot_accession'))
            database = clean_value(row.get('target_database'))
            external_id = clean_value(row.get('external_id'))
            if not accession or not database or not external_id:
                continue
            key = 'ncbi_gene' if database == 'NCBI Gene' else 'refseq_protein' if database == 'NCBI Protein' else database.lower().replace(' ', '_')
            mapping.setdefault(accession, {}).setdefault(key, set()).add(external_id)
    return {acc: {key: sorted(values) for key, values in dbs.items()} for acc, dbs in mapping.items()}


def _candidate_overlay_internal_ids(row: dict[str, Any]) -> list[str]:
    values: set[str] = set()
    for field in ('gene_id', 'transcript_id', 'protein_id', 'source_protein_id'):
        value = clean_value(row.get(field))
        if value:
            values.add(value)
            if '.' in value:
                values.add(value.rsplit('.', 1)[0])
            for prefix in ('gene:', 'transcript:', 'protein:', 'cds:', 'mrna:'):
                values.add(f'{prefix}{value}')
    return sorted(values)


def _standard_overlay_external_ids(row: dict[str, Any]) -> dict[str, list[str]]:
    species_id = clean_value(row.get('species_id'))
    if not species_id:
        return {}
    group = _overlay_group_for_species(species_id, row)
    overlay = _standard_overlay_for_species(group, species_id)
    result: dict[str, set[str]] = {
        'uniprot': set(),
        'ncbi_gene': set(),
        'refseq_protein': set(),
        'refseq_transcript': set(),
        'insdc_protein': set(),
    }
    for internal_id in _candidate_overlay_internal_ids(row):
        item = overlay.get(internal_id) or {}
        for key, values in item.items():
            result.setdefault(key, set()).update(values)
    acc_map = _standard_overlay_accession_map(group)
    for accession in result.get('uniprot', set()):
        for key, values in (acc_map.get(accession) or {}).items():
            result.setdefault(key, set()).update(values)
    return {key: sorted(values) for key, values in result.items() if values}


def _final_row_aliases(row: dict[str, Any]) -> list[tuple[str, str, str]]:
    aliases: list[tuple[str, str, str]] = []
    for field, alias_type, target_type in [
        ('gene_id', 'gene_id', 'gene'),
        ('transcript_id', 'transcript_id', 'transcript'),
        ('protein_id', 'protein_id', 'protein'),
        ('source_protein_id', 'source_protein_id', 'protein'),
        ('tax_id', 'tax_id', 'species'),
        ('assembly_accession', 'assembly_accession', 'species'),
    ]:
        value = clean_value(row.get(field))
        if value:
            aliases.append((value, alias_type, target_type))
    for field, alias_type, target_type in [
        ('uniprot_accessions', 'uniprot', 'protein'),
        ('ncbi_gene_ids', 'ncbi_gene', 'gene'),
        ('refseq_protein_accessions', 'refseq_protein', 'protein'),
        ('insdc_protein_accessions', 'insdc_protein', 'protein'),
        ('ncbi_protein_accessions', 'ncbi_protein', 'protein'),
        ('refseq_transcript_accessions', 'refseq_transcript', 'transcript'),
        ('insdc_sequence_region_accessions', 'insdc_region', 'protein'),
    ]:
        for value in _split(row.get(field, '')):
            aliases.append((value, alias_type, target_type))
    online = _final_online_external_ids(row)
    for value in online.get('ncbi_gene', []):
        aliases.append((value, 'ncbi_gene', 'gene'))
    for value in online.get('refseq_protein', []):
        aliases.append((value, 'refseq_protein', 'protein'))
    overlay = _standard_overlay_external_ids(row)
    for value in overlay.get('uniprot', []):
        aliases.append((value, 'uniprot', 'protein'))
    for value in overlay.get('ncbi_gene', []):
        aliases.append((value, 'ncbi_gene', 'gene'))
    for value in overlay.get('refseq_protein', []):
        aliases.append((value, 'refseq_protein', 'protein'))
    for value in overlay.get('insdc_protein', []):
        aliases.append((value, 'insdc_protein', 'protein'))
    for value in overlay.get('refseq_transcript', []):
        aliases.append((value, 'refseq_transcript', 'transcript'))
    return aliases


def _final_iter_species_rows(species_id: str):
    offset = _final_species_offset(species_id)
    if not offset:
        return
    path = Path(offset.get('path') or '')
    if not path.exists():
        return
    group = offset.get('division') or ''
    header = (((_final_offsets().get('groups') or {}).get(group) or {}).get('header') or [])
    start = int(offset.get('start_byte') or 0)
    end = int(offset.get('end_byte') or 0)
    if not header or not start or not end:
        return
    with path.open('rb') as fh:
        fh.seek(start)
        while fh.tell() < end:
            raw = fh.readline()
            if not raw:
                break
            line = raw.decode('utf-8', errors='replace')
            try:
                values = next(csv.reader([line]))
            except Exception:
                continue
            row = dict(zip(header, values))
            row.setdefault('division', group)
            yield row


def _final_match_row(row: dict[str, Any], q: str, *, prefix: bool = False, id_type: str = '') -> tuple[str, str, str] | None:
    nq = q.casefold()
    for alias, alias_type, target_type in _final_row_aliases(row):
        if id_type and id_type != 'all' and alias_type != id_type:
            continue
        na = alias.casefold()
        if (prefix and na.startswith(nq)) or (not prefix and na == nq):
            return alias, alias_type, target_type
    return None


def _prefix_upper_bound(prefix: str) -> str:
    if not prefix:
        return prefix
    return prefix[:-1] + chr(ord(prefix[-1]) + 1)


def _overlay_alias_iter(group: str, species_id: str):
    overlay = _standard_overlay_for_species(group, species_id)
    for internal_id, item in overlay.items():
        for alias_type, target_type, key in [
            ('uniprot', 'protein', 'uniprot'),
            ('ncbi_gene', 'gene', 'ncbi_gene'),
            ('refseq_protein', 'protein', 'refseq_protein'),
            ('insdc_protein', 'protein', 'insdc_protein'),
            ('refseq_transcript', 'transcript', 'refseq_transcript'),
        ]:
            for value in item.get(key, []):
                yield internal_id, value, alias_type, target_type


def _resolve_overlay_protist_species(q: str, species_id: str, limit: int, *, prefix: bool = False, id_type: str = '') -> list[dict[str, Any]]:
    if _is_final_species(species_id):
        return []
    group = _overlay_group_for_species(species_id)
    nq = q.casefold()
    matches: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    with _conn() as conn:
        for internal_id, alias, alias_type, target_type in _overlay_alias_iter(group, species_id):
            if id_type and id_type != 'all' and alias_type != id_type:
                continue
            na = alias.casefold()
            if not ((prefix and na.startswith(nq)) or (not prefix and na == nq)):
                continue
            row = conn.execute(
                """
                SELECT * FROM id_mapping_chain
                WHERE species_id = ?
                  AND (gene_id = ? OR transcript_id = ? OR protein_id = ? OR source_protein_id = ?)
                LIMIT 1
                """,
                (species_id, internal_id, internal_id, internal_id, internal_id),
            ).fetchone()
            if not row:
                continue
            key = (row['gene_id'], row['transcript_id'], row['protein_id'])
            if key in seen:
                continue
            seen.add(key)
            matches.append(_chain_payload(row, matched_id=alias, id_type=alias_type, species_name=species_id))
            if len(matches) >= limit:
                break
    return matches


def _final_payload(row: dict[str, Any], matched_id: str = '', id_type: str = 'internal_id', target_type: str = 'gene') -> dict[str, Any]:
    chain = {key: clean_value(value) for key, value in row.items()}
    species_id = chain.get('species_id', '')
    gene_id = chain.get('gene_id', '')
    transcript_id = chain.get('transcript_id', '')
    protein_id = chain.get('protein_id', '')
    online_ids = _final_online_external_ids(chain)
    overlay_ids = _standard_overlay_external_ids(chain)
    external_ids = {
        'uniprot': _merge_ids(_split(chain.get('uniprot_accessions', '')), overlay_ids.get('uniprot', [])),
        'ncbi_gene': _merge_ids(_split(chain.get('ncbi_gene_ids', '')), online_ids.get('ncbi_gene', []), overlay_ids.get('ncbi_gene', [])),
        'ncbi_protein': _split(chain.get('ncbi_protein_accessions', '')),
        'refseq_protein': _merge_ids(_split(chain.get('refseq_protein_accessions', '')), online_ids.get('refseq_protein', []), overlay_ids.get('refseq_protein', [])),
        'insdc_protein': _merge_ids(_split(chain.get('insdc_protein_accessions', '')), overlay_ids.get('insdc_protein', [])),
        'refseq_transcript': _merge_ids(_split(chain.get('refseq_transcript_accessions', '')), overlay_ids.get('refseq_transcript', [])),
        'insdc_region': _split(chain.get('insdc_sequence_region_accessions', '')),
    }
    payload = {
        'matched_id': matched_id or gene_id or protein_id or transcript_id,
        'id_type': id_type,
        'species_id': species_id,
        'species_name': species_id,
        'division': chain.get('division', ''),
        'target_type': target_type,
        'target_id': gene_id if target_type == 'gene' else transcript_id if target_type == 'transcript' else protein_id or gene_id,
        'entity_key': gene_id or protein_id or transcript_id,
        'gene_id': gene_id,
        'transcript_id': transcript_id,
        'protein_id': protein_id,
        'mapping_level': chain.get('mapping_level', ''),
        'mapping_status': chain.get('internal_mapping_status', ''),
        'mapping_confidence': chain.get('internal_mapping_confidence', ''),
        'external_mapping_status': chain.get('external_mapping_status', ''),
        'external_mapping_confidence': chain.get('external_mapping_confidence', ''),
        'external_ids': external_ids,
        'online_external_ids': online_ids,
        'standard_overlay_external_ids': overlay_ids,
        'feature_coverage': {
            'genome': bool(gene_id),
            'transcriptome': bool(transcript_id),
            'proteome': bool(protein_id),
        },
        'conflict_warning': chain.get('internal_mapping_status') == 'conflict',
        'external_links': _external_links({**chain, 'uniprot_accessions': ';'.join(external_ids['uniprot']), 'ncbi_gene_ids': ';'.join(external_ids['ncbi_gene']), 'refseq_protein_accessions': ';'.join(external_ids['refseq_protein']), 'insdc_protein_accessions': ';'.join(external_ids['insdc_protein']), 'refseq_transcript_accessions': ';'.join(external_ids['refseq_transcript'])}),
        'runtime_source': 'final_whitelist_species_offset_csv',
    }
    return payload


def _resolve_final_species(q: str, species_id: str, limit: int, *, prefix: bool = False, id_type: str = '') -> list[dict[str, Any]]:
    matches = []
    if not _final_species_offset(species_id):
        return matches
    for row in _final_iter_species_rows(species_id) or []:
        match = _final_match_row(row, q, prefix=prefix, id_type=id_type)
        if not match:
            continue
        alias, alias_type, target_type = match
        matches.append(_final_payload(row, matched_id=alias, id_type=alias_type, target_type=target_type))
        if len(matches) >= limit:
            break
    return matches


def _species_names(species_ids: set[str]) -> dict[str, str]:
    if not species_ids:
        return {}
    return {
        row.species_id: row.display_name
        for row in Species.objects.filter(species_id__in=species_ids).only('species_id', 'display_name')
    }


def _external_links(row: dict[str, Any]) -> list[dict[str, str]]:
    links = []
    for acc in _split(row.get('uniprot_accessions', '')):
        links.append({'database': 'UniProtKB', 'id': acc, 'url': f'https://www.uniprot.org/uniprotkb/{acc}/entry'})
    for gid in _split(row.get('ncbi_gene_ids', '')):
        links.append({'database': 'NCBI Gene', 'id': gid, 'url': f'https://www.ncbi.nlm.nih.gov/gene/{gid}'})
    for acc in _split(row.get('ncbi_protein_accessions', '')) + _split(row.get('refseq_protein_accessions', '')):
        links.append({'database': 'NCBI Protein', 'id': acc, 'url': f'https://www.ncbi.nlm.nih.gov/protein/{acc}'})
    for acc in _split(row.get('refseq_transcript_accessions', '')):
        links.append({'database': 'NCBI Nucleotide', 'id': acc, 'url': f'https://www.ncbi.nlm.nih.gov/nuccore/{acc}'})
    for acc in _split(row.get('insdc_protein_accessions', '')) + _split(row.get('insdc_sequence_region_accessions', '')):
        links.append({'database': 'ENA/INSDC', 'id': acc, 'url': f'https://www.ebi.ac.uk/ena/browser/view/{acc}'})
    tax_id = str(row.get('tax_id') or '').strip()
    if tax_id:
        links.append({'database': 'NCBI Taxonomy', 'id': tax_id, 'url': f'https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={tax_id}'})
    return links


def _detect_id_type(query: str) -> str:
    text = query.strip()
    upper = text.upper()
    if not text:
        return 'empty'
    if upper.startswith(('XP_', 'NP_', 'WP_', 'YP_', 'AP_', 'ZP_')):
        return 'refseq_or_ncbi_protein'
    if upper.startswith(('NM_', 'XM_', 'NR_', 'XR_')):
        return 'refseq_transcript'
    if len(text) in {6, 10} and text[0].isalnum() and any(ch.isdigit() for ch in text):
        return 'uniprot_or_accession'
    if '-t' in text or '.t' in text:
        return 'transcript_id'
    if '-p' in text or '.p' in text:
        return 'protein_id'
    if text.isdigit():
        return 'tax_id_or_ncbi_gene'
    return 'gene_or_symbol'


def _chain_for_alias(conn: sqlite3.Connection, alias_row: sqlite3.Row) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM id_mapping_chain
        WHERE species_id=? AND gene_id=? AND transcript_id=? AND protein_id=?
        LIMIT 1
        """,
        (alias_row['species_id'], alias_row['gene_id'], alias_row['transcript_id'], alias_row['protein_id']),
    ).fetchone()
    data = _row_dict(row)
    if not data:
        data = {key: alias_row[key] for key in alias_row.keys() if key in {'species_id', 'gene_id', 'transcript_id', 'protein_id'}}
    return data


def _match_payload(conn: sqlite3.Connection, alias_row: sqlite3.Row, species_name: str = '') -> dict[str, Any]:
    chain = _chain_for_alias(conn, alias_row)
    overlay_ids = _standard_overlay_external_ids(chain)
    external_ids = {
        'uniprot': _merge_ids(_split(chain.get('uniprot_accessions', '')), overlay_ids.get('uniprot', [])),
        'ncbi_gene': _merge_ids(_split(chain.get('ncbi_gene_ids', '')), overlay_ids.get('ncbi_gene', [])),
        'ncbi_protein': _split(chain.get('ncbi_protein_accessions', '')),
        'refseq_protein': _merge_ids(_split(chain.get('refseq_protein_accessions', '')), overlay_ids.get('refseq_protein', [])),
        'insdc_protein': _merge_ids(_split(chain.get('insdc_protein_accessions', '')), overlay_ids.get('insdc_protein', [])),
        'refseq_transcript': _merge_ids(_split(chain.get('refseq_transcript_accessions', '')), overlay_ids.get('refseq_transcript', [])),
        'insdc_region': _split(chain.get('insdc_sequence_region_accessions', '')),
    }
    return {
        'matched_id': alias_row['alias_value'],
        'id_type': alias_row['alias_type'],
        'species_id': alias_row['species_id'],
        'species_name': species_name or alias_row['species_id'],
        'target_type': alias_row['target_type'],
        'target_id': alias_row['target_id'],
        'entity_key': chain.get('gene_id') or chain.get('protein_id') or chain.get('transcript_id') or alias_row['target_id'],
        'gene_id': chain.get('gene_id') or '',
        'transcript_id': chain.get('transcript_id') or '',
        'protein_id': chain.get('protein_id') or '',
        'mapping_level': chain.get('mapping_level') or '',
        'mapping_status': chain.get('internal_mapping_status') or alias_row['mapping_status'],
        'mapping_confidence': chain.get('internal_mapping_confidence') or alias_row['mapping_confidence'],
        'external_mapping_status': chain.get('external_mapping_status') or alias_row['external_mapping_status'],
        'external_mapping_confidence': chain.get('external_mapping_confidence') or alias_row['external_mapping_confidence'],
        'external_ids': external_ids,
        'standard_overlay_external_ids': overlay_ids,
        'feature_coverage': {
            'genome': bool(chain.get('gene_id')),
            'transcriptome': bool(chain.get('transcript_id')),
            'proteome': bool(chain.get('protein_id')),
        },
        'conflict_warning': (chain.get('internal_mapping_status') == 'conflict'),
        'external_links': _external_links({**chain, 'uniprot_accessions': ';'.join(external_ids['uniprot']), 'ncbi_gene_ids': ';'.join(external_ids['ncbi_gene']), 'refseq_protein_accessions': ';'.join(external_ids['refseq_protein']), 'insdc_protein_accessions': ';'.join(external_ids['insdc_protein']), 'refseq_transcript_accessions': ';'.join(external_ids['refseq_transcript'])}),
    }


def _chain_payload(row: sqlite3.Row, matched_id: str = '', id_type: str = 'internal_id', species_name: str = '') -> dict[str, Any]:
    chain = _row_dict(row)
    overlay_ids = _standard_overlay_external_ids(chain)
    external_ids = {
        'uniprot': _merge_ids(_split(chain.get('uniprot_accessions', '')), overlay_ids.get('uniprot', [])),
        'ncbi_gene': _merge_ids(_split(chain.get('ncbi_gene_ids', '')), overlay_ids.get('ncbi_gene', [])),
        'ncbi_protein': _split(chain.get('ncbi_protein_accessions', '')),
        'refseq_protein': _merge_ids(_split(chain.get('refseq_protein_accessions', '')), overlay_ids.get('refseq_protein', [])),
        'insdc_protein': _merge_ids(_split(chain.get('insdc_protein_accessions', '')), overlay_ids.get('insdc_protein', [])),
        'refseq_transcript': _merge_ids(_split(chain.get('refseq_transcript_accessions', '')), overlay_ids.get('refseq_transcript', [])),
        'insdc_region': _split(chain.get('insdc_sequence_region_accessions', '')),
    }
    return {
        'matched_id': matched_id or chain.get('gene_id') or chain.get('protein_id') or chain.get('transcript_id') or '',
        'id_type': id_type,
        'species_id': chain.get('species_id', ''),
        'species_name': species_name or chain.get('species_id', ''),
        'target_type': 'gene',
        'target_id': chain.get('gene_id') or chain.get('protein_id') or chain.get('transcript_id') or '',
        'entity_key': chain.get('gene_id') or chain.get('protein_id') or chain.get('transcript_id') or '',
        'gene_id': chain.get('gene_id') or '',
        'transcript_id': chain.get('transcript_id') or '',
        'protein_id': chain.get('protein_id') or '',
        'mapping_level': chain.get('mapping_level') or '',
        'mapping_status': chain.get('internal_mapping_status') or '',
        'mapping_confidence': chain.get('internal_mapping_confidence') or '',
        'external_mapping_status': chain.get('external_mapping_status') or '',
        'external_mapping_confidence': chain.get('external_mapping_confidence') or '',
        'external_ids': external_ids,
        'standard_overlay_external_ids': overlay_ids,
        'feature_coverage': {
            'genome': bool(chain.get('gene_id')),
            'transcriptome': bool(chain.get('transcript_id')),
            'proteome': bool(chain.get('protein_id')),
        },
        'conflict_warning': chain.get('internal_mapping_status') == 'conflict',
        'external_links': _external_links({**chain, 'uniprot_accessions': ';'.join(external_ids['uniprot']), 'ncbi_gene_ids': ';'.join(external_ids['ncbi_gene']), 'refseq_protein_accessions': ';'.join(external_ids['refseq_protein']), 'insdc_protein_accessions': ';'.join(external_ids['insdc_protein']), 'refseq_transcript_accessions': ';'.join(external_ids['refseq_transcript'])}),
    }


def resolve_id(query: str, species_id: str = '', limit: int = 25) -> dict[str, Any]:
    q = str(query or '').strip()
    if not q:
        return {'query': q, 'detected_id_type': 'empty', 'matches': [], 'total': 0, 'unmatched': True}
    limit = max(1, min(int(limit or 25), 100))
    detected = _detect_id_type(q)
    matches = []
    with _conn() as conn:
        params: list[Any] = [q.casefold()]
        where = 'normalized_alias = ?'
        if species_id:
            where += ' AND species_id = ?'
            params.append(species_id)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT * FROM id_alias_index
            WHERE {where}
            ORDER BY
              CASE mapping_confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
              CASE mapping_status WHEN 'ok' THEN 0 ELSE 1 END,
              species_id, alias_type, target_id
            LIMIT ?
            """,
            params,
        ).fetchall()
        species_map = _species_names({row['species_id'] for row in rows})
        matches = [_match_payload(conn, row, species_map.get(row['species_id'], '')) for row in rows]
    if species_id and _is_final_species(species_id):
        existing = {(m.get('species_id'), m.get('gene_id'), m.get('transcript_id'), m.get('protein_id')) for m in matches}
        for item in _resolve_final_species(q, species_id, limit):
            key = (item.get('species_id'), item.get('gene_id'), item.get('transcript_id'), item.get('protein_id'))
            if key not in existing:
                matches.append(item)
                existing.add(key)
            if len(matches) >= limit:
                break
    if species_id and not _is_final_species(species_id) and len(matches) < limit:
        existing = {(m.get('species_id'), m.get('gene_id'), m.get('transcript_id'), m.get('protein_id')) for m in matches}
        for item in _resolve_overlay_protist_species(q, species_id, limit - len(matches), prefix=False, id_type=''):
            key = (item.get('species_id'), item.get('gene_id'), item.get('transcript_id'), item.get('protein_id'))
            if key not in existing:
                matches.append(item)
                existing.add(key)
            if len(matches) >= limit:
                break
    return {
        'query': q,
        'species_id': species_id,
        'detected_id_type': detected,
        'matches': matches,
        'total': len(matches),
        'ambiguous': len({(m['species_id'], m['entity_key']) for m in matches}) > 1,
        'unmatched': not matches,
        'runtime_index_scope': _read_json(MANIFEST_PATH).get('runtime_index_scope', 'unknown'),
        'final_whitelist_runtime': 'species_offset_csv_enabled' if species_id and _is_final_species(species_id) else 'not_applicable_or_species_not_indexed',
    }


def batch_resolve_ids(queries: list[str], species_id: str = '', limit_per_query: int = 10) -> dict[str, Any]:
    items = []
    for query in queries[:500]:
        resolved = resolve_id(str(query), species_id=species_id, limit=limit_per_query)
        items.append(resolved)
    return {
        'items': items,
        'matched_count': sum(1 for item in items if item.get('matches')),
        'unmatched_count': sum(1 for item in items if not item.get('matches')),
        'ambiguous_count': sum(1 for item in items if item.get('ambiguous')),
    }


def search_mappings(
    *,
    query: str = '',
    species_id: str = '',
    id_type: str = '',
    mapping_confidence: str = '',
    mapping_status: str = '',
    mapping_level: str = '',
    external_status: str = '',
    conflict_only: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    query = str(query or '').strip()
    limit = max(1, min(int(limit or 50), 200))
    clauses = []
    params: list[Any] = []
    if query:
        normalized_query = query.casefold()
        if species_id:
            clauses.append('normalized_alias = ?')
            params.append(normalized_query)
        else:
            clauses.append('normalized_alias >= ? AND normalized_alias < ?')
            params.extend([normalized_query, _prefix_upper_bound(normalized_query)])
    if species_id:
        clauses.append('species_id = ?')
        params.append(species_id)
    if id_type and id_type != 'all':
        clauses.append('alias_type = ?')
        params.append(id_type)
    if mapping_confidence and mapping_confidence != 'all':
        clauses.append('mapping_confidence = ?')
        params.append(mapping_confidence)
    if mapping_status and mapping_status != 'all':
        clauses.append('mapping_status = ?')
        params.append(mapping_status)
    if external_status and external_status != 'all':
        clauses.append('external_mapping_status = ?')
        params.append(external_status)
    if conflict_only:
        clauses.append("mapping_status = 'conflict'")
    where = ' AND '.join(clauses) if clauses else '1=1'
    params.append(limit)
    matches = []
    with _conn() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM id_alias_index
            WHERE {where}
            ORDER BY normalized_alias, species_id
            LIMIT ?
            """,
            params,
        ).fetchall()
        species_map = _species_names({row['species_id'] for row in rows})
        matches = [_match_payload(conn, row, species_map.get(row['species_id'], '')) for row in rows]
        if mapping_level and mapping_level != 'all':
            matches = [row for row in matches if row.get('mapping_level') == mapping_level]
    if species_id and _is_final_species(species_id):
        final_rows = []
        q = query or ''
        for row in _final_iter_species_rows(species_id) or []:
            if q:
                match = _final_match_row(row, q, prefix=not bool(species_id), id_type=id_type)
                if not match:
                    continue
                alias, alias_type, target_type = match
            else:
                alias, alias_type, target_type = row.get('gene_id') or row.get('protein_id') or row.get('transcript_id') or '', 'internal_id', 'gene'
            payload = _final_payload(row, matched_id=alias, id_type=alias_type, target_type=target_type)
            if mapping_confidence and mapping_confidence != 'all' and payload.get('mapping_confidence') != mapping_confidence:
                continue
            if mapping_status and mapping_status != 'all' and payload.get('mapping_status') != mapping_status:
                continue
            if mapping_level and mapping_level != 'all' and payload.get('mapping_level') != mapping_level:
                continue
            if external_status and external_status != 'all' and payload.get('external_mapping_status') != external_status:
                continue
            if conflict_only and not payload.get('conflict_warning'):
                continue
            final_rows.append(payload)
            if len(final_rows) >= limit:
                break
        existing = {(m.get('species_id'), m.get('gene_id'), m.get('transcript_id'), m.get('protein_id')) for m in matches}
        for item in final_rows:
            key = (item.get('species_id'), item.get('gene_id'), item.get('transcript_id'), item.get('protein_id'))
            if key not in existing:
                matches.append(item)
                existing.add(key)
            if len(matches) >= limit:
                break
    if species_id and query and not _is_final_species(species_id) and len(matches) < limit:
        existing = {(m.get('species_id'), m.get('gene_id'), m.get('transcript_id'), m.get('protein_id')) for m in matches}
        for item in _resolve_overlay_protist_species(query, species_id, limit - len(matches), prefix=False, id_type=id_type):
            key = (item.get('species_id'), item.get('gene_id'), item.get('transcript_id'), item.get('protein_id'))
            if key not in existing:
                matches.append(item)
                existing.add(key)
            if len(matches) >= limit:
                break
    return {'matches': matches, 'total': len(matches), 'search_mode': 'species_scoped_exact_alias' if species_id and query else 'global_prefix_alias' if query else 'filtered_alias', 'filters': {
        'query': query,
        'species_id': species_id,
        'id_type': id_type,
        'mapping_confidence': mapping_confidence,
        'mapping_status': mapping_status,
        'mapping_level': mapping_level,
        'external_status': external_status,
        'conflict_only': conflict_only,
    }}


def get_species_mapping_summary(species_id: str) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM id_mapping_summary WHERE species_id=?', (species_id,)).fetchone()
    if row:
        data = _row_dict(row)
        for key in ['status_counts_json', 'confidence_counts_json', 'level_counts_json', 'external_status_counts_json']:
            data[key.replace('_json', '')] = json.loads(data.pop(key) or '{}')
    else:
        qc = _final_species_qc().get(species_id)
        if not qc:
            raise services.NotFoundError(f'No ID mapping summary for species: {species_id}')
        total = int(float(qc.get('total_mapping_rows') or 0))
        external = int(float(qc.get('rows_with_any_external_id') or 0))
        division = qc.get('division', '')
        data = {
            'species_id': species_id,
            'division': division,
            'total_rows': total,
            'complete_chain_rate': 1.0 if total else 0.0,
            'gene_transcript_only_rate': 0.0,
            'conflict_rate': 0.0,
            'high_confidence_rate': 1.0 if total else 0.0,
            'external_high_confidence_rate': round(external / total, 6) if total else 0.0,
            'uniprot_coverage': 0.0,
            'ncbi_or_insdc_coverage': round(external / total, 6) if total else 0.0,
            'gene_in_genome_rate': '',
            'transcript_in_transcriptome_rate': '',
            'protein_in_proteome_rate': 1.0 if total else 0.0,
            'ambiguous_alias_count': 0,
            'grade': qc.get('mapping_grade') or 'A',
            'status_counts': {'ok': total, 'conflict': 0},
            'confidence_counts': {'high': total, 'medium': 0, 'low': 0},
            'level_counts': {'gene_transcript_protein': total},
            'external_status_counts': {'mapped_rows': external, 'species_standard_only': max(total - external, 0)},
            'runtime_source': 'final_whitelist_species_offset_csv',
        }
    data['download_links'] = {
        'all_species_internal_mapping': '/api/stoichdb/downloads/id-mapping/?kind=omics',
        'all_species_external_mapping': '/api/stoichdb/downloads/id-mapping/?kind=external',
        'species_preview': f'/api/stoichdb/downloads/id-mapping/?species_id={species_id}&kind=preview',
    }
    return data


def get_species_conflicts(species_id: str, limit: int = 100) -> dict[str, Any]:
    if _is_final_species(species_id) and species_id not in (_read_json(QC_PATH).get('per_species_by_id') or {}):
        return {'species_id': species_id, 'items': [], 'total': 0, 'runtime_source': 'final_whitelist_species_offset_csv'}
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT gene_id, transcript_id, protein_id, mapping_level, internal_mapping_status,
                   internal_mapping_confidence, external_mapping_status, external_mapping_evidence
            FROM id_mapping_chain
            WHERE species_id=? AND internal_mapping_status='conflict'
            LIMIT ?
            """,
            (species_id, max(1, min(int(limit or 100), 500))),
        ).fetchall()
    return {'species_id': species_id, 'items': [_row_dict(row) for row in rows], 'total': len(rows)}


def get_entity_mapping_chain(species_id: str, entity_key: str) -> dict[str, Any]:
    resolved = resolve_id(entity_key, species_id=species_id, limit=25)
    if resolved['matches']:
        primary = resolved['matches'][0]
    else:
        with _conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM id_mapping_chain
                WHERE species_id=? AND (gene_id=? OR transcript_id=? OR protein_id=?)
                ORDER BY CASE internal_mapping_confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
                LIMIT 1
                """,
                (species_id, entity_key, entity_key, entity_key),
            ).fetchone()
            primary = _chain_payload(row, matched_id=entity_key) if row else {}
    if not primary:
        return {'available': False, 'query': entity_key, 'matches': []}
    return {
        'available': True,
        'resolved_from': entity_key,
        'primary_match': primary,
        'id_chain': {
            'gene_id': primary.get('gene_id', ''),
            'transcript_id': primary.get('transcript_id', ''),
            'protein_id': primary.get('protein_id', ''),
        },
        'mapping_status': primary.get('mapping_status', ''),
        'mapping_confidence': primary.get('mapping_confidence', ''),
        'external_mapping_status': primary.get('external_mapping_status', ''),
        'external_mapping_confidence': primary.get('external_mapping_confidence', ''),
        'external_ids': primary.get('external_ids', {}),
        'external_links': primary.get('external_links', []),
        'conflict_warning': primary.get('conflict_warning', False),
        'download_url': f'/api/stoichdb/species/{species_id}/entities/{entity_key}/mapping/',
    }


def case2_id_mapping_payload() -> dict[str, Any]:
    payload = _read_json(CASE2_PATH, default={})
    if not payload:
        raise services.NotFoundError('Case 2 ID mapping payload has not been generated.')
    return payload


def manifest_payload() -> dict[str, Any]:
    final_manifest = _read_json(FINAL_MANIFEST_PATH, default={})
    final_offsets = _read_json(FINAL_OFFSETS_PATH, default={})
    final_online = _read_json(FINAL_ONLINE_MANIFEST_PATH, default={})
    standard_overlay = _read_json(STANDARD_OVERLAY_MANIFEST_PATH, default={})
    return {
        'manifest': _read_json(MANIFEST_PATH),
        'schema': _read_json(SCHEMA_PATH),
        'qc_summary': _read_json(QC_PATH),
        'final_whitelist': {
            'manifest': final_manifest,
            'online_external_manifest': final_online,
            'offset_index': {
                'schema_version': final_offsets.get('schema_version'),
                'runtime_seconds': final_offsets.get('runtime_seconds'),
                'groups': final_offsets.get('groups'),
                'species_count': len(final_offsets.get('species') or {}),
            },
            'runtime_mode': 'species-scoped byte-offset CSV lookup for full final-whitelist rows',
        },
        'standard_external_id_overlay': standard_overlay,
    }


def download_path(kind: str = 'external', species_id: str = '', division: str = '') -> Path:
    if division in FINAL_GROUPS:
        group_dir = FINAL_ROOT / division
        online_dir = FINAL_ONLINE_ROOT / division
        if kind == 'omics':
            return group_dir / f'{division}_omics_id_mapping_final_whitelist.csv'
        if kind == 'external':
            return group_dir / f'{division}_external_id_mapping_final_whitelist.csv'
        if kind == 'online_accession':
            return online_dir / f'{division}_uniprot_online_accession_map.csv'
        if kind == 'external_long':
            return online_dir / f'{division}_external_id_mapping_long_final_whitelist.csv'
        if kind == 'online_qc':
            return online_dir / f'{division}_online_external_id_mapping_species_qc.csv'
        if kind == 'species_standard':
            return online_dir / f'{division}_species_standard_ids.csv'
        if kind == 'online_summary':
            return online_dir / f'{division}_online_external_id_mapping_summary.json'
        if kind == 'standard_overlay_index':
            return STANDARD_OVERLAY_ROOT / division / f'{division}_standard_id_overlay_index.csv'
        if kind == 'standard_overlay_online_accession':
            return STANDARD_OVERLAY_ROOT / division / f'{division}_uniprot_online_accession_map.csv'
        if kind == 'qc':
            return group_dir / f'{division}_id_mapping_species_qc.csv'
        if kind == 'manifest':
            return group_dir / f'{division}_id_mapping_summary.json'
    if kind == 'final_manifest':
        return FINAL_MANIFEST_PATH
    if kind == 'final_offsets':
        return FINAL_OFFSETS_PATH
    if kind == 'final_online_manifest':
        return FINAL_ONLINE_MANIFEST_PATH
    if kind == 'final_online_report':
        return FINAL_ONLINE_ROOT / 'final_whitelist_online_external_id_mapping_result_report.md'
    if kind == 'standard_overlay_manifest':
        return STANDARD_OVERLAY_MANIFEST_PATH
    if kind == 'standard_overlay_report':
        return STANDARD_OVERLAY_ROOT / 'standard_external_id_overlay_result_report.md'
    if species_id and kind == 'preview':
        path = DATA_DIR / 'per_species' / f'{species_id}.id_mapping_preview.csv'
        if path.exists():
            return path
    if kind == 'omics':
        return FULL_OMICS_CSV
    if kind == 'manifest':
        return MANIFEST_PATH
    if kind == 'qc':
        return QC_PATH
    return FULL_EXTERNAL_CSV
