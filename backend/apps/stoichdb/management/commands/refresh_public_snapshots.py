import json
from django.core.management.base import BaseCommand
from backend.apps.common.public_snapshots import refresh,invalidate_public_data
class Command(BaseCommand):
 def add_arguments(self,p):
  p.add_argument('--names',default='docs,cases');p.add_argument('--invalidate',action='store_true')
 def handle(self,*args,**o):
  from backend.apps.stoichdb import services,case_studies
  if o['invalidate']:invalidate_public_data()
  functions={'docs':services.docs_payload,'cases':case_studies.case_study_gallery_payload,'quality':services.quality_overview}
  result=[refresh(functions[n]) for n in o['names'].split(',')]
  self.stdout.write(json.dumps(result))
