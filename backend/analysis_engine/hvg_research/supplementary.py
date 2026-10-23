"""Predeclared residual and family-balanced joint sets, separate inference families."""
from .runtime import *
from .enrichment import ora
L=load('labels/hvg_labels');genes=L.gene_id.to_numpy(str);H=L.is_hvg.to_numpy(bool);P=load('features/feature_values').set_index('gene_id').reindex(genes);X=load('core/context');E=load('features/feature_evidence_summary');A=load('annotations/gene_term_membership');T=load('annotations/terms');audit=load('core/core_feature_audit')
rows=[];mrows=[];orows=[];categories=[]
term_index={t:set(g.gene_id) for t,g in A.groupby('term_key')}
expr=zscore(np.log1p(L.mean_expr));det=zscore(L.pct_cells_detected);votes={}
for k in E.loc[E.alias_of.eq(''),'feature_key']:
 check_cancel();a=P[k].to_numpy(float);ok=np.isfinite(a);meta=E.set_index('feature_key').loc[k];omics=meta.omics
 lengthcol={'genome':'genome__locus_length_bp','transcriptome':'transcriptome__length_nt_total','proteome':'proteome__length_aa'}[omics]
 length=pd.to_numeric(X.get(lengthcol,pd.Series(np.nan,index=X.index)),errors='coerce').to_numpy(float)
 cov=np.column_stack([np.ones(len(a)),expr,det]+([] if k.endswith(('::locus_length_bp','::length_nt_total','::length_aa')) or not np.isfinite(length).any() else [zscore(np.log1p(length))]))
 fit=ok&np.isfinite(cov).all(1);residual=np.full(len(a),np.nan)
 if fit.sum()>=2*MIN_N and np.linalg.matrix_rank(cov[fit])==cov.shape[1]:residual[fit]=a[fit]-cov[fit]@np.linalg.lstsq(cov[fit],a[fit],rcond=None)[0]
 for direction,q in [('low',LOW_Q),('high',HIGH_Q)]:
  ref=residual[~H&np.isfinite(residual)];th=np.quantile(ref,q) if len(ref) else np.nan;mask=H&np.isfinite(residual)&((residual<=th) if direction=='low' else(residual>=th));sid='adjusted_'+content_hash([k,direction,member_hash(genes[mask])])[:20]
  rows.append({'set_id':sid,'feature_key':k,'direction':direction,'threshold':th,'n_members':int(mask.sum()),'method':'OLS feature residual on expression/detection/appropriate length; no HVG label used','fit_scope':'all complete valid genes','cross_fitted':False,'status':'generated' if np.isfinite(th) else 'not_estimable'})
  mrows.extend({'set_id':sid,'gene_id':g,'feature_key':k,'direction':direction,'prepared_value':residual[i]} for i,g in enumerate(genes) if mask[i])
  for source,g in A.groupby('source'):
   bg=set(g.gene_id)&set(genes[np.isfinite(residual)]);qset=set(genes[mask])&bg
   orows.append(ora(qset,bg,A,T[T.source.eq(source)],min_term=TERM_MIN,max_term=TERM_MAX,min_query=MIN_QUERY,term_index=term_index,fields={'set_id':sid,'feature_key':k,'direction':direction,'family_id':'F4_adjusted','query_scope':'adjusted_subset'}))
 # Joint set follows the observed direction with a frozen family vote cap; explicitly exploratory.
 direction='high' if meta.effect>0 else 'low';q=HIGH_Q if direction=='high' else LOW_Q;ref=a[ok&~H]
 if len(ref):
  th=np.quantile(ref,q);mask=H&ok&((a>=th) if direction=='high' else (a<=th));family='amino_acid_composition' if meta.family in ['aa_freq','aa_pct'] else omics+'::'+meta.family;votes[family]=votes.get(family,np.zeros(len(a),bool))|mask
joint=(np.sum(list(votes.values()),axis=0)>=2)&H if votes else np.zeros(len(H),bool);jointid='joint_'+member_hash(genes[joint])[:20]
save('gene_sets/adjusted_sets',rows);save('gene_sets/adjusted_set_members',mrows);save('gene_sets/joint_sets',[{'set_id':jointid,'n_members':int(joint.sum()),'rule':'at_least_two_family_direction_votes','interpretation':'exploratory; families not statistically independent'}]);save('gene_sets/joint_set_members',pd.DataFrame({'set_id':jointid,'gene_id':genes[joint]}))
for source,g in A.groupby('source'):
 bg=set(g.gene_id)&set(genes);orows.append(ora(set(genes[joint])&bg,bg,A,T[T.source.eq(source)],min_term=TERM_MIN,max_term=TERM_MAX,min_query=MIN_QUERY,term_index=term_index,fields={'set_id':jointid,'family_id':'F4_joint','query_scope':'joint_subset'}))
out=pd.concat(orows,ignore_index=True) if orows else pd.DataFrame(columns=['family_id','p_value']);out['q_global']=np.nan;out['q_global_by']=np.nan
for _,ids in out.groupby('family_id').groups.items():out.loc[ids,'q_global']=fdr(out.loc[ids,'p_value']);out.loc[ids,'q_global_by']=fdr(out.loc[ids,'p_value'],'by')
save('enrichment/supplementary_ora',out)
# Unordered categories are assessed with contingency tests, never numeric rank codes.
for s in read_json('core/registry_snapshot.json')['fields']:
 if s.get('scope')!='core' or s.get('semantic_type')!='categorical_code':continue
 k=s['omics']+'::'+s['field'];col=s['omics']+'__'+s['field']
 if col not in X:continue
 cat=X[col].astype('string');ct=pd.crosstab(cat,pd.Series(H));p=np.nan;status='insufficient_category_counts'
 if ct.shape[0]>=2 and ct.shape[1]==2:
  if ct.shape==(2,2):_,p=stats.fisher_exact(ct.to_numpy());status='fisher_exact'
  else:
   chi,p0,_,expected=stats.chi2_contingency(ct.to_numpy())
   if (expected>=5).all():p=p0;status='chi_square'
  categories.append({'feature_key':k,'p_value':p,'status':status,'contingency':ct.to_json(),'effect_type':'categorical_association_not_ordinal'})
save('features/categorical_tests',add_fdr(pd.DataFrame(categories,columns=['feature_key','p_value','status','contingency','effect_type'])))
