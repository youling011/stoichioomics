"""Verify the sole authoritative Python manifest against this interpreter."""
from pathlib import Path
import argparse,hashlib,importlib.metadata as metadata,json,platform,sys
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

def verify():
    manifest=Path(__file__).resolve().parents[1]/'requirements.txt'
    groups={}
    for dist in metadata.distributions():
        groups.setdefault(canonicalize_name(dist.metadata['Name']),[]).append(dist)
    expected={}
    for line in manifest.read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        req=Requirement(line)
        if req.marker and not req.marker.evaluate():continue
        expected[canonicalize_name(req.name)]=req
    errors=[]
    for name,req in expected.items():
        rows=groups.get(name,[])
        if len(rows)!=1:errors.append(f'{name}: expected one installation, found {len(rows)}')
        elif rows[0].version not in req.specifier:errors.append(f'{name}: {rows[0].version} does not satisfy {req.specifier}')
    packages={name:rows[0].version for name,rows in sorted(groups.items()) if len(rows)==1}
    if not packages.get('django','').startswith('5.2.'):errors.append('Django must remain in the 5.2 series')
    return {'ok':not errors,'python':platform.python_version(),'platform':sys.platform,'executable':sys.executable,'django':packages.get('django'),'requirements_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'manifest_packages':len(expected),'packages':packages,'errors':errors}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args();result=verify()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False));raise SystemExit(not result['ok'])

