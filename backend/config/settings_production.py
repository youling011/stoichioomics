"""Opt-in production overlay. Business/analysis defaults stay in settings.py."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

# Never inherit a developer database/secret from the project .env by accident.
# An explicitly selected DJANGO_ENV_FILE is supported by the base module.
os.environ.setdefault('DJANGO_ENV_FILE', '')
from .settings import *  # noqa: E402,F403


def _required(name):
    value = os.environ.get(name, '').strip()
    if not value or '__REQUIRED_' in value or value.startswith('CHANGE_ME'):
        raise ImproperlyConfigured(f'{name} must be explicitly configured')
    return value


def _bool(name, default):
    value = os.environ.get(name, str(default)).lower()
    if value not in {'true', 'false', '1', '0'}:
        raise ImproperlyConfigured(f'{name} must be true/false or 1/0')
    return value in {'true', '1'}


def _csv(name):
    return [v.strip() for v in _required(name).split(',') if v.strip()]


DEBUG = False
ROOT_URLCONF = 'backend.config.urls_production'
SECRET_KEY = _required('DJANGO_SECRET_KEY')
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured('DJANGO_SECRET_KEY must be a strong production key')
ALLOWED_HOSTS = _csv('DJANGO_ALLOWED_HOSTS')
if any('*' in v or '://' in v or '/' in v for v in ALLOWED_HOSTS):
    raise ImproperlyConfigured('DJANGO_ALLOWED_HOSTS must contain explicit hostnames/IPs')
CSRF_TRUSTED_ORIGINS = _csv('DJANGO_CSRF_TRUSTED_ORIGINS')
ALLOW_HTTP_TEST = _bool('STOICH_ALLOW_HTTP_TEST', False)
for origin in CSRF_TRUSTED_ORIGINS:
    if not origin.startswith('https://') and not (ALLOW_HTTP_TEST and origin.startswith('http://')):
        raise ImproperlyConfigured('CSRF origins require HTTPS, except explicit HTTP tests')
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [v.strip() for v in os.environ.get('DJANGO_CORS_ALLOWED_ORIGINS', '').split(',') if v.strip()]
SECURE_SSL_REDIRECT = not ALLOW_HTTP_TEST
SESSION_COOKIE_SECURE = not ALLOW_HTTP_TEST
CSRF_COOKIE_SECURE = not ALLOW_HTTP_TEST
# Trusted only because the upstream socket is private and nginx overwrites this header.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
# Opt in after the real domain and certificate lifecycle are confirmed.
SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

if _required('DJANGO_DB_ENGINE').lower() not in {'postgresql', 'postgres'}:
    raise ImproperlyConfigured('Production requires PostgreSQL')
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql',
    'NAME': _required('POSTGRES_DB'),
    'USER': _required('POSTGRES_USER'),
    'PASSWORD': _required('POSTGRES_PASSWORD'),
    'HOST': _required('POSTGRES_HOST'),
    'PORT': _required('POSTGRES_PORT'),
    'CONN_MAX_AGE': int(os.environ.get('POSTGRES_CONN_MAX_AGE', '60')),
    'CONN_HEALTH_CHECKS': True,
    'OPTIONS': {'connect_timeout': int(os.environ.get('POSTGRES_CONNECT_TIMEOUT', '5'))},
}}
if os.environ.get('POSTGRES_SSLMODE'):
    DATABASES['default']['OPTIONS']['sslmode'] = os.environ['POSTGRES_SSLMODE']

# Keep the existing on-disk layout by default. Override only mapped/migrated roots.
for _name in (
    'STATIC_ROOT', 'MEDIA_ROOT', 'WORKSPACE_ROOT', 'CASE_REGISTRY_FILE',
    'ANALYSIS_EXAMPLES_ROOT', 'STOICHDB_DATA_ROOT', 'STOICHDB_PRECOMPUTED_ROOT',
    'STOICH_FEATURE_EXTRACTOR_ROOT', 'SEQUENCE_ANALYSIS_WORKSPACE_ROOT',
    'SEQUENCE_ANALYSIS_LEGACY_WORKSPACE_ROOT', 'SEQUENCE_ANALYSIS_EXAMPLE_ROOT',
    'COMPARE_CORE_ROOT', 'PROTEOME_VIZ_ROOT', 'SEQUENCE_VIZ_ROOT', 'INTEGRATION_VIZ_ROOT',
    'DEPLOYMENT_STATE_ROOT', 'STOICH_FEATURE_REGISTRY_OUTPUT_ROOT',
    'STOICH_FEATURE_PROFILE_ROOT','STOICH_FEATURE_QC_ROOT','STOICH_FEATURE_HOME_ROOT','STOICH_FEATURE_EXPORT_ROOT',
    'STOICH_DATA_ROOT', 'STOICH_FEATURE_ROOT', 'STOICH_PROJECT_ROOT',
    'STOICH_PROJECT_DATA_ROOT', 'STOICHIOOMICS_ROOT', 'STOICH_RUNTIME_ROOT', 'STOICH_BACKUP_ROOT',
):
    if os.environ.get(_name):
        _path = Path(os.environ[_name]).expanduser()
        if not _path.is_absolute():
            raise ImproperlyConfigured(f'{_name} must be an absolute path on the target OS')
        globals()[_name] = _path

# Health checks validate configured roots without creating files or exposing paths.
DEPLOYMENT_READINESS_ROOTS = {
    'registry': STOICHDB_DATA_ROOT,
    'workspace': WORKSPACE_ROOT,
    'uploads': MEDIA_ROOT,
    'sequence_workspace': SEQUENCE_ANALYSIS_WORKSPACE_ROOT,
    'proteome_artifacts': PROTEOME_VIZ_ROOT,
    'sequence_artifacts': SEQUENCE_VIZ_ROOT,
    'integration_artifacts': INTEGRATION_VIZ_ROOT,
}
DEPLOYMENT_READINESS_WRITABLE_ROOTS = {
    'workspace', 'uploads', 'sequence_workspace', 'proteome_artifacts',
    'sequence_artifacts', 'integration_artifacts',
}
