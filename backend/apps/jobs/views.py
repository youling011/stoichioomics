from backend.apps.common.host_paths import Path
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework import status
from django.shortcuts import get_object_or_404

from backend.apps.common.responses import ok, err
from .models import AnalysisJob
from .serializers import AnalysisJobSerializer
from .services import (
    add_uploaded_file,
    autoconfigure_job,
    build_job_config,
    check_job_token,
    cleanup_expired_analysis_jobs,
    create_job,
    ensure_job_token,
    read_job_log,
    request_job_cancel,
    run_job_async,
    run_job_preflight,
)


def _request_token(request):
    token = request.headers.get('X-Job-Token')
    if token:
        return token
    if hasattr(request, 'data') and isinstance(request.data, dict):
        return request.data.get('access_token')
    return None


def _job_payload(job):
    return AnalysisJobSerializer(job).data


@api_view(['GET', 'POST'])
@parser_classes([JSONParser])
def jobs_collection(request):
    if request.method == 'GET':
        jobs = AnalysisJob.objects.order_by('-created_at')[:200]
        return ok(AnalysisJobSerializer(jobs, many=True).data)
    name = request.data.get('name', '')
    metadata_json = request.data.get('metadata_json') or {}
    job = create_job(name=name, metadata_json=metadata_json)
    payload = _job_payload(job)
    payload['access_token'] = getattr(job, 'plain_access_token', '')
    return ok(payload, status=201)


@api_view(['GET', 'DELETE'])
def job_detail(request, job_id: str):
    job = get_object_or_404(AnalysisJob, job_id=job_id)
    if request.method == 'GET':
        return ok(_job_payload(job))
    try:
        ensure_job_token(job, _request_token(request))
    except PermissionError as exc:
        return err(str(exc), status=403)
    # soft delete behavior could be added; for now remove db row only
    job.delete()
    return ok({'deleted': True})


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def job_upload(request, job_id: str):
    job = get_object_or_404(AnalysisJob, job_id=job_id)
    try:
        ensure_job_token(job, _request_token(request))
    except PermissionError as exc:
        return err(str(exc), status=403)
    files = request.FILES.getlist('files')
    if not files:
        return err('No files uploaded', status=400)
    saved = []
    try:
        for f in files:
            rec = add_uploaded_file(job, f)
            saved.append({'file_name': rec.file_name, 'relative_path': rec.relative_path})
    except ValueError as exc:
        return err(str(exc), status=400)
    return ok({'uploaded': saved})


@api_view(['POST'])
@parser_classes([JSONParser])
def job_configure(request, job_id: str):
    job = get_object_or_404(AnalysisJob, job_id=job_id)
    try:
        ensure_job_token(job, _request_token(request))
    except PermissionError as exc:
        return err(str(exc), status=403)
    pipeline_type = request.data.get('pipeline_type', 'full')
    input_mode = request.data.get('input_mode', '')
    expression_cfg = request.data.get('expression_cfg') or {}
    metadata_file = request.data.get('metadata_file')
    stoich_cfg = request.data.get('stoich_cfg') or {'require': False}
    analysis_overrides = request.data.get('analysis_overrides') or {}
    if not input_mode:
        return err('input_mode is required')
    cfg_path = build_job_config(job, pipeline_type, input_mode, expression_cfg, metadata_file, stoich_cfg, analysis_overrides)
    return ok({'config_path': str(cfg_path), 'job': _job_payload(AnalysisJob.objects.get(job_id=job_id))})


@api_view(['POST'])
@parser_classes([JSONParser])
def job_autoconfigure(request, job_id: str):
    job = get_object_or_404(AnalysisJob, job_id=job_id)
    try:
        ensure_job_token(job, _request_token(request))
    except PermissionError as exc:
        return err(str(exc), status=403)
    profile = request.data.get('profile') or 'standard_guided'
    pipeline_type = request.data.get('pipeline_type') or 'full'
    user_overrides = request.data.get('user_overrides') or {}
    try:
        payload = autoconfigure_job(job, profile=profile, user_overrides=user_overrides, pipeline_type=pipeline_type)
        payload['job'] = _job_payload(AnalysisJob.objects.get(job_id=job_id))
        return ok(payload)
    except (ValueError,TypeError) as exc:
        return err(str(exc),status=400)
    except RuntimeError as exc:
        return err(str(exc),status=409)
    except Exception as exc:
        return err(str(exc), status=500)


@api_view(['POST'])
@parser_classes([JSONParser])
def job_confirm_config(request, job_id: str):
    job = get_object_or_404(AnalysisJob, job_id=job_id)
    try:
        ensure_job_token(job, _request_token(request))
    except PermissionError as exc:
        return err(str(exc), status=403)
    profile = request.data.get('profile') or 'standard_guided'
    user_overrides = request.data.get('user_overrides') or {}
    pipeline_type = request.data.get('pipeline_type') or 'full'
    try:
        payload = autoconfigure_job(job, profile=profile, user_overrides=user_overrides, pipeline_type=pipeline_type)
        payload['accepted_auto_config'] = bool(request.data.get('accepted_auto_config', True))
        payload['job'] = _job_payload(AnalysisJob.objects.get(job_id=job_id))
        return ok(payload)
    except (ValueError,TypeError) as exc:
        return err(str(exc),status=400)
    except RuntimeError as exc:
        return err(str(exc),status=409)
    except Exception as exc:
        return err(str(exc), status=500)


@api_view(['POST'])
def job_run(request, job_id: str):
    job = get_object_or_404(AnalysisJob, job_id=job_id)
    try:
        ensure_job_token(job, _request_token(request))
    except PermissionError as exc:
        return err(str(exc), status=403)
    if not job.config_path:
        return err('Job is not configured yet', status=400)
    try:
        run_job_async(job)
    except ValueError as exc:
        return err(str(exc),status=400)
    except RuntimeError as exc:
        return err(str(exc),status=409)
    return ok({'started': True, 'job_id': job.job_id, 'status': 'RUNNING'})


@api_view(['POST', 'GET'])
def job_preflight(request, job_id: str):
    job = get_object_or_404(AnalysisJob, job_id=job_id)
    try:
        return ok(run_job_preflight(job))
    except (ValueError,TypeError) as exc:
        return err(str(exc),status=400)
    except RuntimeError as exc:
        return err(str(exc),status=409)
    except Exception as exc:
        return err(str(exc), status=500)


@api_view(['POST'])
def job_cancel(request, job_id: str):
    job = get_object_or_404(AnalysisJob, job_id=job_id)
    try:
        ensure_job_token(job, _request_token(request))
    except PermissionError as exc:
        return err(str(exc), status=403)
    return ok(request_job_cancel(job))


@api_view(['GET'])
def job_logs(request, job_id: str):
    job = get_object_or_404(AnalysisJob, job_id=job_id)
    try:
        tail = int(request.query_params.get('tail', 200))
    except ValueError:
        tail = 200
    return ok(read_job_log(job, tail=tail))


@api_view(['GET'])
def job_reproducibility(request, job_id: str):
    job = get_object_or_404(AnalysisJob, job_id=job_id)
    path = Path(job.reproducibility_path) if job.reproducibility_path else Path(job.workspace_path) / 'logs' / 'reproducibility_manifest.json'
    if not path.exists():
        return err('Reproducibility manifest not found for this job.', status=404)
    import json
    return ok(json.loads(path.read_text(encoding='utf-8')))


@api_view(['POST'])
def jobs_cleanup(request):
    return ok(cleanup_expired_analysis_jobs())
