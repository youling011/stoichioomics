"""Explicit immutable read layers and separate writable derivatives.

Never changes global settings, original records, pathlib, or scientific identity.
"""
from dataclasses import dataclass
from pathlib import Path
from contextlib import contextmanager
from functools import wraps
from collections import OrderedDict
from threading import RLock
import hashlib,json,os,sys,time,uuid
from django.conf import settings
from .host_paths import Path as HostPath
from .request_cache import resolve as resolve_path

NAMES={
 'proteome':('PROTEOME_VIZ_READ_ROOTS','proteome_visuals_v3'),
 'sequence':('SEQUENCE_VIZ_READ_ROOTS','sequence_visuals_v1'),
 'integration':('INTEGRATION_VIZ_READ_ROOTS','integration_visuals_v1'),
 'home_atlas':('HOME_ATLAS_VIZ_READ_ROOTS','home_atlas_visuals/v1'),
 'compare':('COMPARE_CORE_READ_ROOTS','compare_core'),
 'feature_profiles':('STOICH_FEATURE_PROFILE_READ_ROOTS','feature_profiles'),
 'feature_qc':('STOICH_FEATURE_QC_READ_ROOTS','feature_qc'),
 'feature_home':('STOICH_FEATURE_HOME_READ_ROOTS','feature_home_spotlight'),
 'feature_exports':('STOICH_FEATURE_EXPORT_READ_ROOTS','feature_exports'),
}

@dataclass(frozen=True)
class ArtifactLocation:
 namespace:str
 origin:str
 root:Path
 target:Path
 artifact_version:str=''
 source_identity:str=''

def read_roots(namespace,write_root):
 key,folder=NAMES[namespace];value=getattr(settings,key,os.environ.get(key))
 if value is None:
  base=getattr(settings,'DEPLOYMENT_HISTORICAL_ROOT',os.environ.get('DEPLOYMENT_HISTORICAL_ROOT',getattr(settings,'STOICH_PROJECT_ROOT',settings.BASE_DIR)))
  value=[str(HostPath(base)/'runtime'/folder)] if base else []
 elif isinstance(value,str):
  try:value=json.loads(value)
  except ValueError:raise ValueError(key+'_requires_JSON_array')
 if not isinstance(value,(list,tuple)):raise ValueError(key+'_requires_array')
 roots=[resolve_path(write_root)]
 for item in value:
  p=HostPath(item)
  if not p.is_absolute() or '..' in p.parts:raise ValueError('invalid_historical_root')
  p=resolve_path(p)
  if p not in roots:roots.append(p)
 return tuple(roots)

def contained(root,relative):
 root=resolve_path(root);relative=Path(str(relative).replace('\\','/'))
 if relative.is_absolute() or '..' in relative.parts:raise ValueError('invalid_artifact_relative_path')
 p=resolve_path(root/relative)
 if not p.is_relative_to(root):raise ValueError('artifact_path_escape')
 return p

def locate(namespace,write_root,relative,required=True):
 for i,root in enumerate(read_roots(namespace,write_root)):
  p=contained(root,relative)
  if p.exists():return ArtifactLocation(namespace,'writable' if i==0 else 'historical',root,p)
 if required:raise FileNotFoundError('artifact_not_found')
 return None

def source_root(namespace,write_root,target):
 target=resolve_path(target)
 for root in read_roots(namespace,write_root):
  if target.is_relative_to(root):return root
 raise ValueError('unregistered_artifact_root')

def pointer_candidates(namespace,write_root,relative,reader):
 for i,root in enumerate(read_roots(namespace,write_root)):
  p=contained(root,relative)
  if p.is_file():
   value=reader(p)
   if not isinstance(value,dict):raise ValueError('invalid_publication_pointer')
   yield {**value,'_artifact_root':str(root),'_artifact_origin':'writable' if i==0 else 'historical'}

def pointer_target(namespace,write_root,pointer):
 root=resolve_path(pointer.get('_artifact_root',write_root))
 if root not in read_roots(namespace,write_root):raise ValueError('invalid_pointer_root')
 return contained(root,pointer['path'])

