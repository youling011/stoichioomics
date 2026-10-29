"""Explicit offline update build; daily service start never invokes this."""
import argparse,hashlib,json,os,shutil,subprocess
from pathlib import Path
from frontend_fingerprint import frontend_fingerprint
p=argparse.ArgumentParser();p.add_argument('--install',action='store_true');args=p.parse_args()
root=Path('/opt/local');front=root/'project/frontend';cache=root/'build/npm-cache'
env={**os.environ,'PATH':'/opt/local/node/bin:'+os.environ['PATH'],'npm_config_cache':str(cache)}
commands=[]
if args.install:commands.append(['npm','ci','--no-audit','--no-fund'])
commands += [['npm','run','test:scientific'],['npm','run','build']]
try:
    for cmd in commands:subprocess.run(cmd,cwd=front,env=env,check=True)
finally:
    if args.install and cache.exists():
        assert cache.resolve().parent==root/'build'
        shutil.rmtree(cache)
files=[x for x in (front/'dist').rglob('*') if x.is_file()]
result={'platform':'Linux, independent node_modules',
 'lock_sha256':hashlib.sha256((front/'package-lock.json').read_bytes()).hexdigest(),
 'assets':{str(p.relative_to(front/'dist')):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'dist_files':len(files),'dist_bytes':sum(x.stat().st_size for x in files),'commands':commands,
 'npm_cache_removed':args.install,'frontend_source_sha256':frontend_fingerprint(front)}
Path('/evidence/frontend-build.json').write_text(json.dumps(result,indent=2))
(root/'state/frontend-build-stamp.json').write_text(json.dumps(result,indent=2))
