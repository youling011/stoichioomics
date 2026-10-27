from __future__ import annotations

import os
import subprocess
import sys
from datetime import timedelta
from backend.apps.common.host_paths import Path

from django.conf import settings
from django.db import transaction, connection
from django.utils import timezone

from ..models import OmicsDataset, Species
from .catalog import catalog
from .contracts import ACTIVE, OMICS, VERSION, ANALYSIS_VERSION, CompareError, digest, load_json, root, unique_ids
from .models import CompareRun
from .profiles import artifact_valid
from .sources import resolve, signature


def normalize(payload):
    if not isinstance(payload, dict):
        raise CompareError('Request must be a JSON object.')
    if payload.get('scope', 'core') != 'core':
        raise CompareError('Only Core sources are allowed.', 'core_only')
    cat = catalog()
    if cat['review_required']:
        raise CompareError('Core fields require semantic review.', 'review_required', 409)
    task = payload.get('task', 'multi_species')
    if task not in ('species_profile', 'pairwise', 'multi_species', 'reference_profile', 'two_groups'):
        raise CompareError('Unknown comparison task.')
    groups = payload.get('groups') or {}
    if not isinstance(groups, dict):
        raise CompareError('groups must be an object.')
    ids = unique_ids(payload.get('species_ids', []))
    if task == 'two_groups':
        groups = {g: unique_ids(groups.get(g, [])) for g in ('A', 'B')}
        if not groups['A'] or not groups['B'] or set(groups['A']) & set(groups['B']):
            raise CompareError('Groups must be nonempty and disjoint.')
        combined = groups['A'] + groups['B']
        if ids and set(ids) != set(combined):
            raise CompareError('species_ids must match the union of both groups.')
        ids = combined
    limits = {'species_profile': (1, 1), 'pairwise': (2, 2), 'multi_species': (3, 24), 'reference_profile': (1, 24), 'two_groups': (2, 24)}
    lo, hi = limits[task]
    if not lo <= len(ids) <= hi:
        raise CompareError(f'{task} requires {lo}–{hi} unique target species.')
    omics = payload.get('omics', list(OMICS))
    if not isinstance(omics, list) or not omics or any(o not in OMICS for o in omics):
        raise CompareError('Select one or more valid omics layers.')
    omics = [o for o in OMICS if o in omics]
    reference = payload.get('reference') or {'mode': 'selected'}
    if not isinstance(reference, dict):
        raise CompareError('reference must be an object.')
    if reference.get('mode', 'selected') not in ('selected', 'explicit'):
        raise CompareError('Unknown reference mode.')
    if task == 'reference_profile' and reference.get('mode') != 'explicit':
        raise CompareError('Reference profile requires an explicit reference cohort.')
    if reference.get('mode') == 'explicit':
        refs = unique_ids(reference.get('species_ids', []))
        if reference.get('exclude_targets', True):
            refs = [sid for sid in refs if sid not in ids]
        if not refs or len(refs) > 96:
            raise CompareError('Explicit reference must contain 1–96 species after excluding targets.', 'empty_reference')
        reference = {'mode': 'explicit', 'species_ids': refs, 'exclude_targets': reference.get('exclude_targets', True)}
    else:
        reference = {'mode': 'selected', 'species_ids': ids, 'exclude_targets': False}
    union = list(dict.fromkeys(ids + reference['species_ids']))
    found = set(Species.objects.filter(species_id__in=union).values_list('species_id', flat=True))
    if set(union) != found:
        raise CompareError('Unknown species: ' + ', '.join(sorted(set(union) - found)), 'unknown_species', 404)
    selection = payload.get('field_selection') or {'mode': 'all_core'}
    if not isinstance(selection, dict):
        raise CompareError('field_selection must be an object.')
    if selection.get('mode') not in ('all_core', 'custom'):
        raise CompareError('Unknown field selection mode.')
    allowed = {f['field_key'] for f in cat['fields'] if f['omics'] in omics}
    if selection['mode'] == 'custom':
        chosen = selection.get('fields', [])
        if not isinstance(chosen, list) or not chosen or any(f not in allowed for f in chosen):
            raise CompareError('Custom fields must be registered Core fields in selected omics.')
        selection = {'mode': 'custom', 'fields': sorted(set(chosen))}
    else:
        selection = {'mode': 'all_core'}
    thresholds = payload.get('thresholds') or {}
    if not isinstance(thresholds, dict):
        raise CompareError('thresholds must be an object.')
    try:
        valid_rows = int(thresholds.get('min_valid_rows', 10))
        valid_fraction = float(thresholds.get('min_valid_fraction', .8))
    except (ValueError, TypeError):
        raise CompareError('Invalid coverage thresholds.')
    if not 1 <= valid_rows <= 10000000 or not 0 < valid_fraction <= 1:
        raise CompareError('Coverage thresholds are out of range.')
    stat = payload.get('summary_stat', 'median')
    norm = payload.get('normalization', 'auto')
    if stat not in ('median', 'mean') or norm not in ('auto', 'robust_zscore', 'raw'):
        raise CompareError('Unsupported summary statistic or normalization.')
    for key, expected in [('distance', 'balanced_euclidean'), ('composition_transform', 'hellinger'), ('missing_policy', 'common_panel_no_imputation')]:
        if payload.get(key, expected) != expected:
            raise CompareError(f'Unsupported {key}; use {expected}.')
    if payload.get('weights', {'omics': 'equal', 'families': 'equal'}) != {'omics': 'equal', 'families': 'equal'}:
        raise CompareError('Version 1 uses equal omics and family weights.')
    return {'api_version': VERSION, 'task': task, 'species_ids': ids, 'groups': groups if task == 'two_groups' else {},
            'omics': omics, 'scope': 'core', 'field_selection': selection, 'summary_stat': stat, 'reference': reference,
            'normalization': norm, 'distance': 'balanced_euclidean', 'composition_transform': 'hellinger',
            'missing_policy': 'common_panel_no_imputation', 'weights': {'omics': 'equal', 'families': 'equal'},
            'thresholds': {'min_valid_rows': valid_rows, 'min_valid_fraction': valid_fraction},
            'seed': 42, 'semantic_hash': cat['semantic_hash'], 'method_version': VERSION, 'analysis_version': ANALYSIS_VERSION}


