from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import JSONParser
from backend.apps.common.responses import ok, err
from .services import list_cases, register_existing_case, unregister_existing_case, promote_job, compare_case_ids


@api_view(['GET'])
def registry_cases(request):
    return ok(list_cases())


@api_view(['POST'])
@parser_classes([JSONParser])
def registry_register(request):
    base_dir = request.data.get('base_dir')
    if not base_dir:
        return err('base_dir is required')
    label = request.data.get('label')
    tags = request.data.get('tags') or []
    return ok(register_existing_case(base_dir, label=label, tags=tags))


@api_view(['POST'])
@parser_classes([JSONParser])
def registry_promote(request):
    job_id = request.data.get('job_id')
    if not job_id:
        return err('job_id is required')
    label = request.data.get('label')
    tags = request.data.get('tags') or []
    return ok(promote_job(job_id, label=label, tags=tags))


@api_view(['POST'])
@parser_classes([JSONParser])
def registry_unregister(request):
    base_dir = request.data.get('base_dir')
    if not base_dir:
        return err('base_dir is required')
    return ok({'removed': unregister_existing_case(base_dir)})


@api_view(['POST'])
@parser_classes([JSONParser])
def registry_compare(request):
    case_ids = request.data.get('case_ids') or []
    df = compare_case_ids(case_ids)
    return ok({'rows': df.to_dict(orient='records')})
