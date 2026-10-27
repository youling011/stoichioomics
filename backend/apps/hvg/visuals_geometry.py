"""Read legacy layout metadata only; preview values never enter v2 statistics."""
from collections import OrderedDict
from threading import RLock
from backend.apps.common.workflow_visuals.contracts import digest

_cache=OrderedDict();_lock=RLock()

def original_geometry(run,manifest,kind,params,source_signature):
    key=(str(run),kind,source_signature,digest(params))
    with _lock:
        if key in _cache:_cache.move_to_end(key);return dict(_cache[key])
    from .research_visuals import visuals
    legacy=visuals(run,manifest,kind,params)
    rows=legacy.get('rows') or []
    result={'chart_type':legacy.get('chart_type'),'row_count':len(rows),'family_count':len({str(r.get('family')) for r in rows}),'basis':'original saved-chart geometry only; no preview values used by v2'}
    with _lock:
        _cache[key]=result
        while len(_cache)>128:_cache.popitem(last=False)
    return dict(result)
