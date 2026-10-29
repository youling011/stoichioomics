"""Explicit one-time preparation/sync; existing G: data and PostgreSQL stay intact."""
import hashlib, json, os, shutil, sys, time
from pathlib import Path

SOURCE=Path('/mnt/g/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj')
ROOT=Path('/opt/local'); PROJECT=ROOT/'project'; EVIDENCE=Path('/evidence')
UID,GID=1001,101
def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def snapshot():
    manifest=[]
    ignore={'__pycache__','node_modules','dist','.git','.venv','evidence','test-results','playwright-report'}
    for name in ['backend','configs','shared','scripts','tools','deploy','frontend']:
        for parent,dirs,files in os.walk(SOURCE/name):
            dirs[:]=[d for d in dirs if d not in ignore]
            for filename in files:
                if filename.endswith(('.pyc','.pyo')) or filename.startswith('.env'): continue
                src=Path(parent)/filename; rel=src.relative_to(SOURCE); dst=PROJECT/rel
                if src.is_symlink(): raise RuntimeError('Review source symlink before copying: '+str(rel))
                dst.parent.mkdir(parents=True,exist_ok=True)
                sha=digest(src)
                if not dst.exists() or digest(dst)!=sha: shutil.copyfile(src,dst)
                if digest(dst)!=sha: raise RuntimeError('Source copy checksum mismatch')
                manifest.append({'path':str(rel),'bytes':src.stat().st_size,'sha256':sha})
    for filename in ['manage.py','requirements.txt','requirements-hvg-research-lock.txt','requirements-hvg.txt','requirements-proteome-visuals.txt','environment-hvg.yml','README.md','PRODUCT.md']:
        src=SOURCE/filename; dst=PROJECT/filename; shutil.copyfile(src,dst)
        manifest.append({'path':filename,'bytes':src.stat().st_size,'sha256':digest(src)})
    previous=ROOT/'state/source-manifest.json'
    old=json.loads(previous.read_text()) if previous.is_file() else {'files':[]}
    current={r['path'] for r in manifest};deleted=[]
    for row in old['files']:
        relative=Path(row['path'])
        allowed=(relative.parts and relative.parts[0] in ['backend','configs','shared','scripts','tools','deploy','frontend']) or (len(relative.parts)==1 and relative.name in ['manage.py','requirements.txt','requirements-hvg-research-lock.txt','requirements-hvg.txt','requirements-proteome-visuals.txt','environment-hvg.yml','README.md','PRODUCT.md'])
        if relative.is_absolute() or '..' in relative.parts or not allowed:raise RuntimeError('Invalid prior source path')
        if row['path'] in current:continue
        target=(PROJECT/relative).resolve()
        if not target.is_relative_to(PROJECT) or (SOURCE/relative).exists():raise RuntimeError('Unreviewed deletion')
        if target.exists():
            if digest(target)!=row['sha256']:raise RuntimeError('Manually changed deleted source: '+str(relative))
            target.unlink();deleted.append(row)
    previous.write_text(json.dumps({'files':manifest,'deleted':deleted},ensure_ascii=False,indent=2))
    (EVIDENCE/('source-manifest-'+str(int(time.time()))+'.json')).write_text(json.dumps({
        'source_windows':r'G:\stoichioomics\项目平台数据\stoich_platform_postgres_open_search_v6_2_perf_fix\proj',
        'linux_copy':str(PROJECT),'files':manifest,'total_bytes':sum(x['bytes'] for x in manifest),
        'excluded':sorted(ignore|{'.env','backend_db.sqlite3','runtime','workspace','data'}),
        'data_access':'read-only bind mount; project/data is a symlink; no dataset copy'},ensure_ascii=False,indent=2))
    print('Verified selective source snapshot:',len(manifest),'files,',sum(x['bytes'] for x in manifest),'bytes',flush=True)

