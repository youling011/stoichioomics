"""Run every explicitly discovered test module and record individual outcomes."""
import argparse
import json
import os
from pathlib import Path
import time
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    parser.add_argument('--labels', nargs='*')
    args = parser.parse_args()
    if os.environ.get('DJANGO_SETTINGS_MODULE') != 'deploy.validation_settings':
        parser.error('Use DJANGO_SETTINGS_MODULE=deploy.validation_settings and isolated DB parameters')
    import django
    django.setup()
    from django.test.runner import DiscoverRunner
    from django.conf import settings
    if not settings.DATABASES['default']['TEST']['NAME'].startswith('test_stoich_deploy_'):
        raise RuntimeError('Unsafe test database')
    records = []

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            self.started = time.monotonic()
            super().startTest(test)
        def record(self, test, status, detail=None):
            row = {'id': test.id(), 'status': status, 'seconds': round(time.monotonic() - self.started, 3)}
            if detail:
                row['detail'] = detail
            records.append(row)
        def addSuccess(self, test):
            super().addSuccess(test); self.record(test, 'pass')
        def addError(self, test, err):
            super().addError(test, err); self.record(test, 'error', self._exc_info_to_string(err, test))
        def addFailure(self, test, err):
            super().addFailure(test, err); self.record(test, 'fail', self._exc_info_to_string(err, test))
        def addSkip(self, test, reason):
            super().addSkip(test, reason); self.record(test, 'skip', reason)
        def addSubTest(self, test, subtest, err):
            super().addSubTest(test, subtest, err)
            if err:
                self.record(subtest, 'fail', self._exc_info_to_string(err, test))

    class Runner(DiscoverRunner):
        def get_resultclass(self):
            return Result

    project = Path(__file__).resolve().parents[1]
    labels = args.labels or sorted({'.'.join(p.relative_to(project).with_suffix('').parts)
                                    for p in (project / 'backend').rglob('test*.py')})
    started = time.monotonic()
    try:
        failures = Runner(verbosity=2, interactive=False).run_tests(labels)
    finally:
        Path(args.report).write_text(json.dumps({
            'django': django.get_version(), 'labels': labels,
            'seconds': round(time.monotonic() - started, 2), 'records': records,
            'database': settings.DATABASES['default']['TEST']['NAME'],
            'note': 'Synthetic regression; does not establish production-data or capacity acceptance.'
        }, indent=2), encoding='utf-8')
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
