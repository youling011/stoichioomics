import re
import numpy as np
from .statistics import numbers
def natural(s):return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)',str(s))]
def build(g):
    ids=g.gene_id.astype(str).to_numpy();seq=g.seqid.fillna('').astype(str).to_numpy();pos=numbers(g.start_1).to_numpy(float)
    located=(seq!='')&np.isfinite(pos)&(pos>=0);tracks={};members={}
    for sid in sorted(set(seq[located]),key=natural):
        ix=np.flatnonzero(located&(seq==sid));x=pos[ix];lo=float(x.min());hi=float(x.max());track={'seqid':sid,'n_source':len(ix),'min_start':lo,'max_start':hi}
        for cid,bins,key in [('OV02',48,'island_score'),('OV03',60,'delta_gc')]:
            y=g[key].to_numpy(float)[ix];b=np.clip(np.floor((x-lo)/(hi-lo+1 if cid=='OV02' else hi-lo or 1)*bins).astype(int),0,bins-1);rows=[]
            for k in range(bins):
                use=(b==k)&np.isfinite(y);v=y[use];selection=f'{cid}:track:{sid}:{k}';members[selection]=ids[ix[use]].tolist()
                q=np.quantile(v,[.25,.5,.75]).tolist() if len(v) else [None]*3
                rows.append({'index':k,'start':lo+k*(hi+1-lo)/bins,'end':lo+(k+1)*(hi+1-lo)/bins,'relative_position':(k+.5)/bins,'q25':q[0],'median':q[1],'q75':q[2],'n':len(v),'selection_id':selection})
            track[cid]=rows
        tracks[sid]=track
    return {'tracks':list(tracks.values()),'n_source':len(g),'n_located':int(located.sum()),'n_unlocated':int((~located).sum()),'strategy_counts':g.exon_seq_strategy.value_counts(dropna=False).to_dict() if 'exon_seq_strategy' in g else {}},members
