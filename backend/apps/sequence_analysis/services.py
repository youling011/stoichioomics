from __future__ import annotations

import json
import hashlib
import secrets
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from backend.apps.common.host_paths import Path
from typing import Any

import pandas as pd
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from backend.apps.common.reproducibility import utc_now_iso, write_reproducibility_manifest
from backend.apps.common.atomic_json import atomic_write_json, read_json, json_file_signature
from backend.apps.common.upload_security import (
    SEQUENCE_ANNOTATION_EXTENSIONS,
    SEQUENCE_FASTA_EXTENSIONS,
    SEQUENCE_SAMPLE_SHEET_EXTENSIONS,
    store_uploaded_file,
)
from backend.apps.stoichdb import case_studies
from .feature_panels import build_core_feature_panels
from .contracts import (
    build_analysis_design,
    build_input_qc,
    sample_sheet_template_csv,
    write_sequence_contracts,
)
from .real_engine import (
    entity_comparison_from_rows,
    feature_comparison_from_rows,
    field_summary_from_rows,
    ml_discrimination_from_rows,
    run_sequence_analysis,
    scatter_from_rows,
    top_low_entities_from_rows,
)


OUTPUT_FILES = {
    'features': 'sequence_features.csv',
    'platform_rows': 'rows_for_platform.csv',
    'differential_features': 'differential_features.csv',
    'differential_entities': 'differential_entities.csv',
    'feature_catalog': 'feature_catalog.json',
    'feature_summary_csv': 'feature_summary.csv',
    'feature_summary': 'feature_summary.json',
    'basic_visualization': 'basic_visualization_payload.json',
    'core_feature_panels': 'core_feature_panels.json',
    'top_low_entities_csv': 'top_low_entities.csv',
    'top_low_entities': 'top_low_entities.json',
    'sample_comparison': 'sample_comparison_payload.json',
    'sample_comparison_features_csv': 'sample_comparison_features.csv',
    'sample_comparison_features': 'sample_comparison_features.json',
    'sample_comparison_entities_csv': 'sample_comparison_entities.csv',
    'sample_comparison_entities': 'sample_comparison_entities.json',
    'ml_discrimination': 'ml_discrimination_payload.json',
    'ml_feature_importance': 'ml_feature_importance.csv',
    'ml_feature_importance_json': 'ml_feature_importance.json',
    'ml_predictions': 'ml_predictions.csv',
    'ml_predictions_json': 'ml_predictions.json',
    'method_metadata': 'method_metadata.json',
    'job_manifest': 'job_manifest.json',
    'input_qc': 'input_qc.json',
    'analysis_design': 'analysis_design.json',
    'result_interpretation': 'result_interpretation.json',
    'download_manifest': 'download_manifest.json',
    'plots': 'plots_payload.json',
    'summary': 'summary.json',
    'analysis': 'analysis_payload.json',
    'platform_bundle': 'platform_bundle.json',
    'run_log': 'run_log.json',
}

EMPTY_TABLE_COLUMNS = {
    'differential_features': [
        'feature_name', 'comparison', 'reference_group', 'case_group', 'method',
        'statistic', 'p_value', 'welch_t_p_value', 'fdr', 'effect_size',
        'cliffs_delta', 'importance', 'importance_rank', 'reference_median',
        'case_median', 'reference_n', 'case_n',
    ],
    'differential_entities': [
        'gene_key', 'entity_id', 'gene_id', 'gene_name', 'comparison', 'group',
        'species_id', 'analysis_basis', 'score', 'top_feature', 'effect_size',
        'reference_median', 'case_median', 'p_value', 'fdr', 'supporting_feature_count',
    ],
}


def sequence_workspace() -> Path:
    return Path(getattr(settings, 'SEQUENCE_ANALYSIS_WORKSPACE_ROOT', settings.BASE_DIR / 'runtime' / 'sequence_analysis'))


def legacy_sequence_workspace() -> Path:
    return Path(getattr(settings, 'SEQUENCE_ANALYSIS_LEGACY_WORKSPACE_ROOT', settings.BASE_DIR / 'workspace' / 'sequence_analysis'))


