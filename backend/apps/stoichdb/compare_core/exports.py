from __future__ import annotations

import csv
import json
import os
import zipfile
from pathlib import Path

import numpy as np

from .contracts import CompareError, atomic_json, clean, file_sha, load_json, root
from .profiles import values

NAMES = {'coverage': 'field_coverage', 'rankings': 'feature_rankings', 'differences': 'pairwise_differences',
         'distances': 'pairwise_distances', 'contributions': 'distance_contributions', 'clusters': 'cluster_membership',
         'cross_omics': 'cross_omics_comparison'}


def run_dir(run):
    return root() / 'runs' / str(run.run_id)


def csv_table(path, rows):
    headers = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(clean(v), ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in clean(row).items()})


def publish(run, result, tables, catalog, profiles, checkpoint):
    folder = run_dir(run)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'tables').mkdir(exist_ok=True)
    result['run_id'] = str(run.run_id)
    result['tables'] = {}
    for kind, rows in tables.items():
        checkpoint()
        atomic_json(folder / 'tables' / f'{kind}.json', rows)
        filename = NAMES.get(kind, kind) + '.csv'
        csv_table(folder / filename, rows)
        result['tables'][kind] = {'total': len(rows), 'filename': filename}
    atomic_json(folder / 'request.json', run.request_json)
    sources = [{k: p[k] for k in ('species_id', 'omics', 'dataset_id', 'scope', 'method_version', 'semantic_hash', 'content_sha256',
        'signature', 'header_sha256', 'n_source', 'registered_rows', 'row_count_matches', 'duplicate_identity_n', 'missing_identity_n', 'artifact_path')} for p in profiles]
    atomic_json(folder / 'source_manifest.json', sources)
    from .contracts import digest
    run.source_manifest_hash = digest(sources)
    result['provenance']['source_manifest_hash'] = run.source_manifest_hash
    csv_table(folder / 'field_dictionary.csv', catalog['fields'])
    result['downloads'] = {'bundle': f'/api/stoichdb/compare/core/runs/{run.run_id}/download/'}
    (folder / 'methods.md').write_text('''# Strict Core comparison\n\nAll statistics use all applicable Core rows. No Full supplementation or legacy fingerprints.\nNumeric summaries retain source units; matrices use canonical units. Robust scaling uses the saved cohort.\nCompositions use closed mean profiles and Hellinger embedding. Distances are balanced shared-panel Euclidean distances.\nPCA centers the weighted embedding without re-scaling. Clustering is average linkage.\nGroup tests use species-level summaries, two-sided tie-corrected asymptotic Mann–Whitney U,\nCliff A-minus-B effect, deterministic species bootstrap and run-wide BH correction.\nInsufficient conditions produce explicit null/not_estimable states. No causal interpretation is provided.\nGraph exports contain displayed data; complete statistical tables are in this package.\n''', encoding='utf-8')
    manifest = {'run_id': str(run.run_id), 'result_version': result['result_version'], 'request': run.request_json,
        'source_failures': result.get('source_failures', []),
        'provenance': result['provenance'], 'field_accounting': result['field_accounting'], 'normalization': result['normalization_info'],
        'tables': result['tables'], 'panel_hash': result['panel_hash'], 'transform_hash': result['transform_hash'],
        'analysis_status': result['analysis_status'], 'missing_policy': run.request_json['missing_policy'],
        'weights': run.request_json['weights'], 'omitted': {k: v for k, v in result['analysis_status'].items() if v.get('status') == 'not_estimable'}}
    import importlib.metadata
    manifest['software_versions'] = {name: importlib.metadata.version(name) for name in ('Django', 'numpy', 'scipy', 'scikit-learn', 'pandas', 'pyarrow')}
    atomic_json(folder / 'result.json', result)
    atomic_json(folder / 'manifest.json', manifest)
    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix in ('.json', '.csv', '.md') and not p.name.endswith('.tmp'))
    checks = {p.name: file_sha(p) for p in paths}
    (folder / 'checksums.sha256').write_text(''.join(f'{h}  {name}\n' for name, h in checks.items()), encoding='utf-8')
    archive_path = folder / 'compare_result.zip'
    tmp = folder / 'compare_result.zip.tmp'
    with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths + [folder / 'checksums.sha256']:
            checkpoint()
            archive.write(path, path.name)
    os.replace(tmp, archive_path)
    return result, {'archive_sha256': file_sha(archive_path), 'files': checks}


def run_artifacts_valid(run):
    folder = run_dir(run)
    try:
        from types import SimpleNamespace
        from .profiles import artifact_valid
        sources = load_json(folder / 'source_manifest.json')
        return (all(artifact_valid(SimpleNamespace(artifact_path=p['artifact_path'])) for p in sources)
            and all(file_sha(folder / name) == h for name, h in run.summary_json['artifact_checks']['files'].items())
            and file_sha(folder / 'compare_result.zip') == run.summary_json['artifact_checks']['archive_sha256'])
    except (OSError, ValueError, KeyError):
        return False


