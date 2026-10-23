from pathlib import Path
import json,os,hashlib,zipfile,html,shutil
import numpy as np,pandas as pd
from .catalog import TABLES,FAMILIES
from .artifacts import atomic_json,atomic_frame,digest,content_hash,member_hash
from .statistics import fdr
def collect_and_correct(run,contexts,cfg):
 for info in contexts:_verify_transform_metadata(run/info['directory'],cfg)
 hypotheses=[]
 for key,rel in TABLES.items():
  if key in ['candidates','candidate_evidence','gene_pathways','hypotheses']:continue
  parts=[]
  for info in contexts:
   p=run/info['directory']/(rel+'.parquet')
   if p.is_file():
    frame=pd.read_parquet(p);frame['context_id']=info['context_id'];parts.append(frame)
  if not parts:continue
  frame=pd.concat(parts,ignore_index=True)
  family=FAMILIES.get(key)
  if family and 'p_value' in frame:
   # Main correction spans all declared contexts. Alternative models/scopes remain named families.
   groups=['model'] if key=='adjusted' and 'model' in frame else ['family_id'] if key=='supplementary_ora' and 'family_id' in frame else []
   groupiter=frame.groupby(groups,dropna=False).groups.values() if groups else [frame.index]
   for ids in groupiter:
    frame.loc[ids,'q_global']=fdr(frame.loc[ids,'p_value']);frame.loc[ids,'q_global_by']=fdr(frame.loc[ids,'p_value'],'by')
   if key=='feature_tests':frame['strong_raw']=frame.q_global.lt(cfg['feature_tests']['alpha'])&frame.effect.abs().ge(cfg['feature_tests']['minimum_abs_cliffs_delta'])&((frame.ci_low>0)|(frame.ci_high<0))
   for i,row in frame.iterrows():
    h={k:row.get(k) for k in ['context_id','feature_key','term_key','direction','source','scope','model','set_id','p_value','q_global','q_global_by','status','background_id']};h['family_id']=str(row.get('family_id') or family);h['hypothesis_id']=content_hash([key,i,h]);h['included_in_fdr']=bool(pd.notna(row.get('p_value')));hypotheses.append(h)
   for info in contexts:
    p=run/info['directory']/(rel+'.parquet');atomic_frame(p,frame[frame.context_id.eq(info['context_id'])].drop(columns='context_id'))
  if key=='adjusted':frame['scale']='per_1_IQR_transformed_feature_with_SD_fallback' if cfg['preprocessing']['continuous_scaler']=='robust' else 'per_1_SD_transformed_feature'
  atomic_frame(run/(rel+'.parquet'),frame)
 # Rebuild evidence from globally corrected feature and adjusted tables, before candidate selection.
 for info in contexts:
  ctx=run/info['directory'];p=ctx/'features/feature_tests.parquet'
  if not p.exists():continue
  E=pd.read_parquet(p);adj=pd.read_parquet(ctx/'features/adjusted_feature_tests.parquet');M=pd.read_parquet(ctx/'features/matching_diagnostics.parquet')
  chosen=adj[adj.model.eq('expression_detection_length')].set_index('feature_key') if len(adj) else pd.DataFrame(columns=['q_global','beta'])
  E['adjusted_q']=E.feature_key.map(chosen.q_global);E['adjusted_beta']=E.feature_key.map(chosen.beta)
  E['adjusted_supported']=E.adjusted_q.lt(cfg['feature_tests']['alpha'])&(np.sign(E.effect)==np.sign(E.adjusted_beta))
  E['match_effect']=E.feature_key.map(M.set_index('feature_key').paired_sign_effect) if len(M) else np.nan;E['matching_direction_agrees']=np.sign(E.effect)==np.sign(E.match_effect)
  atomic_frame(ctx/'features/feature_evidence_summary.parquet',E)
 for info in contexts:
  ctx=run/info['directory'];parts={}
  for kind in ['subset','within_hvg','matched_baseline']:
   p=ctx/(TABLES[kind]+'.parquet');parts[kind]=pd.read_parquet(p) if p.exists() else pd.DataFrame()
  a=parts['subset'];b=parts['within_hvg'];c=parts['matched_baseline']
  if len(a):
   keys=[x for x in ['feature_key','direction','source','term_key'] if x in a and x in b]
   cols=keys+[x for x in ['p_value','q_global','fold_enrichment','N','K','n','k','status'] if x in b and x not in keys]
   comp=a.merge(b[cols],on=keys,how='left',suffixes=('_subset','_within_hvg'))
   if len(c):comp=comp.merge(c[[x for x in ['source','term_key','background_id','N','K','n','k','q_global','fold_enrichment'] if x in c]],on=['source','term_key','background_id'],how='left',suffixes=('','_matched_baseline'))
   atomic_frame(ctx/'enrichment/enrichment_comparison.parquet',comp)
 comps=[]
 for info in contexts:
  p=run/info['directory']/'enrichment/enrichment_comparison.parquet'
  if p.exists():f=pd.read_parquet(p);f['context_id']=info['context_id'];comps.append(f)
 if comps:atomic_frame(run/'enrichment/enrichment_comparison.parquet',pd.concat(comps,ignore_index=True))
 atomic_frame(run/'reports/hypothesis_manifest.parquet',pd.DataFrame(hypotheses));return {'hypotheses':len(hypotheses),'scope':'all declared contexts; independent named model/supplementary families'}