def example_sequence_workspace() -> Path:
    return Path(getattr(settings, 'SEQUENCE_ANALYSIS_EXAMPLE_ROOT', settings.BASE_DIR / 'data' / 'examples' / 'sequence_analysis_results'))


def _model8_case4_code_from_job_id(job_id: str) -> str:
    raw = str(job_id or '').strip()
    for prefix in ('model8-case4-', 'model8_case4_'):
        if raw.lower().startswith(prefix):
            return raw[len(prefix):].upper()
    return ''


def _model8_case4_sequence_jobs() -> list[dict[str, Any]]:
    try:
        summary = case_studies.model8_case4_summary_payload()
        gold = case_studies.model8_case4_gold_payload()
    except Exception:
        return []

    generated_at = summary.get('generated_at_utc')
    subset_rows = gold.get('subset_manifest') or []
    out: list[dict[str, Any]] = []
    for row in subset_rows:
        code = str(row.get('case_code') or '').upper()
        if not code:
            continue
        protein_records = int(row.get('protein_records') or 0)
        nucleotide_records = int(row.get('nucleotide_records') or 0)
        out.append({
            'job_id': f'model8-case4-{code}',
            'name': f'Model-8 sequence upload gold: {code}',
            'status': 'SUCCEEDED',
            'analysis_type': 'curated_sequence_upload_gold',
            'omics_type': 'protein + CDS/transcript',
            'group_field': 'case_code / omics',
            'reference_group': 'stored frozen platform feature tables',
            'feature_set': 'model8_gold_standard',
            'genetic_code': '',
            'created_at': generated_at,
            'updated_at': generated_at,
            'expires_at': 'public curated release',
            'is_example': True,
            'source': 'curated_model8_case4',
            'case_family': 'model8_case4_upload_gold',
            'species_case_code': code,
            'summary': {
                'record_count': protein_records + nucleotide_records,
                'sample_count': 1,
                'group_count': 2,
                'protein_records': protein_records,
                'nucleotide_records': nucleotide_records,
                'gff3_rows': row.get('gff3_rows'),
                'pass_rate': summary.get('agreement', {}).get('pass_rate'),
            },
            'outputs': OUTPUT_FILES,
        })
    return out


def _model8_case4_sequence_job(job_id: str) -> dict[str, Any]:
    code = _model8_case4_code_from_job_id(job_id)
    if not code:
        return {}
    for job in _model8_case4_sequence_jobs():
        if job['species_case_code'] == code:
            return job
    return {}


def _now_iso() -> str:
    return utc_now_iso()


