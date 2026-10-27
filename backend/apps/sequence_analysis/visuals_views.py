from urllib.parse import quote
from django.conf import settings
from django.urls import path
from django.views.decorators.gzip import gzip_page
from rest_framework.decorators import api_view,content_negotiation_class
from backend.apps.common.responses import ok,err
from backend.apps.common.workflow_visuals.contracts import parameters
from backend.apps.common.workflow_visuals.exports import export,ExportNegotiation
from backend.apps.common.workflow_visuals.records import records
from . import visuals_v2 as v

@gzip_page
@api_view(['GET'])
@content_negotiation_class(ExportNegotiation)
def visuals(request,job_id,chart_id=None,action=None):
    try:
        if not getattr(settings,'WORKFLOW_VISUALS_V2_ENABLED',True):return err('workflow_visuals_v2_disabled',status=404)
        parameters(request.query_params)
        root,job=v.resolve(job_id)
        if chart_id is None:return ok(v.capability(root,job))
        bundle=v.build(root,job,chart_id,request.query_params)
        prefix='/api/sequence-analysis/jobs/'+quote(job_id,safe='')+'/visuals/'+chart_id+'/'
        bundle.packet['exports']={'plot':prefix+'export/?export_scope=plot','source':prefix+'export/?export_scope=source','records':prefix+'records/'}
        if action=='export':return export(bundle,request.query_params)
        if action=='records':return ok(records(bundle,request.query_params))
        return ok(bundle.public())
    except PermissionError as exc:return err(str(exc),status=403)
    except FileNotFoundError:return err('Saved task or artifact not found.',status=404)
    except (ValueError,TypeError,KeyError) as exc:return err(str(exc),status=400)
    except RuntimeError as exc:return err(str(exc),status=409)

urlpatterns=[path('jobs/<str:job_id>/visuals/<str:chart_id>/export/',visuals,{'action':'export'}),
 path('jobs/<str:job_id>/visuals/<str:chart_id>/records/',visuals,{'action':'records'}),
 path('jobs/<str:job_id>/visuals/<str:chart_id>/',visuals),path('jobs/<str:job_id>/visuals/',visuals)]
