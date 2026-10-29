"""Explicit maintenance commands using the selected private environment."""
import json,os,sys
from pathlib import Path
mode=sys.argv[1]
assert mode in ['main','test','regression']
env=os.environ.copy()
env.update(json.loads(Path('/opt/local/private/'+('runtime-env.json' if mode=='main' else 'test-env.json')).read_text()))
project='/opt/local/project' if mode=='main' else '/opt/local/test-project'
env['PYTHONPATH']=project
if mode=='regression':
    env['DJANGO_SETTINGS_MODULE']='deploy.validation_settings'
    env.update(STOICH_TEST_ROOT='/opt/local/test-state/regression',STOICH_TEST_DB='test_stoich_deploy_regression_20261024',
        STOICH_TEST_DB_HOST=env['POSTGRES_HOST'],STOICH_TEST_DB_PORT=env['POSTGRES_PORT'],
        STOICH_TEST_DB_USER=env['POSTGRES_USER'],STOICH_TEST_DB_PASSWORD=env['POSTGRES_PASSWORD'],
        OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
os.chdir(project)
os.execve('/opt/local/venv/bin/python',['/opt/local/venv/bin/python','-B',*sys.argv[2:]],env)
