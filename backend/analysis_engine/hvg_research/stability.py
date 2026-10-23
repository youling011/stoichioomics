from .runtime import *
import anndata as ad,scanpy as sc
L=load('labels/hvg_labels');genes=L.gene_id.to_numpy(str);H=L.is_hvg.to_numpy(bool);a=ad.read_h5ad(ROOT/'labels/filtered_counts.h5ad')
P=load('features/feature_values').set_index('gene_id').reindex(genes);e=load('features/feature_evidence_summary');keys=e.loc[e.alias_of.eq(''),'feature_key'].tolist()
hv_cfg=DESIGN['phase1_analysis'];method=hv_cfg['hvg_method'];ntop=int(hv_cfg['n_top_genes']);batch=hv_cfg.get('batch_key');donor=CFG['validation']['donor_key'];rng=np.random.default_rng(SEED)
plans=[]
for factor in CFG['validation']['top_n_factors']:plans.append((f'top_{factor}','parameter',max(1,min(a.n_vars,int(ntop*factor))),np.arange(a.n_obs)))
if batch:
 for b in sorted(a.obs[batch].astype(str).unique()):plans.append(('library_'+b,'library_sensitivity',ntop,np.flatnonzero(a.obs[batch].astype(str).to_numpy()==b)))
if donor and donor in a.obs and a.obs[donor].nunique()>=2:
 for d in sorted(a.obs[donor].astype(str).unique()):plans.append(('donor_leave_out_'+d,'leave_one_declared_donor_out',ntop,np.flatnonzero(a.obs[donor].astype(str).to_numpy()!=d)))
for q in range(CFG['validation']['cell_resamples']):
 cells=[]
 for _,frame in a.obs.groupby(batch,observed=True) if batch else [('all',a.obs)]:
  ids=a.obs_names.get_indexer(frame.index);cells.extend(rng.choice(ids,max(3,int(CFG['validation']['cell_fraction']*len(ids))),replace=False))
 plans.append(('resample_'+str(q+1),'technical_cell_resampling',ntop,np.sort(cells)))
runs=[];lr=[];fr=[];sets=[]
primary_sets=load('gene_sets/gene_sets').set_index(['feature_key','direction'])
for rid,kind,n,indices in plans:
 check_cancel();b=a[indices].copy()
 if b.n_obs<3:runs.append({'run_id':rid,'kind':kind,'status':'insufficient_cells'});continue
 kw={'flavor':method,'n_top_genes':min(n,b.n_vars),'inplace':False,'batch_key':None if kind=='library_sensitivity' else batch}
 if method.startswith('seurat_v3'):kw['span']=hv_cfg.get('loess_span',.3)
 else:kw['n_bins']=hv_cfg.get('n_bins',20)
 try:h=sc.pp.highly_variable_genes(b,**kw).highly_variable.to_numpy(bool)
 except Exception as exc:runs.append({'run_id':rid,'kind':kind,'status':'failed','reason':str(exc)});continue
 union=int((H|h).sum());runs.append({'run_id':rid,'kind':kind,'status':'completed','n_cells':b.n_obs,'n_top_genes':n,'H':int(h.sum()),'jaccard_primary':int((H&h).sum())/union if union else None,'interpretation':'declared donor sensitivity, not external dataset validation' if kind=='leave_one_declared_donor_out' else 'technical/parameter sensitivity'})
 lr.extend({'run_id':rid,'gene_id':g,'is_hvg':bool(v),'kind':kind} for g,v in zip(genes,h))
 for k in keys:
  v=P[k].to_numpy(float);ok=np.isfinite(v);r=rank_test(v[ok&h],v[ok&~h]);d=e.set_index('feature_key').loc[k,'effect']
  fr.append({'run_id':rid,'kind':kind,'feature_key':k,'direction_agrees_primary':np.sign(r.get('effect',np.nan))==np.sign(d),**r})
  # Primary discovery threshold is frozen for replication.
  for direction in ['low','high']:
   th=primary_sets.loc[(k,direction),'threshold'];mask=h&ok&((v<=th) if direction=='low' else (v>=th));orig=H&ok&((v<=th) if direction=='low' else(v>=th));u=(mask|orig).sum()
   sets.append({'run_id':rid,'feature_key':k,'direction':direction,'n_genes':int(mask.sum()),'jaccard_primary':float((mask&orig).sum()/u) if u else np.nan,'threshold_policy':'frozen_discovery_threshold'})
 log('stability',rid)
