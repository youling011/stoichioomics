import json
from django.core.management.base import BaseCommand,CommandError
from backend.apps.common import maintenance
from deploy.task_inventory import inventory
class Command(BaseCommand):
 def add_arguments(self,p):
  p.add_argument('action',choices=['status','enter','advance','leave','guard']);p.add_argument('--owner');p.add_argument('--generation',type=int);p.add_argument('--include-requests',action='store_true')
 def handle(self,*a,**o):
  action=o['action']
  if action=='status':result=maintenance.state()
  elif action=='guard':
   result=inventory(o['include_requests']);self.stdout.write(json.dumps(result,default=str))
   if not result['safe_to_stop']:raise CommandError('Stop refused: active work or unreadable task state',returncode=20)
   return
  elif action=='enter':result=maintenance.enter(o['owner'])
  else:
   if not o['owner'] or o['generation'] is None:raise CommandError('Owner and generation are required')
   result=getattr(maintenance,action)(o['owner'],o['generation'])
  self.stdout.write(json.dumps(result,default=str))
