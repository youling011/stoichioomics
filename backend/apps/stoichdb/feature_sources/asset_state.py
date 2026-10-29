"""Read-only asset change tokens, including NTFS metadata-change time.

Windows Python 3.11 st_ctime is file creation time, so it cannot detect a writer
restoring mtime. FileBasicInfo.ChangeTime detects that case without hashing each
HTTP request. Linux uses its native metadata change time. Never changes ACLs.
"""
import os
from pathlib import Path

def change_token(path):
    if os.name!='nt':return {'host':'posix','change_ns':Path(path).stat().st_ctime_ns}
    import ctypes
    from ctypes import wintypes
    class BasicInfo(ctypes.Structure):
        _fields_=[('CreationTime',ctypes.c_longlong),('LastAccessTime',ctypes.c_longlong),
                  ('LastWriteTime',ctypes.c_longlong),('ChangeTime',ctypes.c_longlong),('Attributes',wintypes.DWORD)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    create=kernel.CreateFileW;create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];create.restype=wintypes.HANDLE
    read=kernel.GetFileInformationByHandleEx;read.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD];read.restype=wintypes.BOOL
    close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
    handle=create(str(Path(path).resolve()),0x80,7,None,3,0,None)
    if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:
        info=BasicInfo()
        if not read(handle,0,ctypes.byref(info),ctypes.sizeof(info)):raise ctypes.WinError(ctypes.get_last_error())
        return {'host':'nt','change_ns':int(info.ChangeTime)*100-11644473600000000000}
    finally:close(handle)
