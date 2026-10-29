"""Immutable-file receipts, checked against native host change metadata.

Full SHA receipts are generated offline. Requests use exact registered paths;
changed metadata forces SHA verification and never silently selects another file.
"""
import hashlib,sqlite3
from pathlib import Path
from functools import lru_cache
from django.conf import settings
from .request_cache import resolve as resolve_path

@lru_cache(maxsize=8192)
def _check(index,index_revision,path,size,mtime,ctime):
 with sqlite3.connect('file:'+Path(index).as_posix()+'?mode=ro',uri=True) as c:
  row=c.execute('SELECT sha256,bytes,mtime_ns,ctime_ns FROM files WHERE path=?',(path,)).fetchone()
 if row is None:return False
 sha,expected_size,expected_mtime,expected_ctime=row
 if (size,mtime,ctime)!=(expected_size,expected_mtime,expected_ctime):
  p=Path(path);before=p.stat()
  with p.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
  after=p.stat()
  if actual!=sha or (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('artifact_checksum_mismatch')
 return True

def verify_file(path,required=False):
 index=getattr(settings,'DEPLOYMENT_INTEGRITY_INDEX',None) if settings.configured else None
 if not index:
  if required:raise ValueError('artifact_integrity_receipt_missing')
  return False
 p=resolve_path(path);index=Path(index);s=p.stat();i=index.stat()
 ok=_check(str(index),(i.st_dev,i.st_ino,i.st_size,i.st_mtime_ns,i.st_ctime_ns),str(p),s.st_size,s.st_mtime_ns,s.st_ctime_ns)
 if required and not ok:raise ValueError('artifact_not_in_integrity_receipts')
 return ok

def verify_package(target):
 target=Path(target)
 return verify_file(target/'manifest.json') and verify_file(target/'audit.json')

def verify_cache_identity(path,identity):
 index=getattr(settings,'DEPLOYMENT_INTEGRITY_INDEX',None) if settings.configured else None
 if not index:return False
 verify_file(path,required=True)
 with sqlite3.connect('file:'+Path(index).as_posix()+'?mode=ro',uri=True) as c:
  row=c.execute('SELECT source_identity FROM files WHERE path=?',(str(resolve_path(path)),)).fetchone()
 if not row or row[0]!=identity:raise ValueError('historical_cache_source_identity_mismatch')
 return True
