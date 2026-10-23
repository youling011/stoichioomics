from django.db import models


class CompareCoreProfile(models.Model):
    dataset = models.ForeignKey('stoichdb.OmicsDataset', on_delete=models.CASCADE, related_name='compare_core_profiles')
    build_key = models.CharField(max_length=64, unique=True)
    profile_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    source_signature = models.CharField(max_length=64)
    content_sha256 = models.CharField(max_length=64, blank=True, default='')
    semantic_hash = models.CharField(max_length=64)
    method_version = models.CharField(max_length=64)
    status = models.CharField(max_length=24, default='pending', db_index=True)
    metadata_json = models.JSONField(default=dict)
    artifact_path = models.CharField(max_length=1024, blank=True, default='')
    lease_token = models.CharField(max_length=64, blank=True, default='')
    lease_until = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CompareRun(models.Model):
    import uuid as _uuid
    run_id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    status = models.CharField(max_length=24, default='queued', db_index=True)
    phase = models.CharField(max_length=32, default='queued')
    progress = models.PositiveIntegerField(default=0)
    request_json = models.JSONField(default=dict)
    request_hash = models.CharField(max_length=64, db_index=True)
    source_manifest_hash = models.CharField(max_length=64, blank=True, default='')
    summary_json = models.JSONField(default=dict)
    error_message = models.TextField(blank=True, default='')
    cancel_requested = models.BooleanField(default=False)
    worker_pid = models.PositiveIntegerField(null=True, blank=True)
    lease_token = models.CharField(max_length=64, blank=True, default='')
    lease_until = models.DateTimeField(null=True, blank=True)
    heartbeat = models.DateTimeField(null=True, blank=True)
    attempts = models.JSONField(default=list)
    retry_of = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
