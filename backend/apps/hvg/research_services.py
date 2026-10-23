"""Authenticated, run-scoped result access without loading legacy case caches."""
from pathlib import Path
import json,io
import pandas as pd,numpy as np
import pyarrow.dataset as ds
from backend.analysis_engine.hvg_research.artifacts import safe_path,clean
from backend.analysis_engine.hvg_research.catalog import TABLES
from backend.apps.jobs.models import AnalysisJob
from backend.apps.jobs.services import ensure_job_token
def authorize(identifier,token):
 job=AnalysisJob.objects.filter(job_id=identifier).first()
 if job:
  ensure_job_token(job,token);return Path(job.workspace_path)
 from backend.apps.registry.services import list_cases
 for case in list_cases():
  if case['case_id']==identifier:return Path(case['base_dir'])
 raise FileNotFoundError('Unknown case/job')
def load_run(base,run_id=None):
 parent=Path(base)/'hvg_functional_comparison'
 if not run_id:
  pointer=parent/'active_run.json'
  if not pointer.exists():pointer=parent/'running_run.json'
  if not pointer.exists():raise FileNotFoundError('No research run for this case/job')
  run_id=json.loads(pointer.read_text(encoding='utf-8'))['analysis_run_id']
 run=safe_path(parent/'runs',run_id);p=run/'run_manifest.json'
 if not p.is_file():raise FileNotFoundError('Unknown research run')
 m=json.loads(p.read_text(encoding='utf-8'))
 if m['analysis_run_id']!=run_id:raise ValueError('Run ownership mismatch')
 return run,m
def read_table(run,key,params=None):
 from .research_originals import ORIGINAL_TABLES,original_table
 params=params or {};relative=TABLES.get(key) or ORIGINAL_TABLES.get(key)
 if relative is None:raise ValueError('Unknown result table')
 path=run/(relative+'.parquet')
 if key in ORIGINAL_TABLES:
  import pyarrow as pa
  frame=original_table(run,key,params);dataset=ds.dataset(pa.Table.from_pandas(frame,preserve_index=False))
 elif path.is_file():dataset=ds.dataset(path,format='parquet')
 else:
  # Older completed runs keep these evidence tables per context. Read without rewriting them.
  p=run/'run_manifest.json';manifest=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {};parts=[]
  for c in manifest.get('contexts',[]):
   if params.get('context_id') and c['context_id']!=params['context_id']:continue
   folder=safe_path(run,c['directory']);p=folder/(relative+'.parquet')
   if p.exists():frame=pd.read_parquet(p)
   elif key in ['mapping','feature_provenance'] and (folder/(relative+'.csv')).exists():frame=pd.read_csv(folder/(relative+'.csv'),keep_default_na=False)
   else:continue
   frame['context_id']=c['context_id']
   if key=='mapping' and 'expression_gene_id' in frame:frame['gene_id']=frame.expression_gene_id
   parts.append(frame)
  if not parts:return pd.DataFrame()
  import pyarrow as pa
  dataset=ds.dataset(pa.Table.from_pandas(pd.concat(parts,ignore_index=True),preserve_index=False))
 names=dataset.schema.names;condition=None
 for field in ['context_id','feature_key','term_key','set_id','source','gene_id','direction','status','scope','run_id','model','stoich_class']:
  value=params.get(field)
  if value and field in names:
   e=ds.field(field)==str(value);condition=e if condition is None else condition&e
 if params.get('q_max') is not None and params.get('q_max')!='':
  q=float(params['q_max'])
  if not 0<=q<=1:raise ValueError('q_max outside [0,1]')
  if 'q_global' in names:e=ds.field('q_global')<=q;condition=e if condition is None else condition&e
 frame=dataset.to_table(filter=condition).to_pandas()
 if key=='gsea' and 'nes' in frame:
  frame['nes_status']=np.where(np.isfinite(pd.to_numeric(frame.nes,errors='coerce')),'estimated','not_estimable_no_same_sign_normalization')
  if 'same_sign_null_count' in frame:frame['nominal_p_kind']=np.where(frame.same_sign_null_count.gt(0),'finite_same_sign_tail','conservative_upper_bound')
 if key=='matched_baseline' and params.get('feature_key') and 'background_id' in frame:
  comp=read_table(run,'enrichment_comparison',params)
  if 'background_id' in comp:frame=frame[frame.background_id.isin(comp.background_id)]
 if params.get('query'):
  query=str(params['query'])[:500];cols=[x for x in ['gene_id','gene_name','feature_key','term_key','term_name','final_status'] if x in frame];mask=np.zeros(len(frame),bool)
  for c in cols:mask|=frame[c].astype(str).str.contains(query,case=False,regex=False,na=False).to_numpy()
  frame=frame.loc[mask]
 for field in ['omics','family','final_status','priority_tier']:
  value=params.get(field)
  if value and field in frame:
   frame=frame[frame[field].astype(str).str.startswith(str(value))] if field=='priority_tier' else frame[frame[field].eq(value)]
 return frame
