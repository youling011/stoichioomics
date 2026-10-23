"""Isolated regression database. Never creates fixtures in the curated database."""
from .settings_proteome_viz_test import *
from copy import deepcopy
DATABASES=deepcopy(DATABASES)
DATABASES['default']['NAME']='stoich_sequence_viz_acceptance_20261021'
DATABASES['default']['TEST']={'NAME':'test_stoich_sequence_viz_acceptance_20261021'}
assert str(DATABASES['default']['NAME']) not in [str(__import__('backend.config.settings',fromlist=['DATABASES']).DATABASES['default']['NAME'])]
SEQUENCE_VIZ_ROOT=Path(tempfile.gettempdir())/('stoich_sequence_viz_test_'+str(os.getpid()))
SEQUENCE_VIZ_ON_DEMAND=False
SEQUENCE_VIZ_GENOME_ENABLED=True
SEQUENCE_VIZ_TRANSCRIPTOME_ENABLED=True
