import json
from django.core.management.base import BaseCommand,CommandError
from backend.apps.common.atomic_json import atomic_write_json
from pathlib import Path
from deploy import compatibility as c
class Command(BaseCommand):
 def add_arguments(self,p):
  p.add_argument('--inventory',required=True);p.add_argument('--output',required=True)
 def handle(self,*args,**o):
  try:
   result=c.plan(o['inventory']);atomic_write_json(Path(o['output']),result);self.stdout.write(json.dumps({'actions':len(result['actions']),'science_rebuilds':result['science_rebuilds']}))
  except (ValueError,OSError,KeyError,TypeError) as e:raise CommandError(str(e),returncode=20)
