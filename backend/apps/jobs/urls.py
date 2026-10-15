from django.urls import path
from .views import (
    job_autoconfigure,
    job_cancel,
    job_configure,
    job_confirm_config,
    job_detail,
    job_logs,
    job_preflight,
    job_reproducibility,
    job_run,
    job_upload,
    jobs_cleanup,
    jobs_collection,
)

urlpatterns = [
    path('', jobs_collection),
    path('<str:job_id>/', job_detail),
    path('<str:job_id>/upload/', job_upload),
    path('<str:job_id>/configure/', job_configure),
    path('<str:job_id>/autoconfigure/', job_autoconfigure),
    path('<str:job_id>/confirm-config/', job_confirm_config),
    path('<str:job_id>/preflight/', job_preflight),
    path('<str:job_id>/run/', job_run),
    path('<str:job_id>/cancel/', job_cancel),
    path('<str:job_id>/logs/', job_logs),
    path('<str:job_id>/reproducibility/', job_reproducibility),
    path('maintenance/cleanup/', jobs_cleanup),
]
