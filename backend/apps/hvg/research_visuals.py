"""Run-scoped scientific visual payloads, independent of table pagination.

These are views of saved, globally corrected evidence. No statistic is refit here.
The contract is shared by all ten original HVG result sections and all datasets.
"""
import json
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from backend.analysis_engine.hvg_research.artifacts import clean,safe_path
from backend.analysis_engine.hvg_research.catalog import TABLES

VERSION='hvg_ten_sections_v1'
SECTIONS={
 'overview':{'plots':['universe','annotation_coverage','core_disposition'],'tables':['universes','hypotheses']},
 'input_qc':{'plots':['eligibility','mapping_coverage','core_omics','core_missingness'],'tables':['eligibility','mapping','feature_provenance','core_audit','redundancy','universes']},
 'phase1':{'plots':['hvg_scatter','hvg_histogram','baseline'],'tables':['labels','baseline']},
 'context_patterns':{'plots':['context_coverage','context_effects'],'tables':['features','replication']},
 'group_comparison':{'plots':['feature_forest','feature_volcano','adjusted_forest','matching','distribution','sets'],'tables':['features','feature_tests','core_audit','adjusted','matching','categorical_tests','sets','set_members','gene_features','adjusted_sets','joint_sets']},
 'phase2':{'plots':['feature_function','gsea','interactions'],'tables':['feature_pathways','gsea','gsea_runs','interactions','ranked_genes','leading_edge']},
 'model_evidence':{'plots':['replication','feature_stability','set_stability','threshold_stability','baseline_stability','candidate_frequency'],'tables':['replication','feature_stability','feature_sensitivity','candidate_stability','set_stability','threshold_sensitivity','baseline_stability','replication_labels','matching']},
 'downstream':{'plots':['baseline','subset','within_hvg','within_raw','within_adjusted','candidate_tiers','candidate_priority'],'tables':['baseline','matched_baseline','subset','within_hvg','enrichment_comparison','supplementary_ora','within_pathways','within_adjusted','candidates','candidate_evidence','gene_pathways']},
 'genes':{'plots':[],'tables':['candidates','labels','annotations','candidate_evidence','gene_pathways']},
 'downloads':{'plots':[],'tables':[]},
}
# One chart inventory for the original and research questions in each existing section.
from .research_originals import ORIGINAL_PLOTS,ORIGINAL_TABLE_SECTIONS
for section,kinds in ORIGINAL_PLOTS.items():
 SECTIONS[section]['plots']+=kinds
 SECTIONS[section]['tables']+=ORIGINAL_TABLE_SECTIONS.get(section,[])
SECTIONS['phase1']['plots']=['hvg_scatter','original_mean_score','original_top_hvg','original_dropout','hvg_histogram','baseline']
SECTIONS['group_comparison']['plots']=['feature_forest','feature_volcano','original_omics_effect','original_family_heatmap','original_raw_adjusted','adjusted_forest','matching','distribution','sets']

SPECS={
 'feature_forest':('features','forest','effect'),
 'feature_volcano':('features','volcano','effect'),
 'adjusted_forest':('adjusted','forest','beta'),
 'matching':('matching','bar','paired_sign_effect'),
 'sets':('sets','bar','n_members'),
 'baseline':('baseline','bubble','fold_enrichment'),
 'subset':('subset','bubble','fold_enrichment'),
 'within_hvg':('within_hvg','bubble','fold_enrichment'),
 'candidate_ora':('candidate_ora','bubble','fold_enrichment'),
 'feature_function':('feature_pathways','heatmap','effect'),
 'gsea':('gsea','bar','nes'),
 'interactions':('interactions','forest','beta'),
 'within_raw':('within_pathways','forest','effect'),
 'within_adjusted':('within_adjusted','forest','beta'),
 'replication':('replication','bar','jaccard_primary'),
 'feature_stability':('feature_stability','bar','direction_agreement'),
 'set_stability':('set_stability','bar','jaccard_primary'),
 'threshold_stability':('threshold_sensitivity','bar','jaccard_primary'),
 'candidate_priority':('candidates','scatter','hvg_resampling_frequency'),
}

