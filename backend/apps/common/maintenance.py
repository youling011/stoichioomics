"""Shared admission fence; lifecycle reads/cancellation stay available."""
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json,os,time,uuid
from django.conf import settings
from django.http import JsonResponse
from .artifact_locations import file_lock
from .atomic_json import atomic_write_json
_depth=ContextVar('submission_fence_depth',default=0)

class MaintenanceActive(RuntimeError):pass

def state_root():
 return Path(getattr(settings,'DEPLOYMENT_STATE_ROOT',Path(getattr(settings,'STOICH_RUNTIME_ROOT',settings.BASE_DIR/'runtime'))/'deployment'))
def state_path():return state_root()/'maintenance.json'
def state():
 p=state_path()
 if not p.is_file():return {'format':'deployment-maintenance-v1','state':'normal','generation':0,'owner':None}
 try:value=json.loads(p.read_text())
 except (ValueError,OSError) as e:raise MaintenanceActive('maintenance_state_unreadable') from e
 if value.get('format')!='deployment-maintenance-v1' or value.get('state') not in ['normal','draining','maintenance'] or not isinstance(value.get('generation'),int):raise MaintenanceActive('invalid_maintenance_state')
 if value['state']!='normal' and (not isinstance(value.get('owner'),str) or not value['owner'] or not isinstance(value.get('drain_generation'),int)):raise MaintenanceActive('invalid_maintenance_owner')
 return value
@contextmanager
def submission():
 if _depth.get():yield state();return
 with file_lock(state_root()/'submission.lock',timeout=600):
  current=state()
  if current['state']!='normal':raise MaintenanceActive('Platform maintenance: new submissions are temporarily paused')
  token=_depth.set(1)
  try:yield current
  finally:_depth.reset(token)
def guarded_submission(fn):
 @wraps(fn)
 def call(*args,**kwargs):
  with submission():return fn(*args,**kwargs)
 return call
def enter(owner=None):
 owner=owner or uuid.uuid4().hex
 with file_lock(state_root()/'submission.lock'):
  current=state()
  if current['state']!='normal':
   if current.get('owner')!=owner:raise MaintenanceActive('Maintenance is held by another owner')
   return current
  value={'format':'deployment-maintenance-v1','state':'draining','owner':owner,'generation':current['generation']+1,'drain_generation':current['generation'],'created_at':time.time()};atomic_write_json(state_path(),value);return value
def advance(owner,generation):
 with file_lock(state_root()/'submission.lock'):
  value=state()
  if value.get('owner')!=owner or value['generation']!=int(generation):raise MaintenanceActive('Maintenance ownership mismatch')
  value.update(state='maintenance');atomic_write_json(state_path(),value);return value
def leave(owner,generation):
 with file_lock(state_root()/'submission.lock'):
  value=state()
  if value.get('owner')!=owner or value['generation']!=int(generation):raise MaintenanceActive('Maintenance ownership mismatch')
  value.update(state='normal',owner=None,completed_at=time.time());atomic_write_json(state_path(),value);return value
def accepts_record(record):
 current=state();g=record.get('generation',0)
 return current['state']=='normal' or g<=current.get('drain_generation',-1)

class SubmissionFenceMiddleware:
 def __init__(self,get_response):self.get_response=get_response
 def __call__(self,request):
  path=request.path
  # These POSTs only inspect existing data or cancel existing authorized work.
  readonly_posts=['/api/stoichdb/id-mapping/batch-resolve/','/api/stoichdb/entities/batch-report/','/api/stoichdb/analysis/enrichment/','/api/stoichdb/feature-hub/alignment/','/api/sequence-analysis/prevalidate/','/api/registry/compare/']
  write=request.method not in ['GET','HEAD','OPTIONS'] and path.startswith('/api/') and not path.endswith('/cancel/') and path not in readonly_posts
  if not write:return self.get_response(request)
  try:
   with submission():return self.get_response(request)
  except MaintenanceActive:
   response=JsonResponse({'ok':False,'error':{'message':'New submissions are paused for platform maintenance. Existing task status, results and cancellation remain available.','details':{'code':'deployment_maintenance'}}},status=503);response['Retry-After']='30';return response
