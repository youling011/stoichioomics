"""Owned worker process trees, including Windows virtualenv launcher children."""
import os,subprocess,threading,time
def terminate_tree(proc):
 if proc.poll() is not None:return
 if os.name=='nt':
  import ctypes
  from ctypes import wintypes as w
  k=ctypes.WinDLL('kernel32',use_last_error=True)
  class Entry(ctypes.Structure):
   _fields_=[('dwSize',w.DWORD),('cntUsage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('name',w.WCHAR*260)]
  k.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];k.CreateToolhelp32Snapshot.restype=w.HANDLE;k.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];k.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)];k.CloseHandle.argtypes=[w.HANDLE];k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE;k.TerminateProcess.argtypes=[w.HANDLE,w.UINT];k.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
  snapshot=k.CreateToolhelp32Snapshot(2,0);parents={}
  if snapshot and snapshot!=ctypes.c_void_p(-1).value:
   entry=Entry();entry.dwSize=ctypes.sizeof(entry)
   try:
    ok=k.Process32FirstW(snapshot,ctypes.byref(entry))
    while ok:parents[entry.pid]=entry.parent;ok=k.Process32NextW(snapshot,ctypes.byref(entry))
   finally:k.CloseHandle(snapshot)
  levels={proc.pid:0}
  for _ in range(32):
   additions={pid:levels[parent]+1 for pid,parent in parents.items() if parent in levels and pid not in levels}
   if not additions:break
   levels.update(additions)
  for pid in sorted(levels,key=levels.get,reverse=True):
   h=k.OpenProcess(0x0001|0x00100000,False,pid)
   if h:
    try:k.TerminateProcess(h,130);k.WaitForSingleObject(h,5000)
    finally:k.CloseHandle(h)
  if proc.poll() is None:proc.terminate()
 else:proc.terminate()
 proc.wait(timeout=30)
def watch_owner():
 owner=int(os.environ.get('HVG_RESEARCH_OWNER_PID','0'))
 if not owner:return
 if os.name=='nt':
  import ctypes
  k=ctypes.WinDLL('kernel32',use_last_error=True);k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];k.OpenProcess.restype=ctypes.c_void_p;k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];k.WaitForSingleObject.restype=ctypes.c_ulong;k.CloseHandle.argtypes=[ctypes.c_void_p]
  handle=k.OpenProcess(0x00100000,False,owner)
  if not handle:raise RuntimeError('Cannot monitor research owner process')
  def watch():
   try:
    while True:
     if k.WaitForSingleObject(handle,1000)==0:os._exit(125)
   finally:k.CloseHandle(handle)
 else:
  def watch():
   while True:
    try:os.kill(owner,0)
    except ProcessLookupError:os._exit(125)
    time.sleep(1)
 threading.Thread(target=watch,name='hvg-owner-watch',daemon=True).start()
