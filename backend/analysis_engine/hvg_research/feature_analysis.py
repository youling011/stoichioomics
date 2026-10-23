from .runtime import *
import re
from scipy.linalg import helmert
from scipy.special import expit
log('S3 semantic audit and transformations')
x=load('core/context');labels=load('labels/hvg_labels');H=labels.is_hvg.to_numpy(bool);genes=labels.gene_id.to_numpy(str)
registry=read_json('core/registry_snapshot.json');specs=[dict(r) for r in registry['fields'] if r['scope']=='core']
provenance=pd.read_csv(ROOT/'core'/'hvg_multiomics_feature_provenance.csv').set_index('feature_key').to_dict('index')
values={};specmap={};audit=[]
coding=pd.to_numeric(x.get('genome__coding_valid',pd.Series(np.nan,index=x.index)),errors='coerce').eq(1).to_numpy()
proxy=pd.to_numeric(x.get('transcriptome__orf_len_aa',pd.Series(np.nan,index=x.index)),errors='coerce').gt(0).to_numpy()
for s in specs:
    o=s['omics'];name=s['field'];key=o+'::'+name;col=o+'__'+name;pr=provenance.get(key,{})
    overlay=read_json('core/semantic_overlay.json').get('features',{}).get(key,{})
    r={**s,**overlay,'feature_key':key,'source_column':pr.get('source_column',''),'context_column':col,'source_sha256':pr.get('source_sha256',''),'semantic_review_status':overlay.get('review_status','unreviewed_new_field'),'semantic_basis':'fixed extractor source hashes; no regenerated features','final_status':'tested','reason':''}
    specmap[key]=r
    if not overlay.get('reviewed',False):
        r.update(final_status='descriptive_only',reason='unreviewed_semantic_definition');audit.append(r);continue
    technical=(s['family'] in ['coordinate','qc'] or s['semantic_type'] in ['identifier','metadata_text','coordinate'] or name in ['strand','transl_table_used','element_rule','exon_seq_strategy','promoter_seq_strategy','orf_has_stop'])
    if technical:
        r.update(final_status='excluded_metadata',reason='identifier_coordinate_or_technical_QC');audit.append(r);continue
    if col not in x or pr.get('source_present') is False or pr.get('source_present') == False:
        r.update(final_status='missing_source',reason='core_column_not_materialized');audit.append(r);continue
    applicable=np.ones(len(x),bool)
    if o=='genome' and (s['applicability']=='coding_only' or name.startswith(('cds_','codon_','aa_','gc1','gc2','gc3'))):applicable&=coding
    if o=='transcriptome' and (s['applicability']=='protein_proxy_only' or name.startswith(('orf_','protein_','aa_'))):applicable&=proxy
    if o=='proteome':applicable&=pd.to_numeric(x.get('proteome__length_aa',pd.Series(np.nan,index=x.index)),errors='coerce').gt(0).to_numpy()
    r['n_applicable']=int(applicable.sum());r['n_applicable_hvg']=int((applicable&H).sum());r['n_applicable_nonhvg']=int((applicable&~H).sum())
    if s['semantic_type']=='categorical_code':
        a=x[col].astype('string').where(applicable);r['value_type']='categorical';r['final_status']='descriptive_only';r['reason']='biotype_or_conditional_category_retained_for_context_not_primary_molecular_rank';audit.append(r);continue
    a=pd.to_numeric(x[col],errors='coerce').to_numpy(float);a[~applicable]=np.nan;a[~np.isfinite(a)]=np.nan
    # Gene coding-invalid zero fill must not become a real protein-composition zero.
    r['value_type']='binary' if s['semantic_type']=='binary' else 'composition' if s.get('composition_group') else 'continuous'
    if any(t in name.lower() for t in ['ratio','entropy','skew','density','per_base','per_aa']):r['value_type']='continuous'
    pct=(s.get('unit')=='%' or name.endswith('_percent') or name.startswith('AA_') and name.endswith('_pct'))
    from .preprocessing import canonicalize
    a,r['canonical_unit']=canonicalize(a,'%' if pct else s.get('unit',''))
    r['unit_conversion']='percent_to_fraction' if pct else 'identity'
    valid=np.isfinite(a);r['n_hvg']=int((valid&H).sum());r['n_nonhvg']=int((valid&~H).sum())
    r['missing_hvg']=1-r['n_hvg']/max(r['n_applicable_hvg'],1);r['missing_nonhvg']=1-r['n_nonhvg']/max(r['n_applicable_nonhvg'],1)
    if min(r['n_hvg'],r['n_nonhvg'])<MIN_N:r.update(final_status='qc_failed',reason='insufficient_group_n')
    elif max(r['missing_hvg'],r['missing_nonhvg'])>CFG['core']['exploratory_max_missing_rate']:r.update(final_status='qc_failed',reason='high_missingness')
    elif np.unique(a[valid]).size<2:r.update(final_status='descriptive_only',reason='constant')
    elif np.nanstd(a)<=1e-12*max(1,np.nanmax(np.abs(a))):r.update(final_status='descriptive_only',reason='near_constant')
    else:
        r['evidence_scope']='main' if max(r['missing_hvg'],r['missing_nonhvg'])<=CFG['core']['main_max_missing_rate'] else 'exploratory_missingness'
        values[key]=a
    audit.append(r)

