from .runtime import *
log('S5-S9 full hypothesis functional analysis')
labels=load('labels/hvg_labels');genes=labels.gene_id.to_numpy(str);H=labels.is_hvg.to_numpy(bool);ix={g:i for i,g in enumerate(genes)}
P=load('features/feature_values').drop(columns='gene_id');Z=load('features/model_values').drop(columns='gene_id');keys=P.columns.tolist()
audit=load('core/core_feature_audit').set_index('feature_key');red=load('features/redundancy_groups').set_index('feature_key');keys=[k for k in keys if not red.loc[k,'alias_of']]
members=load('annotations/gene_term_membership');terms=load('annotations/terms')
sources=sorted(members.source.unique());source_masks={s:np.isin(genes,members.loc[members.source==s,'gene_id'].unique()) for s in sources}
term_masks={k:np.isin(genes,g.gene_id.unique()) for k,g in members.groupby('term_key')}
termmeta=terms.set_index('term_key').to_dict('index')
backgrounds={};bgrecords=[]
def bgid(mask,kind):
    digest=set_hash(genes[mask]);bid='bg_'+digest[:16]
    if bid not in backgrounds:
        backgrounds[bid]=mask;bgrecords.extend({'background_id':bid,'gene_id':g,'background_hash':digest} for g in genes[mask])
    return bid

def ora(query,bg,source,fields):
    query=query&bg;N=int(bg.sum());n=int(query.sum());rows=[]
    for t in terms.loc[terms.source==source,'term_key']:
        mask=term_masks[t];K=int((bg&mask).sum());k=int((query&mask).sum())
        if not TERM_MIN<=K<=TERM_MAX:continue
        eligible=N>=2*MIN_N and MIN_QUERY<=n<N
        p=float(stats.hypergeom.sf(k-1,N,K,n)) if eligible else np.nan
        a,b,c,d=k,n-k,K-k,N-n-K+k
        odds=(a*d)/(b*c) if b*c>0 else (np.inf if a*d>0 else np.nan)
        if min(a,b,c,d)>0:
            se=np.sqrt(1/a+1/b+1/c+1/d);lo=np.exp(np.log(odds)-1.96*se);hi=np.exp(np.log(odds)+1.96*se)
        else:lo=hi=np.nan
        rows.append({**fields,'source':source,'term_key':t,'term_id':termmeta[t]['term_id'],'term_name':termmeta[t]['term_name'],'N':N,'K':K,'n':n,'k':k,'fold_enrichment':(k/n)/(K/N) if n and K and N else np.nan,'odds_ratio':odds,'ci_low':lo,'ci_high':hi,'p_value':p,'status':'tested' if eligible else 'insufficient_query_or_no_contrast','background_id':bgid(bg,fields.get('query_scope','')),'query_hash':set_hash(genes[query]),'overlap_genes':';'.join(genes[query&mask])})
    return rows

baseline=[]
for source,bg in source_masks.items():baseline.extend(ora(H,bg,source,{'query_scope':'original_hvg','set_id':'H','family_id':'F3'}))
base=load('enrichment/baseline_ora')  # Independent of all feature/Core eligibility.
log('baseline ORA',len(base),'significant',int(base.q_global.lt(ALPHA).sum()))

