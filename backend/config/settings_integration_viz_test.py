"""Dedicated disposable regression DB and output namespace, never curated data."""
from .settings_sequence_viz_test import *
DATABASES=deepcopy(DATABASES)
DATABASES['default']['NAME']='stoich_integration_viz_acceptance_20261022'
DATABASES['default']['TEST']={'NAME':'test_stoich_integration_viz_acceptance_20261022'}
INTEGRATION_VIZ_ROOT=Path(tempfile.gettempdir())/('stoich_integration_viz_test_'+str(os.getpid()))
INTEGRATION_VIZ_ON_DEMAND=False
INTEGRATION_VIZ_ENABLED=True