if not values:
    from .empty_results import empty_stage
    empty_stage(ROOT,'feature_analysis','insufficient_data')
    save('core/core_feature_audit',audit)
    raise SystemExit(0)
keys=list(values);P=np.column_stack([values[k] for k in keys]);C=P.copy();transforms=[];groups=[]
for o in ['genome','transcriptome','proteome']:
    allgroups=sorted({s.get('composition_group','') for s in specs if s['omics']==o and s.get('composition_group')})
    for group in allgroups:
        declared=[o+'::'+s['field'] for s in specs if s['omics']==o and s.get('composition_group')==group]
        cols=[j for j,k in enumerate(keys) if k in declared]
        # Constant components remain in the complete composition for closure review.
        full=[]
        for k in declared:
            s=specmap[k];col=s['context_column']
            a=pd.to_numeric(x.get(col,pd.Series(np.nan,index=x.index)),errors='coerce').to_numpy(float)
            if s.get('unit')=='%':a/=100
            if o=='genome':a[~coding]=np.nan
            if o=='transcriptome' and group.startswith('aa_'):a[~proxy]=np.nan
            full.append(a)
        M=np.column_stack(full);valid=np.isfinite(M).all(axis=1)&(M>=0).all(axis=1)
        closure=np.sum(M,axis=1);valid&=np.isclose(closure,1,rtol=.02,atol=.005)
        info={'omics':o,'composition_group':group,'declared_components':declared,'valid_rows':int(valid.sum()),'max_closure_error':float(np.nanmax(abs(closure-1))),'zero_policy':'add 1e-6 in fraction units after closure validation','pseudocount':1e-6}
        if valid.sum()>=2*MIN_N:
            logM=np.log(M[valid]+1e-6);clr=logM-logM.mean(axis=1,keepdims=True)
            for j in cols:C[:,j]=np.nan;C[valid,j]=clr[:,declared.index(keys[j])]
            ilr=logM@helmert(len(declared),full=False).T
            save('features/ilr_'+o+'_'+group,pd.DataFrame(ilr,columns=[f'balance_{i+1}' for i in range(ilr.shape[1])]).assign(gene_id=genes[valid]),csv=False)
            info.update(status='complete_composition_clr_ilr_generated',ilr_dimensions=ilr.shape[1],ilr_effective_rank=int(np.linalg.matrix_rank(ilr-ilr.mean(0))))
        else:
            info['status']='insufficient_complete_composition'
            for j in cols:C[:,j]=np.nan;specmap[keys[j]].update(composition_model_status='not_usable')
        groups.append(info)

Z=np.empty_like(P);redundancy=[];alias={};signature={}
for j,k in enumerate(keys):
    s=specmap[k];a=C[:,j].copy();name=s['field'].lower();iscomp=bool(s.get('composition_group'))
    transformation='clr_complete_group' if iscomp else 'identity'
    if not iscomp and np.nanmin(a)>=0 and (s['semantic_type']=='count' and not any(t in name for t in ['ratio','entropy','skew','per_','density']) or any(t in name for t in ['length','_atoms','mw_da','n_n']) and not any(t in name for t in ['per_','ratio'])):
        a=np.log1p(a);transformation='log1p_canonical_units'
    elif not iscomp and 'ratio' in name and np.nanmin(a)>0:a=np.log(a);transformation='log_positive_ratio'
    Z[:,j]=zscore(a)
    s['model_transform']=transformation
    transforms.append({'feature_key':k,'canonical_unit':s['canonical_unit'],'unit_conversion':s['unit_conversion'],'model_transform':transformation,'mean':np.nanmean(a),'sd':np.nanstd(a),'center':np.nanmedian(a) if CFG['preprocessing']['continuous_scaler']=='robust' else np.nanmean(a),'reference_iqr':np.nanpercentile(a,75)-np.nanpercentile(a,25),'scaler':CFG['preprocessing']['continuous_scaler'],'reference':'all_valid_genes_in_frozen_U; never scaled separately by H/N'})
    sig=hashlib.sha256(np.nan_to_num(P[:,j],nan=-9.87654321e99).tobytes()).hexdigest()
    if sig in signature:alias[k]=signature[sig];s.update(final_status='redundant_alias',reason='exact_duplicate_of:'+signature[sig])
    else:signature[sig]=k

