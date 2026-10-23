"""Only production adds readiness; all original routes are reused verbatim."""
from django.urls import path
from backend.apps.core.deployment import readiness_view
from .urls import urlpatterns as original_patterns

urlpatterns = [path('api/health/ready/', readiness_view), *original_patterns]
