"""Fast conditions only: never installs/builds/restores/migrates."""
import hashlib,json,runpy
from pathlib import Path
from frontend_fingerprint import frontend_fingerprint
root=Path('/opt/local');project=root/'project'
check=runpy.run_path(str(project/'scripts/verify_dependencies.py'))['verify']()
assert check['ok'],check['errors']
assert check['packages'].get('uwsgi')=='2.0.31','uWSGI pin mismatch'
assert (project/'frontend/dist/index.html').is_file(),'Build frontend explicitly first'
assert (root/'static/admin/css/base.css').is_file(),'Run collectstatic explicitly first'
env=json.loads((root/'private/runtime-env.json').read_text())
assert 'UWSGI_STATS_SOCKET' not in env,'Use STOICH_UWSGI_STATS_SOCKET; UWSGI_ prefix is interpreted by the uWSGI executable'
assert env['POSTGRES_HOST']=='stoichioomics-postgres-named'
assert env.get('STOICH_DATA_LOCATION_MODE')=='g-only-20261025','Explicit data migration not prepared'
mapping=json.loads(env.get('STOICH_WINDOWS_PATH_MAPPINGS','{}'))
manifest=root/'state/legacy-workspace-map.json'
expected=json.loads(manifest.read_text())['mapping'] if manifest.exists() else {}
assert mapping==expected,'Unreviewed legacy workspace mappings'
for prefix,target in mapping.items():
    assert prefix.lower().replace(chr(92),'/').startswith('g:/stoichioomics/'), 'F or unrelated drive mapping forbidden'
    assert Path(target).is_relative_to(root/'state/workspace'), 'Workspace mapping escaped owned state'
    assert Path(target).parent.is_dir(),'Preserved workspace parent missing'
assert env.get('FUNCTION_ANNOTATION_SOURCE')==r'G:\stoichioomics\项目平台数据\功能注释下载'
stamp=json.loads((root/'state/frontend-build-stamp.json').read_text())
assert stamp['frontend_source_sha256']==frontend_fingerprint(project/'frontend'),'Frontend source changed: run the explicit build command before start'
print(json.dumps({'dependencies':'exact pins match','frontend':'built from current runtime copy',
 'mode':'readonly validation' if env.get('STOICH_LOCAL_READ_ONLY')=='1' else 'writable',
 'database':env['POSTGRES_DB'],'no_install_build_or_migration':True}))

manifest=json.loads((root/'state/source-manifest.json').read_text())
source=Path('/mnt/g/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj')
for row in manifest['files']:
 for base in [project,source]:assert hashlib.sha256((base/row['path']).read_bytes()).hexdigest()==row['sha256'],'Source drift: '+row['path']
for relative,expected in stamp['assets'].items():assert hashlib.sha256((project/'frontend/dist'/relative).read_bytes()).hexdigest()==expected,'Served asset drift'
assert Path(env['DEPLOYMENT_INTEGRITY_INDEX']).is_file(),'Complete historical package receipts required before start'
import sqlite3
with sqlite3.connect('file:'+env['DEPLOYMENT_INTEGRITY_INDEX']+'?mode=ro',uri=True) as connection:
 assert connection.execute('PRAGMA quick_check').fetchone()[0]=='ok','Integrity index is corrupt'
 assert connection.execute("SELECT value FROM metadata WHERE key='format'").fetchone()[0]=='deployment-integrity-index-v1'
 assert connection.execute('SELECT COUNT(*) FROM packages').fetchone()[0]>0,'Historical package index is empty'
