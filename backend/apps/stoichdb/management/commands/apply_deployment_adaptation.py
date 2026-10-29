import json
from django.core.management.base import BaseCommand,CommandError
from backend.apps.common.atomic_json import atomic_write_json
from pathlib import Path
from deploy import compatibility as c
class Command(BaseCommand):
 def add_arguments(self,p):
  p.add_argument('--plan',required=True);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--dry-run',action='store_true');g.add_argument('--apply',action='store_true');p.add_argument('--owner');p.add_argument('--generation',type=int)
 def handle(self,*args,**o):
  try:
   result=c.apply(o['plan'],o['dry_run'],o['owner'],o['generation']);self.stdout.write(json.dumps(result))
  except (ValueError,OSError,KeyError,TypeError) as e:raise CommandError(str(e),returncode=20)
