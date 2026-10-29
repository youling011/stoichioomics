"""Read-only deployment readiness; existing /api/health/ is unchanged."""
import os
from pathlib import Path
from django.conf import settings
from django.db import connections, DatabaseError
from django.http import JsonResponse
from django.views.decorators.http import require_safe


@require_safe
def readiness_view(request):
    checks = {}
    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
            checks['database'] = cursor.fetchone() == (1,)
    except DatabaseError:
        checks['database'] = False
    roots = getattr(settings, 'DEPLOYMENT_READINESS_ROOTS', {})
    writable = getattr(settings, 'DEPLOYMENT_READINESS_WRITABLE_ROOTS', set())
    for name, value in roots.items():
        path = Path(value)
        try:
            mode = os.R_OK | os.X_OK | (os.W_OK if name in writable else 0)
            checks[name] = path.is_dir() and os.access(path, mode)
        except OSError:
            checks[name] = False
    ready = all(checks.values())
    response = JsonResponse({'ok': ready, 'checks': checks}, status=200 if ready else 503)
    response['Cache-Control'] = 'no-store'
    return response


@require_safe
def public_data_revision_view(request):
    """Small public cache identity; no paths, task metadata or credentials."""
    from django.http import HttpResponse
    from backend.apps.common.public_snapshots import revision
    response=HttpResponse(status=204)
    response['X-Stoich-Data-Revision']=revision()
    response['Cache-Control']='no-store'
    return response
