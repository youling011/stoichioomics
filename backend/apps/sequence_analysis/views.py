from __future__ import annotations

from django.http import FileResponse, HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from .services import (
    create_sequence_job,
    entity_comparison,
    export_table,
    feature_comparison,
    field_summary,
    get_sequence_job,
    list_sequence_jobs,
    output_path,
    read_analysis_payload,
    read_analysis_design,
    read_basic_visualization,
    read_core_feature_panels,
    read_download_manifest,
    read_feature_catalog,
    read_feature_summary,
    read_input_qc,
    read_job_manifest,
    read_ml_discrimination,
    read_platform_bundle,
    read_plots,
    read_result_interpretation,
    read_sample_comparison,
    read_sequence_logs,
    read_sequence_reproducibility,
    read_table,
    scatter_payload,
    prevalidate_sequence_inputs,
    sequence_sample_sheet_template,
    top_low_entities,
)


def ok(data, status_code=status.HTTP_200_OK):
    return Response({'ok': True, 'data': data}, status=status_code)


def fail(message, status_code=status.HTTP_400_BAD_REQUEST):
    return Response({'ok': False, 'error': str(message)}, status=status_code)


@api_view(['GET', 'POST'])
@parser_classes([MultiPartParser, FormParser])
def jobs_view(request):
    if request.method == 'GET':
        return ok(list_sequence_jobs())
    try:
        files = request.FILES.getlist('files')
        annotation_files = request.FILES.getlist('annotation_files')
        sample_sheet = request.FILES.get('sample_sheet')
        try:
            genetic_code = int(request.data.get('genetic_code', 1) or 1)
        except ValueError:
            genetic_code = 1
        payload = create_sequence_job(
            uploads=files,
            annotation_uploads=annotation_files,
            sample_sheet=sample_sheet,
            analysis_type=request.data.get('analysis_type', 'single_sequence'),
            omics_type=request.data.get('omics_type', 'transcriptome'),
            group_field=request.data.get('group_field', ''),
            reference_group=request.data.get('reference_group', ''),
            feature_set=request.data.get('feature_set', 'core'),
            genetic_code=genetic_code,
            name=request.data.get('name', ''),
            project_question=request.data.get('project_question', ''),
            comparison_intent=request.data.get('comparison_intent', ''),
            replicate_type=request.data.get('replicate_type', ''),
        )
        return ok(payload, status.HTTP_201_CREATED)
    except ValueError as exc:
        return fail(exc)


@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def prevalidate_view(request):
    try:
        payload = prevalidate_sequence_inputs(
            uploads=request.FILES.getlist('files'),
            annotation_uploads=request.FILES.getlist('annotation_files'),
            sample_sheet=request.FILES.get('sample_sheet'),
            analysis_type=request.data.get('analysis_type', 'single_sequence'),
            omics_type=request.data.get('omics_type', 'transcriptome'),
            group_field=request.data.get('group_field', ''),
            reference_group=request.data.get('reference_group', ''),
        )
        return ok(payload)
    except ValueError as exc:
        return fail(exc)


