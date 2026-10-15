from django.db import models


class AnalysisJob(models.Model):
    class Status(models.TextChoices):
        CREATED = 'CREATED', 'Created'
        UPLOADING = 'UPLOADING', 'Uploading'
        READY = 'READY', 'Ready'
        RUNNING = 'RUNNING', 'Running'
        SUCCEEDED = 'SUCCEEDED', 'Succeeded'
        FAILED = 'FAILED', 'Failed'
        CANCEL_REQUESTED = 'CANCEL_REQUESTED', 'Cancel requested'
        CANCELLED = 'CANCELLED', 'Cancelled'

    job_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255, blank=True, default='')
    module_name = models.CharField(max_length=64, default='hvg')
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.CREATED)
    pipeline_type = models.CharField(max_length=32, blank=True, default='full')
    input_mode = models.CharField(max_length=64, blank=True, default='')
    base_dir = models.CharField(max_length=1024, blank=True, default='')
    workspace_path = models.CharField(max_length=1024, blank=True, default='')
    config_path = models.CharField(max_length=1024, blank=True, default='')
    recommended_mode = models.CharField(max_length=128, blank=True, default='')
    metadata_json = models.JSONField(default=dict, blank=True)
    access_token_hash = models.CharField(max_length=128, blank=True, default='')
    run_attempts = models.PositiveIntegerField(default=0)
    log_path = models.CharField(max_length=1024, blank=True, default='')
    reproducibility_path = models.CharField(max_length=1024, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.job_id


class JobFile(models.Model):
    job = models.ForeignKey(AnalysisJob, related_name='files', on_delete=models.CASCADE)
    file_name = models.CharField(max_length=512)
    relative_path = models.CharField(max_length=1024)
    category = models.CharField(max_length=64, blank=True, default='raw')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('job', 'relative_path')