def _expires_iso() -> str:
    ttl_hours = int(getattr(settings, 'SEQUENCE_ANALYSIS_TTL_HOURS', 24))
    return (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()


def _job_dir(job_id: str) -> Path:
    current = sequence_workspace() / job_id
    legacy = legacy_sequence_workspace() / job_id
    example = example_sequence_workspace() / job_id
    if current.exists() or not legacy.exists():
        if current.exists() or not example.exists():
            return current
        return example
    return legacy


def _job_meta_path(job_id: str) -> Path:
    return _job_dir(job_id) / 'job.json'


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _save_upload(upload: UploadedFile, target_dir: Path, workspace_root: Path, *, allowed: set[str]) -> tuple[Path, dict[str, Any]]:
    stored = store_uploaded_file(upload, target_dir, workspace_root, allowed=allowed)
    return Path(stored.absolute_path), {
        'original_name': stored.original_name,
        'safe_name': stored.safe_name,
        'relative_path': stored.relative_path,
        'size_bytes': stored.size_bytes,
        'sha256': stored.sha256,
        'content_type': stored.content_type,
        'extension': stored.extension,
    }


@lru_cache(maxsize=256)
def _read_json_cached(path: Path, signature: tuple[int, int, int]) -> dict[str, Any]:
    return read_json(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        signature = json_file_signature(path)
        # A worker-local cache must notice another worker's published job state.
        return _read_json_cached(path, signature)
    except FileNotFoundError:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)
    _read_json_cached.cache_clear()
    _read_table_df.cache_clear()
    field_summary.cache_clear()
    scatter_payload.cache_clear()
    feature_comparison.cache_clear()


def _append_sequence_log(root: Path, event: str, payload: dict[str, Any] | None = None) -> None:
    log_path = root / 'logs' / 'job_events.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps({'ts': _now_iso(), 'event': event, 'payload': payload or {}}, ensure_ascii=False) + '\n')


def cleanup_expired_jobs() -> int:
    now = datetime.now(timezone.utc)
    removed = 0
    for root in [sequence_workspace(), legacy_sequence_workspace()]:
        if not root.exists():
            continue
        for meta_path in root.glob('seq_*/job.json'):
            try:
                meta = _read_json(meta_path)
                raw_input_dir = meta_path.parent / 'inputs'
                if meta.get('status') in {'SUCCEEDED', 'FAILED', 'BLOCKED', 'CANCELLED'} and raw_input_dir.exists():
                    shutil.rmtree(raw_input_dir, ignore_errors=True)
                expires_raw = meta.get('expires_at')
                if not expires_raw:
                    continue
                expires_at = datetime.fromisoformat(str(expires_raw).replace('Z', '+00:00'))
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if expires_at <= now:
                    shutil.rmtree(meta_path.parent, ignore_errors=True)
                    removed += 1
            except Exception:
                continue
    return removed


def sequence_sample_sheet_template(analysis_type: str = 'multi_sample', omics_type: str = 'transcriptome') -> tuple[str, str]:
    return sample_sheet_template_csv(analysis_type, omics_type)


def prevalidate_sequence_inputs(
    *,
    uploads: list[UploadedFile],
    annotation_uploads: list[UploadedFile] | None,
    sample_sheet: UploadedFile | None,
    analysis_type: str,
    omics_type: str,
    group_field: str,
    reference_group: str,
) -> dict[str, Any]:
    if not uploads:
        raise ValueError('At least one FASTA file is required for prevalidation.')
    root = sequence_workspace() / 'prevalidate' / f'pv_{uuid.uuid4().hex[:12]}'
    input_dir = root / 'inputs'
    try:
        input_pairs = [_save_upload(upload, input_dir, root, allowed=SEQUENCE_FASTA_EXTENSIONS) for upload in uploads]
        annotation_pairs = [_save_upload(upload, input_dir, root, allowed=SEQUENCE_ANNOTATION_EXTENSIONS) for upload in (annotation_uploads or [])]
        sample_pair = _save_upload(sample_sheet, input_dir, root, allowed=SEQUENCE_SAMPLE_SHEET_EXTENSIONS) if sample_sheet else None
        return build_input_qc(
            input_files=[item[0] for item in input_pairs],
            annotation_files=[item[0] for item in annotation_pairs],
            sample_sheet_path=sample_pair[0] if sample_pair else None,
            analysis_type=analysis_type,
            omics_type=omics_type,
            group_field=group_field,
            reference_group=reference_group,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def create_sequence_job(
    *,
    uploads: list[UploadedFile],
    annotation_uploads: list[UploadedFile] | None,
    sample_sheet: UploadedFile | None,
    analysis_type: str,
    omics_type: str,
    group_field: str,
    reference_group: str,
    feature_set: str,
    genetic_code: int,
    name: str,
    project_question: str = '',
    comparison_intent: str = '',
    replicate_type: str = '',
) -> dict[str, Any]:
    cleanup_expired_jobs()
    if not uploads:
        raise ValueError('At least one FASTA file is required.')
    job_id = f'seq_{uuid.uuid4().hex[:12]}'
    root = _job_dir(job_id)
    input_dir = root / 'inputs'
    output_dir = root / 'outputs'
    token = secrets.token_urlsafe(32)
    input_pairs = [_save_upload(upload, input_dir, root, allowed=SEQUENCE_FASTA_EXTENSIONS) for upload in uploads]
    annotation_pairs = [_save_upload(upload, input_dir, root, allowed=SEQUENCE_ANNOTATION_EXTENSIONS) for upload in (annotation_uploads or [])]
    sample_pair = _save_upload(sample_sheet, input_dir, root, allowed=SEQUENCE_SAMPLE_SHEET_EXTENSIONS) if sample_sheet else None
    input_files = [item[0] for item in input_pairs]
    annotation_files = [item[0] for item in annotation_pairs]
    sample_sheet_path = sample_pair[0] if sample_pair else None
    input_manifest = [item[1] for item in input_pairs]
    annotation_manifest = [item[1] for item in annotation_pairs]
    sample_manifest = sample_pair[1] if sample_pair else None
    params = {
        'analysis_type': analysis_type,
        'omics_type': omics_type,
        'group_field': group_field,
        'reference_group': reference_group,
        'feature_set': feature_set,
        'genetic_code': genetic_code,
        'project_question': project_question,
        'comparison_intent': comparison_intent,
        'replicate_type': replicate_type,
    }
    input_qc = build_input_qc(
        input_files=input_files,
        annotation_files=annotation_files,
        sample_sheet_path=sample_sheet_path,
        analysis_type=analysis_type,
        omics_type=omics_type,
        group_field=group_field,
        reference_group=reference_group,
    )
    analysis_design = build_analysis_design(params, input_qc)
    meta = {
        'job_id': job_id,
        'name': name or job_id,
        'status': 'BLOCKED' if not input_qc.get('analysis_allowed') else 'RUNNING',
        'analysis_type': analysis_type,
        'omics_type': omics_type,
        'group_field': group_field,
        'reference_group': reference_group,
        'feature_set': feature_set,
        'genetic_code': genetic_code,
        'created_at': _now_iso(),
        'updated_at': _now_iso(),
        'expires_at': _expires_iso(),
        'access_control': {
            'token_required_for_mutation': True,
            'token_hash': _token_hash(token),
        },
        'privacy': {
            'raw_uploads_persisted': False,
            'derived_results_persisted_until': 'expires_at',
            'cleanup_policy': f'auto_delete_after_{getattr(settings, "SEQUENCE_ANALYSIS_TTL_HOURS", 24)}h',
            'workspace_isolation': 'per-sequence-job runtime directory',
        },
        'inputs': {
            'files': [path.name for path in input_files],
            'annotation_files': [path.name for path in annotation_files],
            'sample_sheet': sample_sheet_path.name if sample_sheet_path else None,
            'manifest': {
                'files': input_manifest,
                'annotation_files': annotation_manifest,
                'sample_sheet': sample_manifest,
            },
        },
        'reproducibility': {
            'manifest_path': str(root / 'logs' / 'reproducibility_manifest.json'),
            'run_log_path': str(root / 'logs' / 'job_events.log'),
        },
        'input_qc': input_qc,
        'analysis_design': analysis_design,
        'outputs': OUTPUT_FILES,
    }
    _write_json(_job_meta_path(job_id), meta)
    _append_sequence_log(root, 'job_created', {'parameters': params})
    write_sequence_contracts(
        root=root,
        output_dir=output_dir,
        meta=meta,
        params=params,
        output_files=OUTPUT_FILES,
        input_qc=input_qc,
        analysis_design=analysis_design,
        stage='created',
    )
    write_reproducibility_manifest(
        root / 'logs' / 'reproducibility_manifest.json',
        job_id=job_id,
        pipeline_type='sequence_analysis',
        parameters=params,
        inputs=input_manifest + annotation_manifest + ([sample_manifest] if sample_manifest else []),
        base_dir=settings.BASE_DIR,
        extra={'stage': 'created', 'privacy': meta['privacy']},
    )
    if not input_qc.get('analysis_allowed'):
        _append_sequence_log(root, 'job_blocked_by_input_qc', {'blocking_errors': input_qc.get('blocking_errors', [])})
        shutil.rmtree(input_dir, ignore_errors=True)
        meta['inputs']['raw_uploads_deleted_at'] = _now_iso()
        meta['updated_at'] = _now_iso()
        _write_json(_job_meta_path(job_id), meta)
        write_sequence_contracts(
            root=root,
            output_dir=output_dir,
            meta=meta,
            params=params,
            output_files=OUTPUT_FILES,
            input_qc=input_qc,
            analysis_design=analysis_design,
            stage='blocked',
        )
        response_meta = dict(meta)
        response_meta['access_token'] = token
        return response_meta
    thread = threading.Thread(
        target=_run_sequence_job,
        args=(job_id, input_files, annotation_files, sample_sheet_path, output_dir, params),
        daemon=True,
    )
    thread.start()
    response_meta = dict(meta)
    response_meta['access_token'] = token
    return response_meta


def _run_sequence_job(
    job_id: str,
    input_files: list[Path],
    annotation_files: list[Path],
    sample_sheet_path: Path | None,
    output_dir: Path,
    params: dict[str, Any],
) -> None:
    root = _job_dir(job_id)
    input_dir = root / 'inputs'
    meta = _read_json(_job_meta_path(job_id))
    _append_sequence_log(root, 'job_started', {'executor': 'in_process_thread'})
    try:
        summary = run_sequence_analysis(
            input_files=input_files,
            annotation_files=annotation_files,
            sample_sheet_path=sample_sheet_path,
            output_dir=output_dir,
            analysis_type=params['analysis_type'],
            omics_type=params['omics_type'],
            group_field=params['group_field'],
            reference_group=params['reference_group'],
            feature_set=params['feature_set'],
            genetic_code=params['genetic_code'],
        )
        meta.update({
            'status': 'SUCCEEDED',
            'updated_at': _now_iso(),
            'summary': summary,
            'outputs': OUTPUT_FILES,
        })
        write_sequence_contracts(
            root=root,
            output_dir=output_dir,
            meta=meta,
            params=params,
            output_files=OUTPUT_FILES,
            input_qc=meta.get('input_qc') or {},
            analysis_design=meta.get('analysis_design') or {},
            stage='succeeded',
        )
        _append_sequence_log(root, 'job_finished', {'status': 'SUCCEEDED', 'record_count': summary.get('record_count')})
    except Exception as exc:
        meta.update({
            'status': 'FAILED',
            'updated_at': _now_iso(),
            'error_message': str(exc),
            'outputs': OUTPUT_FILES,
        })
        write_sequence_contracts(
            root=root,
            output_dir=output_dir,
            meta=meta,
            params=params,
            output_files=OUTPUT_FILES,
            input_qc=meta.get('input_qc') or {},
            analysis_design=meta.get('analysis_design') or {},
            stage='failed',
        )
        _append_sequence_log(root, 'job_failed', {'error': str(exc)})
    finally:
        # Raw user uploads are only runtime inputs. Derived results remain until TTL cleanup.
        shutil.rmtree(input_dir, ignore_errors=True)
        meta['inputs']['raw_uploads_deleted_at'] = _now_iso()
    _write_json(_job_meta_path(job_id), meta)
    write_sequence_contracts(
        root=root,
        output_dir=output_dir,
        meta=meta,
        params=params,
        output_files=OUTPUT_FILES,
        input_qc=meta.get('input_qc') or {},
        analysis_design=meta.get('analysis_design') or {},
        stage=str(meta.get('status') or 'finished').lower(),
    )


def list_sequence_jobs() -> list[dict[str, Any]]:
    cleanup_expired_jobs()
    jobs = []
    seen = set()
    standard_model8_case4_species = set()
    for root in [sequence_workspace(), legacy_sequence_workspace(), example_sequence_workspace()]:
        if not root.exists():
            continue
        for meta_path in root.glob('seq*/job.json'):
            if meta_path.parent.name in seen:
                continue
            try:
                meta = _read_json(meta_path)
                if meta.get('hidden_from_sequence_index'):
                    seen.add(meta_path.parent.name)
                    continue
                jobs.append(meta)
                seen.add(meta_path.parent.name)
                if (
                    meta.get('case_family') == 'model8_case4_upload_gold'
                    and meta.get('standard_sequence_upload_case')
                    and meta.get('species_case_code')
                ):
                    standard_model8_case4_species.add(str(meta.get('species_case_code')).upper())
            except json.JSONDecodeError:
                continue
    for job in _model8_case4_sequence_jobs():
        if str(job.get('species_case_code') or '').upper() in standard_model8_case4_species:
            continue
        if job['job_id'] not in seen:
            jobs.append(job)
            seen.add(job['job_id'])
    jobs.sort(key=lambda row: row.get('created_at', ''), reverse=True)
    return jobs


def get_sequence_job(job_id: str) -> dict[str, Any]:
    cleanup_expired_jobs()
    meta = _read_json(_job_meta_path(job_id))
    if not meta:
        meta = _model8_case4_sequence_job(job_id)
    if not meta:
        raise FileNotFoundError(job_id)
    return meta


def read_sequence_logs(job_id: str, tail: int = 200) -> dict[str, Any]:
    root = _job_dir(job_id)
    log_path = root / 'logs' / 'job_events.log'
    if not log_path.exists():
        return {'log_path': str(log_path), 'events': []}
    lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
    events = []
    for line in lines[-max(1, min(tail, 1000)):]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            events.append({'ts': '', 'event': 'raw_log_line', 'payload': {'line': line}})
    return {'log_path': str(log_path), 'events': events}


def read_sequence_reproducibility(job_id: str) -> dict[str, Any]:
    root = _job_dir(job_id)
    path = root / 'logs' / 'reproducibility_manifest.json'
    if not path.exists():
        raise FileNotFoundError(job_id)
    return _read_json(path)


def read_job_manifest(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'job_manifest'))


def read_input_qc(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'input_qc'))


