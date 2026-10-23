from .settings import *
import copy
DATABASES=copy.deepcopy(DATABASES)
DATABASES['default'].setdefault('OPTIONS',{})['options']='-c default_transaction_read_only=on'
SEQUENCE_VIZ_GENOME_ENABLED=True
SEQUENCE_VIZ_TRANSCRIPTOME_ENABLED=True
COMPARE_CORE_AUTOSTART=False
CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache','LOCATION':'sequence-viz-readonly-acceptance'}}
