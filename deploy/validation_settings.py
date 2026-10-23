"""Synthetic tests only. Never reads the main project's .env or production DB."""
import os
from pathlib import Path
os.environ['DJANGO_ENV_FILE'] = ''
from backend.config.settings import *  # noqa: E402,F403

_root = Path(os.environ['STOICH_TEST_ROOT']).resolve()
if _root == BASE_DIR.resolve() or BASE_DIR.resolve() in _root.parents:
    raise RuntimeError('Validation state must be outside the project source')
_db = os.environ['STOICH_TEST_DB']
if not _db.startswith('test_stoich_deploy_'):
    raise RuntimeError('Refusing a database name without test_stoich_deploy_ prefix')
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql', 'NAME': 'postgres',
    'HOST': os.environ['STOICH_TEST_DB_HOST'], 'PORT': os.environ['STOICH_TEST_DB_PORT'],
    'USER': os.environ['STOICH_TEST_DB_USER'], 'PASSWORD': os.environ['STOICH_TEST_DB_PASSWORD'],
    'OPTIONS': {'connect_timeout': 5}, 'CONN_MAX_AGE': 0,
    'TEST': {'NAME': _db},
}}
SECRET_KEY = 'isolated-validation-only-' * 4
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
for _name, _relative in {
    'WORKSPACE_ROOT': 'jobs', 'MEDIA_ROOT': 'uploads', 'STATIC_ROOT': 'staticfiles',
    'SEQUENCE_ANALYSIS_WORKSPACE_ROOT': 'sequence_analysis',
    'SEQUENCE_ANALYSIS_LEGACY_WORKSPACE_ROOT': 'legacy_sequence',
    'SEQUENCE_ANALYSIS_EXAMPLE_ROOT': 'sequence_examples', 'COMPARE_CORE_ROOT': 'compare',
    'PROTEOME_VIZ_ROOT': 'proteome', 'SEQUENCE_VIZ_ROOT': 'sequence',
    'INTEGRATION_VIZ_ROOT': 'integration', 'STOICHDB_DATA_ROOT': 'registry',
    'STOICHDB_PRECOMPUTED_ROOT': 'precomputed', 'ANALYSIS_EXAMPLES_ROOT': 'examples',
}.items():
    globals()[_name] = _root / _relative
CASE_REGISTRY_FILE = _root / 'case_registry.json'
COMPARE_CORE_AUTOSTART = False
PROTEOME_VIZ_ON_DEMAND = False
SEQUENCE_VIZ_ON_DEMAND = False
INTEGRATION_VIZ_ON_DEMAND = False
HVG_RESEARCH_ENABLED = True
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'deployment-validation'}}
