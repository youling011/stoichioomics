from .settings import *
import os
DATABASES = {**DATABASES, 'default': {**DATABASES['default']}}
_production_name = DATABASES['default']['NAME']
DATABASES['default']['NAME'] = 'stoich_compare_acceptance'
DATABASES['default']['TEST'] = {'NAME': 'test_stoich_compare_acceptance'}
assert DATABASES['default']['NAME'] != _production_name
assert DATABASES['default']['TEST']['NAME'].startswith('test_stoich_compare_')
COMPARE_CORE_AUTOSTART = False
COMPARE_CORE_ROOT = os.path.join(os.environ.get('TEMP', '/tmp'), 'stoich_compare_test')
