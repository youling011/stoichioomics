import json,os,sys
from pathlib import Path
env=json.loads(Path('/opt/local/private/runtime-env.json').read_text());env.pop('UWSGI_STATS_SOCKET',None);env['DEPLOYMENT_STATE_ROOT']='/opt/local/state';env['STOICH_UWSGI_STATS_SOCKET']='/opt/local/run/uwsgi-stats.sock';os.environ.update(env)
for key,folder in {'STOICH_FEATURE_PROFILE_ROOT':'feature_profiles','STOICH_FEATURE_QC_ROOT':'feature_qc','STOICH_FEATURE_HOME_ROOT':'feature_home_spotlight','STOICH_FEATURE_EXPORT_ROOT':'feature_exports'}.items():
 os.environ.setdefault(key,'/opt/local/state/runtime/'+folder)
project='/mnt/g/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj' if '--source-g' in sys.argv else '/opt/local/project'
if not (Path(project)/'deploy/task_inventory.py').is_file():project='/mnt/g/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj'
sys.path.insert(0,project)
import django;django.setup()
from deploy.task_inventory import inventory
result=inventory(include_requests=True);print(json.dumps(result,ensure_ascii=False))
if not result['safe_to_stop']:raise SystemExit(20)