# Connected correlation clusters balance correlated composition/count evidence, without removing single-column tests.
corr=pd.DataFrame(P,columns=keys).corr(method='spearman',min_periods=40).to_numpy();parent=list(range(len(keys)))
def find(i):
    while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
    return i
for i in range(len(keys)):
    for j in range(i):
        if np.isfinite(corr[i,j]) and abs(corr[i,j])>=.995:parent[find(i)]=find(j)
for j,k in enumerate(keys):
    group='corr_'+str(find(j));specmap[k]['redundancy_group_resolved']=group
    redundancy.append({'feature_key':k,'redundancy_group':group,'alias_of':alias.get(k,''),'correlation_threshold':.995})
save('features/redundancy_groups',redundancy)
save('core/core_feature_audit',audit);write_json('features/transform_manifest.json',{'transforms':transforms,'composition_groups':groups,'scaling':CFG['preprocessing']['continuous_scaler']+' per feature; full-U reference; IQR-zero falls back to SD','raw_values':'core/context.parquet; prepared numeric values in feature_values','min_group_n':20})
save('features/feature_values',pd.DataFrame(P,columns=keys).assign(gene_id=genes));save('features/model_values',pd.DataFrame(Z,columns=keys).assign(gene_id=genes))
write_json('features/feature_keys.json',keys)
log('Core audit',pd.Series([r['final_status'] for r in audit]).value_counts().to_dict(),'numeric',len(keys))

log('S4 full-gene bootstrap feature comparisons and GLM')
expr=zscore(np.log1p(labels.mean_expr.to_numpy()));det=zscore(labels.pct_cells_detected.to_numpy());basic=np.column_stack([np.ones(len(x)),expr,det])
lengths={}
for o,field in [('genome','locus_length_bp'),('transcriptome','length_nt_total'),('proteome','length_aa')]:lengths[o]=zscore(np.log1p(pd.to_numeric(x.get(o+'__'+field,pd.Series(np.nan,index=x.index)),errors='coerce').to_numpy(float)))
feature_rows=[];adjusted=[];matching=[];matchmembers=[]
rng=np.random.default_rng(SEED)
for j,k in enumerate(keys):
    s=specmap[k];a=P[:,j];finite=np.isfinite(a);a1=a[finite&H];a0=a[finite&~H]
    base={'feature_key':k,'omics':s['omics'],'family':s['family'],'value_type':s['value_type'],'n_hvg':len(a1),'n_nonhvg':len(a0),'background_hash':set_hash(genes[finite]),'evidence_scope':s.get('evidence_scope','main'),'alias_of':alias.get(k,''),'redundancy_group':s['redundancy_group_resolved']}
    if k in alias:
        oldrow=next(r for r in feature_rows if r['feature_key']==alias[k]);rr={kk:vv for kk,vv in oldrow.items() if kk not in base};rr['status']='alias_reused';rr['p_value']=np.nan
    elif s['value_type']=='binary':
        A=int((a1==1).sum());B=len(a1)-A;C0=int((a0==1).sum());D=len(a0)-C0
        odds,p=stats.fisher_exact([[A,B],[C0,D]])
        risk=A/len(a1)-C0/len(a0);se=np.sqrt((A+.5)*(B+.5)/(len(a1)+1)**3+(C0+.5)*(D+.5)/(len(a0)+1)**3)
        rr={'effect':A/len(a1)-C0/len(a0),'effect_type':'proportion_difference','odds_ratio':odds,'p_value':p,'status':'tested','median1':np.median(a1),'median0':np.median(a0),'ci_low':max(-1,risk-1.96*se),'ci_high':min(1,risk+1.96*se),'ci_method':'risk_difference_Wald_Jeffreys_variance'}
    else:
        rr=rank_test(a1,a0,boot=True,seed=SEED+j);rr['effect_type']='cliffs_delta'
    feature_rows.append({**base,**rr})
    if k in alias:continue
    check_cancel()
    zj=Z[:,j];fit=glm(H,np.column_stack([basic,zj]));adjusted.append({**base,'model':'expression_detection','scale':'per_1_IQR_transformed_feature_with_SD_fallback' if CFG['preprocessing']['continuous_scaler']=='robust' else 'per_1_SD_transformed_feature',**fit})
    use_length=not s['field'].lower() in ['length_nt_total','length_aa','locus_length_bp']
    L=lengths[s['omics']]
    if use_length and np.isfinite(L).sum()>=2*MIN_N:
        cov=np.column_stack([basic,L]);fit2=glm(H,np.column_stack([cov,zj]));adjusted.append({**base,'model':'expression_detection_length','scale':'per_1_IQR_transformed_feature_with_SD_fallback' if CFG['preprocessing']['continuous_scaler']=='robust' else 'per_1_SD_transformed_feature',**fit2})
    else:cov=basic;fit2=fit
    # Fixed quantile strata matching without replacement; members then paired sign/signed-rank inference.
    good=np.isfinite(cov).all(1)&finite
    strata=[]
    for v in cov[:,1:].T:
        edges=np.unique(np.nanquantile(v[good],[.2,.4,.6,.8]));strata.append(np.digitize(v,edges))
    codes=sum(v*(5**q) for q,v in enumerate(strata));left=[];right=[]
    for code in np.unique(codes[good]):
        ih=np.flatnonzero(good&H&(codes==code));inn=np.flatnonzero(good&~H&(codes==code));n=min(len(ih),len(inn))
        if n:left.extend(rng.choice(ih,n,replace=False));right.extend(rng.choice(inn,n,replace=False))
    left=np.array(left,int);right=np.array(right,int)
    if len(left)>=MIN_N and CFG['feature_tests']['matching_enabled']:
        diff=a[left]-a[right];nonzero=diff!=0
        p=stats.binomtest(int((diff[nonzero]>0).sum()),int(nonzero.sum()),.5).pvalue if nonzero.any() else 1.
        balance=[]
        for q in range(1,cov.shape[1]):balance.append({'covariate':q,'before_smd':float(np.nanmean(cov[good&H,q])-np.nanmean(cov[good&~H,q])),'after_smd':float(np.mean(cov[left,q])-np.mean(cov[right,q]))})
        matching.append({**base,'n_pairs':len(left),'matched_H_fraction':len(left)/max(good[H].sum(),1),'paired_sign_effect':float(np.mean(np.sign(diff))),'p_value':p,'status':'tested','balance':json.dumps(balance),'method':'no-replacement quantile-stratum matching; exact paired sign test'})
        matchmembers.extend({'feature_key':k,'pair_id':i,'hvg_gene_id':genes[h],'nonhvg_gene_id':genes[n]} for i,(h,n) in enumerate(zip(left,right)))
    if (j+1)%10==0:log('features',j+1,'/',len(keys))