def lookup_publication(namespace,write_root,pointer_relative,reader,version='',version_relative=None,validator=None):
 candidates=list(pointer_candidates(namespace,write_root,pointer_relative,reader))
 if namespace=='integration':
  for p in candidates:p['path']=(Path(pointer_relative).parent/'versions'/p['artifact_version']).as_posix()
 if version:
  candidates=[p for p in candidates if p.get('artifact_version')==version]
  for i,root in enumerate(read_roots(namespace,write_root)):
   if version_relative:
    index=contained(root,version_relative)
    if index.is_file():candidates.append({**reader(index),'_artifact_root':str(root),'_artifact_origin':'writable' if i==0 else 'historical'})
   elif namespace=='integration':
    p=contained(root,Path(pointer_relative).parent/'versions'/version/'manifest.json')
    if p.is_file():candidates.append({'artifact_version':version,'path':p.parent.relative_to(root).as_posix(),'_artifact_root':str(root),'_artifact_origin':'writable' if i==0 else 'historical'})
 if not candidates:raise FileNotFoundError('artifact_expired' if version else 'not_prepared')
 selected=None;identities={}
 for pointer in candidates:
  target=pointer_target(namespace,write_root,pointer);manifest_path=target/'manifest.json'
  if not manifest_path.is_file():raise FileNotFoundError('artifact_expired')
  from .artifact_integrity import verify_package
  if getattr(settings,'DEPLOYMENT_INTEGRITY_INDEX',None) and pointer.get('_artifact_origin')=='historical' and not verify_package(target):raise ValueError('artifact_integrity_receipt_missing')
  manifest=reader(manifest_path);identity=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest();v=pointer['artifact_version']
  if v in identities and identities[v]!=identity:raise ValueError('artifact_version_content_conflict')
  identities[v]=identity
  if selected is None and (validator is None or validator(manifest,target)):selected=pointer
 return selected or candidates[0]

def derivative_root(namespace,write_root,target,version=''):
 target=resolve_path(target);root=source_root(namespace,write_root,target)
 # All derivatives live outside immutable source packages, even in the write layer.
 identity=hashlib.sha256((str(root)+'\0'+target.relative_to(root).as_posix()+'\0'+version).encode()).hexdigest()
 p=contained(write_root,'derived/'+identity);p.mkdir(parents=True,exist_ok=True);return p

@contextmanager
def file_lock(path,timeout=60):
 """Kernel-owned lock; automatically released on process death on both hosts."""
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('a+b') as handle:
  if handle.seek(0,2)==0:handle.write(b'0');handle.flush()
  end=time.monotonic()+timeout
  while True:
   try:
    handle.seek(0)
    if os.name=='nt':
     import msvcrt;msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
    else:
     import fcntl;fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    break
   except (OSError,BlockingIOError):
    if time.monotonic()>=end:raise TimeoutError('artifact_lock_timeout')
    time.sleep(.03)
  try:yield
  finally:
   handle.seek(0)
   if os.name=='nt':
    import msvcrt;msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
   else:
    import fcntl;fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

def logical_path_key(value):
 from backend.apps.stoichdb.feature_sources.resolver import alias_key
 return alias_key(value)

def same_source_signatures(stored,current):
 """Only approved logical path representation differs; all other cells exact."""
 if isinstance(stored,dict) and isinstance(current,dict):
  if stored.keys()!=current.keys():return False
  return all((logical_path_key(stored[k])==logical_path_key(current[k]) if k=='path' and isinstance(stored[k],str) and isinstance(current[k],str) else same_source_signatures(stored[k],current[k])) for k in stored)
 return stored==current

_cache=OrderedDict();_lock=RLock();_cache_bytes=0
def _weight(value,seen=None):
 seen=set() if seen is None else seen
 if id(value) in seen:return 0
 seen.add(id(value))
 if hasattr(value,'nbytes'):return int(value.nbytes)+sys.getsizeof(value)
 n=sys.getsizeof(value)
 if isinstance(value,dict):return n+sum(_weight(k,seen)+_weight(v,seen) for k,v in value.items())
 if isinstance(value,(list,tuple)):return n+sum(_weight(v,seen) for v in value)
 return n

def budget_cache(filename):
 def decorate(fn):
  label=fn.__module__+'.'+fn.__name__
  @wraps(fn)
  def call(target,*args):
   global _cache_bytes
   p=Path(target)/filename if filename else Path(target)
   from .artifact_integrity import verify_file
   verify_file(p)
   s=p.stat()
   change=s.st_ctime_ns
   if os.name=='nt':
    from backend.apps.stoichdb.feature_sources.asset_state import change_token
    change=change_token(p)['change_ns']
   key=(label,str(resolve_path(p)),s.st_dev,s.st_ino,s.st_mtime_ns,change,s.st_size,args)
   with _lock:
    if key in _cache:
     value,n=_cache.pop(key);_cache[key]=(value,n);return value
    value=fn(target,*args);n=_weight(value);limit=int(getattr(settings,'ARTIFACT_MEMORY_CACHE_BYTES',128*1024**2)) if settings.configured else 128*1024**2
    if n<=limit:
     while _cache and _cache_bytes+n>limit:
      _,(_,weight)=_cache.popitem(last=False);_cache_bytes-=weight
     _cache[key]=(value,n);_cache_bytes+=n
    return value
  def clear():
   global _cache_bytes
   with _lock:
    for key in list(_cache):
     if key[0]==label:_cache_bytes-=_cache.pop(key)[1]
  call.cache_clear=clear
  return call
 return decorate
