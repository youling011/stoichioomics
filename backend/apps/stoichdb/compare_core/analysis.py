from __future__ import annotations

import hashlib
from collections import defaultdict

import numpy as np
from scipy.cluster.hierarchy import fcluster, leaves_list, linkage
from scipy.spatial.distance import pdist, squareform
from scipy.stats import mannwhitneyu, spearmanr
from sklearn.metrics import silhouette_score
from statsmodels.stats.multitest import multipletests

from .contracts import VERSION, clean, digest


def cliff(a, b):
    delta = np.asarray(a)[:, None] - np.asarray(b)[None, :]
    return float(np.sign(delta).mean())


def compare_groups(a, b, field_key, bootstraps=2000):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if len(a) < 5 or len(b) < 5:
        return {'status': 'descriptive_only', 'reason': 'at_least_5_independent_species_per_group', 'p_value': None, 'cliffs_delta': None, 'ci_low': None, 'ci_high': None}
    seed = np.random.SeedSequence([42, int.from_bytes(hashlib.sha256(field_key.encode()).digest()[:8], 'little')])
    rng = np.random.default_rng(seed)
    draws_a = rng.choice(a, size=(bootstraps, len(a)))
    draws_b = rng.choice(b, size=(bootstraps, len(b)))
    draws = np.sign(draws_a[:, :, None] - draws_b[:, None, :]).mean(axis=(1, 2))
    ci = np.quantile(draws, [.025, .975])
    return {'status': 'ok', 'reason': None, 'cliffs_delta': cliff(a, b), 'ci_low': float(ci[0]), 'ci_high': float(ci[1]),
            'p_value': float(mannwhitneyu(a, b, alternative='two-sided', method='asymptotic', use_continuity=True).pvalue),
            'ci_target': 'cliffs_delta_A_minus_B', 'bootstrap_n': bootstraps, 'seed': 42,
            'test_method': 'two_sided_mann_whitney_asymptotic_tie_corrected_continuity'}


def scale_info(values):
    arr = np.asarray(values, dtype=float)
    center = float(np.median(arr))
    mad = float(np.median(np.abs(arr - center)))
    scale = 1.4826 * mad
    fallback = None
    if scale <= 0:
        scale = float(arr.std())
        fallback = 'population_std'
    return {'center': center, 'scale': scale, 'mad': mad, 'fallback': fallback, 'n_reference': len(arr)}


def weighted_embedding(blocks, omics):
    """An additive, shared Euclidean embedding, with equal omics/family/unit weights."""
    if not blocks:
        return np.empty((0, 0)), []
    families = defaultdict(lambda: defaultdict(list))
    for block in blocks:
        families[block['omics']][block['family']].append(block)
    columns, description = [], []
    offset = 0
    for o in omics:
        for family in sorted(families[o]):
            units = families[o][family]
            weight = 1 / len(omics) / len(families[o]) / len(units)
            for block in units:
                x = np.asarray(block['values'], dtype=float)
                if x.ndim == 1:
                    x = x[:, None]
                if block['kind'] == 'composition':
                    x = np.sqrt(x) / np.sqrt(2.)
                columns.append(x * np.sqrt(weight))
                description.append({k: v for k, v in block.items() if k != 'values'} | {
                    'weight': weight, 'start': offset, 'end': offset + x.shape[1]})
                offset += x.shape[1]
    return np.concatenate(columns, axis=1), description


def geometry(x, ids, blocks):
    if not x.size:
        return [], [], None
    distance = squareform(pdist(x))
    pairs, contributions = [], []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            squared = float(np.sum((x[i] - x[j]) ** 2))
            pairs.append({'source': ids[i], 'target': ids[j], 'distance': float(np.sqrt(squared)),
                          'n_dimensions': x.shape[1], 'n_blocks': len(blocks),
                          'status': 'zero_distance' if squared == 0 else 'ok'})
            for block in blocks:
                part = float(np.sum((x[i, block['start']:block['end']] - x[j, block['start']:block['end']]) ** 2))
                contributions.append({'source': ids[i], 'target': ids[j], 'block': block['key'], 'omics': block['omics'],
                                      'family': block['family'], 'squared_contribution': part,
                                      'share': part / squared if squared > 0 else None,
                                      'n_dimensions': block['end'] - block['start']})
    return pairs, contributions, distance


