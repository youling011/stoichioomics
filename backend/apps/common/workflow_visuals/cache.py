from collections import OrderedDict
from threading import RLock
import hashlib,json
import pandas as pd

_lock=RLock();_frames=OrderedDict();_hashes=OrderedDict();_packets=OrderedDict()
MAX_FRAME_BYTES=256*1024*1024
MAX_PACKET_BYTES=192*1024*1024

def sha_file(path):
    stat=path.stat();key=(str(path),stat.st_mtime_ns,stat.st_size)
    with _lock:
        if key in _hashes:return _hashes[key]
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    if (path.stat().st_mtime_ns,path.stat().st_size)!=(stat.st_mtime_ns,stat.st_size):raise RuntimeError('source_changing')
    value=h.hexdigest()
    with _lock:
        _hashes[key]=value
        while len(_hashes)>512:_hashes.popitem(last=False)
    return value

def read_frame(path):
    if not path.is_file():return pd.DataFrame()
    key=(str(path),sha_file(path))
    with _lock:
        if key in _frames:_frames.move_to_end(key);return _frames[key].copy(deep=False)
    if path.suffix=='.parquet':frame=pd.read_parquet(path)
    else:
        # The C CSV parser segfaults for some saved mixed-schema tables under
        # the deployed threaded uWSGI interpreter. Python's CSV reader retains
        # the same complete rows/NA policy without invoking that native parser.
        # This is presentation I/O only; scientific engine readers are unchanged.
        try:frame=pd.read_csv(path,engine='python',keep_default_na=False,dtype={'seq_md5':str})
        except pd.errors.EmptyDataError:frame=pd.DataFrame()
    if int(frame.memory_usage(deep=True).sum())>MAX_FRAME_BYTES:return frame.copy(deep=False)
    with _lock:
        _frames[key]=frame
        while len(_frames)>1 and (len(_frames)>24 or sum(int(f.memory_usage(deep=True).sum()) for f in _frames.values())>MAX_FRAME_BYTES):_frames.popitem(last=False)
    return frame.copy(deep=False)

def packet_cache(key,builder):
    with _lock:
        if key in _packets:_packets.move_to_end(key);return _packets[key]
    value=builder()
    # Account for Python plotting dictionaries and member indices as well as frames.
    # The multiplier is deliberately conservative; oversized single results are not retained.
    frames={id(f):f for f in [*value.sources.values(),*value.records.values()]}
    value._cache_bytes=sum(int(f.memory_usage(deep=True).sum()) for f in frames.values())+len(json.dumps(value.packet,ensure_ascii=True))*6+sum(len(indices)*36 for groups in value.members.values() for indices in groups.values())
    if value._cache_bytes>MAX_PACKET_BYTES:return value
    with _lock:
        _packets[key]=value
        while _packets and (len(_packets)>16 or sum(v._cache_bytes for v in _packets.values())>MAX_PACKET_BYTES):_packets.popitem(last=False)
    return value

def clear():
    with _lock:_frames.clear();_hashes.clear();_packets.clear()