def presentation(run,m,context_id=None):
 """Describe only real per-section capabilities; optional model never gates research."""
 counts={}
 p=run/'summary.json'
 if p.exists():counts=json.loads(p.read_text(encoding='utf-8')).get('tables',{})
 sections={}
 unified=m.get('model_policy')=='removed'
 for key,original_spec in SECTIONS.items():
  spec={k:list(v) for k,v in original_spec.items()}
  if unified:
   removed={'original_classes','original_expected_observed','original_residuals','original_model_associations','original_model_comparison','original_bootstrap','original_candidate_bubble','original_candidate_enrichment'}
   spec['plots']=[x for x in spec['plots'] if x not in removed]
   spec['tables']=[x for x in spec['tables'] if not x.startswith('original_') or x in {'original_input_qc','original_metadata','original_method_status'}]
   if key=='group_comparison':spec['plots']=[x for x in spec['plots'] if x not in {'original_omics_effect','original_family_heatmap','original_raw_adjusted'}]
   if key=='context_patterns':spec['tables']=['workflow_modes','workflow_subsets','workflow_patterns','workflow_members']+spec['tables']
   if key=='downstream':
    spec['tables']+=['candidate_ora','network_status']
    spec['plots']+=['candidate_ora']
   if key=='phase1':spec['tables']+=['workflow_modes']
  primary={'phase1':['labels'],'group_comparison':['features'],'phase2':['feature_pathways','gsea','interactions'],'model_evidence':['replication','feature_stability'],'downstream':['baseline','candidates'],'genes':['labels']}.get(key,spec['tables'])
  n=0
  for t in primary:
   if t not in TABLES:continue
   if context_id:
    import pyarrow.parquet as pq
    for c in m.get('contexts',[]):
     if c['context_id']!=context_id:continue
     path=safe_path(run,c['directory'])/(TABLES[t]+'.parquet')
     if path.exists():n+=pq.ParquetFile(path).metadata.num_rows
     elif (run/(TABLES[t]+'.parquet')).exists():
      dataset=ds.dataset(run/(TABLES[t]+'.parquet'),format='parquet');condition=(ds.field('context_id')==context_id) if 'context_id' in dataset.schema.names else None;n+=dataset.count_rows(filter=condition)
   elif t in counts:n+=int(counts[t].get('rows',0))
   elif (run/(TABLES[t]+'.parquet')).exists():
    import pyarrow.parquet as pq
    n+=pq.ParquetFile(run/(TABLES[t]+'.parquet')).metadata.num_rows
  state='Ready' if n or key in ['overview','downloads'] else 'Unavailable'
  if key=='context_patterns' and len(m.get('contexts',[]))<2:
   state='Not applicable'
   modepath=run/'workflow/modes.parquet'
   if unified and modepath.exists():
    modes=pd.read_parquet(modepath);advanced=modes[modes['mode'].ne('global_hvg')]
    if advanced.status.eq('completed').any():state='Ready'
    if advanced.status.eq('failed').any():state='Partial'
  if m.get('research_status')=='running' and not n:state='Running'
  sections[key]={**spec,'state':state}
 methods={}
 for c in m.get('contexts',[]):
  p=safe_path(run,c['directory'])/'labels/hvg_method_manifest.json'
  if p.exists():methods[c['context_id']]=json.loads(p.read_text(encoding='utf-8'))
 return {'version':VERSION,'context_id':context_id,'sections':sections,'methods':methods,'annotation_snapshot_id':m.get('annotation_snapshot_id'),'data_release_id':m.get('data_release_id'),'method':'Saved official HVG and full-family corrected research tables; plot selection never refits tests','statistics_use_full_tables':True,'legacy_model_independent':True,'model_policy':m.get('model_policy'),'workflow_contract':m.get('workflow_contract'),'plot_integration':{'policy':'Per-chart retention; merge only identical source data, scientific meaning and interactions. Different axes, color semantics, aggregation or candidate branches remain separate.','original_charts':ORIGINAL_PLOTS,'conditional_combination_candidates':['classes','expected_observed','residuals','model_associations','model_comparison','bootstrap'],'merged_optional_model_reason':'Shared run/global rendering profiles retain class-to-gene navigation, identity lines and diagnostics. Full ordered rows, units, coordinates and interaction profiles are compared without rounding; only exact matches are combined. Different saved previews remain separate.'}}

def _read(run,key,params,columns=None):
 from .research_services import read_table
 if columns is None:return read_table(run,key,params)
 path=run/(TABLES[key]+'.parquet')
 if not path.exists():return pd.DataFrame(columns=columns)
 dataset=ds.dataset(path,format='parquet');names=dataset.schema.names;condition=None
 for c in ['context_id','gene_id']:
  if params.get(c) and c in names:
   term=ds.field(c)==str(params[c]);condition=term if condition is None else condition&term
 cols=[c for c in columns if c in names]
 return dataset.to_table(columns=cols,filter=condition).to_pandas()