setrows=[];setmembers=[];featurelinks=[];orows=[];matched=[];cache=set();sets={}
for j,k in enumerate(keys):
    a=P[k].to_numpy(float);valid=np.isfinite(a);ref=a[valid&~H]
    binary=audit.loc[k,'value_type']=='binary'
    lo,hi=(0.,1.) if binary else tuple(np.quantile(ref,[LOW_Q,HIGH_Q],method='linear')) if len(ref) else (np.nan,np.nan)
    degenerate=not np.isfinite([lo,hi]).all() or lo==hi
    for direction,threshold in [('low',lo),('high',hi)]:
        mask=(H&valid&(not degenerate))&((a<=threshold) if direction=='low' else (a>=threshold))
        sid='set_'+content_hash([DESIGN['context_id'],k,direction,float(threshold),LOW_Q,HIGH_Q,set_hash(genes[mask])])[:20]
        sets[(k,direction)]=(sid,mask)
        setrows.append({'set_id':sid,'feature_key':k,'direction':direction,'threshold':threshold,'reference':'nonhvg_valid_feature_background','quantile':LOW_Q if direction=='low' else HIGH_Q,'quantile_method':'numpy_linear','n_members':int(mask.sum()),'member_hash':set_hash(genes[mask]),'reference_hash':set_hash(genes[valid&~H]),'rule':'binary_value' if binary else 'prepared_feature_percentile','status':'degenerate_threshold' if degenerate else 'generated'})
        percentiles=stats.rankdata(np.r_[ref,a[mask]],method='average')[-int(mask.sum()):] if mask.any() else []
        sortedref=np.sort(ref)
        for idx in np.flatnonzero(mask):
            setmembers.append({'set_id':sid,'feature_key':k,'direction':direction,'gene_id':genes[idx]})
            featurelinks.append({'gene_id':genes[idx],'set_id':sid,'feature_key':k,'direction':direction,'prepared_value':a[idx],'reference_percentile':np.searchsorted(sortedref,a[idx],side='right')/len(ref),'threshold':threshold,'redundancy_group':red.loc[k,'redundancy_group']})
        if degenerate:continue
        for source,amask in source_masks.items():
            bg=valid&amask;hbg=H&bg
            orows.extend(ora(mask,bg,source,{'feature_key':k,'direction':direction,'query_scope':'feature_subset','set_id':sid,'family_id':'F4'}))
            orows.extend(ora(mask,hbg,source,{'feature_key':k,'direction':direction,'query_scope':'within_hvg','set_id':sid,'family_id':'F5'}))
            identity=(source,set_hash(genes[bg]))
            if identity not in cache:
                cache.add(identity);matched.extend(ora(H,bg,source,{'query_scope':'matched_baseline','set_id':'H_on_'+identity[1][:16],'family_id':'F3_matched'}))
    if (j+1)%25==0:log('direction sets/ORA',j+1,'/',len(keys))
save('gene_sets/gene_sets',setrows);save('gene_sets/gene_set_members',setmembers);save('gene_sets/gene_feature_links',featurelinks)
allora=pd.DataFrame(orows,columns=['feature_key', 'direction', 'query_scope', 'set_id', 'family_id', 'source', 'term_key', 'term_id', 'term_name', 'N', 'K', 'n', 'k', 'fold_enrichment', 'odds_ratio', 'ci_low', 'ci_high', 'p_value', 'status', 'background_id', 'query_hash', 'overlap_genes']);allora['q_global']=np.nan;allora['q_global_by']=np.nan
for scope,idx in allora.groupby('query_scope').groups.items():
    allora.loc[idx,'q_global']=fdr(allora.loc[idx,'p_value']);allora.loc[idx,'q_global_by']=fdr(allora.loc[idx,'p_value'],'by')
save('enrichment/feature_set_ora',allora[allora.query_scope=='feature_subset']);save('enrichment/within_hvg_ora',allora[allora.query_scope=='within_hvg'])
mat=add_fdr(pd.DataFrame(matched,columns=['feature_key', 'direction', 'query_scope', 'set_id', 'family_id', 'source', 'term_key', 'term_id', 'term_name', 'N', 'K', 'n', 'k', 'fold_enrichment', 'odds_ratio', 'ci_low', 'ci_high', 'p_value', 'status', 'background_id', 'query_hash', 'overlap_genes']));save('enrichment/matched_baseline_ora',mat)
comp=allora[allora.query_scope=='feature_subset'].merge(allora[allora.query_scope=='within_hvg'][['feature_key','direction','source','term_key','p_value','q_global','fold_enrichment','k','n','status']],on=['feature_key','direction','source','term_key'],how='left',suffixes=('_subset','_within_hvg'))
comp=comp.merge(mat[['source','term_key','background_id','fold_enrichment','q_global','k','n']],on=['source','term_key','background_id'],how='left',suffixes=('','_matched_baseline'))
save('enrichment/enrichment_comparison',comp)
log('ORA done subset and conditional',len(allora),'F4 sig',int(allora.loc[allora.query_scope=='feature_subset','q_global'].lt(ALPHA).sum()),'F5 sig',int(allora.loc[allora.query_scope=='within_hvg','q_global'].lt(ALPHA).sum()))

