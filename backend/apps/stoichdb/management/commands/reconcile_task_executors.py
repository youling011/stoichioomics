from django.core.management.base import BaseCommand,CommandError
from backend.apps.common.task_execution import reconcile,dispatch
class Command(BaseCommand):
 def add_arguments(self,p):p.add_argument('--apply',action='store_true');p.add_argument('--resume-queued',action='store_true')
 def handle(self,*a,**o):
  if o['resume_queued'] and not o['apply']:raise CommandError('--resume-queued requires explicit --apply')
  rows=reconcile(apply=o['apply'])
  if o['resume_queued']:dispatch()
  self.stdout.write(__import__('json').dumps({'interrupted':rows,'applied':o['apply']}))
