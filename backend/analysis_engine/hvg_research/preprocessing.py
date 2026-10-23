import numpy as np
from scipy.linalg import helmert
def canonicalize(a,unit):
 a=np.asarray(a,float)
 if unit in ['%','percent']:return a/100,'fraction'
 if unit in ['kb','kilobase']:return a*1000,'bp'
 if unit in ['Mb','megabase']:return a*1000000,'bp'
 return a,str(unit or '')
def scale_column(a,robust=True):
 a=np.asarray(a,float);center=np.nanmedian(a) if robust else np.nanmean(a);scale=np.subtract(*np.nanpercentile(a,[75,25])) if robust else np.nanstd(a)
 if not scale:scale=np.nanstd(a)
 return (a-center)/scale if scale else np.full_like(a,np.nan)
def composition_coordinates(a,pseudocount=1e-6):
 a=np.asarray(a,float)
 if not np.isfinite(a).all() or (a<0).any() or not np.isclose(a.sum(1),1,rtol=.02,atol=.005).all():raise ValueError('Incomplete/invalid closed composition')
 log=np.log(a+pseudocount);return log-log.mean(1,keepdims=True),log@helmert(a.shape[1],full=False).T