def run_optional_model(run,jobdir,cfg,manifest):
 ctx=run/manifest['contexts'][0]['directory']
 # A separate optional-model baseline adds original uploaded/registry var features,
 # without changing any official labels or the research universe.
 model_dir=run/'work/analysis_phase1';model_dir.mkdir(parents=True,exist_ok=True)
 L=pd.read_csv(ctx/'labels/baseline.csv');varpath=run/'work/standardized/standardized_var.csv'
 if varpath.exists():
  var=pd.read_csv(varpath);var=var.drop(columns=[c for c in var if c!='gene_id' and c in L],errors='ignore')
  L=L.merge(var,on='gene_id',how='left',validate='one_to_one')
 baseline=model_dir/'hvg_baseline.csv';L.to_csv(baseline,index=False)
 method=json.loads((ctx/'labels/hvg_method_manifest.json').read_text(encoding='utf-8'));atomic_json(model_dir/'phase1_mode_summary.json',{'primary_backend':'scanpy','method_metadata':method,'n_rows_primary':len(L),'n_hvgs_primary':int(L.is_hvg.sum()),'analysis_run_id':manifest['analysis_run_id']})
 p=deepcopy_dict(cfg['phase2_stoich']);p['input_baseline_csv']=str(baseline);p['output_dir']=str(run/'work/analysis_phase2');p['research_comparison_reference']=str(ctx/'features/feature_evidence_summary.parquet');p['validation_dir']=str(run/'work/validation');p['input_phase1_summary_json']=str(run/'work/analysis_phase1/phase1_mode_summary.json')
 # Legacy comparison is supplied through an explicit research adapter, not rerun.
 p['research_comparison_summary']={'schema_version':'hvg_research_v1','status':'completed','research_reference':str(ctx/'features/feature_evidence_summary.parquet')}
 from backend.analysis_engine.phase2.runner_core import run_phase2_stoich_pipeline
 try:
  result=run_phase2_stoich_pipeline(p);manifest['model_status']=(result.get('summary') or {}).get('model_status') or ('completed' if p.get('model_enabled',p.get('enabled',True)) else 'disabled')
  return {'status':manifest['model_status'],'output_dir':'work/analysis_phase2'}
 except Exception as exc:manifest['model_status']='failed';manifest['model_limitation']=f'{type(exc).__name__}: {exc}';return {'status':'failed','reason':manifest['model_limitation']}
def deepcopy_dict(d):
 from copy import deepcopy
 return deepcopy(d)
