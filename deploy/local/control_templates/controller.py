"""Project-scoped local Docker operations. No implicit builds, restores or migrations."""
import argparse, json, os, subprocess, sys, time, urllib.request, uuid
from pathlib import Path

if os.name=='nt':
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    sys.stderr.reconfigure(encoding='utf-8',errors='replace')

ROOT=Path(__file__).resolve().parent
PROJECT=Path(r'G:\stoichioomics\项目平台数据\stoich_platform_postgres_open_search_v6_2_perf_fix\proj')
LABEL='stoich.local.owner=stoich-platform-20261024'
APP='stoich-local-app'
WEB='stoich-local-nginx'
VOLUME='stoich_local_runtime_20261024'
PG='stoichioomics-postgres-named'

def run(*args,check=True,capture=False):
    result=subprocess.run(['docker',*map(str,args)],check=check,text=True,encoding='utf-8',errors='replace',
                          stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else result.returncode

def inspect(name):
    raw=run('inspect',name,check=False,capture=True)
    objects=json.loads(raw) if raw else []
    return objects[0] if objects else None

def owned(name):
    obj=inspect(name)
    if obj and obj['Config'].get('Labels',{}).get('stoich.local.owner')!='stoich-platform-20261024':
        raise RuntimeError('Refusing to operate on an unowned container: '+name)
    return obj

def create_app():
    return run('create','--name',APP,'--label',LABEL,'--network','proj_default',
        '--restart','no','--init','--user','1001:101','--memory','4g','--cpus','2',
        '--log-opt','max-size=10m','--log-opt','max-file=2','--tmpfs','/tmp:rw,nosuid,size=128m',
        '--mount',f'type=volume,src={VOLUME},dst=/opt/local',
        '--mount',r'type=bind,src=G:\stoichioomics,dst=/mnt/g/stoichioomics,readonly',
        '--mount',f'type=bind,src={ROOT},dst=/control,readonly',
        '--mount',f'type=bind,src={ROOT / "evidence"},dst=/evidence',
        '--workdir','/opt/local/project','stoich-local-python:20261024',
        '/opt/local/venv/bin/python','-B','/control/launch.py')

def create_web():
    return run('create','--name',WEB,'--label',LABEL,'--restart','no',
        '--publish','127.0.0.1:18080:18080','--memory','256m',
        '--log-opt','max-size=10m','--log-opt','max-file=2',
        '--mount',f'type=volume,src={VOLUME},dst=/opt/local,readonly',
        'nginx:stable','nginx','-c','/opt/local/config/nginx.conf','-g','daemon off;')

def ready(timeout=5):
    request=urllib.request.Request('http://127.0.0.1:18080/api/health/ready/')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=timeout) as response:
        body=response.read(); assert response.status==200
        return json.loads(body)

def maintenance(action,**options):
    command=['exec',APP,'/opt/local/venv/bin/python','-B','/control/maintenance_control.py',action]
    for key,value in options.items():command.extend(['--'+key.replace('_','-'),str(value)])
    return json.loads(run(*command,capture=True))

def nginx_gate(enabled):
    run('exec','-u','0',APP,'/opt/local/venv/bin/python','-B','/control/maintenance_control.py','gate','--enabled',str(int(enabled)))
    run('exec',WEB,'nginx','-t','-c','/opt/local/config/nginx.conf')
    run('exec',WEB,'nginx','-s','reload','-c','/opt/local/config/nginx.conf')

def enter_maintenance():
    nginx_gate(True)
    session=ROOT/'maintenance-session.json'
    owner=json.loads(session.read_text())['owner'] if session.is_file() else uuid.uuid4().hex
    value=maintenance('enter',owner=owner)
    session.write_text(json.dumps({'owner':owner,'generation':value['generation']}))
    deadline=time.monotonic()+300
    while True:
        check=run('exec',APP,'/opt/local/venv/bin/python','-B','/control/task_guard.py',check=False,capture=True)
        try:result=json.loads(check)
        except ValueError:raise RuntimeError('Guard did not return a valid inventory; maintenance retained')
        if result['safe_to_stop']:break
        if result.get('errors') or time.monotonic()>deadline:raise RuntimeError('Stop refused: active/unreadable tasks; maintenance retained. '+json.dumps(result))
        time.sleep(2)
    maintenance('advance',owner=owner,generation=value['generation'])
    return value

