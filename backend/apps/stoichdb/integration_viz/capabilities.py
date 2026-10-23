"""Whole-registry capability audit, never a visualization precomputation.

No distributions, correlations, scores, thresholds, PCA or species artifacts are
generated here. All primary IDs and necessary numeric columns are read in full.
"""
from pathlib import Path
import gc
import numpy as np
import pandas as pd
from .source import registry,release,signature,digest,read,header,supplement
from .contracts import MODES,META,KEY,CORE,FP
from .statistics import numbers
from .mapping import link,aggregate
from .analysis import agreement
def scan(sid):
    ds=registry(sid);frames={};audit={};fields={}
    needed={'genome':['gene_id','source_gene_id','seqid','start_1','coding_valid','exon_seq_strategy']+FP['genome'],'transcriptome':['transcript_id','gene_id','protein_isoelectric_point','protein_gravy']+FP['transcriptome'],'proteome':META['proteome']+FP['proteome']}
    for m in MODES:
        try:
            d=ds[m];sig=signature(d.core_csv_path);f=read(d.core_csv_path,m);stats={};ks=[]
            for k in f:
                if k in META[m]:continue
                x=f[k].to_numpy(dtype=float) if pd.api.types.is_numeric_dtype(f[k]) else numbers(f[k]).to_numpy(float);good=np.isfinite(x);v=x[good];stats[k]={'n_valid':int(good.sum()),'n_missing':int((~good).sum()),'n_zero':int((v==0).sum()),'constant':bool(len(v) and np.ptp(v)==0)};ks.append(k)
                if k in needed[m]:f[k]=x
            audit[m]={'status':'available','dataset_id':d.dataset_id,'signature':sig,'sha256':digest(d.core_csv_path),'n_source':len(f),'header':list(f),'missing_expected_fields':[k for k in CORE[m]+META[m] if k not in f],'numeric_capabilities':stats,'primary_ids_unique':True}
            if signature(d.core_csv_path)!=sig:raise ValueError('source_changed_during_capability_scan')
            frames[m]=f[[k for k in needed[m] if k in f]].copy();fields[m]=[k for k in FP[m] if k in f];del f;gc.collect()
        except (ValueError,OSError,KeyError) as e:audit[m]={'status':'invalid_source','reason':str(e)}
    result={'species_id':sid,'release_id':release(),'audit_kind':'whole-source capability only; no visualization precomputation','core':audit,'status':'classified'}
    if len(frames)!=3:result['modules']={'raw_atlas':{m:audit[m]['status'] for m in MODES},'cross':'invalid_source'};return result
    linked,mapping=link(frames);fields={'genome':['exon_atoms_N_per_base','exon_gc_percent'],'transcriptome':['atoms_per_nt_N','gc_content'],'proteome':['N_atoms_per_aa']};j=aggregate(linked,fields);exact_n,pairs=exact_pair_capability(linked['transcriptome'],linked['proteome']);keys=['genome__exon_atoms_N_per_base','transcriptome__atoms_per_nt_N','proteome__N_atoms_per_aa'];chain=int(j[keys].notna().all(axis=1).sum())
    g=frames['genome'];_,full=supplement(g,ds['genome'].full_csv_path);partial=full['status']!='available' or bool(full.get('missing_full_columns'))
    result.update(source_rows={m:audit[m]['n_source'] for m in MODES},mapping={k:v for k,v in mapping.items() if k!='protein_conflicts'},exact_pair_n=exact_n,valid_pi_pair_n=pairs,n_complete_N_genes=chain,supplement=full,modules={'raw_atlas':{m:'available' for m in MODES},'X0':'available','X1':'available' if chain else 'unavailable','X2':'available' if j[['genome__exon_gc_percent','transcriptome__gc_content']].notna().all(axis=1).any() else 'unavailable','X3':'available' if mapping['T_P'] else 'unavailable','X4':'available' if pairs else 'unavailable','X5':'partial' if chain and partial else 'available' if chain else 'unavailable','X6':'available','X7':'available' if all(jk in audit[m]['numeric_capabilities'] and audit[m]['numeric_capabilities'][jk]['n_valid'] for m in MODES for jk in FP[m]) else 'unavailable','X8':'available' if pairs and chain else 'unavailable','OV02':'partial' if partial else 'available','OV03':'available'})
    return result
def exact_pair_capability(t,p):
    # The audit needs pair counts and finite evidence, not protein-ID string
    # aggregation or per-pair scores. Use the identical exact-ID/gene rules with
    # vectorized group reductions; every source row is still examined.
    f=p.loc[p._gene.ne(''),['_gene','transcript_id','ensembl_transcript_id','pI']].copy();f['_tid']=f.transcript_id.where(f.transcript_id.ne(''),f.ensembl_transcript_id);f=f[f._tid.ne('')];f['_pi']=numbers(f.pI)
    grouped=f.groupby('_tid').agg(gene=('_gene','first'),gene_n=('_gene','nunique'),pi_mean=('_pi','mean'));grouped=grouped[grouped.gene_n.eq(1)]
    tx=t.set_index('transcript_id')[['_gene','protein_isoelectric_point']];paired=tx.join(grouped,how='inner');paired=paired[paired._gene.eq(paired.gene)]
    with np.errstate(over='ignore',invalid='ignore'):valid=np.isfinite(paired.pi_mean.to_numpy(float)-numbers(paired.protein_isoelectric_point).to_numpy(float))
    return len(paired),int(valid.sum())