def _packet(m,kind,rows,**extra):
 return clean({'version':VERSION,'kind':kind,'rows':rows,'status':'ready' if len(rows) else 'not_estimable','reason':None if len(rows) else 'No finite estimates are available in this context. Inspect status and reason in the complete table.','analysis_run_id':m['analysis_run_id'],'annotation_snapshot_id':m.get('annotation_snapshot_id'),'statistics_use_full_tables':True,'statistical_level':'gene-set/feature association, not a gene-level p value','selection_policy':'Full filtered saved table; explicit plot-only reduction; independent of table page/page_size',**extra})

def _finite(frame,value):
 if value not in frame:return frame.iloc[:0]
 return frame[np.isfinite(pd.to_numeric(frame[value],errors='coerce'))].copy()

def _order(frame):
 cols=[c for c in ['q_global','feature_key','term_key','source','scope','model','direction','gene_id'] if c in frame]
 return frame.sort_values(cols,kind='stable',na_position='last') if cols else frame

def visuals(run,m,kind,params):
 from .research_services import coverage,feature_detail
 params=dict(params)
 if params.get('q_max') not in [None,''] and not 0<=float(params['q_max'])<=1:raise ValueError('q_max outside [0,1]')
 if params.get('context_id') and params['context_id'] not in [c['context_id'] for c in m.get('contexts',[])]:raise ValueError('Unknown analysis context')
 # The Core registry's scope='core' is unrelated to F6's all_annotated scope.
 if kind not in ['feature_function','gsea']:params.pop('scope',None)
 if len(m.get('contexts',[]))>1 and not params.get('context_id') and kind not in ['context_coverage','context_effects']:
  raise ValueError('Select context_id for scoped visualizations')
 if kind.startswith('original_'):
  from .research_originals import original_visual
  return original_visual(run,m,kind,params)
 if kind in ['universe','annotation_coverage','context_coverage']:
  records=coverage(run,m)
  if kind!='context_coverage':records=[r for r in records if not params.get('context_id') or r['context_id']==params['context_id']]
  rows=[]
  for r in records:
   if kind=='universe':rows.extend([{'label':'HVG','value':r['H']},{'label':'non-HVG','value':r['N']}])
   elif kind=='annotation_coverage':
    rows=[{'label':'ANY','value':r['annotated_genes'],'fraction':r['annotation_fraction'],'background_n':r['U']}]+[{'label':s,'value':n,'fraction':n/r['U'] if r['U'] else None,'background_n':r['U']} for s,n in r['sources'].items()]
   else:rows.append({'label':r['context_id'],'H':r['H'],'N':r['N'],'annotated_genes':r['annotated_genes'],'U':r['U']})
  return _packet(m,kind,rows,chart_type='stacked' if kind=='context_coverage' else 'bar',x='value',total=sum(r['U'] for r in records),displayed=len(rows),context_id=params.get('context_id'))
 if kind in ['core_disposition','core_omics','core_missingness','eligibility','candidate_tiers','candidate_frequency']:
  key='eligibility' if kind=='eligibility' else 'candidates' if kind=='candidate_tiers' else 'candidate_stability' if kind=='candidate_frequency' else 'core_audit'
  f=_read(run,key,params);total=len(f);rows=[]
  if len(f):
   group='final_status' if kind=='core_disposition' else 'omics' if kind in ['core_omics','core_missingness'] else 'reason' if kind=='eligibility' else 'priority_tier'
   if kind=='core_missingness':
    for omics,g in f.groupby('omics'):
     for field in ['missing_hvg','missing_nonhvg']:
      v=pd.to_numeric(g[field],errors='coerce').dropna() if field in g else pd.Series(dtype=float)
      if len(v):rows.append({'label':omics+' | '+field,'value':float(v.median()),'fields_with_recorded_missingness':len(v),'aggregation':'median field missing fraction'})
   elif kind=='candidate_frequency':
    a=pd.to_numeric(f.get('hvg_resampling_frequency',pd.Series(dtype=float)),errors='coerce').dropna().to_numpy();n,edges=np.histogram(a,bins=np.linspace(0,1,11))
    rows=[{'label':f'{edges[i]:.1f}–{edges[i+1]:.1f}','value':int(n[i])} for i in range(len(n))]
   elif group in f:rows=[{'label':str(k),'value':int(v)} for k,v in f.groupby(group,dropna=False).size().items()]
  return _packet(m,kind,rows,chart_type='bar',source_table=key,x='value',total=total,displayed=len(rows),aggregation='median missing fraction across fields' if kind=='core_missingness' else 'counts over the complete filtered table')
 if kind=='mapping_coverage':
  f=_read(run,'mapping',params);rows=[]
  if len(f) and all(k in f for k in ['omics','mapping_status','expression_gene_id']):
   rows=[{'label':str(o)+' | '+str(s),'value':int(g.expression_gene_id.nunique()),'omics':o,'mapping_status':s} for (o,s),g in f.groupby(['omics','mapping_status'])]
  return _packet(m,kind,rows,chart_type='bar',source_table='mapping',total=len(f),displayed=len(rows),unit='Genes per omics and mapping status')
 if kind=='baseline_stability':
  f=_read(run,'baseline_stability',params);r=_read(run,'replication',params);rows=[]
  if len(f) and 'kind' in r and 'run_id' in f and 'q_within_sensitivity_run' in f:
   f=f[f.run_id.isin(r.loc[r.kind.eq('technical_cell_resampling'),'run_id'])]
   for term,g in f.groupby('term_key'):
    rows.append({'label':g.term_name.iloc[0] if 'term_name' in g else term,'term_key':term,'value':float(g.q_within_sensitivity_run.lt(.05).mean()),'technical_runs':g.run_id.nunique(),'mean_fold':float(g.fold_enrichment.mean()) if 'fold_enrichment' in g else None,'statistical_scope':'Saved per-sensitivity-run BH q<0.05, descriptive pass frequency, not new global q'})
   rows=sorted(rows,key=lambda r:(-r['value'],r['term_key']))[:30]
  return _packet(m,kind,rows,chart_type='bar',source_table='baseline_stability',total=len(f),displayed=len(rows),unit='Technical resample pass frequency (per-run BH q<0.05)')
 if kind in ['hvg_scatter','hvg_histogram']:
  f=_read(run,'labels',params,columns=['gene_id','gene_name','is_hvg','mean_expr','hvg_score','hvg_rank','hvg_score_semantics']);f=_finite(_finite(f,'hvg_score'),'mean_expr');total=len(f)
  if kind=='hvg_histogram':
   rows=[]
   if len(f):
    a=f.hvg_score.to_numpy(float);lo,hi=np.quantile(a,[0,1]);hi=hi if hi>lo else lo+1;edges=np.linspace(lo,hi,31)
    for flag,g in f.groupby('is_hvg'):
     n,_=np.histogram(g.hvg_score.to_numpy(float),bins=edges)
     rows.extend({'label':float((edges[i]+edges[i+1])/2),'value':int(n[i]),'group':'HVG' if flag else 'non-HVG','bin_left':edges[i],'bin_right':edges[i+1]} for i in range(len(n)))
   return _packet(m,kind,rows,chart_type='histogram',x='hvg_score',total=total,displayed=len(rows),source_table='labels')
  parts=[]
  for _,g in f.groupby('is_hvg'):
   g=g.sort_values('gene_id',kind='stable');parts.append(g.iloc[np.linspace(0,len(g)-1,min(2000,len(g))).astype(int)])
  selected=pd.concat(parts,ignore_index=True) if parts else f
  return _packet(m,kind,selected.to_dict('records'),chart_type='scatter',x='mean_expr',y='hvg_score',total=total,displayed=len(selected),source_table='labels',selection_policy='Deterministic gene-ID-spaced preview up to 2000 per H/N group, complete statistics unchanged')
 if kind=='distribution':
  key=params.get('feature_key')
  if not key:
   f=_read(run,'features',{k:v for k,v in params.items() if k not in ['term_key','source','scope','direction']});f=_finite(f,'effect');key=_order(f).feature_key.iloc[0] if len(f) else None
  if not key:return _packet(m,kind,[],chart_type='boxplot')
  labels=_read(run,'labels',params,columns=['gene_id','is_hvg']);values=_read(run,'values',params,columns=['gene_id',key])
  if key not in values:return _packet(m,kind,[],chart_type='boxplot',feature_key=key)
  data=values.merge(labels,on='gene_id',validate='one_to_one');rows=[]
  for flag,g in data.groupby('is_hvg'):
   a=pd.to_numeric(g[key],errors='coerce').dropna().to_numpy()
   if len(a):
    q=np.quantile(a,[0,.05,.25,.5,.75,.95,1]);rows.append({'group':'HVG' if flag else 'non-HVG','n':len(a),'minimum':q[0],'q05':q[1],'q25':q[2],'median':q[3],'q75':q[4],'q95':q[5],'maximum':q[6]})
  return _packet(m,kind,rows,chart_type='boxplot',feature_key=key,total=len(data),displayed=len(rows),source_table='values + labels',whiskers='5th–95th percentiles; min/max in source data',unit='prepared canonical feature value; no separate group standardization')
 if kind=='context_effects':
  f=_read(run,'features',{k:v for k,v in params.items() if k!='context_id'});f=_finite(f,'effect');keys=_order(f).feature_key.drop_duplicates().head(12) if len(f) else []
  g=f[f.feature_key.isin(keys)] if len(f) else f
  if len(m.get('contexts',[]))<2:return _packet(m,kind,[],chart_type='heatmap',reason='Only the global context was declared. No independent group results are available; cell-type or donor differences cannot be inferred.')
  return _packet(m,kind,g.to_dict('records'),chart_type='context_heatmap',total=len(f),displayed=len(g),source_table='features',x='feature_key',y='context_id',value='effect')
 if kind not in SPECS:raise ValueError('Unknown integrated visual kind')
 key,chart,value=SPECS[kind]
 if kind in ['feature_function','gsea'] and not params.get('scope'):params['scope']='all_annotated'
 # Model-specific rows must not be silently mixed in the same axis.
 f=_read(run,key,params)
 if kind=='adjusted_forest' and 'model' in f:
  model=params.get('model') or 'expression_detection_length';f=f[f.model.eq(model)]
 total=len(f);all_status=f.status.value_counts(dropna=False).to_dict() if 'status' in f else {}
 f=_finite(f,value)
 if 'alias_of' in f:f=f[f.alias_of.fillna('').eq('')]
 if chart=='heatmap':
  if len(f) and not params.get('source'):
   # One source/scope per grid avoids collapsing similarly named terms.
   src=_order(f).source.iloc[0];f=f[f.source.eq(src)]
  else:src=params.get('source')
  ordered=_order(f);features=ordered.feature_key.drop_duplicates().head(12) if len(f) else [];terms=ordered.term_key.drop_duplicates().head(14) if len(f) else []
  g=f[f.feature_key.isin(features)&f.term_key.isin(terms)] if len(f) else f
  return _packet(m,kind,g.to_dict('records'),chart_type=chart,source_table=key,total=total,estimable=len(f),displayed=len(g),scope=params.get('scope'),source=src,x='feature_key',y='term_key',value=value,status_counts=all_status)
 if kind=='set_stability' and len(f):
  f=f.groupby(['feature_key','direction'],as_index=False).agg(jaccard_primary=('jaccard_primary','mean'),runs=('jaccard_primary','count'));f['aggregation']='mean Jaccard over saved sensitivity runs'
 if kind=='candidate_priority':
  f=f.sort_values('priority_rank',kind='stable') if 'priority_rank' in f else f
  g=f.iloc[np.linspace(0,len(f)-1,min(1500,len(f))).astype(int)] if len(f) else f
 elif kind=='feature_volcano':g=_order(f)
 elif kind=='feature_stability' and len(f):g=f.sort_values(['direction_agreement','feature_key'],ascending=[True,True]).head(30)
 elif kind=='replication':g=f
 else:g=_order(f).head(30)
 if chart=='forest' and value=='beta' and len(g):
  g=g.copy()
  # Saved beta CI is in odds-ratio units; avoid mixing odds and log odds.
  g['plot_ci_low']=np.log(g.ci_low.where(g.ci_low.gt(0))) if 'ci_low' in g else np.nan
  g['plot_ci_high']=np.log(g.ci_high.where(g.ci_high.gt(0))) if 'ci_high' in g else np.nan
 elif chart=='forest' and len(g):g=g.assign(plot_ci_low=g.get('ci_low'),plot_ci_high=g.get('ci_high'))
 columns=[c for c in g if c not in ['overlap_genes','balance']]
 return _packet(m,kind,g[columns].to_dict('records'),chart_type=chart,source_table=key,total=total,estimable=len(f),displayed=len(g),value=value,status_counts=all_status,scope=params.get('scope'),unit='log odds ratio per prepared-feature scale' if value=='beta' else 'dimensionless effect' if value in ['effect','paired_sign_effect'] else value,selection_policy='All estimable rows for volcano; full sensitivity records; otherwise smallest saved global-q 30 with stable identifiers, or explicitly spaced candidate preview. No page/page_size dependency.')
