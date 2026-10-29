"""Reuse a verified check within one HTTP call; never across requests or tasks."""
from contextvars import ContextVar
from functools import wraps
from .request_timing import stage
_current=ContextVar('stoich_request_checks',default=None)

def request_scope(fn):
 @wraps(fn)
 def call(*args,**kwargs):
  token=_current.set({})
  try:return fn(*args,**kwargs)
  finally:_current.reset(token)
 return call

def once(key,fn):
 values=_current.get()
 if values is None:
  with stage('source'):return fn()
 if key not in values:
  with stage('source'):values[key]=fn()
 return values[key]

def resolve(path):
 """Reuse canonical spelling only while both native file identities still match.

 Every access stats the requested path; symlink/atomic replacement changes the
 key. A different canonical spelling is independently checked before reuse.
 Missing/write paths and all non-HTTP callers keep normal Path.resolve.
 """
 from pathlib import Path
 import os
 p=Path(path)
 if _current.get() is None:return p.resolve()
 def identity(value):
  s=value.stat();v=(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
  if os.name=='nt':
   from backend.apps.stoichdb.feature_sources.asset_state import change_token
   v+= (change_token(value)['change_ns'],)
  return v
 try:before=identity(p)
 except FileNotFoundError:return p.resolve()
 def fresh():
  import stat
  values=_current.get();directories=values.setdefault('canonical-directories',{})
  result=None
  # Reuse only directory prefixes already resolved in this same HTTP call.
  # Check their native identity again and inspect every remaining component;
  # any symlink/reparse point uses the original complete resolver.
  for base,stamp in sorted(directories.items(),key=lambda item:len(item[0].parts),reverse=True):
   if not p.is_absolute() or not p.is_relative_to(base):continue
   relative=p.relative_to(base)
   if '..' in relative.parts:break
   try:
    if identity(base)!=stamp:break
    candidate=base
    for part in relative.parts:
     candidate=candidate/part;s=candidate.lstat()
     if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&0x400:break
    else:
     if identity(base)==stamp:result=candidate
   except OSError:pass
   break
  if result is None:result=p.resolve()
  if identity(result)!=before:raise ValueError('artifact_path_changed_during_resolution')
  if stat.S_ISDIR(before[2]):directories[result]=before
  return result
 result=once(('canonical-path',str(p.absolute()),before),fresh)
 if result!=p and identity(result)!=before:raise ValueError('artifact_path_changed_during_resolution')
 return result