def ordination(x, ids, names, blocks):
    centered = x - x.mean(axis=0) if x.size else x
    rank = int(np.linalg.matrix_rank(centered)) if x.size else 0
    if len(ids) < 4 or rank < 2:
        return {'status': 'not_estimable', 'reason': 'requires_4_species_and_matrix_rank_2', 'rank': rank, 'points': []}, []
    u, singular, vt = np.linalg.svd(centered, full_matrices=False)
    variance = singular ** 2 / np.sum(singular ** 2)
    coords = u[:, :2] * singular[:2]
    points = [{'species_id': sid, 'display_name': names.get(sid, sid), 'entity_id': names.get(sid, sid),
               'x': float(coords[i, 0]), 'y': float(coords[i, 1])} for i, sid in enumerate(ids)]
    loadings = []
    for block in blocks:
        for column in range(block['start'], block['end']):
            component = column - block['start']
            label = block['fields'][component] if component < len(block['fields']) else block['key']
            loadings.append({'field_key': label, 'block': block['key'], 'omics': block['omics'],
                             'pc1': float(vt[0, column]), 'pc2': float(vt[1, column]),
                             'coordinate_basis': 'sqrt_composition' if block['kind'] == 'composition' else 'weighted_robust_z'})
    return {'status': 'ok', 'rank': rank, 'method': 'PCA_SVD_centered_weighted_common_embedding',
            'explained_variance_ratio': variance[:2], 'points': points, 'matrix_hash': digest(x)}, loadings


