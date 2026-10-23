"""Read-only curated-data browser acceptance server, on a separate port."""
from .settings import *
from copy import deepcopy
DATABASES=deepcopy(DATABASES)
DATABASES['default'].setdefault('OPTIONS',{})
DATABASES['default']['OPTIONS']['options']=(DATABASES['default']['OPTIONS'].get('options','')+' -c default_transaction_read_only=on').strip()
STOICH_PROTEOME_VIZ_V3_ENABLED=True
COMPARE_CORE_AUTOSTART=False
CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache','LOCATION':'proteome_browser_acceptance','KEY_PREFIX':'proteome_browser_acceptance'}}
