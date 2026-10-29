"""Bounded read-only SHA validation below captured directory handles.

Linux uses openat/O_NOFOLLOW and a small directory-handle cache. It checks
every file's full bytes and detects root changes, avoiding repeatedly resolving
the same long NTFS mount prefix for thousands of immutable manifest objects.
"""
import os,stat,hashlib
from pathlib import Path
from collections import OrderedDict
class SourceVerifier:
 def __init__(self):self.roots={};self.directories=OrderedDict()
 def __enter__(self):return self
 def __exit__(self,*args):
  for fd in list(self.directories.values())+list(self.roots.values()):os.close(fd)
  self.directories.clear();self.roots.clear()
 def _directory(self,root,parts):
  if root not in self.roots:self.roots[root]=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
  if not parts:return self.roots[root]
  key=(root,parts)
  if key in self.directories:
   fd=self.directories.pop(key);self.directories[key]=fd;return fd
  parent=self._directory(root,parts[:-1]);fd=os.open(parts[-1],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent);self.directories[key]=fd
  while len(self.directories)>128:os.close(self.directories.popitem(last=False)[1])
  return fd
 def sha(self,root,relative):
  root=Path(root);relative=Path(relative)
  if relative.is_absolute() or '..' in relative.parts or not relative.parts or (os.name!='nt' and '\\' in str(relative)):raise ValueError('Source path escape')
  if os.name=='nt':
   p=(root/relative).resolve()
   if not p.is_relative_to(root):raise ValueError('Source symlink escape')
   with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
  try:
   parent=self._directory(str(root),relative.parts[:-1]);fd=os.open(relative.parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
  except OSError as exc:raise ValueError('Source directory/file cannot be opened safely: '+str(relative)) from exc
  with os.fdopen(fd,'rb') as f:
   before=os.fstat(f.fileno())
   if not stat.S_ISREG(before.st_mode):raise ValueError('Source must be a regular file')
   digest=hashlib.file_digest(f,'sha256').hexdigest();after=os.fstat(f.fileno())
  if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('Source changed during checksum validation')
  return digest
 def verify_roots(self):
  for name,fd in self.roots.items():
   current=os.stat(name,follow_symlinks=False);opened=os.fstat(fd)
   if (current.st_dev,current.st_ino)!=(opened.st_dev,opened.st_ino):raise ValueError('Source root changed during validation')
