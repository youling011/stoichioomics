"""Versioned, read-only inventory and narrowly scoped adaptation actions.

No command modifies source, scientific manifests, business DB or historical data.
"""
import hashlib,json,os,socket,shutil,time,uuid
from pathlib import Path
from django.conf import settings
from backend.apps.common.artifact_locations import read_roots,contained,file_lock,pointer_target
from backend.apps.common.atomic_json import atomic_write_json
from backend.apps.common.maintenance import state,state_root

DECISIONS={'reuse_as_is','reuse_with_exact_receipt','expose_historical','rebuild_explicit','preserve_unavailable','exclude_expired'}
SETTINGS={'proteome':'PROTEOME_VIZ_ROOT','sequence':'SEQUENCE_VIZ_ROOT','integration':'INTEGRATION_VIZ_ROOT','compare':'COMPARE_CORE_ROOT','feature_profiles':'STOICH_FEATURE_PROFILE_ROOT','feature_qc':'STOICH_FEATURE_QC_ROOT','feature_home':'STOICH_FEATURE_HOME_ROOT','feature_exports':'STOICH_FEATURE_EXPORT_ROOT'}
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def json_read(path):return json.loads(Path(path).read_text('utf8'))
def write_root(namespace):
 if namespace=='home_atlas':
  from backend.apps.stoichdb.home_atlas_viz.artifacts import artifact_root
  return artifact_root()
 return Path(getattr(settings,SETTINGS[namespace],settings.BASE_DIR/'runtime'/namespace))
def code_manifest():
 root=Path(settings.BASE_DIR);names=[]
 for folder in ['backend','deploy','shared','configs','scripts','tools','frontend/src']:
  for p in (root/folder).rglob('*'):
   if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ['.pyc','.pyo'] and not p.name.startswith('.env'):names.append((p.relative_to(root).as_posix(),sha(p)))
 return hashlib.sha256(json.dumps(sorted(names),separators=(',',':')).encode()).hexdigest()

