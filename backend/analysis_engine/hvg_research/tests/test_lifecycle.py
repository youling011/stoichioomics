import os,sys,json,time,subprocess,tempfile,ctypes
from pathlib import Path
from django.test import SimpleTestCase
from backend.analysis_engine.hvg_research.process_guard import terminate_tree
class OwnedProcessTests(SimpleTestCase):
 def test_owned_grandchild_tree_is_terminated(self):
  if os.name!='nt':self.skipTest('Windows process-tree scenario')
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'pid.json';code="import subprocess,sys,time,json,os; from pathlib import Path; c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); Path(sys.argv[1]).write_text(json.dumps({'parent':os.getpid(),'child':c.pid})); time.sleep(120)"
   proc=subprocess.Popen([sys.executable,'-c',code,str(p)],creationflags=subprocess.CREATE_NO_WINDOW)
   try:
    for _ in range(100):
     if p.exists():break
     time.sleep(.05)
    ids=json.loads(p.read_text());k=ctypes.WinDLL('kernel32');k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];k.OpenProcess.restype=ctypes.c_void_p;k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];k.CloseHandle.argtypes=[ctypes.c_void_p]
    handles=[k.OpenProcess(0x00100000,False,ids[x]) for x in ['parent','child']]
    terminate_tree(proc)
    for h in handles:
     if h:self.assertEqual(k.WaitForSingleObject(h,5000),0);k.CloseHandle(h)
   finally:
    if proc.poll() is None:terminate_tree(proc)
 def test_owner_death_watchdog_exits_actual_worker(self):
  if os.name!='nt':self.skipTest('Windows owner-process scenario')
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'pid.json';code="import subprocess,sys,os,time,json; from pathlib import Path; env=os.environ.copy(); env['HVG_RESEARCH_OWNER_PID']=str(os.getpid()); c=subprocess.Popen([sys.executable,'-c','from backend.analysis_engine.hvg_research.process_guard import watch_owner; import time; watch_owner(); time.sleep(120)'],env=env); Path(sys.argv[1]).write_text(json.dumps({'owner':os.getpid(),'child':c.pid})); time.sleep(120)"
   proc=subprocess.Popen([sys.executable,'-c',code,str(p)],creationflags=subprocess.CREATE_NO_WINDOW)
   try:
    for _ in range(100):
     if p.exists():break
     time.sleep(.05)
    ids=json.loads(p.read_text());time.sleep(1)
    k=ctypes.WinDLL('kernel32');k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];k.OpenProcess.restype=ctypes.c_void_p;k.TerminateProcess.argtypes=[ctypes.c_void_p,ctypes.c_uint];k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];k.CloseHandle.argtypes=[ctypes.c_void_p]
    owner=k.OpenProcess(0x0001|0x00100000,False,ids['owner']);child=k.OpenProcess(0x00100000,False,ids['child']);self.assertTrue(owner);self.assertTrue(child)
    self.assertTrue(k.TerminateProcess(owner,99));self.assertEqual(k.WaitForSingleObject(child,5000),0);k.CloseHandle(owner);k.CloseHandle(child);proc.wait(timeout=10)
   finally:
    if proc.poll() is None:terminate_tree(proc)
