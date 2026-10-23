from pathlib import Path
import pandas as pd,numpy as np
from .artifacts import atomic_frame,member_hash
def write_universes(root):
 root=Path(root);L=pd.read_parquet(root/'labels/hvg_labels.parquet');P=pd.read_parquet(root/'features/feature_values.parquet');A=pd.read_parquet(root/'annotations/gene_term_membership.parquet');genes=L.gene_id.to_numpy(str);H=L.is_hvg.to_numpy(bool);rows=[];members=[];seen=set()
 def add(ids,kind,feature=None,source=None):
  ids=sorted(set(map(str,ids)));digest=member_hash(ids);bid='bg_'+digest[:16];rows.append({'universe_id':bid,'kind':kind,'feature_key':feature,'source':source,'n_genes':len(ids),'member_hash':digest})
  if bid not in seen:members.extend({'background_id':bid,'gene_id':g,'background_hash':digest} for g in ids);seen.add(bid)
 add(genes,'U');add(genes[H],'H');add(genes[~H],'N')
 amasks={s:np.isin(genes,g.gene_id.unique()) for s,g in A.groupby('source')}
 for s,mask in amasks.items():add(genes[mask],'U_A',source=s)
 for feature in P.columns:
  if feature=='gene_id':continue
  valid=np.isfinite(pd.to_numeric(P[feature],errors='coerce').to_numpy(float));add(genes[valid],'U_f',feature);add(genes[valid&H],'H_f',feature);add(genes[valid&~H],'N_f',feature)
  for source,amask in amasks.items():add(genes[valid&amask],'U_fA',feature,source);add(genes[valid&amask&H],'H_fA',feature,source)
 # Term backgrounds are retained from functional testing as well as feature/annotation sets.
 old=root/'labels/universe_members.parquet'
 if old.exists():
  prior=pd.read_parquet(old)
  for bid,g in prior.groupby('background_id'):
   if bid not in seen:members.extend(g.to_dict('records'));seen.add(bid)
 atomic_frame(root/'labels/universes.parquet',pd.DataFrame(rows));atomic_frame(root/'labels/universe_members.parquet',pd.DataFrame(members,columns=['background_id','gene_id','background_hash']))
 return {'sets':len(rows),'unique_member_sets':len(seen)}
