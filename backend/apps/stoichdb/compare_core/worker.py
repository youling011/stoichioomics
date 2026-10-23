from __future__ import annotations

import os
import time
import traceback
import uuid
from datetime import timedelta

from django.db import connection, connections, transaction
from django.utils import timezone

from ..models import Species
from .analysis import analyze
from .catalog import catalog
from .contracts import ACTIVE, Cancelled, CompareError, atomic_json, digest, root
from .exports import publish
from .models import CompareRun
from .profiles import get_profile


def recover_stale():
    expired = CompareRun.objects.filter(status__in=ACTIVE, lease_until__lt=timezone.now()).exclude(status='queued')
    for run in expired:
        previous_token = run.lease_token
        if run.cancel_requested:
            run.status = 'cancelled'
        elif len(run.attempts) < 2:
            run.status = 'queued'
        else:
            run.status = 'interrupted'
        run.error_message = 'The previous worker lease expired; verified profiles can be reused.'
        run.lease_until = None
        run.lease_token = ''
        CompareRun.objects.filter(pk=run.pk, lease_token=previous_token, lease_until__lt=timezone.now()).update(
            status=run.status, error_message=run.error_message, lease_until=None, lease_token='')


def process_one(run_id=None):
    recover_stale()
    with transaction.atomic():
        candidates = CompareRun.objects.select_for_update(skip_locked=True).filter(status='queued')
        if run_id:
            candidates = candidates.filter(pk=run_id)
        run = candidates.order_by('created_at').first()
        if not run:
            return False
        token = uuid.uuid4().hex
        run.status = run.phase = 'profiling'
        run.progress = 1
        run.started_at = timezone.now()
        run.heartbeat = timezone.now()
        run.lease_until = timezone.now() + timedelta(minutes=5)
        run.lease_token = token
        run.worker_pid = os.getpid()
        run.attempts = [*run.attempts, {'attempt': len(run.attempts) + 1, 'started_at': timezone.now().isoformat(), 'pid': os.getpid(), 'lease_token': token}]
        run.save()
    folder = root() / 'runs' / str(run.run_id)
    folder.mkdir(parents=True, exist_ok=True)
    atomic_json(folder / 'request.json', run.request_json)
    last_tick = [0.]
    def checkpoint(force=False):
        now = time.monotonic()
        if not force and now - last_tick[0] < 1:
            return
        state = CompareRun.objects.values('cancel_requested', 'lease_token').get(pk=run.pk)
        if state['cancel_requested']:
            raise Cancelled()
        if state['lease_token'] != token:
            raise CompareError('Worker lease was replaced.', 'lease_lost', 409)
        CompareRun.objects.filter(pk=run.pk, lease_token=token).update(heartbeat=timezone.now(), lease_until=timezone.now() + timedelta(minutes=5))
        last_tick[0] = now
    def progress(phase, value):
        checkpoint(True)
        CompareRun.objects.filter(pk=run.pk, lease_token=token).update(status=phase, phase=phase, progress=value)
    retry = False
    try:
        cat = catalog()
        if cat['semantic_hash'] != run.request_json['semantic_hash']:
            raise CompareError('Core semantics changed since this request. Create a new run.', 'semantics_changed', 409)
        profiles, failures = [], []
        request = run.request_json
        tasks = [(sid, o) for sid in dict.fromkeys(request['species_ids'] + request['reference']['species_ids']) for o in request['omics']]
        for i, (sid, omics) in enumerate(tasks):
            progress('profiling', 1 + int(64 * i / len(tasks)))
            try:
                profile = get_profile(sid, omics, cat, checkpoint)
                profiles.append(profile)
            except Cancelled:
                raise
            except CompareError as exc:
                if exc.code in ('source_changed', 'lease_lost', 'review_required'):
                    raise
                failures.append({'species_id': sid, 'omics': omics, 'reason': exc.code, 'message': str(exc)})
            except (OSError, UnicodeError) as exc:
                failures.append({'species_id': sid, 'omics': omics, 'reason': 'source_unreadable', 'message': str(exc)})
        if not any(p['n_source'] > 0 for p in profiles):
            raise CompareError('No readable, nonempty Core datasets are available.', 'no_usable_sources', 409)
        progress('analyzing', 67)
        species = list(Species.objects.filter(species_id__in=set(request['species_ids'] + request['reference']['species_ids'])).values('species_id', 'display_name', 'domain', 'taxonomy_id', 'source_database', 'assembly_version'))
        result, tables = analyze(request, cat, profiles, species, checkpoint)
        result['source_failures'] = failures
        result['field_accounting']['profile_dataset_completed'] = len(profiles)
        result['field_accounting']['profile_dataset_failed'] = len(failures)
        result['status'] = 'partial' if failures else 'completed'
        progress('exporting', 90)
        result, checks = publish(run, result, tables, cat, profiles, checkpoint)
        with transaction.atomic():
            current = CompareRun.objects.select_for_update().get(pk=run.pk)
            if current.cancel_requested:
                raise Cancelled()
            if current.lease_token != token:
                raise CompareError('Final commit lost its worker lease.', 'lease_lost', 409)
            current.status = result['status']
            current.phase = 'finished'
            current.progress = 100
            current.finished_at = timezone.now()
            current.error_message = ''
            current.attempts[-1].update(status=current.status, finished_at=current.finished_at.isoformat())
            current.lease_until = None
            current.source_manifest_hash = run.source_manifest_hash
            current.summary_json = {**current.summary_json, 'artifact_checks': checks, 'source_failures': failures,
                                    'field_accounting': result['field_accounting'], 'profiles_completed': len(profiles)}
            current.save()
    except Cancelled:
        CompareRun.objects.filter(pk=run.pk, lease_token=token).update(status='cancelled', finished_at=timezone.now(), lease_until=None)
    except Exception as exc:
        traceback.print_exc()
        retry = isinstance(exc, CompareError) and exc.code == 'source_changed' and len(run.attempts) < 2
        terminal = 'interrupted' if isinstance(exc, CompareError) and exc.code == 'lease_lost' else 'failed'
        CompareRun.objects.filter(pk=run.pk, lease_token=token).update(status='queued' if retry else terminal,
            error_message=str(exc)[:4000], finished_at=None if retry else timezone.now(), lease_until=None)
    finally:
        for tmp in folder.glob('*.tmp'):
            tmp.unlink(missing_ok=True)
    if retry:
        process_one(run.run_id)
    return True


def drain(once=False, run_id=None):
    """One short-lived drainer for this database, no permanently idle processes."""
    locked = False
    try:
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_try_advisory_lock(%s)', [718529031])
                locked = bool(cursor.fetchone()[0])
            if not locked:
                return
        idle = 0
        while True:
            handled = process_one(run_id if once else None)
            if once:
                break
            if handled:
                idle = 0
            else:
                idle += 1
                if idle >= 2:
                    break
                time.sleep(1)
    finally:
        if locked:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [718529031])
        connections.close_all()
    # Close the empty-queue/unlock race: a newly submitted drainer may have
    # observed our lock just before release. Submissions after release can own
    # it themselves; submissions before release are covered by this check.
    if not once:
        pending = CompareRun.objects.filter(status='queued').order_by('created_at').first()
        if pending:
            from .runs import dispatch
            dispatch(pending)
        connections.close_all()