def audit():
 from django.db import transaction,connection
 from backend.apps.stoichdb.models import Species,OmicsDataset
 from backend.apps.stoichdb.proteome_viz import artifacts as p,api as pa
 from backend.apps.stoichdb.sequence_viz import artifacts as q
 from backend.apps.stoichdb.complete_core.datasource import CompleteCoreDataSource
 from backend.apps.stoichdb.integration_viz import artifacts as i
 rows=[];errors=[]
 with transaction.atomic():
  if connection.vendor=='postgresql':
   with connection.cursor() as c:c.execute('SET TRANSACTION READ ONLY')
  registry={'species':Species.objects.count(),'datasets':OmicsDataset.objects.count()}
  for namespace in [*SETTINGS,'home_atlas']:
   for historical in read_roots(namespace,write_root(namespace))[1:]:
    if not historical.is_dir():errors.append({'namespace':namespace,'path':str(historical),'error':'Configured historical root is missing'})
  for namespace,pattern in [('proteome','published/*/*.json'),('sequence','published/*/*/*.json'),('integration','species/*/published.json')]:
   for ordinal,root in enumerate(read_roots(namespace,write_root(namespace))):
    for pointer_path in sorted(root.glob(pattern)):
     try:
      pointer=json_read(pointer_path);relative=pointer.get('path')
      if namespace=='integration':relative=(pointer_path.parent/'versions'/pointer['artifact_version']).relative_to(root).as_posix()
      target=contained(root,relative);manifest=target/'manifest.json';m=json_read(manifest);a=json_read(target/'audit.json')
      passed=a.get('passed',a.get('status')=='passed')
      if not passed:raise ValueError('artifact_audit_failed')
      if namespace=='proteome':
       ds=OmicsDataset.objects.defer('browse_meta','summary_payload','analysis_payload','searchable_text').get(dataset_id=m['dataset_id']);stale=pa.manifest_stale(m,ds)
      elif namespace=='sequence':
       ds=CompleteCoreDataSource(m['species_id'],m['omics']);stale=q.stale(m,ds)
      else:stale=i.stale(m['species_id'],target)
      decision='expose_historical' if stale else ('reuse_with_exact_receipt' if ordinal else 'reuse_as_is')
      rows.append({'namespace':namespace,'source_root':str(root),'relative_manifest':manifest.relative_to(root).as_posix(),'source_version':m['artifact_version'],'species_id':m['species_id'],'scope':m.get('primary_scope',m.get('scope','core_plus_optional_full')),'expected_source_sha256':sha(manifest),'source_hash':m['source_hash'],'implementation_hash':m.get('implementation_hash'),'availability':'stale' if stale else 'reusable','decision':decision,'reason':'Current method/source checks differ; frozen version remains readable' if stale else 'Exact current-source and method validation passed; immutable receipts required for reads','target_root':str(write_root(namespace))})
     except Exception as e:
      errors.append({'namespace':namespace,'path':str(pointer_path),'error':type(e).__name__+': '+str(e)})
  from backend.apps.stoichdb.compare_core.models import CompareRun,CompareCoreProfile
  from backend.apps.stoichdb.compare_core.exports import run_dir,run_artifacts_valid
  for run in CompareRun.objects.filter(status__in=['completed','partial']):
   folder=run_dir(run);valid=run_artifacts_valid(run)
   rows.append({'namespace':'compare','object_id':str(run.run_id),'source_root':str(folder),'source_version':str(run.run_id),'target_root':str(write_root('compare')),'availability':'available' if valid else 'missing','decision':'expose_historical' if valid else 'preserve_unavailable','expected_source_sha256':sha(folder/'manifest.json') if (folder/'manifest.json').is_file() else None,'relative_manifest':'manifest.json','reason':'Frozen tables, profiles and ZIP checksums' if valid else 'Saved package failed integrity validation'})
  registry['compare_profiles']={status:CompareCoreProfile.objects.filter(status=status).count() for status in CompareCoreProfile.objects.values_list('status',flat=True).distinct()}
  from backend.apps.stoichdb.home_atlas_viz import artifacts as h
  home=h.manifest();diagnostics=[]
  expected_home={v['species_id']+'__'+mode for v in h.resource('home_atlas_cohort_v1.json')['species'] for mode in ['genome','transcriptome','proteome']}
  actual_home=set(home.get('entries',{}))
  registry['home_expected_objects']=len(expected_home)
  if expected_home-actual_home:errors.append({'namespace':'home_atlas','error':'Expected diagnostic cells missing','cells':sorted(expected_home-actual_home)})
  for key,entry in home.get('entries',{}).items():
   try:
    h.diagnostic(entry);diagnostics.append({'id':key,'valid':True})
    from backend.apps.common.artifact_locations import locate
    located=locate('home_atlas',h.artifact_root(),'diagnostics/objects/'+entry['object_file'])
    rows.append({'namespace':'home_atlas','source_root':str(located.root),'relative_manifest':located.target.relative_to(located.root).as_posix(),'source_version':entry.get('artifact_id',entry['object_file']),'expected_source_sha256':entry['object_sha256'],'target_root':str(h.artifact_root()),'availability':'reusable','decision':'reuse_as_is','reason':'Complete diagnostic object SHA verified; source status remains evaluated by original source_state'})
   except Exception as e:
    diagnostics.append({'id':key,'valid':False,'error':str(e)});errors.append({'namespace':'home_atlas','id':key,'error':str(e)})
  registry['home_diagnostics']=diagnostics
  caches={}
  for namespace in ['feature_profiles','feature_qc','feature_home','feature_exports']:
   counts=[]
   for root in read_roots(namespace,write_root(namespace)):
    files=list(root.glob('*/status.json' if namespace=='feature_exports' else '*.json'));counts.append({'root':str(root),'files':len(files)})
   caches[namespace]=counts
 from deploy.cache_inventory import inventory as cache_inventory
 rows.extend(cache_inventory({n:write_root(n) for n in ['feature_profiles','feature_qc','feature_home','feature_exports']}))
 return {'format':'deployment-compatibility-inventory-v1','created_at':time.time(),'target_container_identity':socket.gethostname(),'source_manifest_sha256':code_manifest(),'registry':registry,'objects':rows,'cache_locations':caches,'errors':errors,'complete':not errors}

def plan(inventory_path):
 data=json_read(inventory_path)
 if data.get('format')!='deployment-compatibility-inventory-v1' or not data.get('complete'):raise ValueError('Incomplete or invalid inventory')
 actions=[]
 for row in data['objects']:
  key=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
  actions.append({**row,'action_id':key,'issue_ids':{'proteome':['F01'],'sequence':['F01'],'integration':['F02'],'compare':['F04','F05'],'home_atlas':['F03'],'feature_profiles':['F06'],'feature_qc':['F06'],'feature_home':['F06'],'feature_exports':['F07','F14']}[row['namespace']],'preconditions':['manifest SHA unchanged','configured read root unchanged','maintenance owner and generation match'],'verify':['original version and SHA preserved'],'rollback':['remove only this adaptation index entry; preserve all packages']})
 return {'format':'deployment-adaptation-plan-v1','inventory_path':str(Path(inventory_path).resolve()),'inventory_sha256':sha(inventory_path),'source_manifest_sha256':data['source_manifest_sha256'],'target_container_identity':data['target_container_identity'],'created_at':time.time(),'actions':actions,'write_bytes_budget':len(json.dumps(actions).encode())*2+65536,'source_mutation':False,'science_rebuilds':[]}

