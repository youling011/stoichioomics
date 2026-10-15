from rest_framework.decorators import api_view

from backend.apps.common.responses import ok, err
from . import entity_report
from . import services


def _as_bool(value, default=False):
    text = str(value if value is not None else '').strip().lower()
    if not text:
        return default
    return text in {'1', 'true', 'yes', 'on'}


@api_view(['GET'])
def entity_search_view(request):
    try:
        return ok(entity_report.search_entities(
            q=request.GET.get('q') or request.GET.get('query') or '',
            species_id=request.GET.get('species_id', ''),
            omics=request.GET.get('omics', ''),
            id_type=request.GET.get('id_type', ''),
            limit=request.GET.get('limit', 30),
            include_synonyms=_as_bool(request.GET.get('include_synonyms'), True),
        ))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def entity_report_view(request, species_id: str, entity_key: str):
    try:
        return ok(entity_report.get_entity_report(
            species_id,
            entity_key,
            prefer_canonical=_as_bool(request.GET.get('prefer_canonical'), True),
            include_raw=_as_bool(request.GET.get('include_raw'), False),
            include_charts=_as_bool(request.GET.get('include_charts'), True),
            include_neighbors=_as_bool(request.GET.get('include_neighbors'), True),
        ))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['POST'])
def entity_batch_report_view(request):
    try:
        return ok(entity_report.batch_entity_report(request.data or {}))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def entity_chart_context_view(request, species_id: str, entity_key: str):
    try:
        return ok(entity_report.get_entity_chart_context(
            species_id,
            entity_key,
            module_id=request.GET.get('module_id', ''),
            chart_id=request.GET.get('chart_id', ''),
            nearest_neighbors=_as_bool(request.GET.get('nearest_neighbors'), True),
        ))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def entity_evidence_view(request, species_id: str, entity_key: str):
    try:
        return ok(entity_report.get_entity_evidence(
            species_id,
            entity_key,
            scope=request.GET.get('scope', ''),
            min_severity=request.GET.get('min_severity', ''),
            module_ids=request.GET.get('module_ids', ''),
        ))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)


@api_view(['GET'])
def entity_raw_view(request, species_id: str, entity_key: str):
    try:
        return ok(entity_report.get_entity_raw(
            species_id,
            entity_key,
            omics=request.GET.get('omics', ''),
            feature_set=request.GET.get('feature_set', 'core'),
        ))
    except services.NotFoundError as exc:
        return err(str(exc), status=404)

