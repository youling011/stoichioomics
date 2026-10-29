import json
from django.core.management.base import BaseCommand,CommandError
from backend.apps.common.atomic_json import atomic_write_json
from pathlib import Path
from deploy import compatibility as c
class Command(BaseCommand):
 def add_arguments(self,p):
  p.add_argument('--read-only',action='store_true',required=True);p.add_argument('--inventory',required=True)
 def handle(self,*args,**o):
  try:
   result=c.audit();atomic_write_json(Path(o['inventory']),result);self.stdout.write(json.dumps({'complete':result['complete'],'objects':len(result['objects']),'errors':result['errors']}));
   if not result['complete']:raise CommandError('Inventory contains errors',returncode=20)
  except (ValueError,OSError,KeyError,TypeError) as e:raise CommandError(str(e),returncode=20)
