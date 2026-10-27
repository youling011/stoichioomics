"""Read-only guard for an explicit stop/restart of this repository's Compose stack."""
import json
import os
from pathlib import Path
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE','backend.config.settings_production')
django.setup()
from django.db import connection,transaction
from backend.apps.jobs.models import AnalysisJob
from backend.apps.stoichdb.compare_core.models import CompareRun
with transaction.atomic():
    with connection.cursor() as cursor:cursor.execute('SET TRANSACTION READ ONLY')
    active=AnalysisJob.objects.filter(status__in=['UPLOADING','RUNNING','CANCEL_REQUESTED']).exists()
    active=active or CompareRun.objects.filter(status__in=['queued','running']).exists()
for root in [Path('/opt/local/state/runtime')]:
    for pattern in ['job.json','status.json','run.json','requests/*.json']:
        for path in root.rglob(pattern):
            try:
                row=json.loads(path.read_text())
                active=active or str(row.get('status',row.get('readiness',''))).upper() in {'RUNNING','QUEUED','PENDING','STARTED'}
            except (ValueError,OSError):pass
if active:
    raise SystemExit('Stop refused: active application tasks exist; wait for completion first.')
print('No active tasks found in the configured database and owned runtime state.')
