"""Own temporary PostgreSQL database/role and isolated workspace; clean both in finally."""
from pathlib import Path
import argparse,importlib,json,os,secrets,sys
sys.dont_write_bytecode=True
PROJECT=Path(__file__).resolve().parents[1]
cli=argparse.ArgumentParser();cli.add_argument('--output-dir',type=Path,required=True);cli.add_argument('labels',nargs='*');args=cli.parse_args()
ROOT=args.output_dir;ROOT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(PROJECT));os.environ['STOICHDB_STORAGE_MODE']='postgresql';os.environ.pop('PGOPTIONS',None)
from backend.config import settings as production
cfg=dict(production.DATABASES['default'])
try:driver=importlib.import_module('psycopg')
except ImportError:driver=importlib.import_module('psycopg2')
sql=importlib.import_module(driver.__name__+'.sql');suffix=str(os.getpid())+'_'+secrets.token_hex(3)
dbname='codex_workflow_visuals_test_'+suffix;role='codex_workflow_visuals_role_'+suffix;password=secrets.token_urlsafe(24)
assert dbname!=cfg['NAME']
admin=driver.connect(dbname='postgres',user=cfg.get('USER'),password=cfg.get('PASSWORD'),host=cfg.get('HOST'),port=cfg.get('PORT'),connect_timeout=10);admin.autocommit=True
created_role=created_db=False;result={'passed':False,'test_database':dbname,'test_role':role,'business_database_modified':False,'cleanup_success':False}
try:
 with admin.cursor() as c:
  c.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT').format(sql.Identifier(role),sql.Literal(password)));created_role=True
  c.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(dbname),sql.Identifier(role)));created_db=True
 os.environ.update(DJANGO_SETTINGS_MODULE='backend.config.settings_workflow_visuals_test',WORKFLOW_VISUALS_TEST_DB_NAME=dbname,WORKFLOW_VISUALS_TEST_DB_USER=role,WORKFLOW_VISUALS_TEST_DB_PASSWORD=password,WORKFLOW_VISUALS_TEST_DB_HOST=str(cfg.get('HOST','')),WORKFLOW_VISUALS_TEST_DB_PORT=str(cfg.get('PORT','')),WORKFLOW_VISUALS_TEST_ROOT=str(ROOT/'workspace'))
 import django;django.setup()
 from django.core.management import call_command
 from django.conf import settings
 assert settings.DATABASES['default']['NAME']==dbname
 labels=args.labels or ['backend.apps.common.workflow_visuals.tests','backend.apps.sequence_analysis.tests','backend.apps.sequence_analysis.test_deployment_lifecycle','backend.apps.sequence_analysis.test_model8_elemental','backend.apps.hvg.tests']
 call_command('test',*labels,verbosity=2,interactive=False,keepdb=True);result['passed']=True
finally:
 try:
  from django.db import connections
  connections.close_all()
 except Exception:pass
 with admin.cursor() as c:
  if created_db:
   c.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()',[dbname]);c.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(dbname)))
  if created_role:c.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
  c.execute('SELECT COUNT(*) FROM pg_database WHERE datname=%s',[dbname]);db_left=c.fetchone()[0]
  c.execute('SELECT COUNT(*) FROM pg_roles WHERE rolname=%s',[role]);role_left=c.fetchone()[0]
  result['cleanup_success']=not db_left and not role_left
 admin.close();(ROOT/'postgres_test_result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
 print('Owned test database and role cleaned:',result['cleanup_success'])