def validate_plan(plan_path,require_maintenance=False,owner=None,generation=None):
 data=json_read(plan_path)
 if data.get('format')!='deployment-adaptation-plan-v1':raise ValueError('Invalid plan format')
 if sha(data['inventory_path'])!=data['inventory_sha256']:raise ValueError('Inventory changed')
 if code_manifest()!=data['source_manifest_sha256']:raise ValueError('Source manifest changed; re-audit')
 if socket.gethostname()!=data['target_container_identity']:raise ValueError('Container identity changed; re-plan')
 if require_maintenance:
  s=state()
  if s['state']!='maintenance' or s.get('owner')!=owner or s['generation']!=int(generation):raise ValueError('Maintenance ownership required')
 # Resolve each configured root once in this read-only validation transaction.
 # Every candidate file is still freshly resolved and its complete SHA checked.
 configured={ns:(write_root(ns).resolve(),read_roots(ns,write_root(ns))) for ns in {v['namespace'] for v in data['actions']}}
 from .source_verifier import SourceVerifier
 source_roots={};target_roots={};seen=set();checks=[]
 for action in data['actions']:
   if action['action_id'] in seen or action['decision'] not in DECISIONS:raise ValueError('Invalid or duplicate action')
   seen.add(action['action_id'])
   ns=action['namespace'];raw_root=action['source_root']
   if raw_root not in source_roots:source_roots[raw_root]=Path(raw_root).resolve()
   root=source_roots[raw_root];write,allowed=configured[ns]
   if ns=='compare':
    if not any(root.is_relative_to(r) for r in allowed):raise ValueError('Unregistered historical run')
   elif root not in allowed:raise ValueError('Unregistered root')
   raw_target=action['target_root']
   if raw_target not in target_roots:target_roots[raw_target]=Path(raw_target).resolve()
   if target_roots[raw_target]!=write:raise ValueError('Invalid write root')
   if action['expected_source_sha256']:checks.append((root,action['relative_manifest'],action['expected_source_sha256']))
   if action['decision']=='rebuild_explicit':raise ValueError('Explicit rebuilding needs a separately approved finite producer action; generic apply never computes')
 # Four bounded I/O readers overlap mount metadata latency. Each owns its
 # directory handles, hashes complete bytes, and rechecks captured roots.
 # No state publication starts until every reader succeeds and exits.
 def verify_chunk(chunk):
  with SourceVerifier() as verifier:
   for root,relative,expected in chunk:
    if verifier.sha(root,relative)!=expected:raise ValueError('Source changed')
   verifier.verify_roots()
 if checks:
  from concurrent.futures import ThreadPoolExecutor
  workers=min(4,len(checks));size=(len(checks)+workers-1)//workers
  with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='adaptation-sha') as pool:
   list(pool.map(verify_chunk,[checks[i:i+size] for i in range(0,len(checks),size)]))
 return data

def apply(plan_path,dry_run=True,owner=None,generation=None):
 data=validate_plan(plan_path,not dry_run,owner,generation);key=sha(plan_path)
 if dry_run:return {'format':'deployment-adaptation-result-v1','dry_run':True,'actions':len(data['actions']),'planned_bytes':data['write_bytes_budget'],'created_requests':0,'plan_sha256':key}
 destination=state_root()/'adaptation';destination.mkdir(parents=True,exist_ok=True)
 if shutil.disk_usage(destination).free<data['write_bytes_budget']+100*1024**2:raise ValueError('Insufficient free space')
 with file_lock(state_root()/'submission.lock'),file_lock(destination/'apply.lock'):
  current=state()
  if current['state']!='maintenance' or current.get('owner')!=owner or current['generation']!=int(generation):raise ValueError('Maintenance ownership changed during validation')
  receipt=destination/(key+'.json')
  if receipt.is_file():return {**json_read(receipt),'idempotent_replay':True}
  index={'format':'deployment-adaptation-index-v1','plan_sha256':key,'actions':data['actions']}
  target=destination/'indices'/(key+'.json');atomic_write_json(target,index)
  result={'format':'deployment-adaptation-result-v1','plan_sha256':key,'inventory_sha256':data['inventory_sha256'],'actions':len(data['actions']),'created_requests':0,'index_sha256':sha(target),'completed_at':time.time(),'maintenance_owner':owner,'generation':int(generation),'source_mutation':False}
  atomic_write_json(receipt,result);atomic_write_json(destination/'current.json',{'plan_sha256':key,'receipt':receipt.name,'index_sha256':result['index_sha256']});return result

def verify(plan_path):
 data=validate_plan(plan_path);receipt=state_root()/'adaptation'/(sha(plan_path)+'.json')
 return {'format':'deployment-adaptation-verification-v1','valid_preconditions':True,'actions':len(data['actions']),'applied':receipt.is_file(),'source_mutation':False,'expected_unavailable':sum(a['decision'] in ['preserve_unavailable','exclude_expired','expose_historical'] for a in data['actions'])}