def result(run):
    if run.status not in ('completed', 'partial'):
        raise CompareError('Results are not ready.', 'result_not_ready', 409)
    try:
        expected = run.summary_json.get('artifact_checks', {}).get('files', {}).get('result.json')
        if expected and file_sha(run_dir(run) / 'result.json') != expected:
            raise CompareError('Saved result checksum does not match.', 'artifact_unavailable', 409)
        return load_json(run_dir(run) / 'result.json')
    except (OSError, ValueError):
        raise CompareError('Saved result artifacts are unavailable.', 'artifact_unavailable', 409)


def table(run, kind, page=1, page_size=50, field='', query='', sort_by='', direction='asc'):
    meta = result(run)
    if kind not in meta['tables']:
        raise CompareError('Unknown result table.')
    try:
        page, page_size = int(page), int(page_size)
    except (ValueError, TypeError):
        raise CompareError('Invalid page parameters.')
    if page < 1 or not 1 <= page_size <= 200 or direction not in ('asc', 'desc'):
        raise CompareError('Page, page size or direction is out of range.')
    rows = load_json(run_dir(run) / 'tables' / f'{kind}.json')
    if field:
        rows = [r for r in rows if r.get('field_key') == field]
    if query:
        q = query.lower()
        rows = [r for r in rows if any(q in str(v).lower() for v in (r.get('field_key'), r.get('species_id'), r.get('family')))]
    if sort_by:
        allowed = set().union(*(r.keys() for r in rows)) if rows else set()
        if rows and sort_by not in allowed:
            raise CompareError('Unknown sort key.')
        present = [r for r in rows if r.get(sort_by) is not None]
        missing = [r for r in rows if r.get(sort_by) is None]
        present.sort(key=lambda r: (str(r.get('species_id', '')), str(r.get('field_key', ''))))
        def key(row):
            v = row[sort_by]
            return (0, float(v)) if isinstance(v, (int, float)) else (1, str(v))
        present.sort(key=key, reverse=direction == 'desc')
        rows = present + missing
    total = len(rows)
    return {'run_id': str(run.run_id), 'kind': kind, 'items': rows[(page - 1) * page_size:page * page_size],
            'total': total, 'page': page, 'page_size': page_size, 'has_next': page * page_size < total}


def distribution(run, field_key, species_ids):
    meta = result(run)
    allowed = set(run.request_json['species_ids'] + run.request_json['reference']['species_ids'])
    if not species_ids or not set(species_ids).issubset(allowed):
        raise CompareError('Distribution species must belong to this run.')
    records = load_json(run_dir(run) / 'tables' / 'profiles.json')
    selected = [r for r in records if r['field_key'] == field_key and r['species_id'] in species_ids]
    if not selected:
        raise CompareError('Field is not present in this run.', 'unknown_field', 404)
    if selected[0]['compare_role'] not in ('numeric', 'composition', 'binary_summary'):
        return {'field_key': field_key, 'status': 'categorical_or_metadata', 'rows': selected, 'points': []}
    sources = load_json(run_dir(run) / 'source_manifest.json')
    arrays = []
    for row in selected:
        source = next((p for p in sources if p['species_id'] == row['species_id'] and p['omics'] == row['omics']), None)
        arr = values(source, row['field']) * row.get('canonical_factor', 1.) if source else np.array([])
        arrays.append((row, arr))
    finite = [v for _, arr in arrays for v in ([float(arr[0]), float(arr[-1])] if len(arr) else [])]
    bins = np.linspace(min(finite), max(finite), 33) if finite and min(finite) < max(finite) else np.array([finite[0] - .5, finite[0] + .5]) if finite else np.array([0., 1.])
    output = []
    for row, arr in arrays:
        positions = np.unique(np.linspace(0, len(arr) - 1, min(1000, len(arr))).astype(int)) if len(arr) else []
        counts, _ = np.histogram(arr, bins=bins)
        output.append({'species_id': row['species_id'], 'n_valid': len(arr), 'display_n': len(positions),
            'ecdf': [[float(arr[i]), (int(i) + 1) / len(arr)] for i in positions], 'histogram': counts,
            'p25': row.get('p25') * row.get('canonical_factor', 1) if row.get('p25') is not None else None,
            'median': row.get('median') * row.get('canonical_factor', 1) if row.get('median') is not None else None,
            'p75': row.get('p75') * row.get('canonical_factor', 1) if row.get('p75') is not None else None,
            'unit': row['unit_canonical'], 'status': row['status'], 'sampling_policy': 'ecdf_display_only_even_order_statistics'})
    wasserstein = None
    if len(arrays) == 2 and all(len(arr) for _, arr in arrays):
        from scipy.stats import wasserstein_distance
        wasserstein = float(wasserstein_distance(arrays[0][1], arrays[1][1]))
    return clean({'field_key': field_key, 'unit': selected[0]['unit_canonical'], 'rows': output,
                  'bin_edges': bins, 'wasserstein': wasserstein, 'statistics_scope': 'all_applicable_core_rows'})
