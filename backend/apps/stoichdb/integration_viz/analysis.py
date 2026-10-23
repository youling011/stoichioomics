import re,hashlib,collections
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from .statistics import numbers,finite,clean,robust,profile
from .contracts import MODES
def island(g,full_path):
    g=g.copy();extra=['locus_atoms_N_per_base','locus_atoms_P_per_base','locus_shannon_entropy_acgt'];used=[k for k in extra if k in g]
    from pathlib import Path
    if full_path and Path(full_path).is_file():
        header=pd.read_csv(full_path,nrows=0).columns.tolist();wanted=[k for k in extra if k in header]
        f=pd.read_csv(full_path,usecols=['gene_id']+wanted,keep_default_na=False,dtype={'gene_id':str})
        if f.gene_id.duplicated().any():raise ValueError('duplicate_full_gene_id')
        aligned=f.set_index('gene_id').reindex(g.gene_id)
        for k in wanted:g[k]=numbers(aligned[k]).to_numpy();used.append(k)
    for k in extra:
        if k not in g:g[k]=np.nan
    g['delta_gc']=g.promoter_gc_percent-g.exon_gc_percent;g['delta_N']=g.promoter_atoms_N_per_base-g.exon_atoms_N_per_base;g['delta_P']=g.promoter_atoms_P_per_base-g.exon_atoms_P_per_base
    comp=['locus_gc_percent','exon_gc_percent','promoter_gc_percent','locus_atoms_N_per_base','exon_atoms_N_per_base','promoter_atoms_N_per_base','locus_atoms_P_per_base','exon_atoms_P_per_base','promoter_atoms_P_per_base','locus_shannon_entropy_acgt','delta_gc','delta_N','delta_P']
    def native(x):
        v=x.dropna()
        if not len(v):return x*np.nan
        med=v.median();mad=(v-med).abs().median();return (x-med)/(mad if mad>0 else 1.)
    z=pd.concat([native(g[k]).abs() for k in comp],axis=1);g['composition_score']=z.mean(axis=1);g['composition_field_n']=z.notna().sum(axis=1)
    di=[k for k in g if re.fullmatch('locus_dinuc_.._freq',k)];co=[k for k in g if re.fullmatch('codon_..._freq',k)]
    d=np.sqrt(((g[di]-g[di].mean())**2).sum(axis=1,min_count=1));g['dinuc_score']=native(d).abs();valid=numbers(g.coding_valid).eq(1);c=pd.Series(np.nan,index=g.index)
    if valid.any():c.loc[valid]=np.sqrt(((g.loc[valid,co]-g.loc[valid,co].mean())**2).sum(axis=1,min_count=1))
    g['codon_score']=native(c).abs();g['component_n']=g[['composition_score','dinuc_score','codon_score']].notna().sum(axis=1);g['island_score']=g[['composition_score','dinuc_score','codon_score']].mean(axis=1)
    return g,{'full_columns_used':used,'missing_full_columns':[k for k in extra if k not in used],'status':'complete' if len(used)==3 else 'partial_available_components','composition_fields_total':13,'composition_fields_available':int(z.notna().any(axis=0).sum()),'n_score_finite':int(g.island_score.notna().sum())}

def agreement(t,p):
    tp=p[p._gene.ne('')].copy();tp['_tid']=tp.transcript_id.astype(str);blank=tp._tid.eq('');tp.loc[blank,'_tid']=tp.loc[blank,'ensembl_transcript_id'];tp=tp[tp._tid.ne('')]
    prot=tp.groupby('_tid').agg(protein_pi=('pI','mean'),protein_gravy=('gravy','mean'),protein_records=('protein_id','size'),protein_ids=('protein_id',lambda x:'|'.join(x)),gene=('_gene','first'),gene_n=('_gene','nunique'));prot=prot[prot.gene_n.eq(1)]
    tx=t.set_index('transcript_id')[['protein_isoelectric_point','protein_gravy','_gene']];out=tx.join(prot,how='inner',lsuffix='_rna',rsuffix='_protein');out=out[out._gene.eq(out.gene)].copy();out['pi_delta']=out.protein_pi-out.protein_isoelectric_point;out['pi_mean']=(out.protein_pi+out.protein_isoelectric_point)/2
    out['gravy_delta']=out.protein_gravy_protein-out.protein_gravy_rna if 'protein_gravy_rna' in out else np.nan
    return out

