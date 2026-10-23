"""HTTPS integration checks for the isolated fixture, including opt-in writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', default='https://platform.test')
    p.add_argument('--ca', required=True)
    p.add_argument('--report', required=True)
    p.add_argument('--writes', action='store_true')
    a = p.parse_args()
    if os.environ.get('STOICH_VALIDATION_ONLY') != '1' or not os.environ.get('POSTGRES_DB', '').startswith('test_stoich_deploy_'):
        p.error('Run only with explicit isolated validation environment')
    context = ssl.create_default_context(cafile=a.ca)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    records = []

    def request(path, data=None, headers=None, method=None):
        r = urllib.request.Request(a.base + path, data=data, headers=headers or {}, method=method)
        try:
            response = opener.open(r, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read()

    def check(name, func):
        try:
            detail = func()
            records.append({'name': name, 'status': 'pass', 'evidence': detail})
        except Exception as exc:
            records.append({'name': name, 'status': 'fail', 'error': str(exc)})

    # A cold scientific Python worker can take time to import its dependencies.
    for _ in range(60):
        try:
            with opener.open(a.base + '/api/health/ready/', timeout=2) as response:
                if response.status == 200:
                    break
        except (OSError, urllib.error.URLError):
            time.sleep(1)
    else:
        raise RuntimeError('Application did not become ready in the isolated startup window')

    def status(path, expected, **kw):
        code, headers, body = request(path, **kw)
        assert code == expected, (path, code, body[:400])
        return {'status': code, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}

    check('HTTPS certificate trusted using test CA', lambda: status('/api/health/', 200))
    check('PostgreSQL and file roots readiness', lambda: status('/api/health/ready/', 200))
    check('Vue landing page', lambda: status('/', 200))
    check('Vue history page refresh', lambda: status('/species/deployment_fixture', 200))
    check('Django admin route', lambda: status('/admin/login/', 200))
    check('Django collected admin CSS', lambda: status('/static/admin/css/base.css', 200))
    check('Missing API is 404, not SPA HTML', lambda: status('/api/not-a-real-route/', 404))
    check('Missing JS asset remains 404', lambda: status('/assets/not-real.js', 404))
    check('Private media remains private', lambda: status('/media/private.txt', 404))
    check('Dotfile blocked', lambda: status('/.env', 404))
    check('Spoofed forwarding protocol overwritten', lambda: status('/api/health/', 200, headers={'X-Forwarded-Proto': 'http'}))
    check('Admin CSRF enforcement', lambda: status('/admin/login/', 403, data=b'username=invalid&password=invalid', headers={'Content-Type': 'application/x-www-form-urlencoded'}))
    check('Public feature CSV download', lambda: status('/api/stoichdb/downloads/files/deployment_fixture__genome/', 200))

    def parity():
        import django
        django.setup()
        from django.test import Client
        client = Client()
        evidence = []
        for path in ['/api/health/', '/api/stoichdb/species/', '/api/stoichdb/species/deployment_fixture/',
                     '/api/stoichdb/search/?q=deployment_fixture', '/api/sequence-analysis/sample-sheet-template/']:
            direct = client.get(path, secure=True, HTTP_HOST='platform.test')
            code, _, body = request(path)
            expected = b''.join(direct.streaming_content) if direct.streaming else direct.content
            assert code == direct.status_code == 200, (path, code, direct.status_code)
            assert body == expected, ('Response mismatch', path)
            evidence.append({'path': path, 'sha256': hashlib.sha256(body).hexdigest()})
        return evidence
    check('Direct Django and Nginx/uWSGI exact response parity', parity)

    if a.writes:
        def sequence():
            boundary = 'stoich-deployment-validation-boundary'
            chunks = []
            for name, value in [('analysis_type', 'single_sequence'), ('omics_type', 'proteome')]:
                chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
            fasta = '>fixture1\n' + 'ACDEFGHIKLMNPQRSTVWY' * 3 + '\n>fixture2\n' + 'ACMN' * 15 + '\n'
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="fixture.faa"\r\nContent-Type: application/octet-stream\r\n\r\n{fasta}\r\n--{boundary}--\r\n'.encode())
            code, _, body = request('/api/sequence-analysis/jobs/', b''.join(chunks), {'Content-Type': 'multipart/form-data; boundary=' + boundary})
            assert code == 201, (code, body[:400])
            job = json.loads(body)['data']
            job_id = job['job_id']
            for _ in range(120):
                _, _, body = request('/api/sequence-analysis/jobs/' + job_id + '/')
                job = json.loads(body)['data']
                if job['status'] in {'SUCCEEDED', 'FAILED', 'BLOCKED'}:
                    break
                time.sleep(.5)
            assert job['status'] == 'SUCCEEDED', (job['status'], job.get('error_message'), job.get('input_qc'))
            for suffix in ['features/', 'feature-summary/', 'basic-visualization/', 'job-manifest/']:
                status('/api/sequence-analysis/jobs/' + job_id + '/' + suffix, 200)
            _, _, body = request('/api/sequence-analysis/jobs/' + job_id + '/features/')
            rows = json.loads(body)['data']['rows']
            matched = [r for r in rows if str(r.get('protein_id', r.get('entity_id', ''))) == 'fixture2']
            assert len(matched) == 1, ('Missing fixture2', rows)
            hand = {'length_aa': 60, 'C_atoms': 225, 'N_atoms': 75, 'S_atoms': 30}
            for key, expected in hand.items():
                assert float(matched[0][key]) == expected, (key, matched[0][key], expected)
            return {'state': job['status'], 'job_id': job_id, 'outputs_checked': 4,
                    'hand_calculated_ACMN_times_15': hand, 'summary': job.get('summary')}
        check('Real multipart sequence upload, background calculation and result APIs', sequence)

        def export():
            payload = {'species_ids': ['deployment_fixture'], 'omics': 'genome', 'scope': 'core',
                       'mode': 'selected_columns', 'fields': ['gene_id', 'gene_len_nt']}
            code, _, body = request('/api/stoichdb/feature-hub/exports/', json.dumps(payload).encode(), {'Content-Type': 'application/json'})
            assert code == 200, (code, body[:400])
            job = json.loads(body)['data']; export_id = job['export_id']
            for _ in range(60):
                _, _, body = request('/api/stoichdb/feature-hub/exports/' + export_id + '/')
                job = json.loads(body)['data']
                if job['status'] in {'completed', 'failed'}:
                    break
                time.sleep(.5)
            assert job['status'] == 'completed', job
            evidence = status('/api/stoichdb/feature-hub/exports/' + export_id + '/download/', 200)
            return {'state': job['status'], 'export_id': export_id, 'download': evidence}
        check('Feature export background thread and ZIP download', export)
    result = {'environment': 'Linux container / private PostgreSQL / test HTTPS certificate / synthetic fixtures',
              'records': records, 'pass': sum(r['status'] == 'pass' for r in records),
              'fail': sum(r['status'] == 'fail' for r in records),
              'limitations': ['Not a public certificate or production-data acceptance.', 'No load or crash-durability guarantee.']}
    Path(a.report).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'pass': result['pass'], 'fail': result['fail']}))
    raise SystemExit(bool(result['fail']))


if __name__ == '__main__':
    main()
