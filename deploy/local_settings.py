"""Local Docker overlay; inherits the existing production adaptation."""
import os
from backend.config.settings_production import *  # noqa: F403

LOCAL_READ_ONLY=os.environ.get('STOICH_LOCAL_READ_ONLY','1')=='1'
if LOCAL_READ_ONLY:
    MIDDLEWARE=['deploy.local_readonly.LocalReadOnlyMiddleware',*MIDDLEWARE]
    DATABASES['default']['OPTIONS']['options']='-c default_transaction_read_only=on'
    # Prevent read requests from automatically scheduling work in the business DB.
    COMPARE_CORE_AUTOSTART=False
    PROTEOME_VIZ_ON_DEMAND=False
    SEQUENCE_VIZ_ON_DEMAND=False
    INTEGRATION_VIZ_ON_DEMAND=False
