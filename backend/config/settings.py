from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parents[2]


def _load_env_file() -> None:
    # Unset preserves development behavior; empty explicitly disables file loading.
    configured = os.environ.get('DJANGO_ENV_FILE')
    if configured == '':
        return
    env_path = Path(configured) if configured is not None else BASE_DIR / '.env'
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'CHANGE_ME_GENERATE_A_PRIVATE_DJANGO_SECRET_KEY')
DEBUG = os.environ.get('DJANGO_DEBUG', '0') == '1'
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', '*').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'backend.apps.core',
    'backend.apps.jobs',
    'backend.apps.files',
    'backend.apps.registry',
    'backend.apps.hvg',
    'backend.apps.stoichdb',
    'backend.apps.sequence_analysis',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'backend.config.wsgi.application'
ASGI_APPLICATION = 'backend.config.asgi.application'

DB_ENGINE = os.environ.get('DJANGO_DB_ENGINE', 'postgresql').lower()
if DB_ENGINE in {'postgres', 'postgresql'} or os.environ.get('POSTGRES_DB'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('POSTGRES_DB', 'stoichioomics'),
            'USER': os.environ.get('POSTGRES_USER', 'postgres'),
            'PASSWORD': os.environ.get('POSTGRES_PASSWORD', ''),
            'HOST': os.environ.get('POSTGRES_HOST', '127.0.0.1'),
            'PORT': os.environ.get('POSTGRES_PORT', '5432'),
            'CONN_MAX_AGE': int(os.environ.get('POSTGRES_CONN_MAX_AGE', '60')),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'backend_db.sqlite3',
        }
    }

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Tokyo'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'uploads'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOW_ALL_ORIGINS = True
CSRF_TRUSTED_ORIGINS = ['http://localhost:5173', 'http://127.0.0.1:5173']

REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': ['backend.apps.common.json_renderer.TimedJSONRenderer'],
    'DEFAULT_PARSER_CLASSES': [
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.MultiPartParser',
        'rest_framework.parsers.FormParser',
    ],
}

PLATFORM_ROOT = BASE_DIR
WORKSPACE_ROOT = BASE_DIR / 'workspace' / 'jobs'
CASE_REGISTRY_FILE = BASE_DIR / 'workspace' / 'case_registry.json'
ANALYSIS_EXAMPLES_ROOT = BASE_DIR / 'data' / 'examples'
STOICHDB_DATA_ROOT = Path(os.environ.get('STOICHDB_DATA_ROOT', str(BASE_DIR / 'data' / 'stoichdb_demo')) )
STOICHDB_PRECOMPUTED_ROOT = Path(os.environ.get(
    'STOICHDB_PRECOMPUTED_ROOT',
    str(BASE_DIR / 'workspace'),
))
STOICH_FEATURE_EXTRACTOR_ROOT = Path(os.environ.get(
    'STOICH_FEATURE_EXTRACTOR_ROOT',
    str(BASE_DIR.parents[1] / '组学化学计量特征提取代码'),
))
SEQUENCE_ANALYSIS_TTL_HOURS = int(os.environ.get('SEQUENCE_ANALYSIS_TTL_HOURS', '24'))
USER_UPLOAD_MAX_BYTES = int(os.environ.get('USER_UPLOAD_MAX_BYTES', str(100 * 1024 * 1024)))
USER_UPLOAD_ALLOWED_EXTENSIONS = [
    item.strip().lower()
    for item in os.environ.get(
        'USER_UPLOAD_ALLOWED_EXTENSIONS',
        '.csv,.tsv,.txt,.json,.yaml,.yml,.h5ad,.mtx,.gz,.zip,.fa,.fasta,.faa,.fna,.fas,.gff,.gff3,.gtf',
    ).split(',')
    if item.strip()
]
JOB_WORKSPACE_TTL_HOURS = int(os.environ.get('JOB_WORKSPACE_TTL_HOURS', str(7 * 24)))
SEQUENCE_ANALYSIS_WORKSPACE_ROOT = Path(os.environ.get(
    'SEQUENCE_ANALYSIS_WORKSPACE_ROOT',
    str(BASE_DIR / 'runtime' / 'sequence_analysis'),
))
SEQUENCE_ANALYSIS_LEGACY_WORKSPACE_ROOT = BASE_DIR / 'workspace' / 'sequence_analysis'
SEQUENCE_ANALYSIS_EXAMPLE_ROOT = Path(os.environ.get(
    'SEQUENCE_ANALYSIS_EXAMPLE_ROOT',
    str(BASE_DIR / 'data' / 'examples' / 'sequence_analysis_results'),
))

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
}

