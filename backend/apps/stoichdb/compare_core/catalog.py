from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from django.conf import settings

from ..models import SchemaRegistry
from .contracts import CompareError, OMICS, digest, load_json


def semantics() -> dict:
    return load_json(Path(settings.BASE_DIR) / 'shared' / 'schemas' / 'compare_core_semantics_v1.json')


def catalog() -> dict:
    rules = semantics()
    fields = {}
    schema_rows = []
    for schema in SchemaRegistry.objects.filter(product_type='core', status='active').order_by('schema_id'):
        if schema.omics_type not in OMICS:
            continue
        schema_rows.append({'schema_id': schema.schema_id, 'omics': schema.omics_type, 'version': schema.version})
        for ordinal, column in enumerate(schema.columns_json or []):
            name = column if isinstance(column, str) else column.get('name') or column.get('field')
            if not name:
                continue
            key = f'{schema.omics_type}.{name}'
            item = fields.setdefault(key, {
                'field_key': key, 'field': name, 'omics': schema.omics_type, 'scope': 'core',
                'label': name.replace('_', ' '), 'schema_ids': [], 'ordinal': ordinal,
                'dtype': (column.get('type') or column.get('dtype') or column.get('inferred_type') or 'unknown') if isinstance(column, dict) else 'unknown',
                **rules['fields'].get(key, {'compare_role': 'review_required', 'family': 'unclassified', 'reason': 'Core field needs explicit semantic review.'}),
            })
            item['schema_ids'].append(schema.schema_id)
    result = list(fields.values())
    if not result:
        raise CompareError('No active Core schemas are registered.', 'no_core_catalog', 503)
    return {'registry_version': rules['version'], 'semantic_hash': digest(result),
            'schemas': schema_rows, 'fields': result, 'items': result,
            'counts': {o: sum(x['omics'] == o for x in result) for o in OMICS},
            'field_count': len(result), 'review_required': [x['field_key'] for x in result if x['compare_role'] == 'review_required']}


def unit_values(field: dict, value):
    if value is None:
        return None
    return value * field.get('canonical_factor', 1.0)


def applicable(field: dict, frame):
    import numpy as np
    import pandas as pd
    mask = np.ones(len(frame), dtype=bool)
    for key, op, expected in field.get('applicability_rule', []):
        if key not in frame:
            return np.zeros(len(frame), dtype=bool), 'applicability_unverified'
        numbers = pd.to_numeric(frame[key].replace({'true': '1', 'false': '0', 'True': '1', 'False': '0'}), errors='coerce').to_numpy(dtype=float)
        mask &= (numbers == expected) if op == 'eq' else (numbers > expected)
    return mask, None
