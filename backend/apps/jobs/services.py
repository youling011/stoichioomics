from __future__ import annotations
from backend.apps.common.host_paths import Path
from typing import Dict, Any
import hashlib
import json
import secrets
import shutil
import threading
import uuid
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.db import transaction

from backend.apps.jobs.models import AnalysisJob, JobFile
from backend.portal.jobs import ensure_job_dirs, update_job_status
from backend.portal.config_builder import build_full_pipeline_config, build_preanalysis_config
from backend.portal.pipeline_runner import run_full_pipeline_from_config, run_preanalysis_from_config
from backend.apps.registry.services import refresh_registry_cache
from backend.analysis_engine.hvg_optional import optional_dependency_report
from backend.apps.jobs.autoconfig import build_job_auto_config
from backend.apps.common.reproducibility import utc_now_iso, write_reproducibility_manifest
from backend.apps.common.upload_security import store_uploaded_file
from backend.apps.jobs.contracts import write_workflow_contracts


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def check_job_token(job: AnalysisJob, token: str | None) -> bool:
    if not job.access_token_hash:
        return True
    return bool(token and secrets.compare_digest(job.access_token_hash, _token_hash(token)))


def ensure_job_token(job: AnalysisJob, token: str | None) -> None:
    if not check_job_token(job, token):
        raise PermissionError('A valid job access token is required for this operation.')


def _job_log_path(job: AnalysisJob) -> Path:
    path = Path(job.log_path) if job.log_path else Path(job.workspace_path) / 'logs' / 'job_events.log'
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_job_log(job: AnalysisJob, event: str, payload: Dict[str, Any] | None = None) -> None:
    path = _job_log_path(job)
    entry = {'ts': utc_now_iso(), 'event': event, 'payload': payload or {}}
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
    if job.log_path != str(path):
        AnalysisJob.objects.filter(pk=job.pk).update(log_path=str(path))
        job.log_path = str(path)


def read_job_log(job: AnalysisJob, tail: int = 200) -> Dict[str, Any]:
    path = _job_log_path(job)
    if not path.exists():
        return {'log_path': str(path), 'events': []}
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    events = []
    for line in lines[-max(1, min(tail, 1000)):]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({'ts': '', 'event': 'raw_log_line', 'payload': {'line': line}})
    return {'log_path': str(path), 'events': events}


def create_job(name: str = '', module_name: str = 'hvg', metadata_json: Dict[str, Any] | None = None) -> AnalysisJob:
    job_id = f'job_{uuid.uuid4().hex[:8]}'
    ws_manifest = ensure_job_dirs(settings.WORKSPACE_ROOT, job_id=job_id)
    token = secrets.token_urlsafe(32)
    job = AnalysisJob.objects.create(
        job_id=job_id,
        name=name or job_id,
        module_name=module_name,
        status=AnalysisJob.Status.CREATED,
        base_dir=ws_manifest['job_dir'],
        workspace_path=ws_manifest['job_dir'],
        access_token_hash=_token_hash(token),
        metadata_json={
            **(metadata_json or {}),
            'workspace_policy': {
                'isolation': 'per-job directory under WORKSPACE_ROOT',
                'token_required_for_mutation': True,
                'ttl_hours': int(getattr(settings, 'JOB_WORKSPACE_TTL_HOURS', 168)),
            },
        },
    )
    setattr(job, 'plain_access_token', token)
    append_job_log(job, 'job_created', {'module_name': module_name})
    write_workflow_contracts(job, stage='created')
    return job


