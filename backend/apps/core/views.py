from django.conf import settings
from rest_framework.decorators import api_view
from backend.apps.common.responses import ok


@api_view(['GET'])
def health_view(request):
    return ok({
        'status': 'healthy',
        'workspace_root': str(settings.WORKSPACE_ROOT),
        'examples_root': str(settings.ANALYSIS_EXAMPLES_ROOT),
        'module': 'hvg-platform',
    })