def read_analysis_design(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'analysis_design'))


def read_result_interpretation(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'result_interpretation'))


def read_download_manifest(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'download_manifest'))


def output_path(job_id: str, kind: str) -> Path:
    file_name = OUTPUT_FILES.get(kind)
    if not file_name:
        raise FileNotFoundError(kind)
    path = _job_dir(job_id) / 'outputs' / file_name
    if not path.exists():
        raise FileNotFoundError(kind)
    return path


def _filter_sort_table(
    df: pd.DataFrame,
    *,
    search: str = '',
    sort_by: str = '',
    sort_order: str = 'asc',
    columns: list[str] | None = None,
) -> pd.DataFrame:
    work = df.copy()
    query = str(search or '').strip().lower()
    if query:
        text_cols = [
            col for col in work.columns
            if work[col].dtype == object or col in {'entity_id', 'gene_id', 'gene_name', 'sample_id', 'group', 'species_id'}
        ]
        if text_cols:
            mask = pd.Series(False, index=work.index)
            for col in text_cols:
                mask = mask | work[col].fillna('').astype(str).str.lower().str.contains(query, regex=False)
            work = work.loc[mask]
    if sort_by and sort_by in work.columns:
        ascending = str(sort_order).lower() != 'desc'
        sortable = pd.to_numeric(work[sort_by], errors='coerce')
        if sortable.notna().any():
            work = work.assign(_sort_value=sortable).sort_values('_sort_value', ascending=ascending, na_position='last').drop(columns=['_sort_value'])
        else:
            work = work.sort_values(sort_by, ascending=ascending, na_position='last')
    if columns:
        keep = [col for col in columns if col in work.columns]
        if keep:
            work = work[keep]
    return work