def add_uploaded_file(job: AnalysisJob, upload, category: str = 'raw') -> JobFile:
    job.refresh_from_db(fields=['status'])
    if job.status in ['RUNNING','CANCEL_REQUESTED']:
        raise RuntimeError('Cannot modify inputs/config while job is running')
    raw_dir = Path(job.workspace_path) / 'raw'
    stored = store_uploaded_file(upload, raw_dir, Path(job.workspace_path))
    job_file, _ = JobFile.objects.get_or_create(
        job=job,
        relative_path=stored.relative_path,
        defaults={'file_name': stored.safe_name, 'category': category},
    )
    upload_manifest = Path(job.workspace_path) / 'logs' / 'upload_manifest.jsonl'
    upload_manifest.parent.mkdir(parents=True, exist_ok=True)
    with upload_manifest.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps({
            'job_id': job.job_id,
            'original_name': stored.original_name,
            'safe_name': stored.safe_name,
            'relative_path': stored.relative_path,
            'size_bytes': stored.size_bytes,
            'sha256': stored.sha256,
            'content_type': stored.content_type,
            'uploaded_at': utc_now_iso(),
        }, ensure_ascii=False) + '\n')
    append_job_log(job, 'file_uploaded', {'file_name': stored.safe_name, 'size_bytes': stored.size_bytes, 'sha256': stored.sha256})
    if job.status == AnalysisJob.Status.CREATED:
        job.status = AnalysisJob.Status.UPLOADING
        job.save(update_fields=['status', 'updated_at'])
    write_workflow_contracts(job, stage='uploaded')
    return job_file


def save_job_config(job: AnalysisJob, cfg: Dict[str, Any], pipeline_type: str) -> Path:
    job.refresh_from_db(fields=['status'])
    if job.status in ['RUNNING','CANCEL_REQUESTED']:
        raise RuntimeError('Cannot modify inputs/config while job is running')
    if pipeline_type == 'full':
        from backend.analysis_engine.hvg_research.workflow import normalize_workflow_config
        cfg = normalize_workflow_config(cfg)
    from .research_config_guard import validate_job_research_config
    validate_job_research_config(job,cfg)
    cfg_dir = Path(job.workspace_path) / 'configs'
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / f'{pipeline_type}_pipeline.yaml'
    import yaml
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding='utf-8')
    job.config_path = str(cfg_path)
    job.pipeline_type = pipeline_type
    job.status = AnalysisJob.Status.READY
    repro_path = Path(job.workspace_path) / 'logs' / 'reproducibility_manifest.json'
    input_manifest = _uploaded_input_manifest(job)
    write_reproducibility_manifest(
        repro_path,
        job_id=job.job_id,
        pipeline_type=pipeline_type,
        parameters=cfg,
        inputs=input_manifest,
        config_path=cfg_path,
        base_dir=settings.BASE_DIR,
        extra={'stage': 'configured'},
    )
    job.reproducibility_path = str(repro_path)
    job.save(update_fields=['config_path', 'pipeline_type', 'status', 'reproducibility_path', 'updated_at'])
    write_workflow_contracts(job, stage='configured', cfg=cfg)
    append_job_log(job, 'config_saved', {'pipeline_type': pipeline_type, 'config_path': str(cfg_path)})
    return cfg_path


def _uploaded_input_manifest(job: AnalysisJob) -> list[dict[str, Any]]:
    manifest_path = Path(job.workspace_path) / 'logs' / 'upload_manifest.jsonl'
    rows: list[dict[str, Any]] = []
    if not manifest_path.exists():
        return rows
    for line in manifest_path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def build_job_config(job: AnalysisJob, pipeline_type: str, input_mode: str, expression_cfg: Dict[str, Any], metadata_file: str | None = None,
                     stoich_cfg: Dict[str, Any] | None = None, analysis_overrides: Dict[str, Any] | None = None) -> Path:
    if pipeline_type == 'preanalysis':
        cfg = build_preanalysis_config(settings.BASE_DIR, settings.WORKSPACE_ROOT, job.job_id, input_mode, expression_cfg, metadata_file, stoich_cfg)
    else:
        cfg = build_full_pipeline_config(settings.BASE_DIR, settings.WORKSPACE_ROOT, job.job_id, input_mode, expression_cfg, metadata_file, stoich_cfg, analysis_overrides)
    return save_job_config(job, cfg, pipeline_type)


def autoconfigure_job(job: AnalysisJob, profile: str = 'standard_guided', user_overrides: Dict[str, Any] | None = None, pipeline_type: str = 'full') -> Dict[str, Any]:
    payload = build_job_auto_config(job, profile=profile, user_overrides=user_overrides or {}, pipeline_type=pipeline_type, write_config=True)
    job.refresh_from_db()
    write_workflow_contracts(job, stage='autoconfigured', cfg=payload.get('effective_config'), auto_config=payload)
    return payload


