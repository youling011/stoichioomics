"""Process-local Linux acceptance sandbox; no source ACL/path changes.

Explicit allow lists deny physical Core to Python AND native Arrow opens.
This helper is opt-in test infrastructure and is never enabled by the app.
"""
import ctypes,os
from pathlib import Path

def deny_unlisted_reads(allowed):
    if os.name!='posix':raise RuntimeError('Linux Landlock acceptance is required')
    libc=ctypes.CDLL(None,use_errno=True)
    libc.syscall.restype=ctypes.c_long
    create,add,restrict=444,445,446
    abi=libc.syscall(create,ctypes.c_void_p(),0,1)
    if abi<1:raise OSError(ctypes.get_errno(),'Landlock unavailable; no denial proof was run')
    read_file,read_dir=1<<2,1<<3
    class Ruleset(ctypes.Structure):_fields_=[('handled_access_fs',ctypes.c_uint64)]
    class Beneath(ctypes.Structure):_pack_=1;_fields_=[('allowed_access',ctypes.c_uint64),('parent_fd',ctypes.c_int32)]
    rules=Ruleset(read_file|read_dir)
    fd=libc.syscall(create,ctypes.byref(rules),ctypes.sizeof(rules),0)
    if fd<0:raise OSError(ctypes.get_errno(),'Cannot create read-denial sandbox')
    try:
        for raw in allowed:
            path=Path(raw)
            if not path.exists():continue
            parent=os.open(path,os.O_PATH|os.O_CLOEXEC)
            try:
                rule=Beneath(read_file|(read_dir if path.is_dir() else 0),parent)
                if libc.syscall(add,fd,1,ctypes.byref(rule),0)<0:raise OSError(ctypes.get_errno(),'Cannot add exact allowed read path '+str(path))
            finally:os.close(parent)
        if libc.prctl(38,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),'Cannot enable process-local no_new_privs')
        if libc.syscall(restrict,fd,0)<0:raise OSError(ctypes.get_errno(),'Cannot apply read-denial sandbox')
    finally:os.close(fd)
    return {'mechanism':'Linux Landlock','abi':abi,'native_reads_restricted':True,'source_acl_modified':False}
