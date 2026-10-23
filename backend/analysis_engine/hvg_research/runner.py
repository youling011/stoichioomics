from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
import os,sys,json,uuid,time,subprocess,traceback,shutil,importlib.metadata
import pandas as pd,numpy as np
from django.conf import settings
from .config import validate_config
from .artifacts import atomic_json,atomic_frame,digest,content_hash,safe_path
from .contracts import GeneUniverse
from .locking import run_lock,ResearchCancelled
from .primary_hvg import official_hvg
from .catalog import TABLES,FAMILIES
def now():return datetime.now(timezone.utc).isoformat()
def run_pipeline(cfg):
 from .workflow import normalize_workflow_config
 cfg=normalize_workflow_config(cfg);r=validate_config(cfg.get('hvg_research'))
 if not getattr(settings,'HVG_RESEARCH_ENABLED',False):raise ValueError('HVG_RESEARCH_ENABLED is disabled; research request was not run as legacy')
 p1=cfg['input_adapter'];ws=p1.get('workspace') or {};jobdir=(Path(ws['root_dir'])/ws['job_id']) if ws.get('enabled') else Path(p1['output_dir']).parent
 parent=jobdir/'hvg_functional_comparison'
 with run_lock(parent):return _locked_pipeline(cfg,r,jobdir,parent)