def publish_report(run,contexts,cfg,manifest):
 for key in ['features','candidates','candidate_evidence','gene_pathways','annotations','labels','gene_features','sets','set_members','feature_stability','candidate_stability']:
  rel=TABLES[key];parts=[]
  for info in contexts:
   p=run/info['directory']/(rel+'.parquet')
   if p.is_file():f=pd.read_parquet(p);f['context_id']=info['context_id'];parts.append(f)
  if parts:atomic_frame(run/(rel+'.parquet'),pd.concat(parts,ignore_index=True))
 summary={'schema_version':'hvg_research_v1','analysis_run_id':manifest['analysis_run_id'],'species_id':manifest['species_id'],'contexts':contexts,'model_status':manifest['model_status'],'workflow_contract':manifest.get('workflow_contract'),'model_policy':manifest.get('model_policy'),'limitations':manifest['limitations'],'validation_scope':'Technical resampling and declared donor sensitivity when available; no external independent validation','tables':{}}
 phenomena=[]
 for key,rel in TABLES.items():
  p=run/(rel+'.parquet')
  if not p.is_file():continue
  f=pd.read_parquet(p);summary['tables'][key]={'rows':len(f),'significant':int(f.q_global.lt(cfg['feature_tests']['alpha']).sum()) if 'q_global' in f else None}
  f.to_csv(run/(rel+'.csv.gz'),index=False,encoding='utf-8-sig',compression='gzip')
  if key=='features':
   for row in f[f.strong_raw].sort_values('q_global').head(30).to_dict('records'):
    phenomena.append({'phenomenon_id':content_hash([row['context_id'],row['feature_key']]),'context_id':row['context_id'],'feature_key':row['feature_key'],'observation':f"HVG feature distribution {'higher' if row['effect']>0 else 'lower'} than non-HVG",'effect':row['effect'],'q_global':row['q_global'],'support_level':'adjusted_association' if row.get('adjusted_supported') else 'raw_association','validation_status':'no independent external replication','alternatives':['gene length','expression/detection differences','cell composition','correlated sequence composition'],'restriction':'Sequence-derived composition is not measured resource consumption or a causal mechanism'})
 from .phenomena import functional_phenomena
 phenomena.extend(functional_phenomena(run,cfg['feature_tests']['alpha']))
 atomic_json(run/'reports/phenomena.json',phenomena);atomic_json(run/'summary.json',summary)
 from backend.apps.hvg.research_visuals import presentation
 atomic_json(run/'reports/presentation.json',presentation(run,manifest))
 _figures(run,cfg,summary)
 lines=['# HVG research results',f"\nRun: {manifest['analysis_run_id']} | Species: {manifest['species_id']}",'\nStandard labels are produced directly by Scanpy; HVG/non-HVG sets are frozen before Core mapping. Every Core field is audited. Units are normalized before transformation and model scaling is performed per feature. Non-significant and non-estimable results are retained. Global BH correction spans all declared contexts; BY results are also saved.','\n## Result counts','\n|Result table|Rows|Global BH significant|','|---|---:|---:|']
 lines.extend(f"|{k}|{v['rows']}|{v['significant'] if v['significant'] is not None else 'Not applicable'}|" for k,v in summary['tables'].items())
 lines+=['\n## Interpretation','\nFeature and set-enrichment q values are not gene-level significance. Correlated fields and overlapping functions are not independent replication. Non-significant adjusted or interaction tests are distinguished from insufficient data. Sequence stoichiometry does not directly measure elemental or ATP consumption and does not establish causality. Without independent external data, candidates remain hypotheses for follow-up validation.','\nDownload complete members, universes, ranks, permutations, mappings and method metadata. Undefined or newly registered fields remain in the audit; their biological definitions are not automatically validated.','\n## Run limitations']+['\n- '+x for x in manifest['limitations']]
 (run/'reports/result_explanation.md').write_text('\n'.join(lines),encoding='utf-8')
 atomic_json(run/'reports/plot_manifest.json',{'plots':[{'plot_kind':x,'png':'figures/'+x+'.png','svg':'figures/'+x+'.svg','source_data':'figures/'+x+'.csv'} for x in PLOTS],'statistics_use_full_tables':True,'chart_preview_limit':30})
 body=''.join(f'<h2>{html.escape(x)}</h2><img alt="{html.escape(x)}" style="max-width:100%" src="figures/{x}.png">' for x in PLOTS)
 (run/'结果总览.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HVG research results</title><main style="max-width:1100px;margin:auto;padding:24px;font:16px/1.6 system-ui;color:#15344f"><h1>HVG research results</h1><p>Inspect interactive evidence in the platform result sections. Download complete statistics and gene-set members for reproducibility.</p>'+body+'</main></html>',encoding='utf-8')
 return {'status':'completed','tables':len(summary['tables']),'figures':len(PLOTS)}
