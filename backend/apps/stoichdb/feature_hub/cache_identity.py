"""Portable cache identity and exact, read-only legacy cache reuse."""
import hashlib,json,os
from pathlib import Path
from functools import lru_cache,wraps
from django.conf import settings
from backend.apps.common.artifact_locations import logical_path_key,read_roots,contained,file_lock
from backend.apps.common.atomic_json import atomic_write_json
from backend.apps.stoichdb.feature_sources import io as feature_io

@lru_cache(maxsize=256)
def _physical_digest(path,size,mtime,ctime):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

@lru_cache(maxsize=256)
def _full_binding_records(database,dataset_id,schema_version):
 from backend.apps.stoichdb.models import FeatureSourceBinding
 return tuple(FeatureSourceBinding.objects.filter(dataset__dataset_id=dataset_id,status='full_backed').values())

def source_content_identity(source):
 logical=feature_io.logical_source(source.path)
 if logical:return logical.record['virtual_csv_sha256']
 # Full identity already sealed by the bound Core's audited Full receipt.
 from backend.apps.stoichdb.models import FeatureSourceBinding
 from backend.apps.stoichdb.feature_sources.resolver import LogicalCore
 values=[]
 for record in (_full_binding_records(str(settings.DATABASES['default']['NAME']),source.dataset_id,source.schema_version) if str(source.path).replace('\\','/').lower().startswith(('g:/stoichioomics/','/mnt/g/stoichioomics/')) else []):
  if logical_path_key(record['full_path'])==logical_path_key(source.path):
   LogicalCore(record).check();values.append(record['full_sha256'])
 if values:
  if len(set(values))!=1:raise ValueError('ambiguous_full_identity')
  return values[0]
 s=source.path.stat();return _physical_digest(str(source.path),s.st_size,s.st_mtime_ns,s.st_ctime_ns)

def fingerprint(source):
 identity=['feature-source-v2',source.dataset_id,source.omics,source.scope,logical_path_key(source.path),source.schema_version,source.row_count,source_content_identity(source)]
 return hashlib.sha256(json.dumps(identity,separators=(',',':')).encode()).hexdigest()

def legacy_fingerprints(source):
 values=[str(source.path)];mount=os.environ.get('STOICH_WINDOWS_DATA_MOUNT','').rstrip('/')
 if mount and str(source.path).startswith(mount+'/'):
  values.append('G:\\stoichioomics'+str(source.path)[len(mount):].replace('/','\\'))
 if str(source.path).lower().replace('\\','/').startswith('g:/stoichioomics/'):
  values.append('/mnt/g/stoichioomics'+str(source.path).replace('\\','/')[len('G:/stoichioomics'):])
 return list(dict.fromkeys(hashlib.sha256(f'{p}|{source.file_size}|{source.file_mtime}|{source.schema_version}'.encode()).hexdigest() for p in values))

def read_cached(namespace,write_path,source,legacy_names,kind,field=None,fields=None,family=None):
 canonical=source.fingerprint;names=[Path(write_path).name,*legacy_names]
 for root in read_roots(namespace,Path(write_path).parent):
  for name in dict.fromkeys(names):
   p=contained(root,name)
   if not p.is_file():continue
   if root.resolve()!=Path(write_path).parent.resolve() and getattr(settings,'DEPLOYMENT_INTEGRITY_INDEX',None):
    from backend.apps.common.artifact_integrity import verify_cache_identity
    verify_cache_identity(p,source_content_identity(source))
   payload=json.loads(p.read_text(encoding='utf8'))
   if payload.get('species_id')!=source.species_id or payload.get('omics')!=source.omics:continue
   if payload.get('scope',payload.get('table_level'))!=source.scope:continue
   if int(payload.get('n_rows',payload.get('entity_count',-1)))!=source.row_count:continue
   old=payload.get('source_sha')
   if old and old not in [canonical,*legacy_fingerprints(source)]:continue
   if kind=='profile' and payload.get('field')!=field:continue
   if kind=='qc' and (set(payload.get('missingness',{}))!=set(fields or []) or payload.get('selected_features')!=len(fields or [])):continue
   if kind=='home' and (payload.get('feature_family','')!=(family or '') or payload.get('dataset_id')!=source.dataset_id or payload.get('schema_version')!=source.schema_version):continue
   result={**payload,'canonical_source_identity':canonical,'cache':{**payload.get('cache',{}),'read_origin':str(p),'identity_version':2}}
   if old:result.update(source_sha=canonical,legacy_cache_identity=old if old!=canonical else payload.get('legacy_cache_identity'))
   return result
 return None

def write_cache(path,payload):atomic_write_json(Path(path),payload)

def calculation_lock(root_getter):
 def decorate(fn):
  @wraps(fn)
  def call(*args,**kwargs):
   key=hashlib.sha256(json.dumps([fn.__name__,args,kwargs],sort_keys=True,default=str).encode()).hexdigest()
   with file_lock(Path(root_getter())/'locks'/(key+'.lock'),timeout=600):return fn(*args,**kwargs)
  return call
 return decorate