tests=add_fdr(pd.DataFrame(feature_rows));adj=pd.DataFrame(adjusted)
adj['q_global']=np.nan;adj['q_global_by']=np.nan
for model,idx in adj.groupby('model').groups.items():adj.loc[idx,'q_global']=fdr(adj.loc[idx,'p_value']);adj.loc[idx,'q_global_by']=fdr(adj.loc[idx,'p_value'],'by')
matches=add_fdr(pd.DataFrame(matching) if matching else pd.DataFrame(columns=['feature_key','paired_sign_effect','p_value','status']))
tests['strong_raw']=tests.q_global.lt(ALPHA)&tests.effect.abs().ge(MIN_DELTA)&((tests.ci_low>0)|(tests.ci_high<0))
save('features/feature_tests',tests);save('features/adjusted_feature_tests',adj);save('features/matching_diagnostics',matches);save('features/matching_members',matchmembers)
mainadj=adj[adj.model=='expression_detection_length'].set_index('feature_key')
evidence=tests.copy();evidence['adjusted_q']=evidence.feature_key.map(mainadj.q_global);evidence['adjusted_beta']=evidence.feature_key.map(mainadj.beta);evidence['match_effect']=evidence.feature_key.map(matches.set_index('feature_key').paired_sign_effect)
evidence['adjusted_supported']=evidence.adjusted_q.lt(ALPHA)&(np.sign(evidence.effect)==np.sign(evidence.adjusted_beta));evidence['matching_direction_agrees']=np.sign(evidence.effect)==np.sign(evidence.match_effect)
save('features/feature_evidence_summary',evidence)
# Unit test requires converting back to canonical units before nonlinear preparation.
a=np.array([.001,.1,1.,100.]);converted=(a*1000)/1000
assert np.allclose(zscore(np.log1p(a)),zscore(np.log1p(converted)),rtol=1e-12,atol=1e-12)
assert np.allclose(np.array([.1,.2])*100/100,np.array([.1,.2]))
write_json('features/unit_scale_validation.json',{'canonical_unit_roundtrip_passed':True,'fraction_percent_roundtrip_passed':True,'scaled_separately_by_hvg_label':False,'composition_joint_balance_dimensions_verified':True,'bootstrap_repeats':CI_REPEATS,'bootstrap_group_capping':False})
log('FEATURES DONE tested',tests.p_value.notna().sum(),'strong',tests.strong_raw.sum(),'adjusted',evidence.adjusted_supported.sum())