def _locked_pipeline(cfg,r,jobdir,parent):
 from backend.apps.hvg.research_repository import freeze_sources
 from backend.apps.jobs.stoich_registry_resolver import _resolve_species_id
 species=_resolve_species_id(cfg['phase2_stoich'].get('species_id') or '')
 cfg['phase2_stoich']['species_id']=species
 if cfg['phase1_analysis'].get('allow_primary_fallback',False):raise ValueError('Research forbids primary backend fallback')
 if not species or species=='unknown':raise ValueError('Research requires an authoritative species_id')
 source=freeze_sources(species,r['enrichment']['annotation_release_id'])
 registry=Path(settings.BASE_DIR)/'shared/schemas/stoich_ml_feature_registry_v1.json'
 code={p.relative_to(Path(settings.BASE_DIR)).as_posix():digest(p) for folder in [Path(__file__).parent,Path(settings.BASE_DIR)/'backend/apps/hvg'] for p in folder.glob('*.py')}
 inputs={}
 raw=Path(cfg['input_adapter']['input_dir'])
 for section in ['expression','metadata','stoich']:
  for k,v in cfg['input_adapter'].get(section,{}).items():
   if isinstance(v,str) and ('file' in k) and v:
    p=raw/v
    if p.is_file():inputs[section+'.'+k]={'sha256':digest(p),'bytes':p.stat().st_size}
 confighash=deepcopy(cfg);confighash.setdefault('hvg_research',{}).get('execution',{}).pop('resume_run_id',None)
 fingerprint=content_hash({'config':confighash,'inputs':inputs,'sources':source,'registry':digest(registry),'semantic_overlay':digest(Path(settings.BASE_DIR)/r['core']['semantic_overlay']),'code':code})
 resume=r['execution']['resume_run_id'];runid=resume or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:10]
 run=safe_path(parent/'runs',runid);manifestpath=run/'run_manifest.json'
 if resume:
  if not manifestpath.is_file():raise ValueError('Unknown resume run')
  manifest=json.loads(manifestpath.read_text(encoding='utf-8'))
  if manifest['dependency_hash']!=fingerprint:raise ValueError('Resume rejected: code/input/config/registry/source changed; create a new run')
  if manifest['research_status']=='complete':raise ValueError('Complete runs are immutable; create a new run')
 else:
  run.mkdir(parents=True,exist_ok=False)
  manifest={'schema_version':'hvg_research_v1','analysis_run_id':runid,'species_id':species,'dependency_hash':fingerprint,'config_hash':content_hash(confighash),'registry_hash':digest(registry),'data_release_id':content_hash(source['datasets']),'annotation_snapshot_id':source['annotation_release_id'],'created_at':now(),'status':'running','research_status':'running','model_status':'pending','stages':{},'limitations':[],'artifacts':[],'contexts':[]}
  from .workflow import CONTRACT
  manifest.update(workflow_contract=CONTRACT,model_policy='removed',model_status='removed')
  atomic_json(run/'inputs/source_snapshot.json',source);atomic_json(run/'inputs/input_hashes.json',inputs);atomic_json(run/'inputs/code_hashes.json',code);atomic_json(run/'inputs/effective_config.json',cfg)
  atomic_json(run/'inputs/environment.json',{d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata.get('Name')})
  atomic_json(run/'design.json',{'config':r,'phase1_analysis':cfg['phase1_analysis'],'statistical_families':FAMILIES,'independence':'gene-level association; technical resampling not external replication'})
 # New runs clear an old job-level cancellation request, never inherit one from a previous attempt.
 old=jobdir/'logs/cancel_requested.json'
 if old.exists():old.unlink()
 if (run/'cancel_requested.json').exists():(run/'cancel_requested.json').unlink()
 atomic_json(parent/'running_run.json',{'analysis_run_id':runid,'status':'running'})
 def cancelled():return (run/'cancel_requested.json').exists() or old.exists()
 def persist():manifest['heartbeat_at']=now();atomic_json(manifestpath,manifest)
 def stage(name,fn,base=run):
  if cancelled():raise ResearchCancelled('User cancelled research')
  previous=manifest['stages'].get(name,{})
  if previous.get('execution_status')=='completed' and all(safe_path(run,k).is_file() and digest(safe_path(run,k))==v for k,v in previous.get('output_hashes',{}).items()):return previous.get('result')
  record={'execution_status':'running','started_at':now()};manifest['stages'][name]=record;persist();start=time.monotonic()
  before={p:digest(p) for p in base.rglob('*') if p.is_file() and p.suffix in ['.parquet','.json','.csv','.h5ad','.npz','.npy','.mtx','.tsv','.gz','.yaml','.yml'] and p!=manifestpath}
  try:
   result=fn();outputs={p.relative_to(run).as_posix():digest(p) for p in base.rglob('*') if p.is_file() and p.suffix in ['.parquet','.json','.csv','.h5ad','.npz','.npy','.mtx','.tsv','.gz','.yaml','.yml'] and p!=manifestpath and (p not in before or digest(p)!=before[p])}
   record.update(execution_status='completed',result=result,output_hashes=outputs,scientific_status=(result.get('scientific_status') or ('no_significant_result' if result.get('significant')==0 else 'significant' if result.get('significant',0)>0 else 'not_applicable')) if isinstance(result,dict) else 'not_applicable')
  except ResearchCancelled:record.update(execution_status='cancelled');raise
  except Exception as exc:record.update(execution_status='failed',reason=f'{type(exc).__name__}: {exc}');raise
  finally:record.update(seconds=time.monotonic()-start,ended_at=now());persist()
  return result
 def worker(name,ctx):
  env=os.environ.copy();env.update({'PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','MPLCONFIGDIR':str(run/'work/mplcache'),'NUMBA_CACHE_DIR':str(run/'work/numbacache'),'HVG_RESEARCH_OWNER_PID':str(os.getpid())})
  log=ctx/'logs'/f'{name}.log';log.parent.mkdir(parents=True,exist_ok=True)
  with log.open('a',encoding='utf-8') as out:
   proc=subprocess.Popen([sys.executable,'-B','-m','backend.analysis_engine.hvg_research.worker',name,str(ctx)],cwd=settings.BASE_DIR,env=env,stdout=out,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
   try:
    last=0
    while proc.poll() is None:
     if cancelled():
      from .process_guard import terminate_tree
      terminate_tree(proc);raise ResearchCancelled('Cancelled scientific worker tree')
     if time.monotonic()-last>5:persist();last=time.monotonic()
     time.sleep(.2)
    if proc.returncode:raise RuntimeError(f'{name} failed; see context log {log.name}')
   finally:
    if proc.poll() is None:
     from .process_guard import terminate_tree
     terminate_tree(proc)
  unavailable=ctx/'reports'/(name+'_unavailable.json')
  if unavailable.exists():return json.loads(unavailable.read_text(encoding='utf-8'))
  return {'worker':name,'status':'completed','scientific_status':'not_applicable'}
 try:
  from backend.input_adapter.merge import build_internal_dataset,export_standardized_dataset
  from backend.analysis_engine.common import ExpressionDataset
  def standardize():
   p=deepcopy(cfg['input_adapter']);p['output_dir']=str(run/'work/standardized');ds,im,v=build_internal_dataset(p)
   if ds.var.index.has_duplicates:raise ValueError('Duplicate input genes')
   layer=cfg['phase1_analysis'].get('input_layer')
   if layer and layer!='X':
    if p.get('expression',{}).get('format')!='h5ad':raise ValueError('input_layer currently requires H5AD input')
    import anndata as ad
    h5=ad.read_h5ad(Path(p['input_dir'])/p['expression']['file'])
    if layer=='raw':
     if h5.raw is None:raise ValueError('Requested raw layer is absent; raw is not assumed to mean counts')
     chosen=h5.raw.to_adata()
    else:
     if layer not in h5.layers:raise ValueError('Requested counts/log layer is absent')
     chosen=h5.copy();chosen.X=h5.layers[layer].copy()
    if chosen.var_names.has_duplicates:raise ValueError('Duplicate genes in selected layer')
    ds.X=chosen.X.tocsr() if hasattr(chosen.X,'tocsr') else __import__('scipy').sparse.csr_matrix(chosen.X)
    ds.var=chosen.var.copy();ds.var['gene_id']=chosen.var_names.astype(str);im['research_selected_layer']=layer
   export_standardized_dataset(ds,p['output_dir'],im,v,p)
   return {'output_dir':p['output_dir']}
  stage('standardize',standardize)
  from backend.validation.runner_core import run_validation_pipeline
  from backend.mode_resolver.runner_core import run_mode_resolution_pipeline
  validation_cfg=deepcopy(cfg.get('validation') or {});validation_cfg.update(input_dir=str(run/'work/standardized'),output_dir=str(run/'work/validation'))
  stoich_file=(cfg['input_adapter'].get('stoich') or {}).get('file')
  if stoich_file:validation_cfg['raw_stoich_file']=str(Path(cfg['input_adapter']['input_dir'])/stoich_file)
  stage('input_validation',lambda:run_validation_pipeline(validation_cfg))
  mode_cfg=deepcopy(cfg.get('mode_resolution') or {});mode_cfg.update(validation_dir=str(run/'work/validation'),output_dir=str(run/'work/mode_resolution'))
  stage('mode_resolution',lambda:run_mode_resolution_pipeline(mode_cfg))
  from backend.validation.loader import load_standardized_bundle
  from backend.analysis_engine.common import bundle_to_expression_dataset
  bundle=load_standardized_bundle(run/'work/standardized',None);dataset=bundle_to_expression_dataset(bundle)
  primarycfg=deepcopy(cfg['phase1_analysis']);sem=primarycfg.get('matrix_semantics') or dataset.uns.get('matrix_semantics')
  primarycfg['matrix_semantics']={'raw_counts':'counts','log_normalized':'log_normalized','log1p_normalized':'log_normalized'}.get(sem,sem)
  if primarycfg.get('primary_backend','scanpy')!='scanpy':raise ValueError('Research primary_backend must be scanpy')
  context_defs=[{'context_id':'global'}]+r['contexts'];contexts=[]
  for definition in context_defs:
   cid=definition['context_id'];folder='context_'+content_hash(cid)[:16];ctx=run/'contexts'/folder
   for part in ['inputs','labels','core','features','annotations','gene_sets','enrichment','pathway_links','within_pathway','stability','candidates','reports','logs']:(ctx/part).mkdir(parents=True,exist_ok=True)
   atomic_json(ctx/'research_config.json',r);atomic_json(ctx/'design.json',{'phase1_analysis':primarycfg,'context_id':cid})
   mask=np.ones(dataset.n_cells,bool)
   if 'field' in definition:
    if definition['field'] not in dataset.obs:raise ValueError('Missing context field '+definition['field'])
    mask=dataset.obs[definition['field']].isin(definition['values']).to_numpy()
   ds=ExpressionDataset(dataset.matrix[mask],dataset.gene_ids,dataset.gene_names,list(np.asarray(dataset.cell_ids)[mask]),dataset.obs.loc[mask].reset_index(drop=True),dataset.uns)
   def labels():
    L,E,A,M=official_hvg(ds,primarycfg);L['context_id']=cid;atomic_frame(ctx/'labels/hvg_labels.parquet',L);atomic_frame(ctx/'labels/gene_eligibility.parquet',E);L.to_csv(ctx/'labels/baseline.csv',index=False);A.write_h5ad(ctx/'labels/filtered_counts.h5ad',compression='gzip');atomic_json(ctx/'labels/hvg_method_manifest.json',M)
    return GeneUniverse(cid,tuple(L.gene_id),tuple(L.loc[L.is_hvg,'gene_id'])).validate()
   info=stage(cid+':official_hvg',labels,ctx);contexts.append({'context_id':cid,'directory':ctx.relative_to(run).as_posix(),**info});manifest['contexts']=contexts;persist()
   from backend.apps.hvg.research_repository import annotation_snapshot,core_snapshot
   stage(cid+':annotation_snapshot',lambda:annotation_snapshot(ctx,species,source['annotation_release_id'],r['enrichment']),ctx)
   from .enrichment import write_baseline
   stage(cid+':baseline_ora',lambda:write_baseline(ctx,r),ctx)
   stage(cid+':core_snapshot',lambda:core_snapshot(ctx,species,r),ctx)
   shutil.copy2(Path(settings.BASE_DIR)/r['core']['semantic_overlay'],ctx/'core/semantic_overlay.json')
   stage(cid+':feature_analysis',lambda:worker('feature_analysis',ctx),ctx)
   stage(cid+':pathway_analysis',lambda:worker('pathway_analysis',ctx),ctx)
   if r['pathway']['gsea_enabled']:stage(cid+':gsea',lambda:worker('gsea',ctx),ctx)
   else:manifest['limitations'].append(cid+': GSEA explicitly disabled')
   stage(cid+':stability',lambda:worker('stability',ctx),ctx)
   stage(cid+':supplementary',lambda:worker('supplementary',ctx),ctx)
  from .unified_modes import run_modes
  from .unified_downstream import run_original_comparison,run_candidate_functions
  global_ctx=run/contexts[0]['directory']
  mode_result=stage('original_metadata_modes',lambda:run_modes(run,dataset,primarycfg,global_ctx,runid))
  manifest['limitations'].extend((mode_result or {}).get('failed_modes',[]))
  comparison_result=stage('original_nonmodel_comparison',lambda:run_original_comparison(run,cfg))
  if (comparison_result or {}).get('status')=='failed':manifest['limitations'].append('Original comparison: '+comparison_result.get('reason','failed'))
  from .universes import write_universes
  for info in contexts:stage(info['context_id']+':universes',lambda:write_universes(run/info['directory']),run/info['directory'])
  from .reporting import collect_and_correct,publish_report
  stage('global_fdr',lambda:collect_and_correct(run,contexts,r))
  for info in contexts:
   ctx=run/info['directory'];stage(info['context_id']+':candidates',lambda:worker('candidates',ctx),ctx)
  stage('nonmodel_candidate_functions',lambda:run_candidate_functions(run,contexts,r))
  manifest['model_status']='removed'
  manifest['model_policy']='removed'
  stage('reporting',lambda:publish_report(run,contexts,r,manifest))
  if cancelled():raise ResearchCancelled('Cancelled before publication')
  for info in contexts:
   ctx=run/info['directory'];am=json.loads((ctx/'annotations/annotation_manifest.json').read_text(encoding='utf-8'));audit=pd.read_parquet(ctx/'core/core_feature_audit.parquet')
   if am['source_status']=='source_missing':manifest['limitations'].append(info['context_id']+': annotation source missing')
   if audit.final_status.eq('missing_source').any():manifest['limitations'].append(info['context_id']+': one or more Core sources/fields missing')
  if not r['feature_tests']['matching_enabled']:manifest['limitations'].append('Matching explicitly disabled')
  if not r['pathway']['rank_relationship_enabled']:manifest['limitations'].append('Continuous feature-function tests explicitly disabled')
  if r['feature_tests']['ci_repeats']<500:manifest['limitations'].append('Reduced bootstrap precision; exploratory execution level')
  if r['pathway']['gsea_enabled'] and r['pathway']['gsea_permutations']<1000:manifest['limitations'].append('Reduced GSEA permutation precision; exploratory execution level')
  if not r['pathway']['gsea_enabled'] or not r['pathway']['within_pathway_enabled'] or not r['pathway']['interaction_enabled']:manifest['limitations'].append('One or more required research analyses explicitly disabled')
  manifest.update(status='completed',research_status='partial' if manifest['limitations'] else 'complete',completed_at=now());persist()
  from .reporting import create_artifact_manifest
  create_artifact_manifest(run,manifest);persist()
  atomic_json(parent/'active_run.json',{'analysis_run_id':runid,'schema_version':'hvg_research_v1','research_status':manifest['research_status']})
  return {'research':{'analysis_run_id':runid,'run_dir':str(run),'status':manifest['research_status'],'model_status':manifest['model_status']},'workspace':{'job_dir':str(jobdir)}}
 except ResearchCancelled:
  manifest.update(status='cancelled',research_status='cancelled');persist();raise
 except Exception as exc:
  manifest.update(status='failed',research_status='failed',error=f'{type(exc).__name__}: {exc}');persist();raise
 finally:
  pointer=parent/'running_run.json'
  if pointer.exists() and json.loads(pointer.read_text(encoding='utf-8')).get('analysis_run_id')==runid:atomic_json(pointer,{'analysis_run_id':runid,'status':manifest['status']})
