from .settings_sequence_viz_browser import *
INTEGRATION_VIZ_ENABLED=True
INTEGRATION_VIZ_ON_DEMAND=True
CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache','LOCATION':'integration-viz-acceptance'}}
