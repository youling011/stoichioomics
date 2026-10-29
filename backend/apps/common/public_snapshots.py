"""Offline public payload snapshots. Private jobs never enter this namespace."""
import hashlib,json,uuid,os,time
from pathlib import Path
from functools import wraps
from django.conf import settings
from backend.apps.common.atomic_json import atomic_write_json
from backend.apps.common.artifact_locations import file_lock,budget_cache
from backend.apps.common.maintenance import state_root

class PublicSnapshotPending(RuntimeError):pass

def root():return state_root()/'runtime/public_snapshots'
def revision():
 from backend.apps.stoichdb.models import DataRelease
 releases=list(DataRelease.objects.filter(is_active=True).values('release_id','version','manifest_sha256','updated_at'))
 p=root()/'data-generation.json';generation=p.read_text() if p.is_file() else ''
 files=[]
 for relative in ['backend/apps/stoichdb/services.py','backend/apps/stoichdb/case_studies.py','backend/apps/stoichdb/function_annotations.py','backend/apps/stoichdb/phylogeny.py']:
  p=Path(settings.BASE_DIR)/relative;stat=p.stat();files.append([relative,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns])
 return hashlib.sha256(json.dumps([releases,generation,files],sort_keys=True,default=str).encode()).hexdigest()

@budget_cache('')
def _read(path,expected_revision=None):return json.loads(Path(path).read_text('utf8'))

def snapshot(name):
 def decorate(fn):
  @wraps(fn)
  def call(*args,**kwargs):
   if getattr(settings,'DEPLOYMENT_PUBLIC_SNAPSHOTS',False) and not args and not kwargs:
    p=root()/(name+'.json')
    if p.is_file():
     expected=revision();value=_read(str(p),expected)
     if value.get('format')=='public-payload-snapshot-v1' and value['revision']==expected==revision():return value['payload']
    if name=='quality':raise PublicSnapshotPending('Public quality snapshot is being refreshed for the active release. Retry shortly.')
   return fn(*args,**kwargs)
  call.snapshot_name=name
  if hasattr(fn,'cache_clear'):call.cache_clear=fn.cache_clear
  return call
 return decorate

def refresh(fn):
 name=fn.snapshot_name
 from backend.apps.common.task_execution import heavy_compute_slot
 with file_lock(root()/(name+'.lock'),timeout=3600),heavy_compute_slot():
  import inspect
  before=revision();payload=inspect.unwrap(fn)();after=revision()
  if before!=after:raise ValueError('Data generation changed during public snapshot build')
  value={'format':'public-payload-snapshot-v1','name':name,'revision':before,'created_at':time.time(),'payload':payload}
  atomic_write_json(root()/(name+'.json'),value)
  return {'name':name,'revision':before,'bytes':(root()/(name+'.json')).stat().st_size}

def invalidate_public_data():
 root().mkdir(parents=True,exist_ok=True)
 atomic_write_json(root()/'data-generation.json',{'generation':uuid.uuid4().hex,'created_at':time.time()})
