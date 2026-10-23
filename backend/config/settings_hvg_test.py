from .settings import *
from copy import deepcopy
_production_name=str(DATABASES['default']['NAME'])
_test_name=os.environ.get('HVG_RESEARCH_TEST_DB','stoich_hvg_acceptance_20261015')
if _test_name==_production_name or not _test_name.startswith(('test_','stoich_hvg_acceptance')):
    raise RuntimeError('Refusing unsafe HVG test database name')
DATABASES=deepcopy(DATABASES)
DATABASES['default']['ENGINE']='django.db.backends.postgresql'
DATABASES['default']['NAME']=_test_name
DATABASES['default']['TEST']={'NAME':'test_'+_test_name}
HVG_RESEARCH_ENABLED=True
