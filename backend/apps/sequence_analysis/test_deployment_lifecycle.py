import json
import os
from pathlib import Path
import tempfile
from threading import Thread
from datetime import datetime, timedelta, timezone
from django.test import SimpleTestCase, override_settings
from backend.apps.common.atomic_json import atomic_write_json, read_json
from . import services
import numpy as np
import pandas as pd
from backend.apps.common.histogram import finite_histogram
from .real_engine import _histogram as engine_histogram
from .feature_panels import _histogram as panel_histogram


class DeploymentLifecycleTests(SimpleTestCase):
    def test_portable_artifact_paths_reject_drives_and_backslash_traversal(self):
        from backend.analysis_engine.hvg_research.artifacts import safe_path
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ['C:/outside', 'C:outside', '..'+chr(92)+'other', chr(92)*2+'server'+chr(92)+'share']:
                with self.subTest(path=bad), self.assertRaises(ValueError):
                    safe_path(tmp, bad)

    def test_normal_histogram_output_is_exactly_numpy(self):
        values = np.linspace(-3, 8, 101)
        expected = np.histogram(values, bins=18)
        actual = finite_histogram(values, bins=18)
        np.testing.assert_array_equal(actual[0], expected[0])
        np.testing.assert_array_equal(actual[1], expected[1])

    def test_adjacent_float_histograms_preserve_every_observation(self):
        values = [1.0, np.nextafter(1.0, np.inf)]
        counts, edges = finite_histogram(values, bins=8)
        self.assertEqual(int(counts.sum()), 2)
        self.assertTrue(np.isfinite(edges).all())
        self.assertEqual(sum(engine_histogram(values)['counts']), 2)
        self.assertEqual(sum(panel_histogram(pd.Series(values))['counts']), 2)

    def test_unrelated_histogram_errors_are_not_hidden(self):
        with self.assertRaises(ValueError):
            finite_histogram([1, 2, float('inf')], bins=8)

    def test_poll_cleanup_preserves_running_inputs_then_cleans_terminal_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / 'current/seq_fixture'
            inputs = job / 'inputs'; inputs.mkdir(parents=True)
            (inputs / 'fixture.faa').write_text('>fixture\nACMN\n')
            meta = {'status': 'RUNNING', 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()}
            atomic_write_json(job / 'job.json', meta)
            with override_settings(SEQUENCE_ANALYSIS_WORKSPACE_ROOT=root/'current', SEQUENCE_ANALYSIS_LEGACY_WORKSPACE_ROOT=root/'legacy'):
                self.assertEqual(services.cleanup_expired_jobs(), 0)
                self.assertTrue((inputs / 'fixture.faa').exists())
                atomic_write_json(job / 'job.json', {**meta, 'status': 'SUCCEEDED'})
                self.assertEqual(services.cleanup_expired_jobs(), 0)
                self.assertFalse(inputs.exists())
                self.assertTrue((job / 'job.json').exists())

    def test_expired_job_still_obeys_existing_ttl_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); job = root/'current/seq_expired'; job.mkdir(parents=True)
            atomic_write_json(job/'job.json', {'status':'SUCCEEDED', 'expires_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()})
            with override_settings(SEQUENCE_ANALYSIS_WORKSPACE_ROOT=root/'current', SEQUENCE_ANALYSIS_LEGACY_WORKSPACE_ROOT=root/'legacy'):
                self.assertEqual(services.cleanup_expired_jobs(), 1)
                self.assertFalse(job.exists())

    def test_cached_reader_observes_external_same_size_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'status.json'
            atomic_write_json(path, {'status':'queued'})
            self.assertEqual(services._read_json(path)['status'], 'queued')
            before = path.stat()
            atomic_write_json(path, {'status':'failed'})
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertEqual(path.stat().st_size, before.st_size)
            self.assertEqual(services._read_json(path)['status'], 'failed')

    def test_concurrent_reader_never_sees_partial_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'status.json'; atomic_write_json(path, {'index':0, 'text':'x'*200})
            errors=[]
            def read():
                for _ in range(100):
                    try:
                        payload=read_json(path); self.assertEqual(len(payload['text']), 200)
                    except Exception as exc:
                        errors.append(str(exc))
            readers=[Thread(target=read) for _ in range(3)]
            for thread in readers: thread.start()
            for i in range(30): atomic_write_json(path, {'index':i, 'text':'x'*200})
            for thread in readers: thread.join()
            self.assertEqual(errors, [])

    def test_failed_serialization_keeps_previous_state_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'status.json'; atomic_write_json(path, {'status':'running'})
            with self.assertRaises(TypeError): atomic_write_json(path, {'bad':object()})
            self.assertEqual(json.loads(path.read_text()), {'status':'running'})
            self.assertEqual(list(Path(tmp).iterdir()), [path])
