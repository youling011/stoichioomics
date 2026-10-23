from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.http import FileResponse
from django.urls import path
from rest_framework.decorators import api_view

from backend.apps.common.responses import err, ok
from ..models import OmicsDataset, Species
from . import exports, runs
from .catalog import catalog
from .contracts import CompareError, OMICS
from .models import CompareRun


def endpoint(methods):
    def decorate(fn):
        @api_view(methods)
        @wraps(fn)
        def wrapped(request, *args, **kwargs):
            if not getattr(settings, 'COMPARE_CORE_ENABLED', True):
                return err('Core comparison is disabled.', status=503, details={'code': 'feature_disabled'})
            try:
                return fn(request, *args, **kwargs)
            except CompareError as exc:
                return err(str(exc), status=exc.status, details={'code': exc.code})
            except CompareRun.DoesNotExist:
                return err('Unknown comparison run.', status=404)
        return wrapped
    return decorate


@endpoint(['GET'])
def catalog_view(request):
    return ok(catalog())


@endpoint(['GET'])
def species_view(request):
    try:
        page = int(request.GET.get('page', 1))
        size = int(request.GET.get('page_size', 12))
    except ValueError:
        raise CompareError('Invalid page parameters.')
    if page < 1 or not 1 <= size <= 200:
        raise CompareError('Page or page_size is out of range.')
    from django.db.models import Q
    qs = Species.objects.all()
    q = request.GET.get('query', '').strip()
    if q:
        qs = qs.filter(Q(species_id__icontains=q) | Q(display_name__icontains=q) | Q(short_name__icontains=q) | Q(taxonomy_id__icontains=q))
    domain = request.GET.get('domain', '')
    if domain:
        qs = qs.filter(domain=domain)
    omics = [x for x in request.GET.get('omics', '').split(',') if x]
    if any(o not in OMICS for o in omics):
        raise CompareError('Unknown omics scope.')
    for o in omics:
        qs = qs.filter(**{f'has_{o}': True})
    qs = qs.order_by('display_name', 'species_id')
    total = qs.count()
    rows = list(qs.values('species_id', 'display_name', 'domain', 'taxonomy_id', 'has_genome', 'has_transcriptome', 'has_proteome')[(page - 1) * size:page * size])
    ids = [r['species_id'] for r in rows]
    availability = {}
    for ds in OmicsDataset.objects.filter(species__species_id__in=ids).values('species__species_id', 'omics_type', 'status', 'row_count_core', 'core_csv_path'):
        availability.setdefault(ds['species__species_id'], {})[ds['omics_type']] = {'registered_rows': ds['row_count_core'], 'status': ds['status'], 'registered_source': bool(ds['core_csv_path'])}
    for row in rows:
        row['core_datasets'] = availability.get(row['species_id'], {})
    return ok({'items': rows, 'page': page, 'page_size': size, 'total': total, 'has_next': page * size < total})


@endpoint(['POST'])
def create_view(request):
    run, created = runs.create(request.data)
    return ok({**runs.status(run), 'reused': not created}, status=202 if created or run.status not in ('completed', 'partial') else 200)


def get_run(run_id):
    return CompareRun.objects.get(pk=run_id)


@endpoint(['GET'])
def status_view(request, run_id):
    return ok(runs.status(get_run(run_id)))


@endpoint(['GET'])
def result_view(request, run_id):
    return ok(exports.result(get_run(run_id)))


@endpoint(['GET'])
def table_view(request, run_id):
    params = request.GET
    return ok(exports.table(get_run(run_id), params.get('kind', 'coverage'), params.get('page', 1), params.get('page_size', 50),
                            params.get('field', ''), params.get('query', ''), params.get('sort_by', ''), params.get('direction', 'asc')))


@endpoint(['GET'])
def distribution_view(request, run_id):
    run = get_run(run_id)
    ids = [sid for sid in request.GET.get('species_ids', ','.join(run.request_json['species_ids'])).split(',') if sid]
    return ok(exports.distribution(run, request.GET.get('field_key', ''), ids))


@endpoint(['POST'])
def cancel_view(request, run_id):
    return ok(runs.status(runs.cancel(get_run(run_id))))


@endpoint(['POST'])
def resume_view(request, run_id):
    return ok(runs.status(runs.resume(get_run(run_id))), status=202)


@endpoint(['GET'])
def download_view(request, run_id):
    run = get_run(run_id)
    meta = exports.result(run)
    kind = request.GET.get('kind', 'bundle')
    if kind == 'bundle':
        filename = 'compare_result.zip'
    elif kind in meta['tables']:
        filename = meta['tables'][kind]['filename']
    elif kind in ('manifest', 'source_manifest', 'request'):
        filename = kind + '.json'
    else:
        raise CompareError('Unknown download kind.')
    location = exports.run_dir(run) / filename
    if not location.is_file():
        raise CompareError('Saved download is unavailable.', 'artifact_unavailable', 404)
    return FileResponse(location.open('rb'), as_attachment=True, filename=filename)


urlpatterns = [
    path('compare/core/catalog/', catalog_view),
    path('compare/core/species/', species_view),
    path('compare/core/runs/', create_view),
    path('compare/core/runs/<uuid:run_id>/', status_view),
    path('compare/core/runs/<uuid:run_id>/result/', result_view),
    path('compare/core/runs/<uuid:run_id>/table/', table_view),
    path('compare/core/runs/<uuid:run_id>/distribution/', distribution_view),
    path('compare/core/runs/<uuid:run_id>/cancel/', cancel_view),
    path('compare/core/runs/<uuid:run_id>/resume/', resume_view),
    path('compare/core/runs/<uuid:run_id>/download/', download_view),
]