# New research creation gate; existing runs remain readable when disabled.
HVG_RESEARCH_ENABLED = os.environ.get('HVG_RESEARCH_ENABLED', '0') == '1'


# Strict Core comparison uses bounded, durable, per-task workers.
COMPARE_CORE_ENABLED = os.environ.get('COMPARE_CORE_ENABLED', '1') == '1'
COMPARE_CORE_AUTOSTART = os.environ.get('COMPARE_CORE_AUTOSTART', '1') == '1'
COMPARE_CORE_ROOT = BASE_DIR / 'runtime' / 'compare_core'

# Whole-population Proteome scientific visualizations; source CSVs remain immutable.
STOICH_PROTEOME_VIZ_V3_ENABLED = os.environ.get("STOICH_PROTEOME_VIZ_V3_ENABLED", "1") == "1"
PROTEOME_VIZ_ROOT = Path(os.environ.get("PROTEOME_VIZ_ROOT", str(BASE_DIR / "runtime" / "proteome_visuals_v3")))

# Independent Genome / Transcriptome complete-population result channel.
SEQUENCE_VIZ_GENOME_ENABLED = os.environ.get("SEQUENCE_VIZ_GENOME_ENABLED", "1") == "1"
SEQUENCE_VIZ_TRANSCRIPTOME_ENABLED = os.environ.get("SEQUENCE_VIZ_TRANSCRIPTOME_ENABLED", "1") == "1"
SEQUENCE_VIZ_ROOT = Path(os.environ.get("SEQUENCE_VIZ_ROOT", str(BASE_DIR / "runtime" / "sequence_visuals_v1")))
SEQUENCE_VIZ_ON_DEMAND = os.environ.get("SEQUENCE_VIZ_ON_DEMAND", "1") == "1"
SEQUENCE_VIZ_COHORT_LIMIT = 32

# Independent complete-Core integration namespace. Enabled only after acceptance.
INTEGRATION_VIZ_ENABLED = os.getenv('INTEGRATION_VIZ_ENABLED', '1').strip().lower() in {'1','true','yes'}
INTEGRATION_VIZ_ON_DEMAND = os.getenv('INTEGRATION_VIZ_ON_DEMAND', '1').strip().lower() in {'1','true','yes'}
INTEGRATION_VIZ_ROOT = Path(os.getenv('INTEGRATION_VIZ_ROOT', str(BASE_DIR / 'runtime/integration_visuals_v1')))
INTEGRATION_VIZ_COHORT_LIMIT = 32

MIDDLEWARE = ['backend.apps.stoichdb.integration_viz.middleware.IntegrationCompressionMiddleware'] + MIDDLEWARE

# Presentation-only local rollout flag; no analysis behavior changes.
WORKFLOW_VISUALS_V2_ENABLED = os.getenv('WORKFLOW_VISUALS_V2_ENABLED', '1').lower() in {'1', 'true', 'yes'}

# Deployment compatibility: immutable historical reads, owned writable state.
DEPLOYMENT_STATE_ROOT = Path(os.environ.get('DEPLOYMENT_STATE_ROOT', str(BASE_DIR / 'runtime' / 'deployment')))
DEPLOYMENT_HISTORICAL_ROOT = os.environ.get('DEPLOYMENT_HISTORICAL_ROOT', os.environ.get('STOICH_PROJECT_ROOT', str(BASE_DIR)))
TASK_EXECUTION_AUTOSTART = os.environ.get('TASK_EXECUTION_AUTOSTART', '1') == '1'
ARTIFACT_MEMORY_CACHE_BYTES = int(os.environ.get('ARTIFACT_MEMORY_CACHE_BYTES', str(128 * 1024**2)))
STOICH_FEATURE_REGISTRY_OUTPUT_ROOT = Path(os.environ.get('STOICH_FEATURE_REGISTRY_OUTPUT_ROOT', str(DEPLOYMENT_STATE_ROOT / 'runtime' / 'feature_registry')))
UWSGI_STATS_SOCKET = os.environ.get('STOICH_UWSGI_STATS_SOCKET') or None
MIDDLEWARE = ['backend.apps.common.maintenance.SubmissionFenceMiddleware', *MIDDLEWARE]

DEPLOYMENT_INTEGRITY_INDEX = os.environ.get('DEPLOYMENT_INTEGRITY_INDEX') or None
DEPLOYMENT_PUBLIC_SNAPSHOTS = os.environ.get('DEPLOYMENT_PUBLIC_SNAPSHOTS','0') == '1'

MIDDLEWARE = ['backend.apps.common.request_timing.RequestTimingMiddleware', *MIDDLEWARE]