def page_table(run,m,key,params):
 page=int(params.get('page',1));size=int(params.get('page_size',50))
 if page<1 or not 1<=size<=200:raise ValueError('page>=1 and page_size between 1 and 200 required')
 f=read_table(run,key,params);sort=params.get('sort');order=params.get('order','asc')
 if order not in ['asc','desc']:raise ValueError('Unknown sort order')
 allowed={'feature_key','gene_id','gene_name','term_key','term_name','q_global','effect','beta','priority_rank','hvg_score','n_members','source','final_status','omics','family','status','nes','fold_enrichment','context_id','priority_tier','n1','n0','rank','hvg_rank','direction'}
 if sort and sort not in allowed:raise ValueError('Unsupported sort column')
 tie=[x for x in ['context_id','feature_key','term_key','gene_id','set_id','direction','scope','model','run_id'] if x in f and x!=sort]
 if sort and sort in f:f=f.sort_values([sort]+tie,ascending=[order=='asc']+[True]*len(tie),kind='stable',na_position='last')
 elif tie:f=f.sort_values(tie,kind='stable')
 return {'rows':clean(f.iloc[(page-1)*size:page*size].to_dict('records')),'total':len(f),'page':page,'page_size':size,'analysis_run_id':m['analysis_run_id'],'schema_version':m['schema_version'],'status':m['research_status'],'limitations':m.get('limitations',[])}
def summary(run,m,params=None):
 p=run/'summary.json';s=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
 from .research_visuals import presentation
 s['presentation']=presentation(run,m,(params or {}).get('context_id'))
 return {**s,'coverage':coverage(run,m),'analysis_run_id':m['analysis_run_id'],'schema_version':m['schema_version'],'status':m['research_status'],'model_status':m.get('model_status'),'workflow_contract':m.get('workflow_contract'),'model_policy':m.get('model_policy'),'stages':{k:{x:v for x,v in rec.items() if x in ['execution_status','scientific_status','started_at','ended_at','seconds','reason']} for k,rec in m['stages'].items()},'limitations':m.get('limitations',[]),'contexts':[{k:v for k,v in x.items() if k!='directory'} for x in m.get('contexts',[])]}
def coverage(run,m):
 label=run/'labels/hvg_labels.parquet';ann=run/'annotations/gene_term_membership.parquet';audit=run/'core/core_feature_audit.parquet'
 if not label.exists():return []
 L=pd.read_parquet(label,columns=['gene_id','context_id','is_hvg']);A=pd.read_parquet(ann) if ann.exists() else pd.DataFrame();C=pd.read_parquet(audit) if audit.exists() else pd.DataFrame();rows=[]
 for cid,g in L.groupby('context_id'):
  a=A[A.context_id.eq(cid)] if len(A) else A;c=C[C.context_id.eq(cid)] if len(C) else C
  rows.append({'context_id':cid,'U':len(g),'H':int(g.is_hvg.sum()),'N':int((~g.is_hvg).sum()),'annotated_genes':a.gene_id.nunique() if len(a) else 0,'annotation_fraction':a.gene_id.nunique()/len(g) if len(a) and len(g) else 0,'audited_core':len(c),'tested_core':int(c.final_status.eq('tested').sum()) if len(c) else 0,'sources':a.groupby('source').gene_id.nunique().to_dict() if len(a) else {}})
 return rows
def gene_detail(run,m,gene,params):
 # Object evidence always includes all applicable Core; plot/table filters do not redefine it.
 params={"context_id":params.get("context_id")}
 if len(m.get('contexts',[]))>1 and not params.get('context_id'):raise ValueError('Select context_id for gene evidence')
 filt={**params,'gene_id':gene};labels=read_table(run,'labels',filt)
 if labels.empty:raise FileNotFoundError('Gene is outside this context universe')
 result={'gene_id':gene,'analysis_run_id':m['analysis_run_id'],'schema_version':m['schema_version'],'label':clean(labels.to_dict('records')),'statistical_level':'Feature/term q values are not gene p values'}
 for key in ['values','core_values','gene_features','candidate_evidence','annotations','gene_pathways','leading_edge','candidate_stability','candidates','set_members']:result[key]=clean(read_table(run,key,filt).to_dict('records'))
 terms=set(x['term_key'] for x in result['annotations']);features=set(x['feature_key'] for x in result['candidate_evidence'])
 for key in ['baseline','subset','within_hvg','within_pathways','within_adjusted','interactions']:
  frame=read_table(run,key,params)
  if 'term_key' in frame:frame=frame[frame.term_key.isin(terms)]
  if key!='baseline' and 'feature_key' in frame:frame=frame[frame.feature_key.isin(features)]
  result[key]=clean(frame.to_dict('records'))
 audit=read_table(run,'core_audit',params);all_values=read_table(run,'values',{'context_id':params.get('context_id')});all_labels=read_table(run,'labels',{'context_id':params.get('context_id')});nonhvg=set(all_labels.loc[~all_labels.is_hvg,'gene_id']);reference=all_values[all_values.gene_id.isin(nonhvg)]
 prepared=result['values'][0] if result['values'] else {};raw=result['core_values'][0] if result['core_values'] else {};value_rows=[]
 for r in audit.to_dict('records'):
  key=r['feature_key'];value=prepared.get(key);ref=pd.to_numeric(reference[key],errors='coerce').dropna().to_numpy() if key in reference else np.array([])
  value_rows.append({'feature_key':key,'omics':r.get('omics'),'unit':r.get('unit'),'raw_value':raw.get(r.get('context_column') or key.replace('::','__')),'prepared_value':value,'nonhvg_reference_percentile':float(np.mean(ref<=value)) if len(ref) and value is not None and pd.notna(value) else None,'feature_disposition':r.get('final_status'),'feature_reason':r.get('reason'),'semantic_review_status':r.get('semantic_review_status')})
 result['core_feature_values']=clean(value_rows);result['mapping_identity']=[]
 for key in ([] if m.get('model_policy')=='removed' else ['original_model_scores','original_candidate_components']):
  result[key]=clean(read_table(run,key,filt).to_dict('records'))
 for c in m.get('contexts',[]):
  if params.get('context_id') and c['context_id']!=params['context_id']:continue
  p=safe_path(run,c['directory'])/'core/hvg_multiomics_mapping_table.csv'
  if p.exists():
   f=pd.read_csv(p,keep_default_na=False);f=f[f.expression_gene_id.eq(gene)];result['mapping_identity'].extend(clean(f.to_dict('records')))
 return result
