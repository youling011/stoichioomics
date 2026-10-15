from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def sample_sheet_template_csv(analysis_type: str = 'multi_sample', omics_type: str = 'transcriptome') -> tuple[str, str]:
    columns = ['file_name', 'sample_id', 'condition', 'species_id', 'replicate_id', 'batch']
    rows = [
        {
            'file_name': 'control_rep1.fasta',
            'sample_id': 'control_rep1',
            'condition': 'control',
            'species_id': 'uploaded_species',
            'replicate_id': 'rep1',
            'batch': 'batch1',
        },
        {
            'file_name': 'stress_rep1.fasta',
            'sample_id': 'stress_rep1',
            'condition': 'stress',
            'species_id': 'uploaded_species',
            'replicate_id': 'rep1',
            'batch': 'batch1',
        },
    ]
    if analysis_type == 'multi_species':
        rows[0]['species_id'] = 'species_a'
        rows[1]['species_id'] = 'species_b'
    if omics_type == 'genome':
        columns.append('gff_file')
        rows[0]['gff_file'] = 'control_rep1.gff3'
        rows[1]['gff_file'] = 'stress_rep1.gff3'

    from io import StringIO

    handle = StringIO()
    writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    filename = f'sequence_sample_sheet_template_{analysis_type}_{omics_type}.csv'
    return filename, handle.getvalue()


def inspect_fasta_path(path: Path) -> dict[str, Any]:
    sequence_count = 0
    total_length = 0
    min_length: int | None = None
    max_length = 0
    duplicate_headers: list[str] = []
    invalid_symbols: dict[str, int] = {}
    headers_seen: set[str] = set()
    sampled_sequence = []
    current_header = ''
    current_length = 0

    nucleotide_symbols = set('ACGTUNRYKMSWBDHV-.')
    protein_symbols = set('ABCDEFGHIKLMNPQRSTVWXYZJUO*-.')

    def flush_record() -> None:
        nonlocal current_header, current_length, sequence_count, total_length, min_length, max_length
        if not current_header:
            return
        sequence_count += 1
        total_length += current_length
        min_length = current_length if min_length is None else min(min_length, current_length)
        max_length = max(max_length, current_length)
        current_header = ''
        current_length = 0

    try:
        with path.open('r', encoding='utf-8', errors='replace') as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith('>'):
                    flush_record()
                    header = line[1:].split()[0] or f'record_{sequence_count + 1}'
                    if header in headers_seen and len(duplicate_headers) < 20:
                        duplicate_headers.append(header)
                    headers_seen.add(header)
                    current_header = header
                    continue
                seq = line.upper()
                current_length += len(seq)
                if sum(len(item) for item in sampled_sequence) < 100000:
                    sampled_sequence.append(seq[:100000])
                for ch in seq:
                    if ch not in nucleotide_symbols and ch not in protein_symbols:
                        invalid_symbols[ch] = invalid_symbols.get(ch, 0) + 1
        flush_record()
    except UnicodeDecodeError as exc:
        return {
            'file_name': path.name,
            'status': 'blocked',
            'message': f'Unable to decode FASTA as text: {exc}',
        }

    sample = ''.join(sampled_sequence)
    nucleotide_like = sum(1 for ch in sample if ch in nucleotide_symbols)
    protein_like = sum(1 for ch in sample if ch in protein_symbols)
    molecule_guess = 'unknown'
    if sample:
        if nucleotide_like / max(1, len(sample)) > 0.9:
            molecule_guess = 'nucleotide'
        elif protein_like / max(1, len(sample)) > 0.9:
            molecule_guess = 'protein'

    status = 'ready'
    messages: list[str] = []
    if sequence_count == 0:
        status = 'blocked'
        messages.append('No FASTA records were detected.')
    if duplicate_headers:
        status = 'degraded' if status == 'ready' else status
        messages.append('Duplicate FASTA headers were detected; downstream entity-level tables may be ambiguous.')
    if invalid_symbols:
        status = 'degraded' if status == 'ready' else status
        messages.append('Unexpected sequence symbols were detected.')

    return {
        'file_name': path.name,
        'status': status,
        'message': ' '.join(messages) if messages else 'FASTA structure is readable.',
        'sequence_count': sequence_count,
        'total_length': total_length,
        'min_length': min_length or 0,
        'max_length': max_length,
        'duplicate_headers': duplicate_headers,
        'invalid_symbols': invalid_symbols,
        'molecule_guess': molecule_guess,
    }


