"""Additional native-component evidence, using the already versioned island method."""
import re
import numpy as np
from .analysis import island
from .statistics import numbers
FIELDS=['gene_id','composition_score','composition_field_n','dinuc_score','codon_score','component_n','island_score']
def compute(g):
    native,_=island(g,'');quality={}
    for name,pattern in [('dinuc','locus_dinuc_.._freq'),('codon','codon_..._freq')]:
        keys=[k for k in g if re.fullmatch(pattern,k)];x=g[keys].to_numpy(float);s=np.nansum(x,axis=1);valid=np.isfinite(x).any(axis=1)
        quality[name+'_noncanonical_frequency_rows']=int((valid&((x<0).any(axis=1)|(x>1).any(axis=1)|(~np.isclose(s,1,atol=1e-6)))).sum())
    quality['valid_pairs_zero_rows']=int(numbers(g.locus_dinuc_total_valid).eq(0).sum()) if 'locus_dinuc_total_valid' in g else None
    quality['coding_valid_without_valid_codons']=int((numbers(g.coding_valid).eq(1)&numbers(g.codon_total_valid).le(0)).sum()) if 'codon_total_valid' in g else None
    quality['component_n_counts']={str(k):int(v) for k,v in native.component_n.value_counts().items()};quality['composition_field_n_counts']={str(k):int(v) for k,v in native.composition_field_n.value_counts().items()};quality['policy']='QC counts only; approved native score masks are unchanged'
    return native[FIELDS],quality
def attach(built,native,quality):
    built['tables']['native_components']=native
    evidence=native.set_index('gene_id').to_dict('index')
    for key in ['chain_rows','candidates','x1_shifts']:
        for row in built['tables'].get(key,[]):row.update({k:v for k,v in evidence[row['gene_id']].items() if k!='island_score'})
    built['source'].setdefault('quality',{}).update(quality)
    built['math'].setdefault('island',{})['component_coverage']=quality
