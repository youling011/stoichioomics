import re,hashlib,collections
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from .statistics import numbers,finite,clean,robust,profile
from .contracts import MODES
def cross_correlations(j,fields):
    """Exact pairwise Spearman, grouped only by identical finite-value masks."""
    masks={};groups={};n=len(j)
    for m in MODES:
        groups[m]=collections.defaultdict(list)
        for field in fields[m]:
            k=m+'__'+field;mask=j[k].notna().to_numpy();sig=np.packbits(mask).tobytes();groups[m][sig].append(k);masks[sig]=mask
    out=[]
    for ma,mb in [('genome','transcriptome'),('genome','proteome'),('transcriptome','proteome')]:
        for sa,fa in groups[ma].items():
            for sb,fb in groups[mb].items():
                mask=masks[sa]&masks[sb];pairn=int(mask.sum());r=np.full((len(fa),len(fb)),np.nan)
                if pairn>=3:
                    a=rankdata(j.loc[mask,fa].to_numpy(float),axis=0,method='average');b=rankdata(j.loc[mask,fb].to_numpy(float),axis=0,method='average');a-=a.mean(axis=0);b-=b.mean(axis=0);na=np.sqrt((a*a).sum(axis=0));nb=np.sqrt((b*b).sum(axis=0));den=na[:,None]*nb[None,:];r=np.divide(a.T@b,den,out=r,where=den>0);r=np.clip(r,-1,1)
                for i,ak in enumerate(fa):
                    for k,bk in enumerate(fb):out.append({'feature_a':ak,'feature_b':bk,'pair_n':pairn,'rho':float(r[i,k]) if np.isfinite(r[i,k]) else None})
    result=pd.DataFrame(out);assert len(result)==sum(len(fields[a])*len(fields[b]) for a,b in [('genome','transcriptome'),('genome','proteome'),('transcriptome','proteome')]);return result
