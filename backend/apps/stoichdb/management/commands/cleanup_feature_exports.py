import json,shutil
from pathlib import Path
from datetime import datetime,timezone
from django.core.management.base import BaseCommand,CommandError
from backend.apps.common.maintenance import submission
from backend.apps.common.artifact_locations import file_lock,contained
class Command(BaseCommand):
 help='Dry-run by default. Only terminal owned writable-layer exports with explicit expiry.'
 def add_arguments(self,p):p.add_argument('--apply',action='store_true')
 def handle(self,*args,**o):
  from backend.apps.stoichdb.feature_hub.export import EXPORT_ROOT,_job_dir
  actions=[];now=datetime.now(timezone.utc)
  with submission(),file_lock(EXPORT_ROOT/'cleanup.lock'):
   for path in sorted(EXPORT_ROOT.glob('fh_*/status.json')):
    value=json.loads(path.read_text('utf8'));eid=path.parent.name
    if value.get('export_id')!=eid or not value.get('created_at') or not value.get('expires_at') or value.get('status') not in ['completed','failed','interrupted']:continue
    expiry=datetime.fromisoformat(value['expires_at'])
    if expiry.tzinfo is None or expiry>=now:continue
    folder=_job_dir(eid).resolve()
    if folder!=contained(EXPORT_ROOT,eid) or folder.is_symlink() or any(p.is_symlink() for p in folder.rglob('*')):raise CommandError('Unsafe export path')
    actions.append({'export_id':eid,'expires_at':value['expires_at'],'applied':bool(o['apply'])})
    if o['apply']:shutil.rmtree(folder)
  self.stdout.write(json.dumps({'dry_run':not o['apply'],'actions':actions}))
