from __future__ import annotations

import io
import os
import shutil
import sqlite3
import time
import uuid
import zipfile
from collections import Counter
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from django.db import transaction
from django.utils import timezone

from .catalog import applicable
from .contracts import VERSION, Cancelled, CompareError, atomic_json, digest, file_sha, load_json, root
from .models import CompareCoreProfile
from .sources import hashed_text, resolve, signature

MISSING = {'', 'na', 'n/a', 'null', 'none'}


def artifact_valid(profile, strict=False):
    folder = Path(profile.artifact_path)
    try:
        checks = load_json(folder / 'checksums.json')
        for name, expected in checks.items():
            path = folder / name
            stat = path.stat()
            if stat.st_size != expected['size']:
                return False
            if strict or stat.st_mtime_ns != expected['mtime_ns'] or name == 'profile.json':
                if file_sha(path) != expected['sha256']:
                    return False
        return all((folder / name).is_file() for name in ('profile.json', 'values.npz', 'identities.sqlite3'))
    except (OSError, ValueError, KeyError):
        return False


def read_profile(profile, current_signature=None):
    data = load_json(Path(profile.artifact_path) / 'profile.json')
    if current_signature is not None:
        data['signature'] = current_signature
    return data


def values(profile, field):
    path = Path(profile['artifact_path']) / 'values.npz'
    with np.load(path, allow_pickle=False) as arrays:
        return arrays[field].copy() if field in arrays else np.array([], dtype=float)


def _claim(dataset, sig, semantic_hash):
    build_key = digest([dataset.dataset_id, sig, semantic_hash, VERSION])
    with transaction.atomic():
        item, _ = CompareCoreProfile.objects.get_or_create(build_key=build_key, defaults={
            'dataset': dataset, 'source_signature': digest(sig), 'semantic_hash': semantic_hash,
            'method_version': VERSION})
        item = CompareCoreProfile.objects.select_for_update().get(pk=item.pk)
        if item.status == 'completed' and artifact_valid(item):
            return item, False
        if item.status == 'building' and item.lease_until and item.lease_until > timezone.now():
            return item, None
        item.status = 'building'
        item.lease_token = uuid.uuid4().hex
        item.lease_until = timezone.now() + timedelta(minutes=5)
        item.error_message = ''
        item.save()
        return item, True


def get_profile(species_id, omics, catalog, checkpoint=lambda: None, force=False):
    source, dataset, header, sig = resolve(species_id, omics)
    while True:
        checkpoint()
        item, owned = _claim(dataset, sig, catalog['semantic_hash'])
        if owned is None:
            time.sleep(.25)
            continue
        if owned is False and not force:
            return read_profile(item, sig)
        if owned is False:
            CompareCoreProfile.objects.filter(pk=item.pk).update(status='stale')
            force = False
            continue
        break
    token = item.lease_token
    try:
        data, folder = build_profile(source, dataset, header, sig, catalog, checkpoint, item.pk, token)
        key = digest([dataset.dataset_id, data['content_sha256'], catalog['semantic_hash'], VERSION])
        with transaction.atomic():
            locked = CompareCoreProfile.objects.select_for_update().get(pk=item.pk)
            if locked.lease_token != token:
                raise CompareError('Profile lease changed during computation.', 'lease_lost', 409)
            existing = CompareCoreProfile.objects.filter(profile_key=key).exclude(pk=item.pk).first()
            if existing and existing.status == 'completed' and artifact_valid(existing):
                # A timestamp-only source change can lead to the same content.
                existing.build_key = locked.build_key
                locked.delete()
                existing.source_signature = digest(sig)
                existing.save(update_fields=['build_key', 'source_signature', 'updated_at'])
                return read_profile(existing, sig)
            if existing:
                existing.profile_key = None
                existing.status = 'stale'
                existing.save(update_fields=['profile_key', 'status', 'updated_at'])
            locked.profile_key = key
            locked.artifact_path = str(folder)
            locked.content_sha256 = data['content_sha256']
            locked.metadata_json = {'species_id': species_id, 'omics': omics, 'n_source': data['n_source'], 'signature': sig}
            locked.status = 'completed'
            locked.lease_until = None
            locked.save()
        return {**data, 'signature': sig}
    except Exception as exc:
        CompareCoreProfile.objects.filter(pk=item.pk, lease_token=token).update(
            status='failed', error_message=str(exc)[:4000], lease_until=None)
        raise


