"""Optional telemetry with standard-library Windows APIs, no extra packages."""
def memory():
    try:
        import os,ctypes
        if os.name=='nt':
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(k,ctypes.c_size_t) for k in ['peak_working','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile']]
            k=ctypes.WinDLL('kernel32');k.GetCurrentProcess.restype=wintypes.HANDLE;p=ctypes.WinDLL('psapi');p.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD];c=Counters();c.cb=ctypes.sizeof(c)
            if not p.GetProcessMemoryInfo(k.GetCurrentProcess(),ctypes.byref(c),c.cb):raise OSError('GetProcessMemoryInfo_failed')
            return {'rss_bytes':c.working,'peak_rss_bytes':c.peak_working,'measurement':'Windows process working set; peak is process lifetime'}
        import resource
        return {'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,'measurement':'getrusage process lifetime'}
    except Exception as e:return {'measurement':'unavailable','telemetry_reason':str(e)}
def available_physical():
    try:
        import ctypes,os
        if os.name!='nt':return None
        class Status(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(k,ctypes.c_ulonglong) for k in ['total','free','tp','ap','tv','av','ae']]
        m=Status();m.length=ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):return m.free
    except Exception:pass
    return None
