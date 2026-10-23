import numpy as np,pandas as pd
from scipy.stats import hypergeom
from .statistics import add_fdr
from .artifacts import atomic_frame,member_hash,content_hash
def ora(query,background,members,terms,*,min_term=10,max_term=500,min_query=1,fields=None,term_index=None):
 query=set(map(str,query));background=set(map(str,background))
 if not query<=background:raise ValueError('ORA query is not subset of background')
 rows=[];N=len(background);n=len(query)
 indexed=term_index if term_index is not None else {t:set(g.gene_id) for t,g in members.groupby('term_key')}
 for term in terms.to_dict('records'):
  hit=indexed.get(term['term_key'],set())&background;K=len(hit)
  if not min_term<=K<=max_term:continue
  overlap=sorted(query&hit);k=len(overlap);valid=N>0 and n>=min_query and n<N
  rows.append({**(fields or {}),**{k:term[k] for k in ['source','term_key','term_id','term_name']},'N':N,'K':K,'n':n,'k':k,'p_value':float(hypergeom.sf(k-1,N,K,n)) if valid else np.nan,'fold_enrichment':(k/n)/(K/N) if n and K and N else np.nan,'background_id':'bg_'+member_hash(background)[:16],'background_hash':member_hash(background),'query_hash':member_hash(query),'overlap_genes':';'.join(overlap),'status':'tested' if valid else 'insufficient_query_or_no_contrast'})
 return pd.DataFrame(rows,columns=list(dict.fromkeys(list((fields or {}).keys())+['source','term_key','term_id','term_name','N','K','n','k','p_value','fold_enrichment','background_id','background_hash','query_hash','overlap_genes','status'])))
def write_baseline(root,cfg):
 L=pd.read_parquet(root/'labels/hvg_labels.parquet');A=pd.read_parquet(root/'annotations/gene_term_membership.parquet');T=pd.read_parquet(root/'annotations/terms.parquet');parts=[];bgrows=[];H=set(L.loc[L.is_hvg,'gene_id'])
 for source,g in A.groupby('source'):
  bg=set(g.gene_id)&set(L.gene_id);parts.append(ora(H&bg,bg,A,T[T.source.eq(source)],min_term=cfg['enrichment']['min_term_size'],max_term=cfg['enrichment']['max_term_size'],min_query=cfg['gene_sets']['min_annotated_query'],fields={'query_scope':'original_hvg','set_id':'H','family_id':'F3'}));bgrows.extend({'background_id':'bg_'+member_hash(bg)[:16],'gene_id':v,'source':source,'kind':'annotation_background'} for v in sorted(bg))
 frame=pd.concat(parts,ignore_index=True) if parts else ora(set(),set(),A,T)
 frame=add_fdr(frame);atomic_frame(root/'enrichment/baseline_ora.parquet',frame);atomic_frame(root/'labels/baseline_background_members.parquet',pd.DataFrame(bgrows,columns=['background_id','gene_id','source','kind']))
 return {'tested':len(frame),'significant':int(frame.q_global.lt(cfg['feature_tests']['alpha']).sum()),'status':'source_missing' if A.empty else 'completed'}
