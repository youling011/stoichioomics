"""Load a private environment without shell expansion; become the uWSGI process."""
import json, os, sys
from pathlib import Path
test=len(sys.argv)>1 and sys.argv[1]=='test'
env=json.loads(Path('/opt/local/private/'+('test-env.json' if test else 'runtime-env.json')).read_text())
os.environ.update(env)
import subprocess
if not test:subprocess.run(['/opt/local/venv/bin/python','-B','/opt/local/project/manage.py','reconcile_task_executors'],check=True)
os.execv('/opt/local/venv/bin/uwsgi',['uwsgi','--ini','/opt/local/config/'+('uwsgi-test.ini' if test else 'uwsgi.ini')])
