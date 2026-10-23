from contextlib import contextmanager
from pathlib import Path
import os
class RunConflict(RuntimeError):pass
class ResearchCancelled(InterruptedError):pass
@contextmanager
def run_lock(folder):
 p=Path(folder)/'.execution.lock';p.parent.mkdir(parents=True,exist_ok=True)
 f=p.open('a+b');f.seek(0);f.write(b'0');f.flush();f.seek(0)
 try:
  try:
   if os.name=='nt':
    import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
   else:
    import fcntl;fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  except OSError as e:raise RunConflict('Another research process owns this workspace') from e
  try:yield
  finally:
   f.seek(0)
   if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
   else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)
 finally:f.close()