def run_job_preflight(job: AnalysisJob) -> Dict[str, Any]:
    checks = []
    deps = optional_dependency_report()
    checks.append({"name": "optional_dependencies", "status": deps["status"], "details": deps})
    if not job.config_path:
        checks.append({"name": "config", "status": "blocked", "message": "Job has no saved pipeline config."})
        result = {"status": "blocked", "checks": checks}
        write_workflow_contracts(job, stage='preflight_blocked', preflight=result)
        return result

    cfg_path = Path(job.config_path)
    if not cfg_path.exists():
        checks.append({"name": "config_file", "status": "blocked", "message": f"Config file does not exist: {cfg_path}"})
        result = {"status": "blocked", "checks": checks}
        write_workflow_contracts(job, stage='preflight_blocked', preflight=result)
        return result

    import yaml
    cfg = yaml.safe_load(cfg_path.read_text(encoding='utf-8')) or {}
    if job.pipeline_type == 'full':
        from backend.analysis_engine.hvg_research.workflow import normalize_workflow_config
        cfg = normalize_workflow_config(cfg)
    raw_dir = Path(job.workspace_path) / 'raw'
    uploaded = list(raw_dir.glob('*')) if raw_dir.exists() else []
    checks.append({
        "name": "uploaded_files",
        "status": "ready" if uploaded else "blocked",
        "file_count": len(uploaded),
        "files": [p.name for p in uploaded[:30]],
    })
    research_cfg = cfg.get('hvg_research') or {}
    if research_cfg.get('enabled'):
        from backend.analysis_engine.hvg_research.config import validate_config
        validate_config(research_cfg)
        from backend.analysis_engine.hvg_research.preflight import research_preflight
        checks.extend(research_preflight(cfg))
        checks.append({'name':'hvg_research_gate','status':'ready' if getattr(settings,'HVG_RESEARCH_ENABLED',False) else 'blocked','message':'Research creation deployment gate'})
    phase2_cfg = cfg.get('phase2_stoich') or {}
    checks.append({
        "name": "phase2_contract",
        "status": "ready" if phase2_cfg.get('target_col') and phase2_cfg.get('hvg_flag_col') else "degraded",
        "target_col": phase2_cfg.get('target_col'),
        "hvg_flag_col": phase2_cfg.get('hvg_flag_col'),
        "feature_set": phase2_cfg.get('feature_set'),
    })
    stoich_resolution_path = Path(job.workspace_path) / 'configs' / 'stoich_registry_resolution.json'
    if stoich_resolution_path.exists():
        try:
            stoich_resolution = json.loads(stoich_resolution_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            stoich_resolution = {"status": "invalid_report"}
        status = stoich_resolution.get("status")
        if status in {"registry_feature_materialized", "sequence_feature_materialized", "user_uploaded_feature_table"}:
            check_status = "ready"
        elif stoich_resolution.get("sequence_upload_required"):
            check_status = "degraded"
        else:
            check_status = "pending"
        checks.append({
            "name": "stoich_feature_resolution",
            "status": check_status,
            "details": stoich_resolution,
        })
    else:
        checks.append({
            "name": "stoich_feature_resolution",
            "status": "pending",
            "message": "Auto-configuration has not produced stoich_registry_resolution.json yet.",
        })
    validation_dir = Path(job.workspace_path) / 'validation'
    mapping_summary_path = validation_dir / 'id_mapping_summary.json'
    if mapping_summary_path.exists():
        mapping = json.loads(mapping_summary_path.read_text(encoding='utf-8'))
        checks.append({
            "name": "strict_id_mapping",
            "status": "ready" if mapping.get('ready_for_phase2_stoich') else ('degraded' if research_cfg.get('enabled') else 'blocked'),
            "details": mapping,
        })
    else:
        checks.append({"name": "strict_id_mapping", "status": "pending", "message": "Validation has not produced id_mapping_summary.json yet."})

    statuses = [c.get("status") for c in checks]
    if "blocked" in statuses:
        status = "blocked"
    elif "degraded" in statuses or "pending" in statuses:
        status = "degraded"
    else:
        status = "ready"
    result = {"status": status, "checks": checks}
    write_workflow_contracts(job, stage=f'preflight_{status}', cfg=cfg, preflight=result)
    return result


def _run_job_sync(job_id: str):
    job = AnalysisJob.objects.get(job_id=job_id)
    if not job.config_path:
        raise RuntimeError('Job has no config_path')
    if job.status == AnalysisJob.Status.CANCEL_REQUESTED:
        job.status = AnalysisJob.Status.CANCELLED
        job.save(update_fields=['status', 'updated_at'])
        append_job_log(job, 'job_cancelled_before_start')
        return {'cancelled': True}
    import yaml
    cfg = yaml.safe_load(Path(job.config_path).read_text(encoding='utf-8'))
    if job.pipeline_type == 'full':
        from backend.analysis_engine.hvg_research.workflow import normalize_workflow_config
        cfg = normalize_workflow_config(cfg)
    job.status = AnalysisJob.Status.RUNNING
    job.error_message = ''
    job.run_attempts += 1
    job.save(update_fields=['status', 'error_message', 'run_attempts', 'updated_at'])
    append_job_log(job, 'job_started', {'attempt': job.run_attempts})
    try:
        repro_path = Path(job.workspace_path) / 'logs' / 'reproducibility_manifest.json'
        write_reproducibility_manifest(
            repro_path,
            job_id=job.job_id,
            pipeline_type=job.pipeline_type,
            parameters=cfg,
            inputs=_uploaded_input_manifest(job),
            config_path=Path(job.config_path),
            base_dir=settings.BASE_DIR,
            extra={'stage': 'run_started', 'attempt': job.run_attempts},
        )
        job.reproducibility_path = str(repro_path)
        job.save(update_fields=['reproducibility_path', 'updated_at'])
        if job.pipeline_type == 'preanalysis':
            result = run_preanalysis_from_config(cfg)
        else:
            result = run_full_pipeline_from_config(cfg)
        if result.get('research'):
            job.refresh_from_db()
            from django.utils.dateparse import parse_datetime
            metadata=job.metadata_json or {};days=int((cfg.get('hvg_research') or {}).get('execution',{}).get('retain_days',30));until=timezone.now()+timedelta(days=days);previous=parse_datetime(str(metadata.get('retain_until') or ''))
            if previous and previous>until:until=previous
            job.metadata_json={**metadata,'hvg_research':result['research'],'retain_until':until.isoformat()}
            job.save(update_fields=['metadata_json','updated_at'])
        # refresh recommended mode and registry cache
        mode_path = Path(job.workspace_path) / 'mode_resolution' / 'mode_resolution.json'
        if mode_path.exists():
            mode = json.loads(mode_path.read_text(encoding='utf-8'))
            job.recommended_mode = mode.get('recommended_mode') or ''
        job.refresh_from_db()
        job.status = AnalysisJob.Status.CANCELLED if job.status == AnalysisJob.Status.CANCEL_REQUESTED else AnalysisJob.Status.SUCCEEDED
        job.error_message = ''
        job.save(update_fields=['status', 'error_message', 'recommended_mode', 'updated_at'])
        write_workflow_contracts(job, stage=str(job.status).lower(), cfg=cfg)
        append_job_log(job, 'job_finished', {'status': job.status})
        refresh_registry_cache()
        return result
    except Exception as e:
        from backend.analysis_engine.hvg_research.locking import ResearchCancelled
        job.refresh_from_db()
        cancelled = isinstance(e, ResearchCancelled) or job.status == AnalysisJob.Status.CANCEL_REQUESTED
        job.status = AnalysisJob.Status.CANCELLED if cancelled else AnalysisJob.Status.FAILED
        job.error_message = '' if cancelled else str(e)
        job.save(update_fields=['status', 'error_message', 'updated_at'])
        write_workflow_contracts(job, stage='failed', cfg=cfg)
        append_job_log(job, 'job_failed', {'error': str(e)})
        raise


def run_job_async(job: AnalysisJob):
    import yaml
    from backend.analysis_engine.hvg_research.config import validate_config
    if job.config_path:
        saved_cfg=yaml.safe_load(Path(job.config_path).read_text(encoding='utf-8')) or {}
        if (saved_cfg.get('hvg_research') or {}).get('enabled'):
            validate_config(saved_cfg['hvg_research'])
            if not getattr(settings,'HVG_RESEARCH_ENABLED',False):raise ValueError('Research creation is disabled by HVG_RESEARCH_ENABLED')
    from django.db import transaction, close_old_connections
    from backend.analysis_engine.hvg_research.locking import RunConflict
    with transaction.atomic():
        claimed = AnalysisJob.objects.select_for_update().get(pk=job.pk)
        if claimed.status in [AnalysisJob.Status.RUNNING, AnalysisJob.Status.CANCEL_REQUESTED]:
            raise RunConflict('This job already has an active execution')
        claimed.status = AnalysisJob.Status.RUNNING
        claimed.save(update_fields=['status','updated_at'])
    append_job_log(claimed, 'job_queued', {'executor':'in_process_thread','atomic_claim':True})
    def execute():
        close_old_connections()
        try:_run_job_sync(claimed.job_id)
        except Exception:pass  # _run_job_sync persists the full failure to the job and log.
        finally:close_old_connections()
    thread=threading.Thread(target=execute,daemon=True,name='hvg-job-'+claimed.job_id)
    try:thread.start()
    except Exception as exc:
        claimed.status=AnalysisJob.Status.FAILED;claimed.error_message=str(exc);claimed.save(update_fields=['status','error_message','updated_at']);raise
    return thread


def request_job_cancel(job: AnalysisJob) -> Dict[str, Any]:
    if job.status in {AnalysisJob.Status.SUCCEEDED, AnalysisJob.Status.FAILED, AnalysisJob.Status.CANCELLED}:
        return {'job_id': job.job_id, 'status': job.status, 'cancel_requested': False, 'message': 'Job is already terminal.'}
    job.status = AnalysisJob.Status.CANCEL_REQUESTED
    job.save(update_fields=['status', 'updated_at'])
    cancel_path = Path(job.workspace_path) / 'logs' / 'cancel_requested.json'
    cancel_path.parent.mkdir(parents=True, exist_ok=True)
    cancel_path.write_text(json.dumps({'job_id': job.job_id, 'requested_at': utc_now_iso()}, ensure_ascii=False, indent=2), encoding='utf-8')
    pointer=Path(job.workspace_path)/'hvg_functional_comparison/running_run.json'
    if pointer.is_file():
        from backend.analysis_engine.hvg_research.artifacts import safe_path, atomic_json
        runid=json.loads(pointer.read_text(encoding='utf-8')).get('analysis_run_id')
        if runid:
            run=safe_path(pointer.parent/'runs',runid)
            atomic_json(run/'cancel_requested.json',{'job_id':job.job_id,'analysis_run_id':runid,'requested_at':utc_now_iso()})
    append_job_log(job, 'cancel_requested')
    return {'job_id': job.job_id, 'status': job.status, 'cancel_requested': True}


def cleanup_expired_analysis_jobs() -> Dict[str, Any]:
    from django.db import transaction
    from django.utils.dateparse import parse_datetime
    cutoff=timezone.now()-timedelta(hours=int(getattr(settings,'JOB_WORKSPACE_TTL_HOURS',168)))
    terminal=[AnalysisJob.Status.SUCCEEDED,AnalysisJob.Status.FAILED,AnalysisJob.Status.CANCELLED]
    ids=list(AnalysisJob.objects.filter(status__in=terminal,updated_at__lt=cutoff).values_list('pk',flat=True))
    removed=[];retained=0
    for pk in ids:
        with transaction.atomic():
            job=AnalysisJob.objects.select_for_update().filter(pk=pk).first()
            if not job or job.status not in terminal or job.updated_at>=cutoff:continue
            metadata=job.metadata_json or {};until=parse_datetime(str(metadata.get('retain_until') or ''))
            if until and timezone.is_naive(until):until=timezone.make_aware(until)
            if metadata.get('archived') or metadata.get('export_in_progress') or metadata.get('resume_in_progress') or (until and until>timezone.now()):retained+=1;continue
            workspace=Path(job.workspace_path).resolve();allowed=Path(settings.WORKSPACE_ROOT).resolve()
            if not workspace.is_relative_to(allowed) or workspace==allowed:retained+=1;continue
            if workspace.exists():shutil.rmtree(workspace,ignore_errors=True)
            removed.append(job.job_id);job.delete()
    return {'removed_count':len(removed),'removed_job_ids':removed,'retained_count':retained,'cutoff':cutoff.isoformat()}
