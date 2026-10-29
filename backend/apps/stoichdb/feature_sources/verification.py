"""Read-only shadow comparison of one Core/Full CSV pair.

Passing this comparison alone does not authorize a production binding: byte
serialization, source versions, Parquet and all consumers still require checks.
"""
from __future__ import annotations

import csv
import hashlib
from itertools import zip_longest
from pathlib import Path
from typing import Any

from .projection import CoreRecipe, ProjectionError


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def compare_csv_pair(core_path: Path, full_path: Path, omics: str, *, fill_noncoding: str = 'zero') -> dict[str, Any]:
    core_path, full_path = Path(core_path), Path(full_path)
    primary = {'genome': 'gene_id', 'transcriptome': 'transcript_id', 'proteome': 'protein_id'}[omics]
    before = [(p.stat().st_size, p.stat().st_mtime_ns) for p in (core_path, full_path)]
    result: dict[str, Any] = {'omics': omics, 'core_path': str(core_path), 'full_path': str(full_path),
                              'rows_core': 0, 'rows_full': 0, 'cells_compared': 0,
                              'different_cells': 0, 'id_order_mismatches': 0, 'duplicate_ids': 0,
                              'empty_ids': 0, 'examples': [], 'binding_ready': False}
    ids_core: set[str] = set()
    ids_full: set[str] = set()
    with core_path.open('r', encoding='utf-8-sig', newline='') as core, full_path.open('r', encoding='utf-8-sig', newline='') as full:
        core_reader, full_reader = csv.DictReader(core), csv.DictReader(full)
        core_header, full_header = core_reader.fieldnames or [], full_reader.fieldnames or []
        recipe = CoreRecipe(omics, tuple(core_header), fill_noncoding)
        recipe.validate_full_header(full_header)
        if primary not in core_header or primary not in full_header:
            raise ProjectionError('primary ID missing')
        result['core_columns'], result['full_columns'] = len(core_header), len(full_header)
        for old, wide in zip_longest(core_reader, full_reader):
            for row, ids, count in ((old, ids_core, 'rows_core'), (wide, ids_full, 'rows_full')):
                if row is None:
                    continue
                if None in row or any(v is None for v in row.values()):
                    raise ProjectionError('malformed CSV row')
                result[count] += 1
                identifier = row[primary]
                if not identifier.strip():
                    result['empty_ids'] += 1
                if identifier in ids:
                    result['duplicate_ids'] += 1
                ids.add(identifier)
            if old is None or wide is None:
                continue
            if old[primary] != wide[primary]:
                result['id_order_mismatches'] += 1
                continue
            rebuilt = recipe.project(wide)
            for field in core_header:
                expected = str(rebuilt[field])
                result['cells_compared'] += 1
                if old[field] != expected:
                    result['different_cells'] += 1
                    if len(result['examples']) < 5:
                        result['examples'].append({'id': old[primary], 'field': field, 'core': old[field], 'reconstructed': expected})
    result['core_sha256'] = _sha256(core_path)
    result['full_sha256'] = _sha256(full_path)
    result['stable_stat'] = before == [(p.stat().st_size, p.stat().st_mtime_ns) for p in (core_path, full_path)]
    result['logical_match'] = (result['rows_core'] == result['rows_full'] and ids_core == ids_full and
        result['stable_stat'] and not any(result[key] for key in
            ('different_cells', 'id_order_mismatches', 'duplicate_ids', 'empty_ids')))
    return result

