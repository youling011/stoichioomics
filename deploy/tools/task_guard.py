"""Read-only complete current-task inventory for the repository Compose stack."""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','deploy.local_settings')
django.setup()
from deploy.task_inventory import inventory
result=inventory(include_requests=False)
if result.get('active') or result.get('errors'):
    raise SystemExit('Stop refused: active tasks or inventory errors exist; inspect deployment task inventory first.')
print('Task inventory permits an explicit stop.')