def main():
    action=sys.argv[1]
    assert action in ['init','sync']
    for name in ['project','config','private','run','static','state/runtime','state/workspace/jobs','state/uploads',
                 'state/home','state/cache','state/matplotlib','test-state','build']:
        (ROOT/name).mkdir(parents=True,exist_ok=True)
    snapshot()
    for name,target in [('data',SOURCE/'data'),('runtime',ROOT/'state/runtime'),('workspace',ROOT/'state/workspace'),('.venv',ROOT/'venv')]:
        link=PROJECT/name
        if not link.exists() and not link.is_symlink(): link.symlink_to(target,target_is_directory=True)
    registry=SOURCE/'workspace/case_registry.json'
    if registry.is_file() and not (ROOT/'state/workspace/case_registry.json').exists():
        if registry.stat().st_size>1024*1024: raise RuntimeError('Review large case registry before copying')
        shutil.copyfile(registry,ROOT/'state/workspace/case_registry.json')
    if action=='init':
        env={}
        for line in (SOURCE/'.env').read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1);env[key.strip()]=value.strip().strip('\"').strip("'")
        import secrets
        env.update({
            'DJANGO_SETTINGS_MODULE':'deploy.local_settings','DJANGO_ENV_FILE':'',
            'DJANGO_SECRET_KEY':secrets.token_urlsafe(64),'DJANGO_ALLOWED_HOSTS':'localhost,127.0.0.1,testserver',
            'DJANGO_CSRF_TRUSTED_ORIGINS':'http://localhost:18080,http://127.0.0.1:18080',
            'DJANGO_DB_ENGINE':'postgresql','POSTGRES_HOST':'stoichioomics-postgres-named','POSTGRES_PORT':'5432',
            'STOICH_ALLOW_HTTP_TEST':'1','DJANGO_SECURE_HSTS_SECONDS':'0','POSTGRES_CONN_MAX_AGE':'60',
            'STOICH_LOCAL_READ_ONLY':'1','STOICH_WINDOWS_DATA_MOUNT':'/mnt/g/stoichioomics',
            'STOICH_WINDOWS_PATH_MAPPINGS':'{}','STOICH_DATA_LOCATION_MODE':'g-only-20261025',
            'FUNCTION_ANNOTATION_SOURCE':r'G:\stoichioomics\项目平台数据\功能注释下载',
            'STOICHDB_DATA_ROOT':str(SOURCE/'data/stoichdb_demo'),
            'STOICH_FEATURE_EXTRACTOR_ROOT':'/mnt/g/stoichioomics/项目平台数据/组学化学计量特征提取代码',
            'STOICH_FEATURE_ROOT':'/mnt/g/stoichioomics/全组学特征数据',
            'STOICHIOOMICS_ROOT':'/mnt/g/stoichioomics','STOICH_PROJECT_ROOT':str(SOURCE),
            'STOICH_PROJECT_DATA_ROOT':str(SOURCE/'data'),'STOICH_DATA_ROOT':str(SOURCE/'data'),
            'STOICH_RUNTIME_ROOT':str(ROOT/'state/runtime'),'STATIC_ROOT':str(ROOT/'static'),
            'HOME':str(ROOT/'state/home'),'XDG_CACHE_HOME':str(ROOT/'state/cache'),
            'MPLCONFIGDIR':str(ROOT/'state/matplotlib'),'PYTHONDONTWRITEBYTECODE':'1',
            'PYTHONUNBUFFERED':'1','PYTHONPATH':str(PROJECT),
        })
        for key,relative in {'MEDIA_ROOT':'uploads','WORKSPACE_ROOT':'workspace/jobs',
            'CASE_REGISTRY_FILE':'workspace/case_registry.json','COMPARE_CORE_ROOT':'runtime/compare_core',
            'SEQUENCE_ANALYSIS_WORKSPACE_ROOT':'runtime/sequence_analysis',
            'SEQUENCE_ANALYSIS_LEGACY_WORKSPACE_ROOT':'workspace/sequence_analysis',
            'PROTEOME_VIZ_ROOT':'runtime/proteome_visuals_v3','SEQUENCE_VIZ_ROOT':'runtime/sequence_visuals_v1',
            'INTEGRATION_VIZ_ROOT':'runtime/integration_visuals_v1'}.items():
            env[key]=str(ROOT/'state'/relative)
            if key!='CASE_REGISTRY_FILE': Path(env[key]).mkdir(parents=True,exist_ok=True)
        # Historical precomputed artifacts stay read-only; new outputs are isolated.
        env['STOICHDB_PRECOMPUTED_ROOT']=str(SOURCE/'workspace')
        private=ROOT/'private/runtime-env.json'
        if private.exists(): raise RuntimeError('Refusing to overwrite private runtime environment')
        private.write_text(json.dumps(env));private.chmod(0o600);os.chown(private,UID,GID)
    sys.path.insert(0,str(PROJECT))
    from deploy.render import render
    config={'project_root':str(PROJECT),'venv_root':str(ROOT/'venv'),
        'frontend_root':str(PROJECT/'frontend/dist'),'static_root':str(ROOT/'static'),
        'domain':'localhost','environment_file':str(ROOT/'private/platform.env'),
        'service_user':'stoichioomics','service_group':'nginx','nginx_user':'nginx','nginx_group':'nginx',
        'processes':2,'threads':2,'upload_body_limit_mib':512,'read_timeout_seconds':600,
        'stop_timeout_seconds':120,'config_root':str(ROOT/'config')}
    render(config,ROOT/'config','http-test')
    site=ROOT/'config/nginx-site.conf';text=site.read_text()
    text=text.replace('listen 127.0.0.1:18080;','listen 18080;')
    text=text.replace('/run/stoichioomics/uwsgi.sock','/opt/local/run/uwsgi.sock')
    text=text.replace('/var/log/nginx/stoichioomics-access.log','/dev/stdout').replace('/var/log/nginx/stoichioomics-error.log','/dev/stderr')
    site.write_text(text)
    master=ROOT/'config/nginx.conf';master.write_text(master.read_text().replace('/var/log/nginx/stoichioomics-main-error.log','/dev/stderr'))
    ini=ROOT/'config/uwsgi.ini';ini.write_text(ini.read_text().replace('/run/stoichioomics/uwsgi.sock','/opt/local/run/uwsgi.sock').replace('env = DJANGO_SETTINGS_MODULE=backend.config.settings_production','env = DJANGO_SETTINGS_MODULE=deploy.local_settings')+'\nstats = /opt/local/run/uwsgi-stats.sock\n')
    for relative in (['state','test-state','build','run','project/frontend'] if action=='init' else []):
        for parent,dirs,files in os.walk(ROOT/relative,followlinks=False):
            os.chown(parent,UID,GID)
            for name in files:
                path=Path(parent)/name
                if not path.is_symlink(): os.chown(path,UID,GID)
    sys.path.insert(0,'/control/continuation_20261025')
    from quality_config import configure
    configure(PROJECT,ROOT/'config')
    import subprocess
    subprocess.run([sys.executable,'-B','/control/maintenance_control.py','gate','--enabled','1'],check=True)
    os.chown(ROOT/'static',UID,GID)
    (ROOT/'private').chmod(0o700);os.chown(ROOT/'private',UID,GID)
    (ROOT/'run').chmod(0o750)
    (EVIDENCE/'render-adaptation.json').write_text(json.dumps({'template_source':'existing deploy.render http-test',
       'container_listen':'18080','host_publish':'127.0.0.1:18080:18080',
       'socket':'/opt/local/run/uwsgi.sock','settings':'deploy.local_settings',
       'resources':'2 workers x 2 threads; 4 GiB app; 2 CPU; initial local values, not capacity acceptance'},indent=2))

if __name__=='__main__':main()