def _parse_columns(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        raw = value
    else:
        raw = str(value).split(',')
    return [item.strip() for item in raw if item.strip()]


def read_table(
    job_id: str,
    kind: str,
    limit: int = 100,
    offset: int = 0,
    search: str = '',
    sort_by: str = '',
    sort_order: str = 'asc',
    columns: str | list[str] | None = None,
) -> dict[str, Any]:
    try:
        df = _read_table_df(job_id, kind).copy()
    except pd.errors.EmptyDataError:
        columns = EMPTY_TABLE_COLUMNS.get(kind, [])
        return {
            'columns': columns,
            'rows': [],
            'total': 0,
            'limit': int(limit if limit > 0 else 100),
            'offset': int(max(offset, 0)),
        }
    filtered = _filter_sort_table(
        df,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        columns=_parse_columns(columns),
    )
    total = len(df)
    filtered_total = len(filtered)
    if offset < 0:
        offset = 0
    if limit <= 0:
        limit = 100
    page = filtered.iloc[offset: offset + limit]
    return {
        'columns': list(filtered.columns),
        'rows': json.loads(page.to_json(orient='records')),
        'total': int(total),
        'filtered_total': int(filtered_total),
        'limit': int(limit),
        'offset': int(offset),
        'search': search,
        'sort_by': sort_by,
        'sort_order': sort_order,
    }


def export_table(job_id: str, kind: str, search: str = '', sort_by: str = '', sort_order: str = 'asc', columns: str | list[str] | None = None) -> tuple[str, str]:
    path = output_path(job_id, kind)
    df = _read_table_df(job_id, kind).copy()
    filtered = _filter_sort_table(
        df,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        columns=_parse_columns(columns),
    )
    filename = f'{kind}_filtered.csv' if search or sort_by or columns else path.name
    return filename, filtered.to_csv(index=False)


def read_plots(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'plots'))


