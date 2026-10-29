"""Spawn-safe entry points; no model imports before Django initialization."""
from backend.apps.stoichdb.feature_sources import io as feature_io
def initialize():
    import os
    for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS']:os.environ[k]='1'
    import django
    django.setup()
    from django.db import connection
    with connection.cursor() as c:c.execute('SET default_transaction_read_only=on')
def run(sid):
    import time,gc
    from .capabilities import scan
    begin=time.monotonic()
    try:r=scan(sid)
    except Exception as e:r={'species_id':sid,'status':'failed','error':str(e),'error_type':type(e).__name__}
    r['seconds']=time.monotonic()-begin;gc.collect();return r
