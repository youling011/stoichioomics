"""Frozen extractor and audited pure-projection provenance; no extractor execution."""
import ast,hashlib,json
from pathlib import Path
from .projection import ProjectionError

def frozen_provenance():
    root=Path(__file__).resolve().parent
    data=json.loads((root.parent/'resources/corefull_projection_provenance.json').read_text(encoding='utf-8'))
    if data['projection_sha256']!=hashlib.sha256((root/'projection.py').read_bytes()).hexdigest():raise ProjectionError('Projection rule drift requires full revalidation')
    code=(root/'arrow.py').read_text(encoding='utf-8')
    for name in ['project','encoded_rows']:
        node=next(n for n in ast.parse(code).body if isinstance(n,ast.FunctionDef) and n.name==name)
        actual=hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()
        if actual!=data[name+'_ast_sha256']:raise ProjectionError('Audited Arrow projection/serialization drift')
    return data

def recipe_digest(recipe):
    return hashlib.sha256(json.dumps(recipe,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

from functools import lru_cache
from .asset_state import change_token

@lru_cache(maxsize=8)
def _checked_runtime_rules(states):
    return frozen_provenance()

def assert_runtime_rules():
    root=Path(__file__).resolve().parent
    paths=[root/'projection.py',root/'arrow.py',root.parent/'resources/corefull_projection_provenance.json']
    states=[]
    for path in paths:
        stat=path.stat();token=change_token(path)
        states.append((str(path),stat.st_size,stat.st_mtime_ns,token['host'],token['change_ns']))
    return _checked_runtime_rules(tuple(states))