def source_probe(request):
    """Bulk registration lookup + stat only; parsing/hashing belongs to the worker."""
    ids = list(dict.fromkeys(request['species_ids'] + request['reference']['species_ids']))
    registered = {(ds.species.species_id, ds.omics_type): ds for ds in
        OmicsDataset.objects.select_related('species').filter(species__species_id__in=ids, omics_type__in=request['omics'])}
    rows = []
    for sid in ids:
        for omics in request['omics']:
            try:
                ds = registered.get((sid, omics))
                if ds and ds.core_csv_path and Path(ds.core_csv_path).is_file():
                    sig = signature(Path(ds.core_csv_path))
                else:
                    source, ds, header, sig = resolve(sid, omics)
                rows.append({'species_id': sid, 'omics': omics, 'dataset_id': ds.dataset_id, 'signature': sig,
                             'probe_version': 'core_stat_v1'})
            except (OSError, CompareError) as exc:
                rows.append({'species_id': sid, 'omics': omics, 'error': getattr(exc, 'code', 'source_unavailable')})
    return rows


def dispatch(run):
    if not getattr(settings, 'COMPARE_CORE_AUTOSTART', True):
        return
    folder = root() / 'runs' / str(run.run_id)
    folder.mkdir(parents=True, exist_ok=True)
    # The child processes one durable job, closes its connections and exits. No daemon thread.
    if CompareRun.objects.filter(status__in=('profiling', 'analyzing', 'exporting'), lease_until__gt=timezone.now()).exists():
        return  # The short-lived queue drainer will pick up this queued job.
    command = [sys.executable, '-B', str(Path(settings.BASE_DIR) / 'manage.py'), 'run_compare_worker', '--drain']
    with (folder / 'worker.log').open('ab') as log:
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        child = subprocess.Popen(command, cwd=str(settings.BASE_DIR), stdout=log, stderr=log, stdin=subprocess.DEVNULL, **options)
    CompareRun.objects.filter(pk=run.pk).update(worker_pid=child.pid)


def create(payload):
    # Recover abandoned leases on submission after a service restart, then
    # serialize only the short lookup/create section for identical requests.
    from .worker import recover_stale
    recover_stale()
    request = normalize(payload)
    key = digest(request)
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [int(key[:15], 16)])
        run, created = _create(request)
        if run.status == 'queued':
            transaction.on_commit(lambda: dispatch(run))
    return run, created


def _create(request):
    canonical = {**request, 'species_ids': request['species_ids'],
                 'reference': {**request['reference'], 'species_ids': sorted(request['reference']['species_ids'])},
                 'groups': {k: sorted(v) for k, v in request['groups'].items()}}
    key = digest(canonical)
    probe = source_probe(request)
    probe_hash = digest(probe)
    prior = CompareRun.objects.filter(request_hash=key).order_by('-created_at').first()
    if prior and prior.status in ACTIVE and prior.summary_json.get('source_probe_hash') == probe_hash:
        return prior, False
    if prior and prior.status == 'completed' and prior.summary_json.get('source_probe_hash') == probe_hash:
        from .exports import run_artifacts_valid
        if run_artifacts_valid(prior):
            return prior, False
    run = CompareRun.objects.create(request_json=request, request_hash=key, retry_of=prior,
                                   summary_json={'source_probe_hash': probe_hash, 'source_probe': probe,
                                                 'unique_species': len(set(request['species_ids'] + request['reference']['species_ids']))})
    return run, True


def status(run):
    return {'run_id': str(run.run_id), 'status': run.status, 'phase': run.phase, 'progress': run.progress,
            'request_snapshot': run.request_json, 'summary': {k: v for k, v in run.summary_json.items() if k != 'source_probe'},
            'error': run.error_message or None, 'attempts': run.attempts,
            'created_at': run.created_at.isoformat(), 'heartbeat': run.heartbeat.isoformat() if run.heartbeat else None,
            'finished_at': run.finished_at.isoformat() if run.finished_at else None}


def cancel(run):
    with transaction.atomic():
        run = CompareRun.objects.select_for_update().get(pk=run.pk)
        if run.status == 'cancelled':
            return run
        if run.status not in ACTIVE:
            raise CompareError('A terminal run cannot be cancelled.', 'terminal_run', 409)
        run.cancel_requested = True
        if run.status == 'queued':
            run.status = 'cancelled'
            run.finished_at = timezone.now()
        else:
            run.status = 'cancel_requested'
        run.save()
    return run


def resume(run):
    if run.status not in ('failed', 'interrupted'):
        raise CompareError('Only failed or interrupted runs can be resumed.', 'not_resumable', 409)
    if run.lease_until and run.lease_until > timezone.now():
        raise CompareError('An active worker still owns the run.', 'worker_active', 409)
    run.status = 'queued'
    run.cancel_requested = False
    run.error_message = ''
    run.finished_at = None
    run.save()
    dispatch(run)
    return run
