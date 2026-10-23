import numpy as np
from .contracts import DNA,words
from .statistics import native,mean_available
from .composition import counts
def derive(ds):
    v=ds['values'];n=ds['n'];get=lambda k:v.get(k,np.full(n,np.nan));coding=get('coding_valid')==1
    span=get('end_1')-get('start_1')+1;span[(get('end_1')<get('start_1'))]=np.nan;v['gene_span_bp']=span
    for name,suffix in [('delta_gc_pp','gc_percent'),('delta_n','atoms_N_per_base'),('delta_p','atoms_P_per_base'),('delta_entropy_bits','shannon_entropy_acgt')]:v[name]=get('promoter_'+suffix)-get('exon_'+suffix)
    for name,k,log in [('log_span','gene_span_bp',True),('log_transcripts','transcript_count',False),('log_upstream','upstream_intergenic_bp',False)]:
        a=get(k);v[name]=np.log10(np.where(a>0,a,np.nan)) if log else np.log1p(np.where(a>=0,a,np.nan))
    v['GC12_percent']=(get('gc1_percent')+get('gc2_percent'))/2
    reconstruction={}
    for prefix,denom in [('codon_','codon_total_valid'),('promoter_dinuc_','promoter_dinuc_total_valid')]:
        ws=words(DNA,3 if prefix=='codon_' else 2);fields=[prefix+w+'_count' for w in ws]
        a,info=counts(v,fields,[prefix+w+'_freq' for w in ws],denom,n);reconstruction[prefix]=info
        for j,k in enumerate(fields):v[k]=a[:,j]
    df=[f'locus_dinuc_{w}_freq' for w in words(DNA,2)];a=np.column_stack([get(k) for k in df]);good=np.isfinite(a).all(1)&(a>=0).all(1)&(abs(a.sum(1)-1)<=1e-6)&(get('locus_dinuc_total_valid')>0);dist=np.full(n,np.nan)
    if good.any():dist[good]=np.linalg.norm(a[good]-a[good].mean(0),axis=1)
    v['dinuc_distance']=dist
    cf=[f'codon_{w}_freq' for w in words(DNA,3)];a=np.column_stack([get(k) for k in cf]);good=np.isfinite(a).all(1)&(a>=0).all(1)&(abs(a.sum(1)-1)<=1e-6)&(get('codon_total_valid')>0)&coding;dist=np.full(n,np.nan)
    if good.any():dist[good]=np.linalg.norm(a[good]-a[good].mean(0),axis=1)
    v['codon_deviation']=dist
    comp=['locus_gc_percent','exon_gc_percent','promoter_gc_percent',*[f'{r}_atoms_{e}_per_base' for e in 'NP' for r in ['locus','exon','promoter']],'locus_shannon_entropy_acgt','delta_gc_pp','delta_n','delta_p']
    a=np.column_stack([get(k) for k in comp]);v['composition_coverage']=np.isfinite(a).sum(1);v['composition_score']=mean_available(abs(native(a)));v['dinuc_score']=abs(native(v['dinuc_distance']));v['codon_score']=abs(native(dist));modules=np.column_stack([v[k] for k in ['composition_score','dinuc_score','codon_score']]);v['island_score']=mean_available(modules);v['score_module_coverage']=np.isfinite(modules).sum(1)
    ds['source']['composition_reconstruction']=reconstruction;ds['coding']=coding
    return ds
