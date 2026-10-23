"""Typed, explicit source-missing outcomes; no fake p=1 for unperformed tests."""
from pathlib import Path
import json,pandas as pd,numpy as np
from .catalog import TABLES
from .artifacts import atomic_frame,atomic_json
COMMON=['feature_key','gene_id','term_key','term_name','source','scope','set_id','direction','status','p_value','q_global','q_global_by','effect','ci_low','ci_high','n1','n0','alias_of','family','omics','redundancy_group','beta','model','paired_sign_effect','strong_raw','adjusted_supported','adjusted_q','matching_direction_agrees','run_id','priority_tier','hvg_resampling_frequency','priority_rank','gene_name','support_type','fold_enrichment']
def empty_stage(root,stage,reason):
 root=Path(root);L=pd.read_parquet(root/'labels/hvg_labels.parquet')
 selections={'feature_analysis':['feature_tests','features','adjusted','matching','matching_members','values','model_values','redundancy'],
 'pathway_analysis':['sets','set_members','gene_features','matched_baseline','subset','within_hvg','enrichment_comparison','feature_pathways','interactions','within_pathways','within_adjusted'],
 'gsea':['gsea','gsea_runs','ranked_genes','leading_edge'],
 'stability':['replication','feature_stability','candidate_stability','set_stability'],
 'candidates':['candidates','candidate_evidence','gene_pathways'],
 'supplementary':['adjusted_sets','joint_sets','supplementary_ora','categorical_tests']}
 for key in selections[stage]:
  rel=TABLES[key];f=pd.DataFrame(columns=COMMON)
  if key in ['values','model_values']:f=L[['gene_id']].copy()
  atomic_frame(root/(rel+'.parquet'),f)
 if stage=='feature_analysis':
  reg=json.loads((root/'core/registry_snapshot.json').read_text(encoding='utf-8'));rows=[]
  for s in reg['fields']:
   if s.get('scope')=='core':rows.append({**s,'feature_key':s['omics']+'::'+s['field'],'final_status':'missing_source' if reason=='source_missing' else 'qc_failed','reason':reason,'semantic_review_status':'not_tested','n_hvg':0,'n_nonhvg':0})
  atomic_frame(root/'core/core_feature_audit.parquet',pd.DataFrame(rows))
  atomic_json(root/'features/feature_keys.json',[]);atomic_json(root/'features/transform_manifest.json',{'status':reason,'transforms':[]})
 if stage=='stability':
  atomic_frame(root/'stability/gene_hvg_stability.parquet',pd.DataFrame({'gene_id':L.gene_id,'hvg_resampling_frequency':np.nan}));atomic_json(root/'stability/validation_scope.json',{'status':reason,'independent_dataset_validation':False})
 atomic_json(root/'reports'/(stage+'_unavailable.json'),{'execution_status':'completed','scientific_status':reason,'reason':reason})
