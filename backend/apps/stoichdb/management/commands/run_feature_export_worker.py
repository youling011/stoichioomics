from django.core.management.base import BaseCommand,CommandError
from backend.apps.common.task_execution import find,execute,resume
class Command(BaseCommand):
 def add_arguments(self,p):p.add_argument('--export-id',required=True);p.add_argument('--resume',action='store_true')
 def handle(self,*a,**o):
  record=resume('feature_export',o['export_id']) if o['resume'] else find('feature_export',o['export_id'])
  if not record:raise CommandError('No registered task executor request')
  self.stdout.write(__import__('json').dumps(execute(record['request_id']),default=str))