def chain_math(j,g,t,p):
    keys=['genome__exon_atoms_N_per_base','transcriptome__atoms_per_nt_N','proteome__N_atoms_per_aa'];c=j.dropna(subset=keys)[keys+['transcriptome__gc_content','genome__exon_gc_percent']].copy();refs={}
    for m,k in zip(['G','T','P'],keys):c['z'+m],refs[m]=robust(c[k])
    c['shift_GT']=c.zT-c.zG;c['shift_TP']=c.zP-c.zT;c['gc_delta']=100*c['transcriptome__gc_content']-c['genome__exon_gc_percent']
    exact=agreement(t,p);delta=exact.groupby('gene').pi_delta.apply(lambda a:a.abs().mean());c['pi_disagreement']=delta.reindex(c.index);c['genome_island']=g.set_index('gene_id').island_score.reindex(c.index)
    scores=pd.DataFrame({'G':c.genome_island,'T':c.zT.abs(),'P':c.zP.abs()},index=c.index);complete=scores.notna().all(axis=1);thresholds=scores.loc[complete].quantile(.95);flags=scores.loc[complete].ge(thresholds)
    c['outlier_pattern']=None
    if len(flags):c.loc[complete,'outlier_pattern']=flags.astype(int).astype(str).agg(''.join,axis=1)
    c['resource_magnitude']=(c.shift_GT.abs()+c.shift_TP.abs())/2;eligible=c[['resource_magnitude','gc_delta','pi_disagreement']].notna().all(axis=1)
    for k,target in [('resource_magnitude','resource_percentile'),('gc_delta','GC_percentile'),('pi_disagreement','pI_percentile')]:c.loc[eligible,target]=c.loc[eligible,k].abs().rank(method='average',pct=True)
    c['candidate_score']=100*c[['resource_percentile','GC_percentile','pI_percentile']].mean(axis=1,skipna=False);threshold=c.candidate_score.quantile(.95);c['candidate']=c.candidate_score.ge(threshold)&c.candidate_score.notna()
    directions=collections.Counter(zip(np.asarray(c.shift_GT>=0),np.asarray(c.shift_TP>=0)));quadrants={str(int(a))+str(int(b)):n for (a,b),n in directions.items()};transitions={}
    strata={}
    for m in ['G','T','P']:
        q=c['z'+m].quantile([1/3,2/3]).to_numpy();strata[m]=np.searchsorted(q,c['z'+m],side='right') if len(c) else np.array([],int)
    for a,b in [('G','T'),('T','P')]:
        counts=np.array([[((strata[a]==i)&(strata[b]==k)).sum() for k in range(3)] for i in range(3)]);den=counts.sum(axis=1,keepdims=True);prob=np.divide(counts,den,out=np.full((3,3),np.nan),where=den>0);transitions[a+b]={'counts':counts.tolist(),'probabilities':[[float(v) if np.isfinite(v) else None for v in row] for row in prob],'sum':int(counts.sum())}
    result={'n_N_chains':len(c),'robust_references':refs,'shift_GT':profile(c.shift_GT),'shift_TP':profile(c.shift_TP),'quadrants':quadrants,'x2_gc_pair_n':int(j[['genome__exon_gc_percent','transcriptome__gc_content']].notna().all(axis=1).sum()),'x3_RNA_protein_pair_n':{k:int(j[['transcriptome__gc_content','proteome__'+k]].notna().all(axis=1).sum()) for k in ['N_atoms_per_aa','pI','gravy']},'exact_transcript_pairs':len(exact),'pi_delta':profile(exact.pi_delta),'pi_delta_zero':int(exact.pi_delta.eq(0).sum()),'outlier_eligible':int(complete.sum()),'outlier_disjoint_counts':c.outlier_pattern.value_counts().to_dict(),'outlier_thresholds':{k:float(v) if np.isfinite(v) else None for k,v in thresholds.items()},'candidate_eligible':int(eligible.sum()),'candidate_count':int(c.candidate.sum()),'candidate_threshold':float(threshold) if np.isfinite(threshold) else None,'transitions':transitions,'checks':{'quadrants_conserve':sum(quadrants.values())==len(c),'outlier_partition_conserves':int(c.outlier_pattern.notna().sum())==sum(c.outlier_pattern.value_counts()),'transitions_conserve':all(v['sum']==len(c) for v in transitions.values()),'eligible_candidate_bound':int(c.candidate.sum())<=int(eligible.sum()),'no_multijoin_expansion':len(c)<=len(g)}}
    return c,exact,result
