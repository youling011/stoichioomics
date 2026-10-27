"""Opt-in filesystem boundary for unchanged Windows records on a Linux host.

G:\\stoichioomics and explicitly configured legacy prefixes can be mapped.
Database/JSON values are never rewritten.
No pathlib or third-party library is monkey-patched.
"""
import json, os
from functools import lru_cache
from pathlib import Path as NativePath, PureWindowsPath


@lru_cache(maxsize=8)
def _mappings(mount, extra):
    mapping={r'G:\stoichioomics':mount} if mount else {}
    if extra:
        configured=json.loads(extra)
        if not isinstance(configured,dict):raise ValueError('Path mappings must be a JSON object')
        mapping.update(configured)
    pairs=[]
    for prefix,target in mapping.items():
        win=PureWindowsPath(prefix);native=NativePath(target)
        if not win.is_absolute() or '..' in win.parts or not native.is_absolute():
            raise ValueError('Path mappings require absolute prefixes without parent traversal')
        pairs.append((tuple(p.casefold() for p in win.parts),native))
    return sorted(pairs,key=lambda item:len(item[0]),reverse=True)


def mapped_path(value):
    mount=os.environ.get('STOICH_WINDOWS_DATA_MOUNT','')
    extra=os.environ.get('STOICH_WINDOWS_PATH_MAPPINGS','')
    if os.name=='nt' or not (mount or extra) or not isinstance(value,(str,os.PathLike)):
        return value
    raw=os.fspath(value)
    if not isinstance(raw,str):return value
    win=PureWindowsPath(raw)
    if not win.is_absolute():return value
    folded=tuple(p.casefold() for p in win.parts)
    for prefix,target in _mappings(mount,extra):
        if folded[:len(prefix)]==prefix:
            if '..' in win.parts:raise ValueError('Parent traversal in mapped Windows path')
            return target.joinpath(*win.parts[len(prefix):])
    return value


class Path(type(NativePath())):
    """Native concrete Path with mapping only at opted-in application boundaries."""
    def __new__(cls,*args):
        return super().__new__(cls,*(mapped_path(arg) for arg in args))
