"""Opt-in I/O at reviewed consumers. Physical and logical metadata stay distinct."""
from .discovery import logical_glob,logical_rglob
from contextlib import closing
from dataclasses import dataclass
import io
from backend.apps.common.host_paths import Path,mapped_path
from .resolver import (logical_source,open_source,source_available,source_header,
 source_sha256,source_signature,read_csv,read_scope,clear_binding_cache)

def source_exists(path):
    try:source=logical_source(path)
    except (OSError,ValueError):return False
    return bool(source) or Path(path).exists()

@dataclass(frozen=True)
class SourceMetadata:
    size: int
    mtime_ns: int
    mtime: float
    ino: int
    logical: bool
    physical_dependency: dict

def source_metadata(path):
    source=logical_source(path)
    if source:
        old=source.legacy_metadata()
        return SourceMetadata(old['size'],old['mtime_ns'],old.get('mtime',old['mtime_ns']/1e9),old.get('ino',0),True,source.physical_identity())
    stat=Path(path).stat()
    return SourceMetadata(stat.st_size,stat.st_mtime_ns,stat.st_mtime,stat.st_ino,False,{})

def arrow_open_csv(path,*args,**kwargs):
    import pyarrow.csv as pc
    from .resolver import _ClosingReader
    source=logical_source(path)
    if not source:return pc.open_csv(mapped_path(path),*args,**kwargs)
    stream=source.open_binary()
    try:return _ClosingReader(pc.open_csv(stream,*args,**kwargs),stream)
    except BaseException:stream.close();raise

def arrow_read_csv(path,*args,**kwargs):
    import pyarrow.csv as pc
    source=logical_source(path)
    if source:
        with source.open_binary() as stream:return pc.read_csv(stream,*args,**kwargs)
    return pc.read_csv(mapped_path(path),*args,**kwargs)