def build_profile(source, dataset, header, sig, catalog, checkpoint, profile_pk=None, token=''):
    fields = [f for f in catalog['fields'] if f['omics'] == source.omics]
    if any(f['compare_role'] == 'review_required' for f in fields):
        raise CompareError('Unreviewed Core fields must be assigned semantics before analysis.', 'review_required', 409)
    numeric = [f for f in fields if f['compare_role'] in ('numeric', 'composition', 'binary_summary')]
    temp = root() / 'building' / uuid.uuid4().hex
    temp.mkdir(parents=True, exist_ok=True)
    raw_path = temp / 'numeric.bin'
    stats = {f['field']: {'n_source': 0, 'n_applicable': 0, 'n_structural_na': 0, 'n_missing': 0,
                         'n_nonfinite': 0, 'n_invalid': 0, 'n_valid': 0, 'n_zero': 0} for f in fields}
    reasons = {}
    previews = {f['field']: [] for f in fields if f['compare_role'] == 'metadata'}
    categories = {f['field']: Counter() for f in fields if f['compare_role'] == 'category_summary'}
    groups = {}
    for f in numeric:
        if f['composition_group']:
            groups.setdefault(f['composition_group'], []).append(f)
    compositions = {g: {'n_valid': 0, 'n_applicable': 0, 'n_invalid_composition': 0,
                         'sum': np.zeros(len(fs)), 'max_closure_error': 0.0} for g, fs in groups.items()}
    positions = {f['field']: i for i, f in enumerate(numeric)}
    primary = {'genome': 'gene_id', 'transcriptome': 'transcript_id', 'proteome': 'protein_id'}[source.omics]
    identity_path = temp / 'identities.sqlite3'
    identity = sqlite3.connect(identity_path)
    mmap = None
    identity.execute('CREATE TABLE ids (id TEXT PRIMARY KEY, row_index INTEGER, content_hash TEXT, duplicates INTEGER DEFAULT 0, conflicts INTEGER DEFAULT 0)')
    identity.execute('CREATE TABLE rows (row_index INTEGER PRIMARY KEY, entity_id TEXT)')
    n = missing_ids = 0
    text, reader = hashed_text(source.path)
    checkpoint_at = time.monotonic()
    try:
        with text, raw_path.open('wb') as raw:
            for frame in pd.read_csv(text, dtype=str, keep_default_na=False, chunksize=4096):
                checkpoint()
                if time.monotonic() - checkpoint_at > 10 and profile_pk:
                    CompareCoreProfile.objects.filter(pk=profile_pk, lease_token=token).update(lease_until=timezone.now() + timedelta(minutes=5))
                    checkpoint_at = time.monotonic()
                count = len(frame)
                matrix = np.full((count, len(numeric)), np.nan, dtype=np.float64)
                for f in fields:
                    name = f['field']
                    row = stats[name]
                    row['n_source'] += count
                    if name not in frame:
                        row['n_applicable'] += count
                        row['n_missing'] += count
                        reasons[name] = 'missing_field'
                        continue
                    series = frame[name].astype(str).str.strip()
                    missing = series.str.lower().isin(MISSING).to_numpy()
                    if f['compare_role'] in ('metadata', 'category_summary'):
                        row['n_applicable'] += count
                        row['n_missing'] += int(missing.sum())
                        row['n_valid'] += int((~missing).sum())
                        if name in categories:
                            categories[name].update(series[~missing].value_counts().to_dict())
                        else:
                            previews[name] = list(dict.fromkeys(previews[name] + series[~missing].head(12).tolist()))[:12]
                        continue
                    mask, reason = applicable(f, frame)
                    if reason:
                        reasons[name] = reason
                        mask[:] = True  # retain raw distributions; block admission later
                    row['n_applicable'] += int(mask.sum())
                    row['n_structural_na'] += int((~mask).sum())
                    parse = series.replace({'True': '1', 'False': '0', 'true': '1', 'false': '0'}) if f['compare_role'] == 'binary_summary' else series
                    numbers = pd.to_numeric(parse, errors='coerce').to_numpy(dtype=float)
                    nonfinite = series.str.lower().isin({'nan', '+nan', '-nan', 'inf', '+inf', '-inf', 'infinity', '-infinity'}).to_numpy()
                    bad = ~np.isfinite(numbers) & ~missing & ~nonfinite
                    lo, hi = f.get('bounded_min'), f.get('bounded_max')
                    if lo is not None:
                        bad |= np.isfinite(numbers) & (numbers < lo)
                    if hi is not None:
                        bad |= np.isfinite(numbers) & (numbers > hi)
                    if f['compare_role'] == 'binary_summary':
                        bad |= np.isfinite(numbers) & ~np.isin(numbers, [0., 1.])
                    valid = mask & ~missing & ~nonfinite & ~bad & np.isfinite(numbers)
                    row['n_missing'] += int((mask & missing).sum())
                    row['n_nonfinite'] += int((mask & nonfinite).sum())
                    row['n_invalid'] += int((mask & bad & ~missing & ~nonfinite).sum())
                    row['n_valid'] += int(valid.sum())
                    row['n_zero'] += int((valid & (numbers == 0)).sum())
                    matrix[valid, positions[name]] = numbers[valid]
                for group, fs in groups.items():
                    comp = compositions[group]
                    block = matrix[:, [positions[f['field']] for f in fs]] * np.array([f['canonical_factor'] for f in fs])
                    mask, _ = applicable(fs[0], frame)
                    comp['n_applicable'] += int(mask.sum())
                    totals = block.sum(axis=1)
                    complete = np.isfinite(block).all(axis=1) & (block >= 0).all(axis=1) & (totals > 0)
                    errors = np.abs(totals - 1)
                    valid = complete & (errors <= 1e-4)
                    comp['n_valid'] += int(valid.sum())
                    comp['n_invalid_composition'] += int((mask & ~valid).sum())
                    if valid.any():
                        comp['sum'] += (block[valid] / totals[valid, None]).sum(axis=0)
                        comp['max_closure_error'] = max(comp['max_closure_error'], float(errors[valid].max()))
                matrix.tofile(raw)
                ids = frame[primary].astype(str).tolist()
                identity.executemany('INSERT INTO rows VALUES (?,?)', ((n + i, x) for i, x in enumerate(ids)))
                rows = frame.fillna('').to_numpy()
                for i, entity_id in enumerate(ids):
                    if not entity_id.strip():
                        missing_ids += 1
                        continue
                    identity.execute('''INSERT INTO ids (id,row_index,content_hash) VALUES (?,?,?)
                        ON CONFLICT(id) DO UPDATE SET duplicates=duplicates+1,
                        conflicts=conflicts+CASE WHEN content_hash<>excluded.content_hash THEN 1 ELSE 0 END''',
                        (entity_id, n + i, digest(rows[i].tolist())))
                identity.commit()
                n += count
        content_hash = reader.hasher.hexdigest()
        if signature(source.path) != sig:
            raise CompareError('Core source changed during scanning; retry with a new snapshot.', 'source_changed', 409)
        duplicate_n, conflict_n = identity.execute('SELECT coalesce(sum(duplicates),0),coalesce(sum(conflicts),0) FROM ids').fetchone()
        data = {'species_id': source.species_id, 'omics': source.omics, 'dataset_id': dataset.dataset_id,
                'scope': 'core', 'method_version': VERSION, 'semantic_hash': catalog['semantic_hash'],
                'content_sha256': content_hash, 'signature': sig, 'header_sha256': digest(header),
                'registered_rows': dataset.row_count_core, 'n_source': n, 'row_count_matches': n == dataset.row_count_core,
                'full_supplement_used': False, 'statistics_scope': 'all_applicable_core_rows',
                'duplicate_identity_n': duplicate_n, 'conflicting_identity_n': conflict_n, 'missing_identity_n': missing_ids,
                'fields': [], 'categories': [], 'composition_blocks': [], 'warnings': list(source.warnings)}
        mmap = np.memmap(raw_path, mode='r', dtype=np.float64, shape=(n, len(numeric))) if n else None
        with zipfile.ZipFile(temp / 'values.npz', 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            for f in fields:
                checkpoint()
                name = f['field']
                record = {**f, **stats[name], 'species_id': source.species_id, 'dataset_id': dataset.dataset_id,
                          'status': reasons.get(name, 'ok'), 'reason': reasons.get(name), 'source_unit': f['unit_source']}
                record['missing_rate'] = record['n_missing'] / record['n_applicable'] if record['n_applicable'] else None
                if name in positions:
                    arr = np.sort(np.asarray(mmap[:, positions[name]])[np.isfinite(mmap[:, positions[name]])]) if n else np.array([], dtype=float)
                    with archive.open(name + '.npy', 'w') as handle:
                        np.lib.format.write_array(handle, arr, allow_pickle=False)
                    q = np.quantile(arr, [.1, .25, .5, .75, .9], method='linear') if len(arr) else [None] * 5
                    record.update(mean=float(arr.mean()) if len(arr) else None, population_std=float(arr.std()) if len(arr) else None,
                                  min=float(arr[0]) if len(arr) else None, max=float(arr[-1]) if len(arr) else None,
                                  p10=q[0], p25=q[1], median=q[2], p75=q[3], p90=q[4],
                                  zero_rate=record['n_zero'] / len(arr) if len(arr) else None,
                                  is_constant_within_species=bool(len(arr) and arr[0] == arr[-1]))
                    if not len(arr) and record['status'] == 'ok':
                        record['status'] = record['reason'] = 'no_valid_values'
                    if f['compare_role'] == 'binary_summary':
                        record.update(true_count=int((arr == 1).sum()), false_count=int((arr == 0).sum()), true_rate=float(arr.mean()) if len(arr) else None)
                elif name in categories:
                    for value, count in sorted(categories[name].items()):
                        data['categories'].append({'species_id': source.species_id, 'field_key': f['field_key'], 'category': value,
                                                   'count': count, 'n_valid': record['n_valid'], 'fraction': count / record['n_valid']})
                else:
                    record['preview'] = previews.get(name, [])
                data['fields'].append(record)
        if mmap is not None:
            # Verify proposed formula aliases on row-aligned, canonical values, not just means.
            verified = {}
            aliases = {}
            for f in numeric:
                if f.get('redundancy_group'):
                    aliases.setdefault(f['redundancy_group'], []).append(f)
            for alias, members in aliases.items():
                if len(members) < 2:
                    continue
                base = mmap[:, positions[members[0]['field']]] * members[0]['canonical_factor']
                if all(np.array_equal(np.isfinite(base), np.isfinite(mmap[:, positions[f['field']]])) and
                       np.allclose(base, mmap[:, positions[f['field']]] * f['canonical_factor'], equal_nan=True, rtol=1e-12, atol=1e-12)
                       for f in members[1:]):
                    verified[alias] = [f['field_key'] for f in members]
            data['validated_redundancy'] = verified
            mmap._mmap.close()
            del mmap
            mmap = None
        raw_path.unlink(missing_ok=True)
        for group, fs in groups.items():
            comp = compositions[group]
            representative = comp.pop('sum') / comp['n_valid'] if comp['n_valid'] else None
            data['composition_blocks'].append({'group': group, 'omics': source.omics, 'species_id': source.species_id,
                'field_keys': [f['field_key'] for f in fs], **comp, 'values': representative,
                'status': 'ok' if representative is not None else 'not_estimable'})
        # Explicit density weighting is only emitted when its numerator and denominator exist in Core.
        weighted = {}
        if source.omics in ('transcriptome', 'proteome'):
            length = 'length_nt_acgu' if source.omics == 'transcriptome' else 'length_aa'
            field_map = {f['field']: f for f in data['fields']}
            denominator = field_map.get(length, {})
            for element in ('C', 'N', 'P', 'S'):
                numerator = field_map.get(element + '_atoms', {})
                if numerator.get('mean') is not None and denominator.get('mean') and numerator['n_valid'] == denominator['n_valid'] == n:
                    weighted[element] = {'value': numerator['mean'] / denominator['mean'], 'formula': f'sum({element}_atoms)/sum({length})', 'n': n}
        data['length_weighted_densities'] = weighted
        identity.close()
        key = digest([dataset.dataset_id, content_hash, catalog['semantic_hash'], VERSION])
        destination = root() / 'profiles' / digest(dataset.dataset_id)[:20] / key
        data['artifact_path'] = str(destination)
        atomic_json(temp / 'profile.json', data)
        checks = {}
        for name in ('profile.json', 'values.npz', 'identities.sqlite3'):
            path = temp / name
            checks[name] = {'sha256': file_sha(path), 'size': path.stat().st_size, 'mtime_ns': path.stat().st_mtime_ns}
        atomic_json(temp / 'checksums.json', checks)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            existing_ok = False
            try:
                existing_checks = load_json(destination / 'checksums.json')
                existing_ok = all(file_sha(destination / name) == entry['sha256'] for name, entry in existing_checks.items())
            except (OSError, ValueError, KeyError):
                pass
            if existing_ok:
                shutil.rmtree(temp)
            else:
                os.replace(destination, destination.with_name(destination.name + '.stale-' + uuid.uuid4().hex))
                os.replace(temp, destination)
        else:
            os.replace(temp, destination)
        return load_json(destination / 'profile.json'), destination
    finally:
        if mmap is not None:
            mmap._mmap.close()
        try:
            identity.close()
        except Exception:
            pass
        if temp.exists():
            # Only this freshly generated UUID building directory is removed.
            if not temp.resolve().is_relative_to((root() / 'building').resolve()):
                raise RuntimeError('Refusing to remove an unrelated directory')
            shutil.rmtree(temp)