@api_view(['GET'])
def sample_sheet_template_view(request):
    filename, csv_text = sequence_sample_sheet_template(
        request.query_params.get('analysis_type', 'multi_sample'),
        request.query_params.get('omics_type', 'transcriptome'),
    )
    response = HttpResponse(csv_text, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@api_view(['GET'])
def job_detail_view(request, job_id):
    try:
        return ok(get_sequence_job(job_id))
    except FileNotFoundError:
        return fail('Sequence analysis job not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def job_logs_view(request, job_id):
    try:
        try:
            tail = int(request.query_params.get('tail', 200))
        except ValueError:
            tail = 200
        return ok(read_sequence_logs(job_id, tail=tail))
    except FileNotFoundError:
        return fail('Sequence analysis job not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def job_reproducibility_view(request, job_id):
    try:
        return ok(read_sequence_reproducibility(job_id))
    except FileNotFoundError:
        return fail('Sequence reproducibility manifest not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def job_manifest_view(request, job_id):
    try:
        return ok(read_job_manifest(job_id))
    except FileNotFoundError:
        return fail('Sequence job manifest not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def input_qc_view(request, job_id):
    try:
        return ok(read_input_qc(job_id))
    except FileNotFoundError:
        return fail('Sequence input QC not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def analysis_design_view(request, job_id):
    try:
        return ok(read_analysis_design(job_id))
    except FileNotFoundError:
        return fail('Sequence analysis design not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def result_interpretation_view(request, job_id):
    try:
        return ok(read_result_interpretation(job_id))
    except FileNotFoundError:
        return fail('Sequence result interpretation not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def download_manifest_view(request, job_id):
    try:
        return ok(read_download_manifest(job_id))
    except FileNotFoundError:
        return fail('Sequence download manifest not found.', status.HTTP_404_NOT_FOUND)


def _limit_offset(request):
    try:
        limit = int(request.query_params.get('limit', 100))
        offset = int(request.query_params.get('offset', 0))
    except ValueError:
        limit, offset = 100, 0
    return min(limit, 1000), max(offset, 0)


@api_view(['GET'])
def features_view(request, job_id):
    try:
        limit, offset = _limit_offset(request)
        return ok(read_table(
            job_id,
            'features',
            limit=limit,
            offset=offset,
            search=request.query_params.get('search', ''),
            sort_by=request.query_params.get('sort_by', ''),
            sort_order=request.query_params.get('sort_order', 'asc'),
            columns=request.query_params.get('columns'),
        ))
    except FileNotFoundError:
        return fail('Sequence features table not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def differential_features_view(request, job_id):
    try:
        limit, offset = _limit_offset(request)
        return ok(read_table(
            job_id,
            'differential_features',
            limit=limit,
            offset=offset,
            search=request.query_params.get('search', ''),
            sort_by=request.query_params.get('sort_by', ''),
            sort_order=request.query_params.get('sort_order', 'asc'),
            columns=request.query_params.get('columns'),
        ))
    except FileNotFoundError:
        return fail('Differential features table not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def differential_entities_view(request, job_id):
    try:
        limit, offset = _limit_offset(request)
        return ok(read_table(
            job_id,
            'differential_entities',
            limit=limit,
            offset=offset,
            search=request.query_params.get('search', ''),
            sort_by=request.query_params.get('sort_by', ''),
            sort_order=request.query_params.get('sort_order', 'asc'),
            columns=request.query_params.get('columns'),
        ))
    except FileNotFoundError:
        return fail('Differential entities table not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def plots_view(request, job_id):
    try:
        return ok(read_plots(job_id))
    except FileNotFoundError:
        return fail('Plot payload not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def platform_bundle_view(request, job_id):
    try:
        return ok(read_platform_bundle(job_id))
    except FileNotFoundError:
        return fail('Platform visualization bundle not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def analysis_payload_view(request, job_id):
    try:
        return ok(read_analysis_payload(job_id))
    except FileNotFoundError:
        return fail('Analysis payload not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def feature_catalog_view(request, job_id):
    try:
        return ok(read_feature_catalog(job_id))
    except FileNotFoundError:
        return fail('Feature catalog not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def feature_summary_view(request, job_id):
    try:
        return ok(read_feature_summary(job_id, request.query_params.get('feature', '')))
    except FileNotFoundError:
        return fail('Feature summary not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def basic_visualization_view(request, job_id):
    try:
        return ok(read_basic_visualization(job_id))
    except FileNotFoundError:
        return fail('Basic visualization payload not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def core_feature_panels_view(request, job_id):
    try:
        filters = {
            'group': request.query_params.get('group', ''),
            'sample_id': request.query_params.get('sample_id', ''),
            'species_id': request.query_params.get('species_id', ''),
            'condition': request.query_params.get('condition', ''),
            'seqid': request.query_params.get('seqid', ''),
            'strand': request.query_params.get('strand', ''),
            'source_db': request.query_params.get('source_db', ''),
            'biotype': request.query_params.get('biotype', ''),
            'transcript_biotype': request.query_params.get('transcript_biotype', ''),
        }
        return ok(read_core_feature_panels(
            job_id,
            filters=filters,
            panel_id=request.query_params.get('panel_id', ''),
        ))
    except FileNotFoundError:
        return fail('Core feature panels payload not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def top_low_view(request, job_id):
    try:
        try:
            n = int(request.query_params.get('n', 10))
        except ValueError:
            n = 10
        return ok(top_low_entities(job_id, request.query_params.get('feature', ''), n=max(1, min(n, 50))))
    except KeyError:
        return fail('Requested Top/Low feature not found.', status.HTTP_404_NOT_FOUND)
    except FileNotFoundError:
        return fail('Top/Low entities payload not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def sample_comparison_view(request, job_id):
    try:
        return ok(read_sample_comparison(job_id))
    except FileNotFoundError:
        return fail('Sample comparison payload not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET', 'POST'])
def ml_discrimination_view(request, job_id):
    try:
        label_field = request.data.get('label_field') if request.method == 'POST' else request.query_params.get('label_field')
        return ok(read_ml_discrimination(job_id, label_field or 'group'))
    except FileNotFoundError:
        return fail('ML discrimination payload not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def field_summary_view(request, job_id):
    try:
        return ok(field_summary(job_id, request.query_params.get('field', '')))
    except KeyError:
        return fail('Requested feature field not found.', status.HTTP_404_NOT_FOUND)
    except FileNotFoundError:
        return fail('Platform rows not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def scatter_view(request, job_id):
    try:
        sample = int(request.query_params.get('sample', 1200))
    except ValueError:
        sample = 1200
    try:
        return ok(scatter_payload(
            job_id,
            request.query_params.get('x', ''),
            request.query_params.get('y', ''),
            sample=sample,
        ))
    except KeyError:
        return fail('Requested scatter fields not found.', status.HTTP_404_NOT_FOUND)
    except FileNotFoundError:
        return fail('Platform rows not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def feature_comparison_view(request, job_id):
    try:
        return ok(feature_comparison(job_id, request.query_params.get('feature', '')))
    except KeyError:
        return fail('Requested comparison feature not found.', status.HTTP_404_NOT_FOUND)
    except FileNotFoundError:
        return fail('Platform rows not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def entity_comparison_view(request, job_id):
    entities = [item.strip() for item in request.query_params.get('entities', '').split(',') if item.strip()]
    features = [item.strip() for item in request.query_params.get('features', '').split(',') if item.strip()]
    try:
        return ok(entity_comparison(job_id, entities, features))
    except KeyError:
        return fail('Requested entities or features were not found.', status.HTTP_404_NOT_FOUND)
    except FileNotFoundError:
        return fail('Platform rows not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def download_view(request, job_id, kind):
    try:
        path = output_path(job_id, kind)
        return FileResponse(path.open('rb'), as_attachment=True, filename=path.name)
    except FileNotFoundError:
        return fail('Requested output file not found.', status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
def table_export_view(request, job_id, kind):
    try:
        filename, csv_text = export_table(
            job_id,
            kind,
            search=request.query_params.get('search', ''),
            sort_by=request.query_params.get('sort_by', ''),
            sort_order=request.query_params.get('sort_order', 'asc'),
            columns=request.query_params.get('columns'),
        )
        response = HttpResponse(csv_text, content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
    except FileNotFoundError:
        return fail('Requested table kind not found.', status.HTTP_404_NOT_FOUND)
