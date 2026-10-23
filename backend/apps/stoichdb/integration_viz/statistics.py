import re,hashlib,collections
import numpy as np
import pandas as pd
from scipy.stats import rankdata
def numbers(s):return pd.to_numeric(s.replace({'True':1,'False':0,'true':1,'false':0}),errors='coerce').replace([np.inf,-np.inf],np.nan)

def finite(a):
    x=np.asarray(a,float);return x[np.isfinite(x)]

def clean(s):return '' if s is None or (isinstance(s,float) and np.isnan(s)) else str(s).strip()

def array_hash(a):return hashlib.sha256(np.asarray(a,dtype='<f8').tobytes()).hexdigest()

def robust(s):
    x=numbers(s);v=x.dropna();med=v.median() if len(v) else np.nan;mad=(v-med).abs().median() if len(v) else np.nan
    scale=1.4826*mad;fallback='MAD'
    if not np.isfinite(scale) or mad<=1e-12:scale=v.std(ddof=0);fallback='SD'
    if not np.isfinite(scale) or scale<=1e-12:scale=1.;fallback='constant'
    return (x-med)/scale,{'n':len(v),'median':float(med) if len(v) else None,'mad':float(mad) if len(v) else None,'scale':float(scale),'fallback':fallback}

def profile(a):
    v=finite(a);result={'n_source':len(a),'n_valid':len(v),'n_missing':len(a)-len(v),'n_zero':int((v==0).sum()),'n_unique':int(len(np.unique(v)))}
    if len(v):
        q=np.quantile(v,[0,.05,.25,.5,.75,.95,1]);result.update(dict(zip(['min','p05','p25','median','p75','p95','max'],map(float,q))))
        c,e=np.histogram(v,bins=np.array([v[0]-.5,v[0]+.5]) if np.ptp(v)==0 else np.linspace(v.min(),v.max(),41));u,w=np.unique(v,return_counts=True)
        result.update(histogram_sum=int(c.sum()),ecdf_count=int(w.sum()),histogram_counts=c.tolist(),histogram_edges=e.tolist(),unique_value_frequency_sha256=array_hash(np.column_stack([u,w])))
    else:result.update(histogram_sum=0,ecdf_count=0,histogram_counts=[],histogram_edges=[])
    return result

def distribution(a,bins=45):
    v=finite(a);r=profile(a)
    r['kind']='empty' if not len(v) else 'point_mass' if np.ptp(v)==0 else 'histogram'
    if len(v):
        counts,edges=np.histogram(v,bins=[v[0]-.5,v[0]+.5] if np.ptp(v)==0 else np.linspace(v.min(),v.max(),bins+1));u,w=np.unique(v,return_counts=True)
        r['histogram']={'edges':edges.tolist(),'counts':counts.tolist()};r['ecdf']={'values':u.tolist(),'counts':w.tolist(),'cdf':(np.cumsum(w)/len(v)).tolist()}
    else:r.update(histogram={'edges':[],'counts':[]},ecdf={'values':[],'counts':[],'cdf':[]})
    for k in ['histogram_counts','histogram_edges']:r.pop(k,None)
    return r

def conditional(x,y):
    x,y=np.asarray(x,float),np.asarray(y,float);good=np.isfinite(x)&np.isfinite(y);xx,yy=x[good],y[good];membership=np.full(len(x),-1,int)
    if not len(xx):return [],membership
    bounds=np.unique(np.quantile(xx,np.linspace(0,1,11)));n=max(1,len(bounds)-1);b=np.clip(np.searchsorted(bounds,xx,side='right')-1,0,n-1);membership[good]=b
    edges=np.array([yy[0]-.5,yy[0]+.5]) if np.ptp(yy)==0 else np.linspace(yy.min(),yy.max(),51);groups=[]
    for i in range(n):
        v=yy[b==i];vx=xx[b==i]
        if not len(v):continue
        q=np.quantile(v,[.05,.25,.5,.75,.95]);c,_=np.histogram(v,edges)
        groups.append({'index':i,'n':len(v),'x_median':float(np.median(vx)),'q05':float(q[0]),'q25':float(q[1]),'median':float(q[2]),'q75':float(q[3]),'q95':float(q[4]),'ridge_counts':c.tolist(),'ridge_edges':edges.tolist()})
    return groups,membership