def read_platform_bundle(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'platform_bundle'))


def read_analysis_payload(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'analysis'))


def read_feature_catalog(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'feature_catalog'))


def read_feature_summary(job_id: str, feature: str = '') -> dict[str, Any]:
    payload = _read_json(output_path(job_id, 'feature_summary'))
    if feature:
        rows = [row for row in payload.get('rows', []) if row.get('feature_name') == feature]
        return {**payload, 'rows': rows}
    return payload


def read_basic_visualization(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'basic_visualization'))


def read_core_feature_panels(job_id: str, filters: dict[str, str] | None = None, panel_id: str = '') -> dict[str, Any]:
    filters = {key: value for key, value in (filters or {}).items() if value}
    if filters:
        payload = build_core_feature_panels(_rows_df(job_id), str(get_sequence_job(job_id).get('omics_type') or ''), filters=filters)
    else:
        payload = _read_json(output_path(job_id, 'core_feature_panels'))
    if panel_id:
        panels = [panel for panel in payload.get('panels', []) if panel.get('panel_id') == panel_id]
        return {**payload, 'panels': panels}
    return payload


def read_sample_comparison(job_id: str) -> dict[str, Any]:
    return _read_json(output_path(job_id, 'sample_comparison'))


def read_ml_discrimination(job_id: str, label_field: str = 'group') -> dict[str, Any]:
    if not label_field or label_field == 'group':
        return _read_json(output_path(job_id, 'ml_discrimination'))
    df = _rows_df(job_id)
    if label_field == 'species_condition' and {'species_id', 'condition'}.issubset(df.columns):
        df = df.assign(species_condition=df['species_id'].astype(str) + ':' + df['condition'].astype(str))
    return ml_discrimination_from_rows(df, label_field=label_field)