PLOTS=['01_hvg_universe','02_core_audit','03_feature_effects','04_adjusted_support','05_baseline_enrichment','06_subset_enrichment','07_feature_pathways','08_within_function','09_candidates_stability']
def _figures(run,cfg,summary):
 import matplotlib;matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 plt.rcParams.update({'font.size':10,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False})
 out=run/'figures';out.mkdir(exist_ok=True)
 specs=[('labels','is_hvg',None),('core_audit','final_status',None),('features','feature_key','effect'),('adjusted','feature_key','beta'),('baseline','term_name','fold_enrichment'),('subset','term_name','fold_enrichment'),('feature_pathways','term_name','effect'),('within_pathways','feature_key','effect'),('candidates','gene_id','hvg_resampling_frequency')]
 for name,(key,label,value) in zip(PLOTS,specs):
  p=run/(TABLES[key]+'.parquet');f=pd.read_parquet(p) if p.exists() else pd.DataFrame();fig,ax=plt.subplots(figsize=(11,7))
  if len(f) and value is None:
   vc=f[label].astype(str).value_counts();df=vc.rename_axis(label).rename('count').reset_index();ax.barh(df[label],df['count']);ax.set_xlabel('Genes' if key=='labels' else 'Core fields')
  elif len(f) and value in f:
   df=f[np.isfinite(pd.to_numeric(f[value],errors='coerce'))].copy()
   if 'q_global' in df:df=df.sort_values('q_global')
   df=df.head(20);colors=['#23628b' if pd.notna(q) and q<cfg['feature_tests']['alpha'] else '#9ea9b2' for q in df.get('q_global',pd.Series(np.nan,index=df.index))]
   ax.barh(np.arange(len(df)),df[value],color=colors);ax.set_yticks(np.arange(len(df)),df[label].astype(str));ax.invert_yaxis();ax.set_xlabel(value+'; blue = global BH significant, grey = other')
  else:df=f.head(0);ax.text(.5,.5,'No estimable results; inspect stage status',ha='center',transform=ax.transAxes)
  ax.set_title(name.replace('_',' '));fig.tight_layout();fig.savefig(out/(name+'.png'),dpi=180);fig.savefig(out/(name+'.svg'));plt.close(fig);df.to_csv(out/(name+'.csv'),index=False,encoding='utf-8-sig')
def create_artifact_manifest(run,manifest):
 for stage in manifest['stages'].values():
  original=stage.get('output_hashes',{})
  stage.setdefault('produced_output_hashes',dict(original))
  stage['output_hashes']={rel:digest(run/rel) for rel in original if (run/rel).is_file()}
 artifacts=[]
 for p in sorted(run.rglob('*')):
  rel=p.relative_to(run)
  supporting_work=rel.parts[:2] in [('work','analysis_phase1'),('work','analysis_phase2'),('work','visualization'),('work','downstream')]
  if not p.is_file() or ('work' in rel.parts and not supporting_work) or 'logs' in rel.parts or p.name in ['run_manifest.json','download_manifest.json','research_bundle.zip'] or p.name.startswith('.'):continue
  artifacts.append({'artifact_id':content_hash(rel.as_posix())[:24],'path':rel.as_posix(),'bytes':p.stat().st_size,'sha256':digest(p),'format':p.suffix.lstrip('.'),'status':'available'})
 manifest['artifacts']=artifacts;atomic_json(run/'download_manifest.json',{'schema_version':'hvg_research_v1','artifacts':artifacts,'csv_policy':'Machine-readable UTF-8 IDs unchanged; safe spreadsheet export through API is separate'})
 # Manifest is written before zipping to make the bundle self-contained.
 atomic_json(run/'run_manifest.json',manifest)
 tmp=run/'.research_bundle.zip.tmp'
 with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
  for row in artifacts:
   if (run/'cancel_requested.json').exists():raise InterruptedError('Cancelled during export')
   z.write(run/row['path'],row['path'])
  z.write(run/'run_manifest.json','run_manifest.json');z.write(run/'download_manifest.json','download_manifest.json')
 os.replace(tmp,run/'research_bundle.zip');manifest['artifacts'].append({'artifact_id':'complete_bundle','path':'research_bundle.zip','bytes':(run/'research_bundle.zip').stat().st_size,'sha256':digest(run/'research_bundle.zip'),'format':'zip','status':'available'})

