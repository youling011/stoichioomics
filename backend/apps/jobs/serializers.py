from rest_framework import serializers
from .models import AnalysisJob, JobFile


class JobFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobFile
        fields = ['id', 'file_name', 'relative_path', 'category', 'uploaded_at']


class AnalysisJobSerializer(serializers.ModelSerializer):
    files = JobFileSerializer(many=True, read_only=True)

    class Meta:
        model = AnalysisJob
        fields = [
            'id', 'job_id', 'name', 'module_name', 'status', 'pipeline_type', 'input_mode',
            'base_dir', 'workspace_path', 'config_path', 'recommended_mode', 'metadata_json',
            'run_attempts', 'log_path', 'reproducibility_path', 'error_message',
            'created_at', 'updated_at', 'files'
        ]