@lru_cache(maxsize=128)
def _read_table_df(job_id: str, kind: str) -> pd.DataFrame:
    # Saved-result HTTP reads share the deployment-compatible CSV parser used
    # by the scientific figures. Keep this legacy reader's original NA policy.
    return pd.read_csv(output_path(job_id, kind), engine='python', dtype={'seq_md5':str})


def _rows_df(job_id: str) -> pd.DataFrame:
    return _read_table_df(job_id, 'platform_rows').copy()


@lru_cache(maxsize=512)
def field_summary(job_id: str, field: str) -> dict[str, Any]:
    return field_summary_from_rows(_rows_df(job_id), field)


@lru_cache(maxsize=512)
def scatter_payload(job_id: str, x_field: str, y_field: str, sample: int = 1200) -> dict[str, Any]:
    return scatter_from_rows(_rows_df(job_id), x_field, y_field, sample=sample)


@lru_cache(maxsize=512)
def feature_comparison(job_id: str, feature: str) -> dict[str, Any]:
    return feature_comparison_from_rows(_rows_df(job_id), feature)


def entity_comparison(job_id: str, entities: list[str], features: list[str]) -> dict[str, Any]:
    return entity_comparison_from_rows(_rows_df(job_id), entities, features)


def top_low_entities(job_id: str, feature: str = '', n: int = 10) -> dict[str, Any]:
    if feature:
        return top_low_entities_from_rows(_rows_df(job_id), feature=feature, n=n)
    return _read_json(output_path(job_id, 'top_low_entities'))