lr=pd.DataFrame(lr,columns=['run_id','gene_id','is_hvg','kind']);fr=pd.DataFrame(fr)
if len(fr):
 fr['q_within_sensitivity_run']=np.nan
 for _,ids in fr.groupby('run_id').groups.items():fr.loc[ids,'q_within_sensitivity_run']=fdr(fr.loc[ids,'p_value'])
tech=lr[lr.kind.eq('technical_cell_resampling')]
freq=tech.groupby('gene_id').is_hvg.mean().rename('hvg_resampling_frequency').reset_index()
sf=fr[fr.kind.eq('technical_cell_resampling')].groupby('feature_key').agg(direction_agreement=('direction_agrees_primary','mean'),effect_mean=('effect','mean'),effect_sd=('effect','std')).reset_index() if len(fr) else pd.DataFrame(columns=['feature_key','direction_agreement','effect_mean','effect_sd'])
for name,df in [('replication_runs',pd.DataFrame(runs)),('replication_labels',lr),('feature_sensitivity',fr),('feature_stability',sf),('gene_hvg_stability',freq),('set_stability',pd.DataFrame(sets))]:save('stability/'+name,df)
write_json('stability/validation_scope.json',{'independent_dataset_validation':False,'declared_donor_leave_one_out':bool(donor and donor in a.obs and a.obs[donor].nunique()>=2),'donor_key':donor,'cell_resamples':CFG['validation']['cell_resamples'],'thresholds_frozen_from_discovery':True,'interpretation':'Resampling is technical stability, not independent biological validation'})

# Predeclared alternate quantiles never choose the primary discovery threshold.
alternate=[]
for k in keys:
 v=P[k].to_numpy(float);ok=np.isfinite(v);ref=v[ok&~H]
 if not len(ref):continue
 for direction,q in [('low',.25),('high',.75)]:
  th=float(np.quantile(ref,q));mask=H&ok&((v<=th) if direction=='low' else (v>=th));main=primary_sets.loc[(k,direction),'threshold'];orig=H&ok&((v<=main) if direction=='low' else(v>=main));union=(mask|orig).sum()
  alternate.append({'feature_key':k,'direction':direction,'alternative_quantile':q,'threshold':th,'n_members':int(mask.sum()),'jaccard_primary':float((mask&orig).sum()/union) if union else np.nan,'interpretation':'Predeclared threshold sensitivity, not independent validation'})
save('stability/threshold_sensitivity',alternate)
from .enrichment import ora
A=load('annotations/gene_term_membership');T=load('annotations/terms');baseline=[]
for rid,g in lr.groupby('run_id'):
 h=set(g.loc[g.is_hvg,'gene_id'])
 for source,ann in A.groupby('source'):
  bg=set(ann.gene_id)&set(genes);f=ora(h&bg,bg,A,T[T.source.eq(source)],min_term=TERM_MIN,max_term=TERM_MAX,min_query=MIN_QUERY,fields={'run_id':rid,'family_id':'F3_sensitivity'});baseline.append(f)
br=pd.concat(baseline,ignore_index=True) if baseline else pd.DataFrame(columns=['run_id','p_value'])
br['q_within_sensitivity_run']=np.nan
for _,indices in br.groupby('run_id').groups.items():br.loc[indices,'q_within_sensitivity_run']=fdr(br.loc[indices,'p_value'])
save('stability/baseline_enrichment_stability',br)
