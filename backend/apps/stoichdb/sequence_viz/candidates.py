import numpy as np
def module_score(values,module):
    a=values[module].copy();p=values.get(module+'_percentile')
    if p is not None:a[~np.isfinite(p)]=np.nan
    return a
def rank(values,ids,omics,module='',coverage='all',top_ties=0):
    allowed=['island_score','composition_score','dinuc_distance','codon_deviation'] if omics=='genome' else ['resource_score','pattern_proxy_score','orf_len_aa','codon_distance','protein_instability_index','max_run_any']
    module=module or allowed[0]
    if module not in allowed:raise ValueError('invalid_candidate_module')
    if coverage not in ['all','complete','partial']:raise ValueError('invalid_coverage')
    top_ties=int(top_ties)
    if not 0<=top_ties<=100:raise ValueError('top_ties_outside_0_100')
    score=module_score(values,module);order=np.lexsort((np.asarray(ids),-np.nan_to_num(score,nan=-np.inf)));original_rank=np.empty(len(order),int);original_rank[order]=np.arange(1,len(order)+1);full=3 if omics=='genome' else 6
    if coverage!='all':order=order[values['score_module_coverage'][order]==full] if coverage=='complete' else order[values['score_module_coverage'][order]<full]
    cutoff=None
    if top_ties:
        eligible=np.isfinite(score[order]);percentile=values.get(module+'_percentile')
        if percentile is not None:eligible&=np.isfinite(percentile[order])
        valid=order[eligible]
        if len(valid):cutoff=float(score[valid[min(top_ties,len(valid))-1]]);order=valid[score[valid]>=cutoff]
        else:order=valid
    return order,original_rank,{'module':module,'coverage':coverage,'top_ties':top_ties,'tie_cutoff_raw':cutoff,'rank_population_n':len(ids),'selected_n':len(order)}
