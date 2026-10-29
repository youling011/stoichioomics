from django.core.management.base import BaseCommand,CommandError
from backend.apps.common.task_execution import drain,execute
class Command(BaseCommand):
 def add_arguments(self,p):p.add_argument('--drain',action='store_true');p.add_argument('--request-id')
 def handle(self,*a,**o):
  if bool(o['drain'])==bool(o['request_id']):raise CommandError('Select exactly one of --drain or --request-id')
  if o['drain']:drain()
  else:self.stdout.write(__import__('json').dumps(execute(o['request_id']),default=str))
