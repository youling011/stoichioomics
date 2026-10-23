from .runtime import *
import gseapy, gseapy.algorithm as ga
# NumPy 2.4 removed np.in1d; np.isin has the same membership semantics used here.
if not hasattr(np,'in1d'):np.in1d=np.isin
log('S8 genuine GSEApy weighted enrichment with preserved permutation nulls')
labels=load('labels/hvg_labels');genes=labels.gene_id.to_numpy(str);H=labels.is_hvg.to_numpy(bool)
P=load('features/feature_values').drop(columns='gene_id');audit=load('core/core_feature_audit').set_index('feature_key');red=load('features/redundancy_groups').set_index('feature_key')
members=load('annotations/gene_term_membership');terms=load('annotations/terms');termsets={t:set(g.gene_id) for t,g in members.groupby('term_key')};tm=terms.set_index('term_key').to_dict('index')
keys=[k for k in P if not red.loc[k,'alias_of'] and audit.loc[k,'value_type']!='binary']
runs=[];results=[];rankrows=[];leading=[];nulls=[]
for j,k in enumerate(keys):
    values=P[k].to_numpy(float)
    for source in sorted(members.source.unique()):
        annotated=np.isin(genes,members.loc[members.source==source,'gene_id'].unique())
        for scope in ['all_annotated','hvg_annotated']:
            bg=np.isfinite(values)&annotated&(H if scope=='hvg_annotated' else True)
            inds=np.flatnonzero(bg);a=values[inds]
            rid=hashlib.sha256((k+'|'+source+'|'+scope).encode()).hexdigest()[:20]
            if len(inds)<2*MIN_N or len(np.unique(a))<20:
                runs.append({'run_id':rid,'feature_key':k,'source':source,'scope':scope,'status':'insufficient_rank_resolution_or_background','n_genes':len(inds)});continue
            tied=1-len(np.unique(a))/len(a)
            if tied>.5:
                runs.append({'run_id':rid,'feature_key':k,'source':source,'scope':scope,'status':'severe_ties_use_distribution_test','tie_fraction':tied,'n_genes':len(inds)});continue
            score=zscore(a);order=np.lexsort((genes[inds],-score));ordered_genes=genes[inds][order];score=score[order]
            sets={t:sorted(termsets[t]&set(ordered_genes)) for t in terms.loc[terms.source==source,'term_key']}
            sets={t:g for t,g in sets.items() if TERM_MIN<=len(g)<=min(TERM_MAX,len(ordered_genes)-1)}
            if not sets:
                runs.append({'run_id':rid,'feature_key':k,'source':source,'scope':scope,'status':'no_eligible_gene_sets','n_genes':len(inds)});continue
            rankrows.extend({'run_id':rid,'feature_key':k,'scope':scope,'source':source,'gene_id':g,'rank':r+1,'rank_score':s} for r,(g,s) in enumerate(zip(ordered_genes,score)))
            eslist=[];enulls=[];local=[]
            for q,(term,query) in enumerate(sets.items()):
                check_cancel()
                seed=SEED+int(hashlib.sha256((rid+'|'+term).encode()).hexdigest()[:8],16)%(2**31-100)
                es,esnull,hits,RES=ga.enrichment_score(ordered_genes,score,query,weight=1.,nperm=N_PERM,seed=seed)
                same=esnull>=0 if es>=0 else esnull<0;den=int(same.sum());tail=int(np.sum(esnull[same]>=es)) if es>=0 else int(np.sum(esnull[same]<=es))
                p=(tail+1)/(den+1);norm=float(np.mean(esnull[same]));nes=es/abs(norm) if norm else np.nan
                peak=int(np.argmax(RES)) if es>=0 else int(np.argmin(RES));le=[ordered_genes[h] for h in hits if (h<=peak if es>=0 else h>=peak)]
                local.append({'run_id':rid,'feature_key':k,'source':source,'scope':scope,'term_key':term,'term_name':tm[term]['term_name'],'es':es,'nes':nes,'p_value':p,'raw_tail_count':tail,'same_sign_null_count':den,'p_resolution':1/(den+1),'term_size':len(query),'n_ranked_genes':len(ordered_genes),'tie_fraction':tied,'method':'GSEApy.algorithm.enrichment_score weighted=1 gene-set permutations','permutation_num':N_PERM,'finite_sample_correction':'(same_sign_tail+1)/(same_sign_nulls+1)','leading_edge_count':len(le),'status':'computed' if np.isfinite(nes) else 'nominal_conservative_upper_bound_NES_unavailable','nominal_p_kind':'finite_same_sign_tail' if den else 'conservative_upper_bound_without_same_sign_nulls'})
                leading.extend({'run_id':rid,'feature_key':k,'term_key':term,'source':source,'scope':scope,'gene_id':g} for g in le)
                eslist.append(es);enulls.append(esnull)
                nulls.append({'run_id':rid,'term_key':term,'es_null':json.dumps(esnull.tolist(),separators=(',',':'))})
            # The original within-rank GSEA FDR and finite-sample global BH answer distinct questions.
            try:
                sig=list(ga.gsea_significance(np.array(eslist),np.array(enulls)))
                for r,sigrow in zip(local,sig):r['tool_within_rank_fdr']=float(sigrow[3])
            except Exception as err:
                for r in local:r['tool_within_rank_fdr']=np.nan;r['tool_fdr_status']=type(err).__name__
            results.extend(local);runs.append({'run_id':rid,'feature_key':k,'source':source,'scope':scope,'status':'computed','n_genes':len(inds),'n_terms':len(sets),'tie_fraction':tied,'rank_background_hash':set_hash(ordered_genes),'rank_score':'zscore prepared feature within common rank background; identical across terms','permutations':N_PERM})
    if (j+1)%10==0:
        log('GSEA features',j+1,'/',len(keys),'results',len(results))
        save('pathway_links/gsea_runs_checkpoint',runs,csv=False)
res=add_fdr(pd.DataFrame(results) if results else pd.DataFrame(columns=['feature_key','term_key','source','scope','p_value','status','es','nes']));save('pathway_links/gsea_results',res);save('pathway_links/gsea_runs',runs);save('pathway_links/ranked_genes',rankrows);save('pathway_links/leading_edge_members',leading)
save('pathway_links/gsea_permutation_nulls',nulls,csv=False)
write_json('pathway_links/gsea_method.json',{'gseapy_version':gseapy.__version__,'implementation':'official GSEApy enrichment_score and gsea_significance; nulls preserved for valid finite-permutation p','permutation_type':'gene_set; not donor validation','nperm':N_PERM,'primary_feature_pathway_inference':'F6 full distribution tests; GSEA independent support family','rank_weight':1,'scope':['all_annotated','hvg_annotated'],'finite_p':'(tail+1)/(same-sign-null-count+1)','all_features_computed_before_significance_display':True,'numpy_in1d_compatibility_alias':True})
log('GSEA DONE',len(res),'global sig',int(res.q_global.lt(ALPHA).sum()))
