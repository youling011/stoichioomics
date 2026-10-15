from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', include('backend.apps.core.urls')),
    path('api/jobs/', include('backend.apps.jobs.urls')),
    path('api/files/', include('backend.apps.files.urls')),
    path('api/registry/', include('backend.apps.registry.urls')),
    path('api/hvg/', include('backend.apps.hvg.urls')),
    path('api/stoichdb/', include('backend.apps.stoichdb.urls')),
    path('api/sequence-analysis/', include('backend.apps.sequence_analysis.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