def _read_sample_sheet(path: Path | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame()
    sheet = pd.read_csv(path, sep=None, engine='python')
    sheet.columns = [str(col).strip().lower().replace(' ', '_') for col in sheet.columns]
    rename = {
        'file': 'file_name',
        'filename': 'file_name',
        'fasta': 'file_name',
        'fasta_file': 'file_name',
        'sample': 'sample_id',
        'sample_name': 'sample_id',
        'species': 'species_id',
        'gff': 'gff_file',
        'gff3': 'gff_file',
        'annotation': 'gff_file',
        'annotation_file': 'gff_file',
    }
    return sheet.rename(columns={k: v for k, v in rename.items() if k in sheet.columns})


def build_input_qc(
    *,
    input_files: list[Path],
    annotation_files: list[Path],
    sample_sheet_path: Path | None,
    analysis_type: str,
    omics_type: str,
    group_field: str,
    reference_group: str,
) -> dict[str, Any]:
    blocking_errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    fasta_reports = [inspect_fasta_path(path) for path in input_files]
    for report in fasta_reports:
        if report.get('status') == 'blocked':
            blocking_errors.append({'code': 'FASTA_BLOCKED', 'file': report.get('file_name'), 'message': report.get('message')})
        elif report.get('status') == 'degraded':
            warnings.append({'code': 'FASTA_DEGRADED', 'file': report.get('file_name'), 'message': report.get('message')})

    if omics_type == 'genome' and not annotation_files:
        blocking_errors.append({'code': 'GENOME_REQUIRES_GFF3', 'message': 'Genome mode requires at least one GFF3/GTF annotation file.'})

    sheet_report: dict[str, Any] = {'status': 'not_provided', 'rows': 0, 'columns': []}
    try:
        sheet = _read_sample_sheet(sample_sheet_path)
        if not sheet.empty:
            sheet_report = {'status': 'ready', 'rows': int(len(sheet)), 'columns': list(sheet.columns)}
            if 'file_name' not in sheet.columns:
                blocking_errors.append({'code': 'SAMPLE_SHEET_MISSING_FILE_NAME', 'message': 'Sample sheet must contain file_name or fasta_file.'})
            else:
                sheet_files = {Path(str(value)).name for value in sheet['file_name'].dropna().tolist()}
                fasta_names = {path.name for path in input_files}
                missing = sorted(fasta_names - sheet_files)
                extra = sorted(sheet_files - fasta_names)
                if missing:
                    warnings.append({'code': 'SAMPLE_SHEET_MISSING_FASTA_ROWS', 'files': missing[:20], 'message': 'Some uploaded FASTA files are not represented in the sample sheet.'})
                if extra:
                    warnings.append({'code': 'SAMPLE_SHEET_EXTRA_FASTA_ROWS', 'files': extra[:20], 'message': 'Sample sheet contains rows that do not match uploaded FASTA files.'})
            required_group = group_field or ('species_id' if analysis_type == 'multi_species' else 'condition')
            if analysis_type != 'single_sequence' and required_group not in sheet.columns:
                warnings.append({'code': 'GROUP_FIELD_NOT_IN_SAMPLE_SHEET', 'field': required_group, 'message': 'The selected grouping field was not found; engine fallback grouping will be used.'})
            if reference_group and required_group in sheet.columns:
                groups = {str(value) for value in sheet[required_group].dropna().tolist()}
                if reference_group not in groups:
                    warnings.append({'code': 'REFERENCE_GROUP_NOT_FOUND', 'reference_group': reference_group, 'available_groups': sorted(groups)[:30]})
            if omics_type == 'genome' and len(annotation_files) > 1 and 'gff_file' not in sheet.columns:
                blocking_errors.append({'code': 'GENOME_MULTI_GFF_REQUIRES_MAPPING', 'message': 'Multiple genome FASTA/GFF files require a sample sheet gff_file column.'})
    except Exception as exc:
        blocking_errors.append({'code': 'SAMPLE_SHEET_READ_FAILED', 'message': str(exc)})

    record_count = sum(int(report.get('sequence_count') or 0) for report in fasta_reports)
    comparison_allowed = analysis_type != 'single_sequence' and len(input_files) >= 2 and not blocking_errors
    return {
        'generated_at': _now_iso(),
        'analysis_type': analysis_type,
        'omics_type': omics_type,
        'analysis_allowed': not blocking_errors,
        'comparison_allowed': comparison_allowed,
        'blocking_errors': blocking_errors,
        'warnings': warnings,
        'fasta_files': fasta_reports,
        'annotation_files': [{'file_name': path.name, 'size_bytes': path.stat().st_size if path.exists() else None} for path in annotation_files],
        'sample_sheet': sheet_report,
        'summary': {
            'file_count': len(input_files),
            'annotation_file_count': len(annotation_files),
            'record_count': record_count,
            'group_field': group_field or ('species_id' if analysis_type == 'multi_species' else 'condition' if analysis_type == 'multi_sample' else 'group'),
            'reference_group': reference_group or '',
        },
    }


def build_analysis_design(params: dict[str, Any], input_qc: dict[str, Any]) -> dict[str, Any]:
    analysis_type = params.get('analysis_type') or input_qc.get('analysis_type')
    omics_type = params.get('omics_type') or input_qc.get('omics_type')
    group_field = params.get('group_field') or input_qc.get('summary', {}).get('group_field')
    return {
        'generated_at': _now_iso(),
        'module': 'Uploaded sequence stoichiometry',
        'research_question': params.get('project_question') or 'Uploaded sequence stoichiometric profiling and comparison.',
        'comparison_intent': params.get('comparison_intent') or ('comparative' if analysis_type != 'single_sequence' else 'descriptive'),
        'replicate_type': params.get('replicate_type') or 'not_specified',
        'analysis_type': analysis_type,
        'omics_type': omics_type,
        'feature_set': params.get('feature_set', 'core'),
        'group_field': group_field,
        'reference_group': params.get('reference_group') or '',
        'statistical_plan': {
            'descriptive_features': True,
            'differential_features': analysis_type != 'single_sequence' and input_qc.get('comparison_allowed', False),
            'differential_entities': analysis_type != 'single_sequence' and input_qc.get('comparison_allowed', False),
            'multiple_testing': 'Benjamini-Hochberg FDR when differential tests are available.',
            'effect_size_required_for_interpretation': True,
        },
        'evidence_policy': {
            'primary_tables': ['sequence_features.csv', 'differential_features.csv', 'differential_entities.csv'],
            'visual_payloads': ['basic_visualization_payload.json', 'core_feature_panels.json', 'sample_comparison_payload.json', 'ml_discrimination_payload.json'],
            'interpretation_rule': 'Treat exploratory ML/separability as hypothesis-generating unless sample size and validation support are adequate.',
        },
        'input_qc_status': 'ready' if input_qc.get('analysis_allowed') else 'blocked',
    }


def build_result_interpretation(meta: dict[str, Any], input_qc: dict[str, Any], analysis_design: dict[str, Any]) -> dict[str, Any]:
    summary = meta.get('summary') or {}
    warnings = list(input_qc.get('warnings') or [])
    if summary.get('group_count', 0) and int(summary.get('group_count') or 0) < 2:
        warnings.append({'code': 'DESCRIPTIVE_ONLY', 'message': 'Only one group was detected; comparative claims should not be made.'})
    return {
        'generated_at': _now_iso(),
        'job_id': meta.get('job_id'),
        'status': meta.get('status'),
        'research_question': analysis_design.get('research_question'),
        'high_level_result': {
            'record_count': summary.get('record_count'),
            'sample_count': summary.get('sample_count'),
            'group_count': summary.get('group_count'),
            'feature_count': summary.get('feature_count'),
            'differential_feature_count': summary.get('differential_feature_count'),
            'differential_entity_count': summary.get('differential_entity_count'),
        },
        'interpretation_scope': {
            'can_support_descriptive_profile': meta.get('status') == 'SUCCEEDED',
            'can_support_group_comparison': bool(input_qc.get('comparison_allowed')) and meta.get('status') == 'SUCCEEDED',
            'can_support_publication_grade_claim': bool(input_qc.get('comparison_allowed')) and int(summary.get('sample_count') or 0) >= 6,
        },
        'recommended_read_order': [
            'input_qc.json',
            'analysis_design.json',
            'summary.json',
            'feature_summary.json',
            'differential_features.csv',
            'differential_entities.csv',
            'method_metadata.json',
        ],
        'warnings': warnings,
        'claim_guardrails': [
            'Report feature direction, effect size, FDR and group sample counts together.',
            'Do not interpret Top/Low records as differential entities unless group-aware support is present.',
            'Use ML discrimination outputs as exploratory evidence unless external validation or adequate cross-validation is available.',
        ],
    }


def build_job_manifest(meta: dict[str, Any], stage: str) -> dict[str, Any]:
    return {
        'generated_at': _now_iso(),
        'stage': stage,
        'job_id': meta.get('job_id'),
        'name': meta.get('name'),
        'module': 'Uploaded sequence stoichiometry',
        'status': meta.get('status'),
        'created_at': meta.get('created_at'),
        'updated_at': meta.get('updated_at'),
        'expires_at': meta.get('expires_at'),
        'privacy': meta.get('privacy'),
        'inputs': meta.get('inputs'),
        'outputs': meta.get('outputs') or {},
        'reproducibility': meta.get('reproducibility'),
    }


def build_download_manifest(job_id: str, output_files: dict[str, str], output_dir: Path) -> dict[str, Any]:
    items = []
    for kind, filename in output_files.items():
        path = output_dir / filename
        items.append({
            'kind': kind,
            'filename': filename,
            'exists': path.exists(),
            'size_bytes': path.stat().st_size if path.exists() else None,
            'download_url': f'/api/sequence-analysis/jobs/{job_id}/download/{kind}/',
        })
    return {
        'generated_at': _now_iso(),
        'job_id': job_id,
        'items': items,
        'required_research_contract': [
            'job_manifest',
            'input_qc',
            'analysis_design',
            'method_metadata',
            'result_interpretation',
            'download_manifest',
            'reproducibility_manifest',
        ],
    }


def write_sequence_contracts(
    *,
    root: Path,
    output_dir: Path,
    meta: dict[str, Any],
    params: dict[str, Any],
    output_files: dict[str, str],
    input_qc: dict[str, Any] | None = None,
    analysis_design: dict[str, Any] | None = None,
    stage: str,
) -> dict[str, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    input_qc = input_qc or meta.get('input_qc') or {}
    analysis_design = analysis_design or meta.get('analysis_design') or build_analysis_design(params, input_qc)
    result_interpretation = build_result_interpretation(meta, input_qc, analysis_design)
    job_manifest = build_job_manifest(meta, stage)
    download_manifest = build_download_manifest(str(meta.get('job_id') or ''), output_files, output_dir)
    payloads = {
        'input_qc': input_qc,
        'analysis_design': analysis_design,
        'result_interpretation': result_interpretation,
        'job_manifest': job_manifest,
        'download_manifest': download_manifest,
    }
    filenames = {
        'input_qc': 'input_qc.json',
        'analysis_design': 'analysis_design.json',
        'result_interpretation': 'result_interpretation.json',
        'job_manifest': 'job_manifest.json',
        'download_manifest': 'download_manifest.json',
    }
    for key, payload in payloads.items():
        _write_json(output_dir / filenames[key], payload)
    download_manifest = build_download_manifest(str(meta.get('job_id') or ''), output_files, output_dir)
    _write_json(output_dir / filenames['download_manifest'], download_manifest)
    payloads['download_manifest'] = download_manifest
    _write_json(root / 'logs' / 'job_manifest.json', job_manifest)
    return payloads
