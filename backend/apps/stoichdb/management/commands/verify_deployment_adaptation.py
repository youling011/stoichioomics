import json
from django.core.management.base import BaseCommand,CommandError
from backend.apps.common.atomic_json import atomic_write_json
from pathlib import Path
from deploy import compatibility as c
class Command(BaseCommand):
 def add_arguments(self,p):
  p.add_argument('--plan',required=True);p.add_argument('--report',required=True)
 def handle(self,*args,**o):
  try:
   result=c.verify(o['plan']);atomic_write_json(Path(o['report']),result);self.stdout.write(json.dumps(result));
   if not result['applied']:raise CommandError('Valid plan has not been applied',returncode=10)
  except (ValueError,OSError,KeyError,TypeError) as e:raise CommandError(str(e),returncode=20)
