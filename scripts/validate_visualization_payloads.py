from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Validate basic-visualization payload consistency.')
    parser.add_argument(
        '--registry-root',
        default='data/stoichdb_demo',
        help='Stage6 registry root that contains index.json and per-species payload folders.',
    )
    parser.add_argument(
        '--schema-root',
        default='backend/apps/stoichdb/schemas',
        help='Directory containing summary/analysis/cross_omics/rows JSON schema files.',
    )
    parser.add_argument(
        '--feature-display-schema',
        default='shared/schemas/stoich_feature_display_schema.json',
        help='Feature display schema used to identify core fields.',
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def numeric_series(rows: list[dict[str, Any]], field: str) -> pd.Series:
    return pd.to_numeric(pd.Series([row.get(field) for row in rows], dtype='object'), errors='coerce').dropna()


def infer_entity_key(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    first = rows[0] if isinstance(rows[0], dict) else {}
    for key in ['entity_id', 'gene_id', 'transcript_id', 'protein_id']:
        if key in first:
            return key
    return None


def validate_required_schema(payload: Any, schema: dict[str, Any], context: str, errors: list[str]) -> None:
    expected_type = schema.get('type')
    if expected_type == 'object' and not isinstance(payload, dict):
        errors.append(f'{context}: expected object payload')
        return
    if expected_type == 'array' and not isinstance(payload, list):
        errors.append(f'{context}: expected array payload')
        return
    if isinstance(payload, dict):
        for key in schema.get('required') or []:
            if key not in payload:
                errors.append(f'{context}: missing required key "{key}"')
        properties = schema.get('properties') or {}
        for key, child_schema in properties.items():
            if key in payload and isinstance(child_schema, dict):
                child_required = child_schema.get('required') or []
                if child_required and isinstance(payload.get(key), dict):
                    for child_key in child_required:
                        if child_key not in payload[key]:
                            errors.append(f'{context}.{key}: missing required key "{child_key}"')
    if isinstance(payload, list):
        item_schema = schema.get('items') or {}
        any_of = item_schema.get('anyOf') or []
        if any_of:
            for idx, item in enumerate(payload[:200]):
                if not isinstance(item, dict):
                    errors.append(f'{context}[{idx}]: expected row object')
                    continue
                if not any(all(req in item for req in option.get('required') or []) for option in any_of):
                    errors.append(f'{context}[{idx}]: row lacks any accepted entity identifier')


def schema_map(schema_root: Path) -> dict[str, dict[str, Any]]:
    schemas = {}
    for name in ['summary', 'analysis', 'cross_omics', 'rows']:
        path = schema_root / f'{name}.schema.json'
        schemas[name] = load_json(path) if path.exists() else {}
    return schemas


def core_fields_by_omics(feature_display_schema: Path) -> dict[str, list[str]]:
    if not feature_display_schema.exists():
        return {}
    payload = load_json(feature_display_schema)
    fields = {}
    for omics, items in (payload.get('omics') or {}).items():
        fields[omics] = [
            str(item.get('field'))
            for item in items
            if isinstance(item, dict) and item.get('field') and item.get('allow_in_basic', True)
        ]
    return fields


def validate_feature_contract(rows: list[dict[str, Any]], core_fields: list[str], context: str, errors: list[str]) -> None:
    if not rows or not core_fields:
        return
    available = set()
    for row in rows[:500]:
        if isinstance(row, dict):
            available.update(key for key, value in row.items() if value not in (None, ''))
    missing_core = [field for field in core_fields if field not in available]
    if missing_core:
        errors.append(f'{context}: missing core feature fields from sampled rows: {missing_core[:12]}')


def check_correlation_matrix(matrix: dict[str, dict[str, float]], errors: list[str], context: str) -> None:
    for key, row in matrix.items():
        if key not in row:
            continue
        diag = row.get(key)
        if diag is None:
            continue
        try:
            value = float(diag)
        except Exception:
            errors.append(f'{context}: correlation diagonal "{key}" is not numeric')
            continue
        if abs(value - 1.0) > 1e-3:
            errors.append(f'{context}: correlation diagonal "{key}" expected 1.0, got {value}')


def check_transcript_gc_display(rows: list[dict[str, Any]], context: str, errors: list[str]) -> None:
    pairs = pd.DataFrame({
        'gc_content': pd.to_numeric(pd.Series([row.get('gc_content') for row in rows], dtype='object'), errors='coerce'),
        'gc_percent_display': pd.to_numeric(pd.Series([row.get('gc_percent_display') for row in rows], dtype='object'), errors='coerce'),
    }).dropna()
    if pairs.empty:
        return
    if float(pairs['gc_content'].max()) > 1.5:
        return
    ratio = (pairs['gc_percent_display'] / pairs['gc_content'].replace(0, pd.NA)).dropna()
    if ratio.empty:
        return
    median_ratio = float(ratio.median())
    if abs(median_ratio - 100.0) > 20.0:
        errors.append(
            f'{context}: gc_percent_display appears inconsistent with gc_content fraction '
            f'(median ratio {median_ratio:.2f}, expected around 100).'
        )


def check_scatter_sampling(rows: list[dict[str, Any]], summary: dict[str, Any], context: str, errors: list[str]) -> None:
    scatter = summary.get('scatter') or {}
    if not isinstance(scatter, dict) or not scatter:
        return
    row_id_key = infer_entity_key(rows)
    if not row_id_key:
        return
    row_ids = [str(row.get(row_id_key)) for row in rows if row.get(row_id_key) is not None]
    if len(row_ids) < 120:
        return

    for key, points in scatter.items():
        if not isinstance(points, list) or len(points) < 80:
            continue
        point_id_key = infer_entity_key(points)
        if not point_id_key:
            continue
        point_ids = [str(point.get(point_id_key)) for point in points if point.get(point_id_key) is not None]
        probe = min(80, len(point_ids), len(row_ids))
        if probe < 40:
            continue
        if point_ids[:probe] == row_ids[:probe]:
            errors.append(
                f'{context}: scatter[{key}] first {probe} points match row order; '
                f'payload likely comes from sequential head() instead of sampled rows.'
            )


def validate_summary(rows: list[dict[str, Any]], summary: dict[str, Any], context: str, errors: list[str], omics: str) -> None:
    feature_cards = summary.get('feature_cards') or {}
    for field, card in feature_cards.items():
        series = numeric_series(rows, field)
        if series.empty:
            continue
        mean_expected = round(float(series.mean()), 4)
        p05_expected = round(float(series.quantile(0.05)), 4)
        p95_expected = round(float(series.quantile(0.95)), 4)
        mean_payload = float(card.get('mean', 0))
        p05_payload = float(card.get('p05', 0))
        p95_payload = float(card.get('p95', 0))
        if abs(mean_expected - mean_payload) > 0.05:
            errors.append(f'{context}: feature_cards[{field}].mean mismatch ({mean_payload} vs {mean_expected})')
        if abs(p05_expected - p05_payload) > 0.1:
            errors.append(f'{context}: feature_cards[{field}].p05 mismatch ({p05_payload} vs {p05_expected})')
        if abs(p95_expected - p95_payload) > 0.1:
            errors.append(f'{context}: feature_cards[{field}].p95 mismatch ({p95_payload} vs {p95_expected})')

    top_entities = summary.get('top_entities') or {}
    if 'top' not in top_entities or 'bottom' not in top_entities:
        errors.append(f'{context}: top_entities must include both "top" and "bottom" keys')

    corr = summary.get('correlation_matrix') or {}
    if isinstance(corr, dict) and corr:
        check_correlation_matrix(corr, errors, context)

    field_meta = summary.get('field_meta') or []
    if field_meta:
        declared_fields = {str(item.get('field')) for item in field_meta if isinstance(item, dict)}
        missing_meta_fields = [field for field in feature_cards.keys() if field not in declared_fields]
        if missing_meta_fields:
            errors.append(f'{context}: field_meta missing feature_cards fields: {missing_meta_fields[:6]}')

    check_scatter_sampling(rows, summary, context, errors)
    if omics == 'transcriptome':
        check_transcript_gc_display(rows, context, errors)


def validate_registry(registry_root: Path, schema_root: Path, feature_display_schema: Path) -> tuple[int, list[str]]:
    index_path = registry_root / 'index.json'
    if not index_path.exists():
        return 0, [f'Missing index.json under {registry_root}']
    idx = load_json(index_path)
    errors: list[str] = []
    checked = 0
    schemas = schema_map(schema_root)
    core_fields = core_fields_by_omics(feature_display_schema)
    validate_required_schema(idx, {'type': 'object', 'required': ['species']}, 'index.json', errors)

    for species in idx.get('species', []):
        species_id = species.get('species_id')
        if not species_id:
            continue
        cross_path = registry_root / species_id / 'cross_omics.json'
        if cross_path.exists():
            validate_required_schema(load_json(cross_path), schemas.get('cross_omics') or {}, f'{species_id}/cross_omics.json', errors)
        for omics in ['genome', 'transcriptome', 'proteome']:
            summary_path = registry_root / species_id / omics / 'summary.json'
            analysis_path = registry_root / species_id / omics / 'analysis.json'
            rows_path = registry_root / species_id / omics / 'rows.json'
            if not summary_path.exists() or not rows_path.exists():
                continue
            summary = load_json(summary_path)
            rows = load_json(rows_path)
            validate_required_schema(summary, schemas.get('summary') or {}, f'{species_id}/{omics}/summary.json', errors)
            validate_required_schema(rows, schemas.get('rows') or {}, f'{species_id}/{omics}/rows.json', errors)
            if analysis_path.exists():
                validate_required_schema(load_json(analysis_path), schemas.get('analysis') or {}, f'{species_id}/{omics}/analysis.json', errors)
            if not isinstance(rows, list):
                errors.append(f'{species_id}/{omics}: rows.json is not a list')
                continue
            validate_feature_contract(rows, core_fields.get(omics, []), f'{species_id}/{omics}', errors)
            validate_summary(rows, summary, f'{species_id}/{omics}', errors, omics)
            checked += 1

    return checked, errors


def main() -> None:
    args = parse_args()
    registry_root = Path(args.registry_root)
    checked, errors = validate_registry(registry_root, Path(args.schema_root), Path(args.feature_display_schema))
    print(f'Checked summary payloads: {checked}')
    if errors:
        print(f'Validation failed with {len(errors)} issue(s):')
        for msg in errors[:200]:
            print(f'- {msg}')
        raise SystemExit(1)
    print('Validation passed.')


if __name__ == '__main__':
    main()