def feature_detail(run,m,key,params):
 params={"context_id":params.get("context_id")}
 if len(m.get('contexts',[]))>1 and not params.get('context_id'):raise ValueError('Select context_id for feature evidence')
 filt={**params,'feature_key':key};out={'feature_key':key,'analysis_run_id':m['analysis_run_id'],'schema_version':m['schema_version']}
 for tab in ['core_audit','features','adjusted','matching','sets','feature_stability']:out[tab]=clean(read_table(run,tab,filt).to_dict('records'))
 vals=read_table(run,'values',params);labels=read_table(run,'labels',params)
 out['distribution']=[]
 if key in vals:
  data=vals.merge(labels[['gene_id','is_hvg']],on='gene_id',how='inner')
  for flag,g in data.groupby('is_hvg'):
   a=pd.to_numeric(g[key],errors='coerce').dropna();out['distribution'].append({'group':'HVG' if flag else 'non-HVG','n':len(a),'quantiles':clean(np.quantile(a,[0,.05,.25,.5,.75,.95,1])) if len(a) else []})
 return out
def plots(run,m,kind,params):
 mapping={'forest':('features','feature_key','effect'),'volcano':('features','effect','q_global'),'enrichment':('baseline','term_name','fold_enrichment'),'feature_pathway':('feature_pathways','term_name','effect'),'within_function':('within_pathways','feature_key','effect'),'stability':('replication','run_id','jaccard_primary'),'candidate':('candidates','gene_id','hvg_resampling_frequency'),'gsea':('gsea','term_name','nes')}
 if kind=='gsea_curve':
  ranked=read_table(run,'ranked_genes',{**params,'term_key':None}).sort_values('rank')
  if not params.get('run_id') or not params.get('term_key'):raise ValueError('GSEA curve needs run_id and term_key')
  ann=read_table(run,'annotations',{'context_id':params.get('context_id'),'term_key':params['term_key']});genes=ranked.gene_id.to_numpy(str);score=ranked.rank_score.to_numpy(float)
  if not len(ranked):return {'rows':[],'status':'not_available'}
  hit=np.isin(genes,ann.gene_id);weight=abs(score)*hit;den=weight.sum();miss=(~hit).sum()
  curve=np.cumsum(weight/den-(~hit)/miss) if den and miss else np.full(len(score),np.nan)
  indices=np.unique(np.r_[np.linspace(0,len(score)-1,min(1000,len(score))).astype(int),np.nanargmax(curve),np.nanargmin(curve)])
  return {'rows':clean([{'rank':int(i+1),'running_es':curve[i]} for i in indices]),'hits':np.flatnonzero(hit).tolist(),'total_ranked_genes':len(score),'method':'Weighted GSEA running ES reconstructed from the actual saved rank and term membership','analysis_run_id':m['analysis_run_id']}
 if kind=='distribution':return feature_detail(run,m,params.get('feature_key'),params)
 if kind not in mapping:raise ValueError('Unknown plot kind')
 key,x,y=mapping[kind];f=read_table(run,key,params);n=len(f)
 if 'q_global' in f:f=f.sort_values('q_global')
 f=f.head(200)
 return {'rows':clean(f.to_dict('records')),'total':n,'displayed':len(f),'sample_policy':'first 200 after global-q stable sorting; statistics use complete tables','x':x,'y':y,'analysis_run_id':m['analysis_run_id']}
