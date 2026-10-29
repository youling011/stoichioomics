import os,sys,json,argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('action',choices=['gate','enter','advance','leave','status','configure']);p.add_argument('--owner');p.add_argument('--generation',type=int);p.add_argument('--enabled',type=int,choices=[0,1]);p.add_argument('--source-g',action='store_true');a=p.parse_args()
root=Path('/opt/local');config=root/'config'
if a.action=='gate':
 maps=config/'nginx-maintenance-map.conf';maps.write_text('map "$request_method:$uri" $stoich_new_submission { default 0; ~^POST:/api/.*/cancel/$ 0; ~^POST:/api/(stoichdb/id-mapping/batch-resolve|stoichdb/entities/batch-report|sequence-analysis/prevalidate)/$ 0; ~^(POST|PUT|PATCH|DELETE):/api/ 1; }\nmap "$stoich_maintenance_enabled:$stoich_new_submission" $stoich_block_submission { default 0; "1:1" 1; }\n')
 gate=config/'nginx-maintenance-server.conf';gate.write_text('set $stoich_maintenance_enabled '+str(a.enabled)+''';
error_page 503 =503 @stoich_maintenance;
if ($stoich_block_submission) { return 503; }
location @stoich_maintenance { default_type application/json; add_header Retry-After 30 always; return 503 '{"ok":false,"error":{"message":"Platform maintenance: new submissions paused"}}'; }
''')
 master=config/'nginx.conf';s=master.read_text();marker='    include "/opt/local/config/nginx-site.conf";'
 if 'nginx-maintenance-map.conf' not in s:assert marker in s;s=s.replace(marker,'    include "/opt/local/config/nginx-maintenance-map.conf";\n'+marker);master.write_text(s)
 site=config/'nginx-site.conf';s=site.read_text()
 if 'nginx-maintenance-server.conf' not in s:s=s.replace('server {','server {\n    include "/opt/local/config/nginx-maintenance-server.conf";',1);site.write_text(s)
 print(json.dumps({'gate_enabled':bool(a.enabled)}));raise SystemExit(0)
private=root/'private/runtime-env.json';env=json.loads(private.read_text());env.pop('UWSGI_STATS_SOCKET',None);env.update(DEPLOYMENT_STATE_ROOT='/opt/local/state',STOICH_UWSGI_STATS_SOCKET='/opt/local/run/uwsgi-stats.sock')
if a.action=='configure':
 backup=private.with_name('runtime-env.pre-compat-20261029.json')
 if not backup.exists():backup.write_bytes(private.read_bytes());backup.chmod(0o600)
 hist='/mnt/g/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj';env.update(DEPLOYMENT_HISTORICAL_ROOT=hist,STOICH_FEATURE_REGISTRY_OUTPUT_ROOT='/opt/local/state/runtime/feature_registry',DEPLOYMENT_INTEGRITY_INDEX='/opt/local/state/runtime/deployment_integrity.sqlite3',DEPLOYMENT_PUBLIC_SNAPSHOTS='1',DEPLOYMENT_PYTHON='/opt/local/venv/bin/python',TASK_EXECUTION_AUTOSTART='1')
 folders={'PROTEOME_VIZ_READ_ROOTS':'proteome_visuals_v3','SEQUENCE_VIZ_READ_ROOTS':'sequence_visuals_v1','INTEGRATION_VIZ_READ_ROOTS':'integration_visuals_v1','HOME_ATLAS_VIZ_READ_ROOTS':'home_atlas_visuals/v1','COMPARE_CORE_READ_ROOTS':'compare_core','STOICH_FEATURE_PROFILE_READ_ROOTS':'feature_profiles','STOICH_FEATURE_QC_READ_ROOTS':'feature_qc','STOICH_FEATURE_HOME_READ_ROOTS':'feature_home_spotlight','STOICH_FEATURE_EXPORT_READ_ROOTS':'feature_exports'}
 for key,folder in folders.items():env[key]=json.dumps([hist+'/runtime/'+folder])
 for key,folder in {'STOICH_FEATURE_PROFILE_ROOT':'feature_profiles','STOICH_FEATURE_QC_ROOT':'feature_qc','STOICH_FEATURE_HOME_ROOT':'feature_home_spotlight','STOICH_FEATURE_EXPORT_ROOT':'feature_exports'}.items():env[key]='/opt/local/state/runtime/'+folder
 previous_owner=private.stat()
 temp=private.with_suffix('.tmp');temp.write_text(json.dumps(env));temp.chmod(0o600);os.chown(temp,previous_owner.st_uid,previous_owner.st_gid);os.replace(temp,private)
 print(json.dumps({'configured_nonsecret_keys':sorted([*folders,'DEPLOYMENT_STATE_ROOT','DEPLOYMENT_HISTORICAL_ROOT','DEPLOYMENT_INTEGRITY_INDEX','DEPLOYMENT_PUBLIC_SNAPSHOTS','STOICH_FEATURE_REGISTRY_OUTPUT_ROOT','TASK_EXECUTION_AUTOSTART','STOICH_UWSGI_STATS_SOCKET'])}));raise SystemExit(0)
os.environ.update(env);project='/mnt/g/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj' if a.source_g else '/opt/local/project';sys.path.insert(0,project)
if not (Path(project)/'backend/apps/common/maintenance.py').is_file():
 project='/mnt/g/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj';sys.path.insert(0,project)
import django;django.setup()
from backend.apps.common import maintenance as m
if a.action=='enter':result=m.enter(a.owner)
elif a.action=='advance':result=m.advance(a.owner,a.generation)
elif a.action=='leave':result=m.leave(a.owner,a.generation)
else:result=m.state()
print(json.dumps(result))
