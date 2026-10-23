import numpy as np
from .contracts import RNA,AA,words
from .composition import counts
from .statistics import native,mean_available,percentile
def derive(ds):
    v=ds['values'];n=ds['n'];get=lambda k:v.get(k,np.full(n,np.nan));den=get('length_nt_acgu');coding=(get('aa_len')>0)&(get('codon_valid_codons')>0);v['coding_coverage_raw']=np.divide(get('orf_len_nt'),den,out=np.full(n,np.nan),where=den>0)
    audits={}
    for prefix,ws,total,partial in [('dinuc_',words(RNA,2),'dinuc_valid_pairs',False),('codon_',words(RNA,3),'codon_valid_codons',False),('aa_',AA,'aa_len',True)]:
        fields=[prefix+w+'_count' for w in ws];a,info=counts(v,fields,[prefix+w+'_freq' for w in ws],total,n,partial);audits[prefix]=info
        for j,k in enumerate(fields):v[k]=a[:,j]
    # Core fractions may reconstruct pooled nucleotide counts only after integer/closure checks.
    nf=[f'n_{w}' for w in RNA];a,info=counts(v,nf,[f'frac_{w}' for w in RNA],'length_nt_acgu',n);audits['nucleotides']=info
    for j,k in enumerate(nf):v[k]=a[:,j]
    for e in 'CHONP':
        k=f'atoms_per_nt_{e}'
        if k not in v:v[k]=np.divide(get(f'{e}_atoms'),den,out=np.full(n,np.nan),where=den>0)
        if f'{e}_atoms' not in v:v[f'{e}_atoms']=v[k]*den
    ws=words(RNA,3);freq=np.column_stack([get('codon_'+w+'_freq') for w in ws]);good=np.isfinite(freq).all(1)&(freq>=0).all(1)&(abs(freq.sum(1)-1)<=1e-6)&coding
    entropy=np.full(n,np.nan);gc3=np.full(n,np.nan);distance=np.full(n,np.nan)
    if good.any():
        f=freq[good];entropy[good]=-np.sum(np.where(f>0,f*np.log2(np.where(f>0,f,1)),0),axis=1);gc3[good]=f[:,[w[-1] in 'GC' for w in ws]].sum(1);distance[good]=np.linalg.norm(f-f.mean(0),axis=1)
    v['derived_codon_entropy_bits']=entropy;v['derived_gc3_fraction']=gc3;v['codon_distance']=distance
    resource=np.column_stack([get(k) for k in ['atoms_per_nt_N','atoms_per_nt_P','C_N_ratio','N_P_ratio','mw_rna_nmp_per_nt_Da']]);v['resource_score']=mean_available(abs(native(resource)));v['resource_coverage']=np.isfinite(resource).sum(1);v['pattern_proxy_score']=mean_available(native(np.column_stack([get(k) for k in ['gc_content','max_run_any','nt_entropy']]))*np.array([1,1,-1]))
    modules=['resource_score','pattern_proxy_score','orf_len_aa','codon_distance','protein_instability_index','max_run_any']
    for k in modules:
        a=get(k).copy()
        if k in ['orf_len_aa','codon_distance','protein_instability_index']:a[~coding]=np.nan
        v[k+'_percentile']=percentile(a)
    v['score_module_coverage']=np.isfinite(np.column_stack([v[k+'_percentile'] for k in modules])).sum(1)
    ds['coding']=coding;ds['source']['composition_reconstruction']=audits
    return ds
