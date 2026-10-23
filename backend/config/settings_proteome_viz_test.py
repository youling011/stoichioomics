"""Isolated PostgreSQL test database; never point TestCase at the curated database."""
from .settings import *
PROTEOME_VIZ_ON_DEMAND=False
from copy import deepcopy
import tempfile
DATABASES=deepcopy(DATABASES)
_production_name=str(DATABASES['default']['NAME'])
_test_name='stoich_proteome_viz_acceptance_20261020'
assert _production_name not in [_test_name,'test_'+_test_name]
DATABASES['default']['ENGINE']='django.db.backends.postgresql'
DATABASES['default']['NAME']=_test_name
DATABASES['default']['TEST']={'NAME':'test_'+_test_name}
PROTEOME_VIZ_ROOT=Path(tempfile.gettempdir())/('stoich_proteome_viz_test_'+str(os.getpid()))
STOICH_PROTEOME_VIZ_V3_ENABLED=True
COMPARE_CORE_AUTOSTART=False
COMPARE_CORE_ROOT=Path(tempfile.gettempdir())/('stoich_compare_proteome_test_'+str(os.getpid()))
CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache','LOCATION':'proteome_viz_test','KEY_PREFIX':'proteome_viz_test'}}