def _verify_transform_metadata(ctx,cfg):
 p=ctx/'features/transform_manifest.json'
 if not p.exists():return
 manifest=json.loads(p.read_text(encoding='utf-8'));transforms=manifest.get('transforms',[])
 if not transforms:return
 P=pd.read_parquet(ctx/'features/feature_values.parquet');Z=pd.read_parquet(ctx/'features/model_values.parquet');X=pd.read_parquet(ctx/'core/context.parquet');registry=json.loads((ctx/'core/registry_snapshot.json').read_text(encoding='utf-8'));specs={r['omics']+'::'+r['field']:r for r in registry['fields'] if r.get('scope')=='core'}
 for tr in transforms:
  key=tr['feature_key'];kind=tr['model_transform'];a=P[key].to_numpy(float).copy();valid=np.isfinite(Z[key].to_numpy(float));scaler=cfg['preprocessing']['continuous_scaler']
  if kind=='log1p_canonical_units':a=np.log1p(a)
  elif kind=='log_positive_ratio':a=np.log(a)
  elif kind=='clr_complete_group':
   group=next((g for g in manifest.get('composition_groups',[]) if key in g['declared_components']),None)
   if group:
    cols=[]
    for k in group['declared_components']:
     o,n=k.split('::',1);v=pd.to_numeric(X[o+'__'+n],errors='coerce').to_numpy(float)
     if specs[k].get('unit')=='%':v=v/100
     cols.append(v)
    M=np.column_stack(cols);logs=np.log(M[valid]+group['pseudocount']);a[:]=np.nan;a[valid]=(logs-logs.mean(1,keepdims=True))[:,group['declared_components'].index(key)]
  if valid.any():
   center=float(np.nanmedian(a)) if scaler=='robust' else float(np.nanmean(a));iqr=float(np.nanpercentile(a,75)-np.nanpercentile(a,25));sd=float(np.nanstd(a));scale=iqr if scaler=='robust' else sd
   if not np.isfinite(scale) or scale<=1e-12*max(np.nanmax(abs(a)),1e-12):scale=sd
   verified=bool(np.allclose((a[valid]-center)/scale,Z.loc[valid,key],rtol=1e-8,atol=1e-8)) if scale else False
   if not verified:raise ValueError('Saved feature transform cannot be reconstructed: '+key)
   tr.update(scaler=scaler,center=center,scale=scale,reference_iqr=iqr,reference_sd=sd,reconstruction_verified=True)
 manifest['scaling']=cfg['preprocessing']['continuous_scaler']+' per-column shared frozen-U reference; IQR-zero SD fallback';manifest['label_revision']='Verified actual saved model values; no estimates changed';atomic_json(p,manifest)
 a=ctx/'features/adjusted_feature_tests.parquet'
 if a.exists():
  f=pd.read_parquet(a);f['scale']='per_1_IQR_transformed_feature_with_SD_fallback' if cfg['preprocessing']['continuous_scaler']=='robust' else 'per_1_SD_transformed_feature';atomic_frame(a,f)
