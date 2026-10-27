"""Original HVG views restored from the selected run's persisted evidence.

Presentation only: no HVG refit, new p values, annotation substitution or model fit.
Each original question has its own capability and a specific missing-data reason.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from backend.analysis_engine.hvg_research.artifacts import clean

ORIGINAL_PLOTS={
 'overview':['original_workflow'],
 'input_qc':['original_mapping_quality'],
 'phase1':['original_mean_score','original_top_hvg','original_dropout'],
 'context_patterns':['original_pattern_counts','original_subset_counts'],
 'group_comparison':['original_omics_effect','original_family_heatmap','original_raw_adjusted'],
 'phase2':['original_classes','original_expected_observed','original_residuals','original_model_associations'],
 'model_evidence':['original_model_comparison','original_bootstrap'],
 'downstream':['original_candidate_bubble','original_candidate_enrichment'],
 'genes':[], 'downloads':[]}

# Fixed run-relative, read-only paths. Never follow absolute paths in old JSON manifests.
ORIGINAL_TABLES={
 'original_method_status':'work/visualization/backend_status_table.csv',
 'original_input_qc':'work/standardized/input_validation_report.json',
 'original_metadata':'work/standardized/standardized_h5ad_report.json',
 'original_model_comparison':'work/analysis_phase2/model_comparison.csv',
 'original_bootstrap':'work/analysis_phase2/bootstrap_feature_stability.csv',
 'original_model_scores':'work/analysis_phase2/hvg_stoich_scores.csv',
 'original_model_associations':'work/analysis_phase2/feature_associations.csv',
 'original_negative_controls':'work/analysis_phase2/negative_control_report.json',
 'original_evidence':'work/analysis_phase2/evidence_assessment.json',
 'original_candidate_components':'work/downstream/candidate_score_components.csv',
 'original_candidate_ora':'work/downstream/functional_enrichment_top_terms.csv',
 'original_candidate_ora_full':'work/downstream/enrichment_ora.csv',
 'original_candidate_gsea':'work/downstream/gsea_prerank_results.csv',
 'original_ppi':'work/downstream/ppi_module_enrichment.csv',
 'original_enrichment_summary':'work/downstream/functional_enrichment_summary.json',
}
ORIGINAL_TABLE_SECTIONS={
 'input_qc':['original_input_qc','original_metadata'],
 'phase1':['original_method_status'],
 'phase2':['original_model_scores','original_model_associations'],
 'model_evidence':['original_model_comparison','original_bootstrap','original_negative_controls','original_evidence'],
 'downstream':['original_candidate_components','original_candidate_ora','original_candidate_ora_full','original_candidate_gsea','original_ppi','original_enrichment_summary'],
 'genes':['original_model_scores','original_candidate_components']}
GLOBAL_ONLY=set(ORIGINAL_TABLES)-{'original_input_qc','original_metadata','original_method_status'}

def original_table(run,key,params=None):
 params=params or {}
 if key in GLOBAL_ONLY and params.get('context_id','global')!='global':return pd.DataFrame([{'status':'not_applicable','reason':'The saved prediction/downstream branch applies to global only. Select global to inspect it.'}])
 path=run/ORIGINAL_TABLES[key]
 if not path.exists():return pd.DataFrame([{'status':'not_generated','reason':'This run did not save '+ORIGINAL_TABLES[key]}])
 if path.suffix=='.csv':
  try:f=pd.read_csv(path,engine='python')
  except pd.errors.EmptyDataError:f=pd.DataFrame()
 else:
  data=json.loads(path.read_text(encoding='utf-8'))
  f=pd.DataFrame(data) if isinstance(data,list) else pd.DataFrame([data])
 if f.empty:return pd.DataFrame([{'status':'no_saved_rows','reason':'The saved output contains no rows. Inspect the model or downstream status for the reason.'}])
 for col in f.select_dtypes(include=['object']).columns:
  f[col]=f[col].map(lambda v:json.dumps(clean(v),ensure_ascii=False) if isinstance(v,(dict,list)) else v)
 return f

def _json(run,rel):
 p=run/rel
 return json.loads(p.read_text(encoding='utf-8')) if p.is_file() else {}

def _csv(run,rel):
 p=run/rel
 if not p.is_file():return pd.DataFrame()
 try:return pd.read_csv(p,engine='python')
 except pd.errors.EmptyDataError:return pd.DataFrame()

def _finite(f,*cols):
 if any(c not in f for c in cols):return f.iloc[:0]
 return f[np.logical_and.reduce([np.isfinite(pd.to_numeric(f[c],errors='coerce')) for c in cols])].copy()

def _preview(f,limit=2000):
 if len(f)<=limit:return f
 if 'gene_id' in f:f=f.sort_values('gene_id',kind='stable')
 return f.iloc[np.linspace(0,len(f)-1,limit).astype(int)]

def original_visual(run,m,kind,params):
 from .research_services import read_table
 from .research_visuals import _packet
 # Function/source/direction/q filters do not redefine input diagnostics or model outputs.
 context=params.get('context_id') or 'global';ctx={'context_id':context}
 def read(key):return read_table(run,key,ctx)
 rows=[];chart='bar';extra={'origin':'original_workflow','context_id':context}
 def packet(f,typ,reason=None,**kw):
  records=f.to_dict('records') if isinstance(f,pd.DataFrame) else f
  return _packet(m,kind,records,chart_type=typ,total=kw.pop('total',len(records)),displayed=len(records),reason=reason if not records else None,**extra,**kw)
 model_kinds={'original_classes','original_expected_observed','original_residuals','original_model_associations','original_model_comparison','original_bootstrap','original_candidate_bubble','original_candidate_enrichment'}
 if kind in model_kinds:
  if m.get('model_policy')=='removed':return packet([],'original_unavailable','Predictive modeling and model-derived candidate scoring are removed from this workflow.')
  if context!='global':return packet([], 'original_unavailable','The saved prediction and candidate-score branch is global only. Select global to inspect this original result.')
  model=_json(run,'work/analysis_phase2/hvg_stoich_model.json');summary=_json(run,'work/analysis_phase2/hvg_summary.json');plots=_json(run,'work/analysis_phase2/plots_payload.json')
  tables=_json(run,'work/visualization/tables_payload.json')
  def table(name,rel=None):
   f=_csv(run,rel) if rel else pd.DataFrame()
   if not f.empty:return f
   values=tables.get(name,{})
   return pd.DataFrame(values.get('rows',[]) if isinstance(values,dict) else values or [])
  reason=summary.get('phase2_skip_reason') or summary.get('skip_reason') or model.get('skip_reason') or {}
  if isinstance(reason,dict):reason=reason.get('reason_message') or reason.get('message') or reason.get('reason')
  reason=reason or ('The optional prediction branch is '+str(m.get('model_status') or 'not run')+'. No finite saved values are available for this chart.')
  if kind=='original_classes':
   f=pd.DataFrame(plots.get('class_bar') or [])
   if f.empty:f=table('hvg_stoich_class_table')
   f=_finite(f,'count');rows=[{**r,'label':r.get('stoich_class'),'value':r['count']} for r in f.to_dict('records')]
   return packet(rows,'bar',reason,unit='Genes',source_table='original_model_scores',value='value',interaction='class_to_gene_filter')
  if kind=='original_expected_observed':
   f=pd.DataFrame(plots.get('expected_observed_scatter') or []);f=_finite(f,'stoich_expected_var','observed_hvg_signal')
   return packet(_preview(f),'original_scatter',reason,total=len(f),x='stoich_expected_var',y='observed_hvg_signal',x_label='Expected HVG signal',y_label='Observed HVG signal',identity_line=True,source_table='original_model_scores')
  if kind=='original_residuals':
   f=table('signal_residual_table','work/analysis_phase2/hvg_stoich_scores.csv');f=_finite(f,'stoich_excess_var')
   if f.empty:f=_finite(pd.DataFrame(plots.get('residual_scatter') or []),'stoich_excess_var')
   if len(f):
    counts,edges=np.histogram(f.stoich_excess_var,bins=24);rows=[{'label':float((edges[i]+edges[i+1])/2),'value':int(counts[i]),'bin_left':float(edges[i]),'bin_right':float(edges[i+1])} for i in range(24)]
   return packet(rows,'original_histogram',reason,total=len(f),x_label='Prediction residual',source_table='original_model_scores')
  if kind=='original_model_associations':
   f=table('feature_associations_table','work/analysis_phase2/feature_associations.csv')
   if f.empty:f=pd.DataFrame(plots.get('feature_association_top') or [])
   f=_finite(f,'cliffs_delta');f=f.head(16)
   return packet([{**r,'label':r.get('feature') or r.get('feature_key'),'value':r['cliffs_delta']} for r in f.to_dict('records')],'bar',reason,value='value',unit="Model-branch Cliff's delta",source_table='original_model_associations')
  if kind in ['original_model_comparison','original_bootstrap']:
   key='model_comparison' if kind=='original_model_comparison' else 'bootstrap_feature_stability'
   f=table(key+'_table','work/analysis_phase2/'+key+'.csv')
   if f.empty:f=pd.DataFrame(model.get(key) or [])
   metrics=['cv_r2','r2','roc_auc','mae','rmse','mean_score'] if key=='model_comparison' else ['selection_frequency','mean_abs_importance','sign_stability','frequency','stability']
   metric=next((c for c in metrics if not _finite(f,c).empty),None)
   if metric:f=_finite(f,metric)
   else:f=f.iloc[:0]
   return packet([{**r,'label':r.get('model_id') or r.get('model') or r.get('feature') or r.get('feature_key') or r.get('model_name'),'value':r[metric]} for r in f.to_dict('records')],'bar',reason,value='value',unit=metric or 'Model metric',source_table='original_model_comparison' if key=='model_comparison' else 'original_bootstrap')
  if kind=='original_candidate_bubble':
   f=table('candidate_score_components_table','work/downstream/candidate_score_components.csv');f=_finite(f,'stoich_excess_component','rank_component','candidate_score')
   return packet(_preview(f),'original_scatter','Candidate-score components were not saved as finite residual, rank and score values. They are not replaced with the research evidence priority.',total=len(f),x='stoich_excess_component',y='rank_component',size='candidate_score',x_label='Residual score component',y_label='Rank score component',source_table='original_candidate_components')
  f=table('functional_enrichment_top_terms_table','work/downstream/functional_enrichment_top_terms.csv')
  if f.empty:f=table('enrichment_summary_table','work/downstream/enrichment_ora.csv')
  if 'status' in f:f=f[f.status.eq('generated')]
  q=next((k for k in ['fdr_bh','fdr','q_value','p_value'] if k in f),None)
  f=_finite(f,q) if q else f.iloc[:0]
  if len(f):f=f.sort_values(q,kind='stable').head(30)
  return packet([{**r,'original_q':r[q],'q_field':q} for r in f.to_dict('records')],'original_enrichment','No finite candidate-score ORA terms were saved. Baseline HVG and feature-subset enrichment are distinct analyses shown elsewhere in this module.',source_table='original_candidate_ora',scope='candidate_score_branch')
 if kind=='original_workflow':
  rows=[{'label':name,'value':float(rec.get('seconds') or 0),'execution_status':rec.get('execution_status'),'scientific_status':rec.get('scientific_status'),'reason':rec.get('reason')} for name,rec in m.get('stages',{}).items()]
  return packet(rows,'original_status','No stage execution records were saved.',unit='Elapsed seconds')
 if kind=='original_mapping_quality':
  f=read('mapping')
  if len(f) and {'omics','mapping_status','expression_gene_id'}<=set(f):
   for omics,g in f.groupby('omics'):
    total=g.expression_gene_id.nunique()
    for status,s in g.groupby('mapping_status'):
     n=s.expression_gene_id.nunique();rows.append({'label':str(omics)+' | '+str(status),'value':100*n/total if total else None,'gene_count':n,'denominator':total,'omics':omics,'mapping_status':status})
  return packet(rows,'bar','No per-gene mapping records were saved for this context.',unit='Expression gene IDs (%)',value='value',source_table='mapping')
 if kind in ['original_mean_score','original_top_hvg','original_dropout']:
  f=read('labels')
  if kind=='original_top_hvg':
   if 'is_hvg' in f:f=f[f.is_hvg.eq(True)]
   f=_finite(f,'hvg_rank','hvg_score');total=len(f)
   if len(f):f=f.sort_values(['hvg_rank','gene_id'],kind='stable').head(20)
   return packet([{**r,'label':r['gene_id'],'value':r['hvg_score']} for r in f.to_dict('records')],'bar','No standard HVG ranks and finite method scores were saved.',total=total,value='value',unit='Official HVG score',source_table='labels')
  if kind=='original_dropout':
   f=_finite(f,'hvg_rank','pct_cells_detected','dropout_rate')
   if 'is_hvg' in f:f=f[f.is_hvg.eq(True)]
   if len(f):f=f.sort_values(['hvg_rank','gene_id'],kind='stable').head(80)
   return packet(f,'original_scatter','Detection fraction and dropout rate were not recorded in the standard labels; missing values are not imputed.',x='pct_cells_detected',y='dropout_rate',x_label='Cells detected (recorded fraction)',y_label='Dropout rate',source_table='labels')
  f=_finite(f,'mean_expr','hvg_score')
  return packet(_preview(f,4000),'original_scatter','No finite expression means and official HVG scores were saved.',total=len(f),x='mean_expr',y='hvg_score',x_label='Mean expression (linear)',y_label='Official HVG score',source_table='labels',descriptive_trends=True)
 if kind in ['original_pattern_counts','original_subset_counts']:
  if m.get('model_policy')=='removed':
   key='workflow_patterns' if kind=='original_pattern_counts' else 'workflow_subsets'
   f=read_table(run,key,{})
   if kind=='original_pattern_counts' and {'pattern','count'}<=set(f):
    f=f.dropna(subset=['pattern','count']);rows=[{**r,'label':str(r['mode'])+' | '+str(r['pattern']),'value':r['count']} for r in f.to_dict('records')]
   elif kind=='original_subset_counts' and {'mode','label','n_hvgs'}<=set(f):
    f=f[pd.to_numeric(f.n_hvgs,errors='coerce').notna()];rows=[{**r,'label':str(r['mode'])+' | '+str(r['label']),'value':r['n_hvgs']} for r in f.to_dict('records')]
   return packet(rows,'bar','No applicable metadata modes produced finite pattern/subset counts. Inspect mode status, metadata requirements and skipped reasons.',unit='Genes' if kind=='original_pattern_counts' else 'HVGs',value='value',source_table=key)
  contexts=m.get('contexts',[])
  if kind=='original_subset_counts':
   from .research_services import coverage
   contexts=coverage(run,m)
   rows=[{'label':c['context_id'],'value':c.get('H'),'n_genes':c.get('U'),'n_nonhvg':c.get('N'),'n_cells':c.get('n_cells')} for c in contexts]
   return packet(rows,'bar','No saved subset summaries are available.',unit='HVGs',value='value',source_table='universes')
  for c in contexts:
   p=run/c['directory']/'labels/hvg_method_manifest.json'
   if p.exists():
    v=json.loads(p.read_text(encoding='utf-8'));rows.append({'label':c['context_id'],'value':v.get('cells_after'),'n_cells_before':v.get('cells_before')})
  reason='Only a global HVG analysis was declared. Condition/timecourse/trajectory pattern categories were not computed; no categories are inferred from library suffixes.'
  if len(contexts)<2:return packet([],'bar',reason,unit='Cells',value='value')
  return packet([r for r in rows if r['value'] is not None],'bar','Per-context cell counts were not saved.',unit='Cells',value='value',source_table='universes')
 if kind in ['original_omics_effect','original_family_heatmap','original_raw_adjusted']:
  f=read_table(run,'features',{k:v for k,v in params.items() if k not in ['scope','source','term_key','direction']});f=_finite(f,'effect','q_global')
  if kind=='original_omics_effect':return packet(f,'original_omics_volcano','No finite saved feature effects and global q values are available.',source_table='features')
  if kind=='original_family_heatmap':
   if {'omics','family'}<=set(f):
    for (omics,family),g in f.groupby(['omics','family']):rows.append({'omics':omics,'family':family,'median_effect':float(g.effect.median()),'tested_fields':len(g),'significant_fields':int(g.q_global.lt(.05).sum())})
   return packet(rows,'original_family_heatmap','No tested features with recorded omics and family labels are available.',source_table='features',aggregation='Descriptive median of saved feature effects; no family-level test or FDR is refit')
  a=read_table(run,'adjusted',{k:v for k,v in params.items() if k not in ['scope','source','term_key','direction','q_max']})
  if 'model' in a:a=a[a.model.eq('expression_detection_length')]
  a=_finite(a,'beta')
  if len(f) and len(a):
   g=f.merge(a[[k for k in ['feature_key','beta','q_global','scale','model'] if k in a]],on='feature_key',suffixes=('','_adjusted'));rows=g.to_dict('records')
  return packet(rows,'original_raw_adjusted','No paired raw effect and covariate-adjusted coefficient was estimable in this context.',source_table='adjusted',x_label="Raw Cliff's delta",y_label='Adjusted log odds ratio')
 raise ValueError('Unknown original workflow chart')
