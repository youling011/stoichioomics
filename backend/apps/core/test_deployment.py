import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch, MagicMock
from django.db import OperationalError
from django.test import SimpleTestCase, RequestFactory, override_settings
from .deployment import readiness_view


class ReadinessTests(SimpleTestCase):
    def test_readiness_route_is_only_added_by_production_overlay(self):
        from django.urls import resolve, Resolver404
        self.assertIs(resolve('/api/health/ready/', urlconf='backend.config.urls_production').func, readiness_view)
        with self.assertRaises(Resolver404):
            resolve('/api/health/ready/', urlconf='backend.config.urls')

    def test_success_has_no_paths_and_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = MagicMock()
            db.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
            with override_settings(DEPLOYMENT_READINESS_ROOTS={'files': tmp}), patch('backend.apps.core.deployment.connections', {'default': db}):
                response = readiness_view(RequestFactory().get('/api/health/ready/'))
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(tmp, response.content.decode())
            self.assertEqual(list(Path(tmp).iterdir()), [])
            db.cursor.return_value.__enter__.return_value.execute.assert_called_once_with('SELECT 1')

    def test_database_failure_is_503_without_exception_details(self):
        db = MagicMock()
        db.cursor.side_effect = OperationalError('private host and password')
        with override_settings(DEPLOYMENT_READINESS_ROOTS={}), patch('backend.apps.core.deployment.connections', {'default': db}):
            response = readiness_view(RequestFactory().get('/api/health/ready/'))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private', response.content.decode())

    def test_missing_root_is_503(self):
        db = MagicMock()
        db.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
        with tempfile.TemporaryDirectory() as tmp, override_settings(DEPLOYMENT_READINESS_ROOTS={'files': Path(tmp) / 'absent'}), patch('backend.apps.core.deployment.connections', {'default': db}):
            response = readiness_view(RequestFactory().get('/api/health/ready/'))
        self.assertEqual(response.status_code, 503)

    def test_post_is_not_allowed(self):
        self.assertEqual(readiness_view(RequestFactory().post('/api/health/ready/')).status_code, 405)


class ProductionSettingsTests(SimpleTestCase):
    def run_settings(self, changes):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('DJANGO_', 'POSTGRES_', 'STOICH_'))}
        env.update({
            'DJANGO_SECRET_KEY': 'unit-test-only-abcdef0123456789-' * 3,
            'DJANGO_ALLOWED_HOSTS': 'platform.test',
            'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://platform.test',
            'DJANGO_DB_ENGINE': 'postgresql', 'POSTGRES_DB': 'test_stoich_deploy_config',
            'POSTGRES_USER': 'test_role', 'POSTGRES_PASSWORD': 'test-only-password',
            'POSTGRES_HOST': '127.0.0.1', 'POSTGRES_PORT': '1', 'DJANGO_ENV_FILE': '',
            'PYTHONDONTWRITEBYTECODE': '1',
        })
        env.update(changes)
        code = ('import backend.config.settings_production as s; '
                'assert s.DEBUG is False; assert s.CORS_ALLOW_ALL_ORIGINS is False; '
                'assert s.DATABASES["default"]["NAME"] == "test_stoich_deploy_config"; '
                'assert s.TIME_ZONE == "Asia/Tokyo"; print(s.SECURE_SSL_REDIRECT)')
        return subprocess.run([sys.executable, '-B', '-c', code], cwd=Path(__file__).resolve().parents[3], env=env, text=True, capture_output=True, timeout=40)

    def test_secure_defaults_without_database_connection(self):
        result = self.run_settings({})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'True')

    def test_missing_password_fails_closed(self):
        result = self.run_settings({'POSTGRES_PASSWORD': ''})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('POSTGRES_PASSWORD must be explicitly configured', result.stderr)

    def test_wildcard_host_is_rejected(self):
        self.assertNotEqual(self.run_settings({'DJANGO_ALLOWED_HOSTS': '*'}).returncode, 0)

    def test_http_requires_explicit_test_flag(self):
        self.assertNotEqual(self.run_settings({'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://localhost'}).returncode, 0)
        result = self.run_settings({'DJANGO_CSRF_TRUSTED_ORIGINS': 'http://localhost', 'STOICH_ALLOW_HTTP_TEST': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'False')


class TemplateTests(SimpleTestCase):
    def config(self):
        return dict(project_root='/srv/platform/proj', venv_root='/srv/platform/proj/.venv',
                    frontend_root='/srv/www/platform', static_root='/srv/www/static',
                    domain='platform.test', certificate='/etc/certs/full.pem', certificate_key='/etc/certs/key.pem',
                    environment_file='/etc/platform.env', service_user='stoichioomics', service_group='www-data',
                    processes=2, threads=2, upload_body_limit_mib=512, read_timeout_seconds=300, stop_timeout_seconds=3600)

    def render(self, config, tmp, profile='https'):
        from deploy.render import render
        return render(config, tmp, profile)

    def test_https_config_protocol_and_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.render(self.config(), tmp)
            nginx = (Path(tmp) / 'nginx-site.conf').read_text()
            uwsgi = (Path(tmp) / 'uwsgi.ini').read_text()
        self.assertIn('uwsgi_pass unix:/run/stoichioomics/uwsgi.sock;', nginx)
        self.assertIn('try_files $uri $uri/ /index.html;', nginx)
        self.assertIn('ssl_protocols TLSv1.2 TLSv1.3;', nginx)
        self.assertIn('module = backend.config.wsgi:application', uwsgi)
        self.assertIn('enable-threads = true', uwsgi)
        self.assertNotIn('harakiri =', uwsgi)

    def test_placeholder_and_injection_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for key, value in [('project_root', '__REQUIRED_PATH__'), ('domain', 'host;return 200'), ('venv_root', '/srv/a\nExecStart=/bad'), ('threads', 0)]:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    self.render({**self.config(), key: value}, tmp)

    def test_http_profile_is_loopback_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                self.render(self.config(), tmp, 'http-test')
            self.render({**self.config(), 'domain': 'localhost'}, tmp, 'http-test')
            self.assertIn('listen 127.0.0.1:18080;', (Path(tmp) / 'nginx-site.conf').read_text())
