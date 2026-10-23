from .runtime import *
log('S11 candidate evidence integration')
labels=load('labels/hvg_labels');e=load('features/feature_evidence_summary');fs=load('stability/feature_stability');gs=load('stability/gene_hvg_stability');names=load('annotations/gene_names');membership=load('gene_sets/gene_feature_links');ann=load('annotations/gene_term_membership')
strong=e[e.strong_raw].copy();strong['recommended_direction']=np.where(strong.effect>0,'high','low')
links=membership.merge(strong[['feature_key','omics','family','recommended_direction','effect','ci_low','ci_high','q_global','adjusted_q','adjusted_supported','matching_direction_agrees']],on='feature_key',how='inner')
links=links[links.direction==links.recommended_direction].merge(fs,on='feature_key',how='left')
links['voting_family']=np.where(links.family.isin(['aa_freq','aa_pct']),'amino_acid_composition',links.omics+'::'+links.family)
links['evidence_group']=links.redundancy_group
links=links.sort_values(['gene_id','q_global','feature_key']).drop_duplicates(['gene_id','evidence_group'])
links['statistical_level']='feature_between_gene_sets; not a gene p-value'
save('candidates/candidate_evidence',links)
candidate=labels[labels.is_hvg&labels.gene_id.isin(links.gene_id)].copy()
name_map=names.drop_duplicates('gene_id').set_index('gene_id').gene_name
candidate['gene_name']=candidate.gene_id.map(name_map).fillna(candidate.gene_id)
candidate=candidate.merge(gs,on='gene_id',how='left')
candidate['correlation_clusters_descriptive']=candidate.gene_id.map(links.groupby('gene_id').redundancy_group.nunique()).fillna(0).astype(int)
candidate['feature_family_support_count']=candidate.gene_id.map(links.groupby('gene_id').voting_family.nunique()).fillna(0).astype(int)
candidate['adjusted_support_groups']=candidate.gene_id.map(links[links.adjusted_supported].groupby('gene_id').voting_family.nunique()).fillna(0).astype(int)
candidate['matched_direction_groups']=candidate.gene_id.map(links[links.matching_direction_agrees].groupby('gene_id').voting_family.nunique()).fillna(0).astype(int)
candidate['annotated']=candidate.gene_id.isin(ann.gene_id)
subset=load('enrichment/feature_set_ora');conditional=load('enrichment/within_hvg_ora');wp=load('within_pathway/within_pathway_tests')
pathlinks=[]
validpairs=set(zip(strong.feature_key,strong.recommended_direction))
set_genes={sid:set(g.gene_id) for sid,g in membership.groupby('set_id')}
term_genes={tid:set(g.gene_id) for tid,g in ann.groupby('term_key')}
for scope,table in [('subset_vs_universe',subset),('subset_within_hvg',conditional)]:
    for r in table[table.q_global.lt(ALPHA)].to_dict('records'):
        if (r['feature_key'],r['direction']) not in validpairs:continue
        for gene in sorted(set_genes.get(r['set_id'],set()) & term_genes.get(r['term_key'],set())):
            if gene:pathlinks.append({'gene_id':gene,'feature_key':r['feature_key'],'term_key':r['term_key'],'term_name':r['term_name'],'source':r['source'],'support_type':scope,'set_id':r['set_id'],'q_value':r['q_global'],'fold_enrichment':r['fold_enrichment'],'statistical_level':'gene_set_enrichment; not a gene p-value'})
annsets={t:set(g.gene_id) for t,g in ann.groupby('term_key')}
linkgenes={k:set(g.gene_id) for k,g in links.groupby('feature_key')}
for r in wp[wp.q_global.lt(ALPHA)&wp.feature_key.isin(strong.feature_key)].to_dict('records'):
    for gene in sorted(annsets[r['term_key']]&linkgenes.get(r['feature_key'],set())):
        pathlinks.append({'gene_id':gene,'feature_key':r['feature_key'],'term_key':r['term_key'],'term_name':r['term_name'],'source':r['source'],'support_type':'within_pathway_raw_difference','set_id':'','q_value':r['q_global'],'fold_enrichment':np.nan,'statistical_level':'feature difference within term; not a gene p-value'})
pl=pd.DataFrame(pathlinks,columns=['gene_id','feature_key','term_key','term_name','source','support_type','set_id','q_value','fold_enrichment','statistical_level']);save('candidates/gene_pathway_links',pl)
candidate['feature_function_supported']=candidate.gene_id.isin(pl.loc[pl.support_type.isin(['subset_vs_universe','subset_within_hvg']),'gene_id'])
candidate['within_pathway_supported']=candidate.gene_id.isin(pl.loc[pl.support_type=='within_pathway_raw_difference','gene_id'])
candidate['priority_tier']=np.select([candidate.feature_function_supported&candidate.hvg_resampling_frequency.ge(.8),candidate.within_pathway_supported&candidate.hvg_resampling_frequency.ge(.8),candidate.hvg_resampling_frequency.ge(.8)&candidate.adjusted_support_groups.ge(2)],['A feature-function and technical stability','B within-pathway and technical stability','C feature and adjusted technical stability'],default='D exploratory feature-supported HVG')
candidate=candidate.sort_values(['priority_tier','feature_family_support_count','adjusted_support_groups','hvg_resampling_frequency','hvg_score','gene_id'],ascending=[True,False,False,False,False,True])
candidate['priority_rank']=np.arange(1,len(candidate)+1);candidate['independent_validation']='not_performed'
save('candidates/candidate_genes',candidate)
save('candidates/prioritized_candidates',candidate[candidate.priority_tier.str.startswith(('A','B'))])
save('candidates/unannotated_feature_candidates',candidate[~candidate.annotated])
save('candidates/gene_term_links',ann[ann.gene_id.isin(candidate.gene_id)])
write_json('candidates/selection_manifest.json',{'candidate_pool':'official primary H only','selection':'at least one strong-raw feature (BH<0.05, abs delta>=0.147, bootstrap CI excludes zero), direction-consistent Q20/Q80 set membership','sorting':'tier, feature-family support count, adjusted family support, cell-resampling frequency, official score, stable gene ID','family_balance':'one vote per omics-family; amino-acid fractions across all omics share one family; no extra votes from many codon components; families are not statistically independent','functional_support_requires':'same strongly differential feature-direction pair, gene is an actual enrichment-overlap member','no_gene_p_values_invented':True,'unannotated_candidates_retained':True,'same_data_dependency':'all feature/function evidence exploratory; resampling is not independent biological validation','n_candidates':len(candidate),'tier_counts':candidate.priority_tier.value_counts().to_dict()})
log('CANDIDATES DONE',len(candidate),'tiers',candidate.priority_tier.value_counts().to_dict())
