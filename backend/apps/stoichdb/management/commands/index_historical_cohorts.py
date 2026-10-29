import json
from django.core.management.base import BaseCommand
class Command(BaseCommand):
 def handle(self,*args,**o):
  from backend.apps.stoichdb.integration_viz.cohort_artifacts import index_historical_cohorts
  self.stdout.write(json.dumps(index_historical_cohorts()))
