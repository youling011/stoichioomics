from django.urls import path
from django.views.decorators.gzip import gzip_page
from rest_framework.decorators import api_view
from backend.apps.common.responses import ok,err
from backend.apps.hvg import research_services as service
from backend.portal.results import load_case_outputs_lazy

@gzip_page
@api_view(['GET'])
def manifest(request,identifier):
 try:
  base=service.authorize(identifier,request.headers.get('X-Job-Token'));outputs=load_case_outputs_lazy(base)
  phase1=outputs.get('phase1_summary') or {};phase2=outputs.get('phase2_summary') or {}
  compact=lambda value:{k:v for k,v in value.items() if isinstance(v,(str,int,float,bool)) or v is None}
  return ok({'format':'hvg-result-manifest-v1','identifier':identifier,'phase1':compact(phase1),'phase2':compact(phase2),'visualization_manifest':outputs.get('visualization_manifest') or {},'links':{'summary':f'/api/hvg/{identifier}/summary/','phase1':f'/api/hvg/{identifier}/phase1-summary/','phase2':f'/api/hvg/{identifier}/phase2-summary/','plots':f'/api/hvg/{identifier}/plots/','group_comparison':f'/api/hvg/{identifier}/group-comparison/summary/','visuals':f'/api/hvg/{identifier}/visuals/'}})
 except PermissionError as exc:return err(str(exc),status=403)
 except FileNotFoundError:return err('Saved result not found.',status=404)
urlpatterns=[path('<str:identifier>/manifest/',manifest)]