log('S8/S9 all-feature all-term distribution/within-term/interaction')
expr=zscore(np.log1p(labels.mean_expr));detect=zscore(labels.pct_cells_detected)
ctx=load('core/context')
length={o:zscore(np.log1p(pd.to_numeric(ctx.get(o+'__'+n,pd.Series(np.nan,index=ctx.index)),errors='coerce'))) for o,n in [('genome','locus_length_bp'),('transcriptome','length_nt_total'),('proteome','length_aa')]}
continuous=[];within=[];interactions=[];withinadj=[]
for j,k in enumerate(keys):
    a=P[k].to_numpy(float);z=Z[k].to_numpy(float);valid=np.isfinite(a)
    check_cancel()
    L=length[audit.loc[k,'omics']];same_length=audit.loc[k,'field'] in ['locus_length_bp','length_nt_total','length_aa']
    cov=np.column_stack([np.ones(len(a)),expr,detect]+([] if same_length or np.isfinite(L).sum()<2*MIN_N else [L]))
    for source,amask in source_masks.items():
        bg=valid&amask
        for t in terms.loc[terms.source==source,'term_key']:
            tm=term_masks[t];K=int((bg&tm).sum())
            if not TERM_MIN<=K<=TERM_MAX:continue
            fields={'feature_key':k,'source':source,'term_key':t,'term_name':termmeta[t]['term_name']}
            for scope,scopebg in [('all_annotated',bg),('hvg_annotated',bg&H)]:
                inside=scopebg&tm;outside=scopebg&~tm
                rr=rank_test(a[inside],a[outside]) if CFG['pathway']['rank_relationship_enabled'] else {'p_value':np.nan,'status':'not_run_by_config'};continuous.append({**fields,'scope':scope,'family_id':'F6','background_id':bgid(scopebg,scope),**rr})
            inh=bg&tm&H;inn=bg&tm&~H
            rr=rank_test(a[inh],a[inn]) if CFG['pathway']['within_pathway_enabled'] else {'p_value':np.nan,'status':'not_run_by_config'};within.append({**fields,'family_id':'F7','background_id':bgid(bg&tm,'within_term'),**rr})
            four=[int(inh.sum()),int(inn.sum()),int((bg&~tm&H).sum()),int((bg&~tm&~H).sum())]
            if min(four)>=MIN_N:
                fmask=bg&np.isfinite(cov).all(1)&np.isfinite(z)
                X=np.column_stack([cov,z,tm.astype(float),z*tm.astype(float)])
                fit=glm(H[fmask],X[fmask]) if CFG['pathway']['interaction_enabled'] else {'p_value':np.nan,'status':'not_run_by_config'};interactions.append({**fields,'family_id':'F8','n_H_in':four[0],'n_N_in':four[1],'n_H_out':four[2],'n_N_out':four[3],**fit})
                wfmask=bg&tm&np.isfinite(cov).all(1)&np.isfinite(z)
                fit2=glm(H[wfmask],np.column_stack([cov,z])[wfmask]) if CFG['pathway']['within_pathway_enabled'] else {'p_value':np.nan,'status':'not_run_by_config'};withinadj.append({**fields,'model':'expression_detection_length','family_id':'F7_adjusted',**fit2})
            else:
                interactions.append({**fields,'family_id':'F8','n_H_in':four[0],'n_N_in':four[1],'n_H_out':four[2],'n_N_out':four[3],'status':'insufficient_four_cell_groups','p_value':np.nan})
                withinadj.append({**fields,'family_id':'F7_adjusted','status':'insufficient_group_n','p_value':np.nan})
    if (j+1)%20==0:log('pathway grid',j+1,'/',len(keys))
for name,rows in [('pathway_links/feature_pathway_tests',continuous),('within_pathway/within_pathway_tests',within),('pathway_links/feature_pathway_interactions',interactions),('within_pathway/within_pathway_adjusted',withinadj)]:
    frame=add_fdr(pd.DataFrame(rows) if rows else pd.DataFrame(columns=['feature_key','term_key','source','term_name','p_value','effect','status','family_id']));save(name,frame);log(name,len(frame),'tested',int(frame.p_value.notna().sum()),'sig',int(frame.q_global.lt(ALPHA).sum()))
save('labels/universe_members',pd.DataFrame(bgrecords,columns=['background_id','gene_id','background_hash']))
log('FUNCTIONAL DONE')
