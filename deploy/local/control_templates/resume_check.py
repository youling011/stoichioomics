import json,hashlib,os,sys
from pathlib import Path
root=Path('/opt/local');env=json.loads((root/'private/runtime-env.json').read_text());os.environ.update(env);sys.path.insert(0,str(root/'project'))
import django;django.setup()
from deploy.compatibility import code_manifest
stamp=json.loads((root/'state/deployment-acceptance.json').read_text())
assert stamp['format']=='deployment-acceptance-v1' and stamp['accepted'] is True
assert stamp['source_manifest_sha256']==code_manifest(),'Acceptance belongs to a different source revision'
assert (root/'state/adaptation/current.json').is_file(),'Adaptation apply receipt missing'
print('Current source revision and adaptation acceptance match')
