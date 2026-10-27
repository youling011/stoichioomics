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
def visuals(request,identifier,chart_id=None,action=None):
    try:
        if not getattr(settings,'WORKFLOW_VISUALS_V2_ENABLED',True):return err('workflow_visuals_v2_disabled',status=404)
        parameters(request.query_params);source=v.resolve(identifier,request.headers.get('X-Job-Token'),request.query_params)
        if chart_id is None:return ok(v.capabilities(source))
        bundle=v.build(source,chart_id,request.query_params);prefix='/api/hvg/'+quote(identifier,safe='')+'/visuals/'+chart_id+'/'
        bundle.packet['exports']={'plot':prefix+'export/?export_scope=plot','source':prefix+'export/?export_scope=source','records':prefix+'records/'}
        if action=='export':return export(bundle,request.query_params)
        if action=='records':return ok(records(bundle,request.query_params))
        return ok(bundle.public())
    except PermissionError as exc:return err(str(exc),status=403)
    except FileNotFoundError:return err('Saved case/run/artifact not found.',status=404)
    except (ValueError,TypeError,KeyError) as exc:return err(str(exc),status=400)
    except RuntimeError as exc:return err(str(exc),status=409)

urlpatterns=[path('<str:identifier>/visuals/<str:chart_id>/export/',visuals,{'action':'export'}),
 path('<str:identifier>/visuals/<str:chart_id>/records/',visuals,{'action':'records'}),
 path('<str:identifier>/visuals/<str:chart_id>/',visuals),path('<str:identifier>/visuals/',visuals)]