def analyze(request, catalog, profiles, species, checkpoint=lambda: None):
    targets = request['species_ids']
    references = request['reference']['species_ids']
    explicit = request['reference']['mode'] == 'explicit'
    ids = list(dict.fromkeys(targets + references)) if request['task'] == 'reference_profile' else targets[:]
    names = {s['species_id']: s['display_name'] for s in species}
    catalog_fields = [f for f in catalog['fields'] if f['omics'] in request['omics']]
    lookup = {sid: {} for sid in dict.fromkeys(targets + references)}
    by_dataset = {}
    for profile in profiles:
        by_dataset[(profile['species_id'], profile['omics'])] = profile
        lookup[profile['species_id']].update({r['field_key']: r for r in profile['fields']})
    tables = {kind: [] for kind in ('coverage', 'profiles', 'categories', 'rankings', 'differences', 'distances',
                                  'contributions', 'pca_loadings', 'clusters', 'group_comparison', 'cross_omics',
                                  'candidates', 'excluded_fields', 'composition_profiles', 'pca_coordinates')}
    tables['dataset_qc'], tables['weighted_densities'] = [], []
    unavailable = []
    for sid in lookup:
        for f in catalog_fields:
            row = lookup[sid].get(f['field_key'])
            if row is None:
                row = {**f, 'species_id': sid, 'status': 'source_unavailable', 'reason': 'source_unavailable',
                       'n_source': None, 'n_applicable': None, 'n_valid': None, 'mean': None, 'median': None}
                lookup[sid][f['field_key']] = row
            tables['profiles'].append(row)
            if row.get(request['summary_stat']) is not None:
                row['value_source'] = row[request['summary_stat']]
                row['value_canonical'] = row[request['summary_stat']] * row.get('canonical_factor', 1.)
            tables['coverage'].append({k: row.get(k) for k in ('species_id', 'field_key', 'omics', 'compare_role', 'family', 'status',
                'reason', 'n_source', 'n_applicable', 'n_valid', 'n_missing', 'n_structural_na', 'n_nonfinite', 'n_invalid', 'n_zero', 'missing_rate')})
    for profile in profiles:
        tables['dataset_qc'].append({k: profile.get(k) for k in ('species_id', 'omics', 'dataset_id', 'scope',
            'n_source', 'registered_rows', 'row_count_matches', 'duplicate_identity_n', 'conflicting_identity_n',
            'missing_identity_n', 'content_sha256', 'header_sha256', 'warnings')})
        for element, density in profile.get('length_weighted_densities', {}).items():
            tables['weighted_densities'].append({'species_id': profile['species_id'], 'omics': profile['omics'],
                'element': element, **density})
        tables['categories'].extend(profile['categories'])
        for block in profile['composition_blocks']:
            for i, key in enumerate(block['field_keys']):
                tables['composition_profiles'].append({'species_id': profile['species_id'], 'omics': profile['omics'],
                    'group': block['group'], 'field_key': key, 'mean_composition': block['values'][i] if block['values'] is not None else None,
                    'n_valid': block['n_valid'], 'n_applicable': block['n_applicable'], 'status': block['status'],
                    'n_invalid_composition': block['n_invalid_composition']})
    stat = request['summary_stat']
    requested = set(request['field_selection'].get('fields', [])) if request['field_selection']['mode'] == 'custom' else {f['field_key'] for f in catalog_fields}
    threshold = request['thresholds']
    def good(row):
        return row.get('status') == 'ok' and (row.get('n_valid') or 0) >= threshold['min_valid_rows'] and (row.get('n_valid') or 0) / max(row.get('n_applicable') or 0, 1) >= threshold['min_valid_fraction']
    def canonical(row):
        value = row.get(stat)
        return float(value) * row.get('canonical_factor', 1.) if value is not None else None
    normalization = {}
    scalar_values = {}
    blocks = []
    used = set()
    excluded = {}
    standardizable = ((explicit and len(references) >= 5) or (not explicit and len(targets) >= 3)) and request['normalization'] != 'raw'
    for f in catalog_fields:
        checkpoint()
        key = f['field_key']
        if key not in requested:
            excluded[key] = 'not_requested'
            continue
        if f['compare_role'] != 'numeric':
            if f['compare_role'] != 'composition':
                excluded[key] = 'metadata_or_quality_summary'
            continue
        vals = [(sid, canonical(lookup[sid][key])) for sid in targets if good(lookup[sid][key])]
        for rank, (sid, value) in enumerate(sorted(vals, key=lambda x: (-x[1], x[0])), 1):
            tables['rankings'].append({'field_key': key, 'omics': f['omics'], 'species_id': sid, 'display_name': names.get(sid, sid),
                'rank': rank, 'value': value, 'source_value': lookup[sid][key].get(stat), 'unit': f['unit_canonical'], 'summary_stat': stat})
        ref_values = [canonical(lookup[sid][key]) for sid in references if good(lookup[sid][key])]
        if ref_values:
            for sid, value in vals:
                percentile = 100 * (sum(v < value for v in ref_values) + .5 * sum(v == value for v in ref_values)) / len(ref_values)
                tables['candidates'].append({'species_id': sid, 'field_key': key, 'value': value, 'unit': f['unit_canonical'],
                    'percentile': percentile, 'n_reference': len(ref_values), 'includes_target': sid in references,
                    'status': 'ok' if len(ref_values) >= 5 else 'descriptive_small_reference',
                    'candidate': bool(len(ref_values) >= 5 and (percentile <= 5 or percentile >= 95))})
        if f['family'] == 'quality_numeric':
            excluded[key] = 'technical_quality_field'
            continue
        if not all(good(lookup[sid][key]) for sid in ids):
            excluded[key] = 'incomplete_common_panel'
            continue
        minimum_ref = 5 if explicit else 3
        if not standardizable or len(ref_values) < minimum_ref:
            excluded[key] = 'no_valid_reference_scale'
            continue
        info = scale_info(ref_values)
        info['constant_between_targets'] = len({v for _, v in vals}) <= 1
        normalization[key] = info
        if info['scale'] <= 0:
            excluded[key] = 'constant_reference'
            continue
        vector = [(canonical(lookup[sid][key]) - info['center']) / info['scale'] for sid in ids]
        scalar_values[key] = dict(zip(ids, vector))
        # Collapse a declared redundancy only if all source profiles verified row-aligned equality.
        alias = f.get('redundancy_group')
        existing = next((b for b in blocks if b.get('redundancy_group') == alias), None) if alias else None
        verified = bool(alias and all(alias in p.get('validated_redundancy', {}) for p in profiles if p['omics'] == f['omics']))
        if existing and verified and np.allclose(existing['values'], vector, rtol=1e-12, atol=1e-12):
            excluded[key] = 'validated_redundant_alias_of:' + existing['key']
            continue
        blocks.append({'key': key, 'omics': f['omics'], 'family': f['family'], 'kind': 'scalar', 'fields': [key],
                       'redundancy_group': alias if verified else None, 'values': vector})
        used.add(key)
    all_groups = defaultdict(list)
    for f in catalog_fields:
        if f['field_key'] in requested and f['compare_role'] in ('composition', 'binary_summary'):
            ranked = [(sid, canonical(lookup[sid][f['field_key']])) for sid in targets if good(lookup[sid][f['field_key']])]
            for rank, (sid, value) in enumerate(sorted(ranked, key=lambda item: (-item[1], item[0])), 1):
                tables['rankings'].append({'field_key': f['field_key'], 'omics': f['omics'], 'species_id': sid,
                    'display_name': names.get(sid, sid), 'rank': rank, 'value': value,
                    'source_value': lookup[sid][f['field_key']].get(stat), 'unit': f['unit_canonical'], 'summary_stat': stat})
    for f in catalog_fields:
        if f['compare_role'] == 'composition':
            all_groups[f['composition_group']].append(f)
    for group, fs in all_groups.items():
        group_keys = [f['field_key'] for f in fs]
        if not set(group_keys).issubset(requested):
            for key in set(group_keys) & requested:
                excluded[key] = 'incomplete_composition_selection'
            continue
        representatives = []
        for sid in ids:
            profile = by_dataset.get((sid, fs[0]['omics']))
            block = next((b for b in profile['composition_blocks'] if b['group'] == group), None) if profile else None
            if not block or block['status'] != 'ok' or block['n_valid'] < threshold['min_valid_rows'] or block['n_valid'] / max(block['n_applicable'], 1) < threshold['min_valid_fraction']:
                break
            representatives.append(block['values'])
        if len(representatives) != len(ids):
            for key in group_keys:
                excluded[key] = 'incomplete_common_composition_panel'
            continue
        blocks.append({'key': group, 'omics': fs[0]['omics'], 'family': group, 'kind': 'composition',
                       'fields': group_keys, 'values': representatives})
        used.update(group_keys)
    # Differences retain every requested analyzable scalar/composition field, not just distance features.
    if len(targets) == 2:
        left, right = targets
        for f in catalog_fields:
            key = f['field_key']
            if key not in requested or f['compare_role'] not in ('numeric', 'composition', 'binary_summary'):
                continue
            a, b = lookup[left][key], lookup[right][key]
            va, vb = canonical(a), canonical(b)
            valid = va is not None and vb is not None
            info = normalization.get(key)
            tables['differences'].append({'field_key': key, 'omics': f['omics'], 'family': f['family'], 'source': left, 'target': right,
                'value_a': va, 'value_b': vb, 'source_value_a': a.get(stat), 'source_value_b': b.get(stat),
                'signed_delta': va - vb if valid else None, 'abs_delta': abs(va - vb) if valid else None,
                'reference_scaled_delta': (va - vb) / info['scale'] if valid and info and info['scale'] else None,
                'n_valid_a': a.get('n_valid'), 'n_valid_b': b.get('n_valid'), 'unit': f['unit_canonical'],
                'ratio': va / vb if valid and va > 0 and vb > 0 and f['unit_canonical'] not in ('pH', 'dimensionless') else None,
                'status': 'ok' if valid else 'not_estimable'})
    # Target x all available numeric fields: plot windowing never changes analysis inputs.
    heat_fields = [f for f in catalog_fields if f['field_key'] in requested and f['compare_role'] in ('numeric', 'composition', 'binary_summary')]
    heat_raw, heat_scaled = [], []
    for j, sid in enumerate(targets):
        for i, f in enumerate(heat_fields):
            row = lookup[sid][f['field_key']]
            heat_raw.append([i, j, canonical(row)])
            heat_scaled.append([i, j, scalar_values.get(f['field_key'], {}).get(sid)])
    present_omics = [o for o in request['omics'] if any(b['omics'] == o for b in blocks)]
    complete_scope = set(present_omics) == set(request['omics'])
    x, description = weighted_embedding(blocks, present_omics) if blocks else (np.empty((len(ids), 0)), [])
    pairs, contributions, distance = geometry(x, ids, description) if complete_scope else ([], [], None)
    tables['distances'], tables['contributions'] = pairs, contributions
    ordination_result, loadings = ordination(x, ids, names, description) if complete_scope else ({'status': 'not_estimable', 'reason': 'required_omics_unavailable', 'points': []}, [])
    tables['pca_loadings'] = loadings
    tables['pca_coordinates'] = ordination_result['points']
    cluster_info = {'status': 'not_estimable', 'reason': 'requires_4_species_and_nonzero_separation'}
    cluster_order = ids[:]
    if distance is not None and len(ids) >= 4 and float(distance.max()) > 0:
        tree = linkage(squareform(distance, checks=False), method='average', optimal_ordering=True)
        cluster_order = [ids[i] for i in leaves_list(tree)]
        k = min(4, max(2, int(np.sqrt(len(ids)))))
        labels = fcluster(tree, k, criterion='maxclust')
        score = float(silhouette_score(x, labels)) if 1 < len(set(labels)) < len(ids) else None
        tables['clusters'] = [{'species_id': sid, 'display_name': names.get(sid, sid), 'cluster': int(labels[i])} for i, sid in enumerate(ids)]
        cluster_info = {'status': 'ok', 'method': 'average_linkage_shared_euclidean_embedding', 'k': k, 'silhouette': score,
                        'linkage': tree, 'order': cluster_order, 'note': 'Exploratory structure; k is a display cut, not a validated optimum.'}
    cross_layers = {}
    for omics in request['omics']:
        own = [b for b in blocks if b['omics'] == omics]
        if not own:
            cross_layers[omics] = {'status': 'not_estimable', 'pairs': []}
            continue
        own_x, own_desc = weighted_embedding(own, [omics])
        own_pairs, _, _ = geometry(own_x, ids, own_desc)
        cross_layers[omics] = {'status': 'ok', 'pairs': own_pairs, 'n_blocks': len(own)}
    for i, a in enumerate(request['omics']):
        for b in request['omics'][i + 1:]:
            map_a = {(p['source'], p['target']): p['distance'] for p in cross_layers[a]['pairs']}
            map_b = {(p['source'], p['target']): p['distance'] for p in cross_layers[b]['pairs']}
            shared = sorted(set(map_a) & set(map_b))
            va, vb = [map_a[k] for k in shared], [map_b[k] for k in shared]
            estimable = len(shared) >= 3 and np.std(va) > 0 and np.std(vb) > 0
            tables['cross_omics'].append({'omics_a': a, 'omics_b': b, 'n_pairs': len(shared),
                'spearman': float(spearmanr(va, vb).statistic) if estimable else None,
                'status': 'descriptive' if estimable else 'not_estimable', 'p_value': None,
                'reason': 'Shared pairs are dependent; no independent-pair significance test.'})
    if request['task'] == 'reference_profile' and distance is not None:
        for sid in targets:
            rows = sorted(((float(distance[ids.index(sid), ids.index(r)]), r) for r in references if r != sid), key=lambda item: (item[0], item[1]))
            for rank, (value, reference) in enumerate(rows, 1):
                tables['rankings'].append({'field_key': '__reference_distance__', 'species_id': sid, 'reference_species': reference,
                    'rank': rank, 'value': value, 'unit': 'weighted distance', 'panel_hash': digest(sorted(used))})
    if request['task'] == 'two_groups':
        a_ids, b_ids = request['groups']['A'], request['groups']['B']
        units = [str(s.get('taxonomy_id') or '') for s in species if s['species_id'] in targets]
        independent = len(units) == len(targets) and all(u not in ('', '0', 'unknown', 'None') for u in units) and len(set(units)) == len(units)
        tested = []
        for f in catalog_fields:
            if f['field_key'] not in requested or f['compare_role'] != 'numeric':
                continue
            checkpoint()
            key = f['field_key']
            va = [canonical(lookup[sid][key]) for sid in a_ids if good(lookup[sid][key])]
            vb = [canonical(lookup[sid][key]) for sid in b_ids if good(lookup[sid][key])]
            row = {'field_key': key, 'unit': f['unit_canonical'], 'n_A': len(va), 'n_B': len(vb),
                   'median_A': float(np.median(va)) if va else None, 'median_B': float(np.median(vb)) if vb else None,
                   'mean_A': float(np.mean(va)) if va else None, 'mean_B': float(np.mean(vb)) if vb else None,
                   'q_value': None, 'family_scope': 'all_testable_non_quality_numeric_fields'}
            if independent and f['family'] != 'quality_numeric':
                row.update(compare_groups(va, vb, key))
            else:
                row.update(status='descriptive_only', reason='technical_quality_field' if f['family'] == 'quality_numeric' else 'independent_taxonomy_units_unverified',
                           p_value=None, cliffs_delta=None, ci_low=None, ci_high=None)
            if row.get('p_value') is not None:
                tested.append(row)
            tables['group_comparison'].append(row)
        if tested:
            qs = multipletests([r['p_value'] for r in tested], method='fdr_bh')[1]
            for row, q in zip(tested, qs):
                row['q_value'], row['m_tested'] = float(q), len(tested)
    for key, reason in excluded.items():
        tables['excluded_fields'].append({'field_key': key, 'reason': reason})
    # Flat matrices are server-side export artifacts, never reconstructed from displayed rows.
    raw_matrix, scaled_matrix = [], []
    for sid in targets:
        raw = {'species_id': sid, 'display_name': names.get(sid, sid)}
        scaled = dict(raw)
        for f in heat_fields:
            raw[f['field_key']] = canonical(lookup[sid][f['field_key']])
            scaled[f['field_key']] = scalar_values.get(f['field_key'], {}).get(sid)
        raw_matrix.append(raw)
        scaled_matrix.append(scaled)
    valid_distance = distance is not None and len(ids) >= 2
    data = {'result_version': request.get('analysis_version', VERSION), 'request_snapshot': request,
            'species': species, 'targets': targets, 'analysis_species': ids,
            'provenance': {'method_version': VERSION, 'semantic_hash': catalog['semantic_hash'], 'scope': 'core',
                           'full_supplement_used': False, 'statistics_scope': 'all_applicable_core_rows'},
            'field_accounting': {'catalog_count_global': catalog['field_count'], 'selected_scope_field_count': len(catalog_fields),
                                 'covered_scope_field_count': len(catalog_fields), 'expected_dataset_field_records': len(lookup) * len(catalog_fields),
                                 'resolved_dataset_field_records': len(tables['profiles']), 'matrix_used': sorted(used),
                                 'matrix_excluded': tables['excluded_fields'], 'n_blocks': len(blocks), 'n_embedding_dimensions': x.shape[1]},
            'normalization_info': {'mode': 'fixed_reference_robust_z' if explicit else 'batch_relative_robust_z', 'fields': normalization,
                                   'reference_species_ids': references, 'reference_mode': request['reference']['mode']},
            'analysis_status': {'distance': {'status': 'ok' if valid_distance else 'not_estimable',
                'reason': None if valid_distance else ('required_omics_unavailable' if not complete_scope else 'insufficient_features_or_species'),
                'low_dimensional': len(blocks) < 4, 'kind': 'composition_only' if not any(b['kind'] == 'scalar' for b in blocks) else 'balanced_euclidean'},
                'pca': {k: v for k, v in ordination_result.items() if k != 'points'}, 'clustering': cluster_info},
            'plots': {'fingerprint': {'x_labels': [f['field_key'] for f in heat_fields], 'y_labels': [names.get(sid, sid) for sid in targets],
                                      'values': heat_scaled, 'raw_values': heat_raw, 'fields': heat_fields},
                      'distance': {'x_labels': [names.get(sid, sid) for sid in ids], 'y_labels': [names.get(sid, sid) for sid in ids],
                                   'values': [[i, j, float(distance[j, i])] for j in range(len(ids)) for i in range(len(ids))] if valid_distance else []},
                      'ordination': ordination_result},
            'cross_omics_layers': cross_layers, 'panel_hash': digest(sorted(used)), 'transform_hash': digest([normalization, description])}
    tables['scalar_matrix_raw'], tables['scalar_matrix_scaled'] = raw_matrix, scaled_matrix
    return clean(data), clean(tables)
