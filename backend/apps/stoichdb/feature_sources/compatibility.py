"""Exact, fail-closed compatibility for independently audited I/O-only refactors.

Scientific fingerprint input is preserved only for the precisely registered new
source AND storage-adapter bytes. Any algorithm/adapter drift returns actual
bytes and the existing stale checks continue to reject old artifacts.
"""
import base64,hashlib,json
from functools import lru_cache
from pathlib import Path

PROJECT=Path(__file__).resolve().parents[4]
POLICY=Path(__file__).resolve().parents[1]/'resources/corefull_implementation_compatibility.json'

def _policy():
    if not POLICY.is_file():return None
    data=json.loads(POLICY.read_text(encoding='utf-8'))
    if data.get('format')!='corefull-io-compatibility-v1' or not data.get('active'):return None
    for relative,expected in data['storage_adapter_sha256'].items():
        path=PROJECT/relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:return None
    return data

def implementation_bytes(path):
    path=Path(path);actual=path.read_bytes();policy=_policy()
    if not policy:return actual
    try:relative=path.resolve().relative_to(PROJECT).as_posix()
    except ValueError:return actual
    receipt=policy['io_sources'].get(relative)
    if not receipt or not receipt['ast_io_equivalent'] or hashlib.sha256(actual).hexdigest()!=receipt['after_sha256']:return actual
    original=base64.b64decode(receipt['before_source_base64'])
    if hashlib.sha256(original).hexdigest()!=receipt['before_sha256']:raise ValueError('Invalid implementation compatibility receipt')
    return original

def storage_implementation_identity():
    policy=_policy()
    return policy['storage_adapter_sha256'] if policy else {}

def implementation_digest(path):
    return hashlib.sha256(implementation_bytes(path)).hexdigest()
