import logging,time,uuid,re,json
from contextvars import ContextVar
from contextlib import contextmanager
from django.db import connection
log=logging.getLogger('stoich.request.timing')
_current=ContextVar('stoich_request_timing',default=None)
@contextmanager
def stage(name):
 stats=_current.get()
 if stats is None:yield;return
 start=time.perf_counter()
 try:yield
 finally:stats['stages'][name]=stats['stages'].get(name,0)+time.perf_counter()-start
def json_bytes(length):
 stats=_current.get()
 if stats is not None:stats['json_bytes']=length
class RequestTimingMiddleware:
 def __init__(self,get_response):self.get_response=get_response
 def __call__(self,request):
  start=time.perf_counter();stats={'db_seconds':0,'queries':0,'stages':{}};token=_current.set(stats)
  supplied=request.headers.get('X-Request-ID','');rid=supplied if re.fullmatch('[A-Za-z0-9_-]{8,64}',supplied) else uuid.uuid4().hex
  def trace(execute,sql,params,many,context):
   before=time.perf_counter()
   try:return execute(sql,params,many,context)
   finally:stats['db_seconds']+=time.perf_counter()-before;stats['queries']+=1
  try:
   with connection.execute_wrapper(trace):response=self.get_response(request)
  finally:_current.reset(token)
  elapsed=time.perf_counter()-start;response['X-Request-ID']=rid;response['Server-Timing']=', '.join([f"app;dur={elapsed*1000:.2f}",f"db;dur={stats['db_seconds']*1000:.2f}"]+[f'{name};dur={seconds*1000:.2f}' for name,seconds in sorted(stats['stages'].items())])
  if 'json_bytes' in stats:response['X-JSON-Decoded-Bytes']=str(stats['json_bytes'])
  if elapsed>1:log.info(json.dumps({'request_id':rid,'path':request.path,'status':response.status_code,'seconds':round(elapsed,4),'db_seconds':round(stats['db_seconds'],4),'queries':stats['queries'],'stages':stats['stages'],'json_bytes':stats.get('json_bytes')}))
  return response
