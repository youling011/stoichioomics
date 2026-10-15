from pathlib import Path
from django.conf import settings
from rest_framework.decorators import api_view
from backend.apps.common.responses import ok


@api_view(['GET'])
def files_root(request):
    root = Path(settings.MEDIA_ROOT)
    files = []
    if root.exists():
        for p in sorted(root.rglob('*')):
            if p.is_file():
                files.append({'path': str(p.relative_to(root)), 'size': p.stat().st_size})
    return ok({'media_root': str(root), 'files': files[:500]})