def resume_submissions():
    session=json.loads((ROOT/'maintenance-session.json').read_text())
    ready(timeout=30)
    # Final acceptance stamp is explicitly written only after full verification.
    run('exec',APP,'/opt/local/venv/bin/python','-B','/control/resume_check.py')
    maintenance('leave',owner=session['owner'],generation=session['generation'])
    nginx_gate(False)
    (ROOT/'maintenance-session.json').unlink()
    print('Verified maintenance ownership released; submissions resumed')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['start','status','check','logs','stop','restart','sync','build','static','rollback','readonly','clear-quality-cache','maintenance-status','resume-submissions','refresh-public'])
    p.add_argument('--install-frontend-dependencies',action='store_true')
    p.add_argument('--keep-maintenance',action='store_true')
    args=p.parse_args()
    run('info','--format','{{.OSType}}')
    if args.action=='start':
        for name in ['stoich-local-python:20261024','nginx:stable']:
            if not inspect(name):raise RuntimeError('Required local image is missing; explicit preparation needed, no automatic pull')
        pg=inspect(PG)
        if not pg or not pg['State']['Running']: raise RuntimeError('Existing PostgreSQL container is unavailable; it will not be started or recreated automatically')
        current=owned(APP)
        if current and any(m['Destination'].startswith('/mnt/legacy-') for m in current['Mounts']):
            raise RuntimeError('Legacy F mount detected: use the recorded migration/recreation procedure, not daily start')
        if not current or not current['State']['Running']:
            run('run','--rm','--label',LABEL,'--user','1001:101',
                '--mount',f'type=volume,src={VOLUME},dst=/opt/local,readonly',
                '--mount',r'type=bind,src=G:\stoichioomics,dst=/mnt/g/stoichioomics,readonly',
                '--mount',f'type=bind,src={ROOT},dst=/control,readonly',
                '--workdir','/opt/local/project','stoich-local-python:20261024',
                '/opt/local/venv/bin/python','-B','/control/prestart_check.py')
        if not current: create_app()
        if not owned(WEB): create_web()
        for name in [APP,WEB]:
            if not owned(name)['State']['Running']: run('start',name)
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            try: print(json.dumps(ready(timeout=30)));break
            except Exception: time.sleep(1)
        else: raise RuntimeError('Readiness timeout; inspect project logs')
        if not args.keep_maintenance and (ROOT/'maintenance-session.json').is_file():
            check=run('exec',APP,'test','-f','/opt/local/state/deployment-acceptance.json',check=False)
            if check==0:resume_submissions()
            else:print('Maintenance retained pending compatibility acceptance')
    elif args.action=='maintenance-status':
        print(json.dumps(maintenance('status')))
    elif args.action=='resume-submissions':
        resume_submissions()
    elif args.action=='refresh-public':
        run('exec',APP,'/opt/local/venv/bin/python','-B','/control/run_in_env.py','main','manage.py','refresh_public_snapshots','--names','docs,cases,quality','--invalidate')
        run('exec','-u','0',APP,'/opt/local/venv/bin/python','-B','/control/refresh_quality.py')
        run('exec',WEB,'nginx','-t','-c','/opt/local/config/nginx.conf')
        run('exec',WEB,'nginx','-s','reload','-c','/opt/local/config/nginx.conf')
    elif args.action=='status':
        for name in [APP,WEB]:
            obj=owned(name)
            print(json.dumps({'name':name,'state':obj['State'] if obj else 'not created',
                              'ports':obj.get('NetworkSettings',{}).get('Ports') if obj else None}))
        try: print(json.dumps({'readiness':ready()}))
        except Exception as exc: print('Readiness unavailable:',type(exc).__name__)
    elif args.action=='clear-quality-cache':
        obj=owned(WEB)
        if not obj or not obj['State']['Running']: raise RuntimeError('Start the project Nginx first')
        run('exec',WEB,'find','/var/cache/nginx/stoich_quality','-type','f','-delete')
        print('Only this project public quality-response cache cleared; no science data or user jobs changed')
    elif args.action=='check':
        if not owned(APP) or not owned(APP)['State']['Running']:
            raise RuntimeError('Start the local application before read-only checking')
        report='/evidence/operator-preflight-'+str(int(time.time()))+'.json'
        code=run('exec',APP,'/opt/local/venv/bin/python','-B','/control/run_in_env.py','main',
            '-m','deploy.preflight','--database','--sample-limit','20','--report',report,check=False)
        print('Read-only preflight report:',ROOT/'evidence'/Path(report).name)
        raise SystemExit(code)
    elif args.action=='logs':
        for name in [APP,WEB]:
            if owned(name): run('logs','--tail','100',name)
    elif args.action in ['stop','rollback','restart','readonly']:
        # Refuse stop if current project task metadata reports active work.
        obj=owned(APP)
        if obj and obj['State']['Running']:
            enter_maintenance()
        for name in [WEB,APP]:
            obj=owned(name)
            if obj and obj['State']['Running']:
                run('stop','--timeout','120',name)
                state=owned(name)['State']
                if state['ExitCode']!=0 or state.get('OOMKilled'):
                    raise RuntimeError('Abnormal project shutdown: '+name+'; inspect project logs')
        if args.action=='readonly':
            run('run','--rm','--label',LABEL,'--user','1001:101',
                '--mount',f'type=volume,src={VOLUME},dst=/opt/local',
                '--mount',f'type=bind,src={ROOT},dst=/control,readonly',
                'stoich-local-python:20261024','/opt/local/venv/bin/python','-B','/control/set_readonly.py')
            subprocess.run([sys.executable,str(__file__),'start'],check=True)
        elif args.action=='restart':
            subprocess.run([sys.executable,str(__file__),'start'],check=True)
        elif args.action=='rollback':
            print('Local Nginx/uWSGI stopped. Original Windows source, .env, venv and PostgreSQL are retained.')
            print('Use readonly for the Linux safety fallback. New Linux jobs require the retained volume; original Windows alone cannot read their Linux paths. See LOCAL_RUN.md.')
    elif args.action in ['sync','build','static']:
        for name in [APP,WEB]:
            obj=owned(name)
            if obj and obj['State']['Running']: raise RuntimeError('Stop this project before sync; do not overwrite running code')
        if args.action=='static':
            run('run','--rm','--label',LABEL,'--network','proj_default','--user','1001:101',
                '--memory','1g','--cpus','2',
                '--mount',f'type=volume,src={VOLUME},dst=/opt/local',
                '--mount',r'type=bind,src=G:\stoichioomics,dst=/mnt/g/stoichioomics,readonly',
                '--mount',f'type=bind,src={ROOT},dst=/control,readonly',
                'stoich-local-python:20261024','/opt/local/venv/bin/python','-B',
                '/control/run_in_env.py','main','manage.py','collectstatic','--noinput')
            return
        if args.action=='build':
            command=['run','--rm','--label',LABEL,'--user','1001:101','--memory','2g','--cpus','2',
                '--mount',f'type=volume,src={VOLUME},dst=/opt/local',
                '--mount',f'type=bind,src={ROOT},dst=/control,readonly',
                '--mount',f'type=bind,src={ROOT / "evidence"},dst=/evidence',
                'stoich-local-python:20261024','/opt/local/venv/bin/python','-B','/control/build_frontend.py']
            if args.install_frontend_dependencies:command.append('--install')
            run(*command);return
        run('run','--rm','--label',LABEL,'--network','proj_default',
            '--mount',f'type=volume,src={VOLUME},dst=/opt/local',
            '--mount',r'type=bind,src=G:\stoichioomics,dst=/mnt/g/stoichioomics,readonly',
            '--mount',f'type=bind,src={ROOT},dst=/control,readonly',
            '--mount',f'type=bind,src={ROOT / "evidence"},dst=/evidence',
            'python:3.11','python','-B','/control/bootstrap.py','sync')

if __name__=='__main__': main()
