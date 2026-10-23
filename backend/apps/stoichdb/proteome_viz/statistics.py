import numpy as np
from scipy.stats import spearmanr,rankdata

QUANTILES=np.array([0,.05,.25,.5,.75,.95,1])

def finite(a):
    a=np.asarray(a,float);return a[np.isfinite(a)]

def robust(a):
    a=np.asarray(a,float);one=a.ndim==1
    if one:a=a[:,None]
    z=np.full_like(a,np.nan);med=np.full(a.shape[1],np.nan);scale=np.ones(a.shape[1]);mad=np.zeros(a.shape[1]);fallback=[]
    for j in range(a.shape[1]):
        good=np.isfinite(a[:,j]);v=a[good,j]
        if not len(v):fallback.append('unavailable');continue
        med[j]=np.median(v);mad[j]=np.median(abs(v-med[j]));sd=np.std(v)
        scale[j]=mad[j] if mad[j]>1e-12 else sd if sd>1e-12 else 1.
        fallback.append('MAD' if mad[j]>1e-12 else 'SD' if sd>1e-12 else 'constant')
        z[good,j]=(v-med[j])/scale[j]
    return (z[:,0] if one else z),{'median':med.tolist(),'mad':mad.tolist(),'scale':scale.tolist(),'fallback':fallback}

def summary(a):
    a=np.asarray(a,float);v=finite(a)
    base={'n_source':len(a),'n_valid':len(v),'n_missing':len(a)-len(v),'n_zero':int((v==0).sum())}
    if not len(v):return {**base,'quantiles':None,'mean':None,'status':'unavailable'}
    _,sc=robust(v)
    return {**base,'quantiles':np.quantile(v,QUANTILES,method='linear').tolist(),'mean':float(np.mean(v)),'mad':sc['mad'][0],'scale':sc['scale'][0],'fallback':sc['fallback'][0],'status':'available'}

def histogram(a,log=False):
    v=finite(a);invalid=int((v<=0).sum()) if log else 0
    if log:v=v[v>0]
    if not len(v):return {'edges':[],'counts':[],'n_valid':0,'invalid_nonpositive':invalid,'kind':'unavailable'}
    tolerance=32*np.finfo(float).eps*max(1.,float(np.max(abs(v))))
    if np.ptp(v)<=tolerance:return {'edges':[float(np.median(v))],'counts':[len(v)],'n_valid':len(v),'invalid_nonpositive':invalid,'kind':'point_mass','value_bounds':[float(v.min()),float(v.max())],'numerical_tolerance':tolerance}
    b=np.histogram_bin_edges(np.log10(v) if log else v,bins='fd');nb=int(np.clip(len(b)-1,14,70))
    edges=np.geomspace(v.min(),v.max(),nb+1) if log else np.linspace(v.min(),v.max(),nb+1)
    counts,edges=np.histogram(v,edges)
    assert counts.sum()==len(v)
    return {'edges':edges.tolist(),'counts':counts.tolist(),'n_valid':len(v),'invalid_nonpositive':invalid,'kind':'histogram','axis_transform':'log10' if log else 'identity'}

def ecdf(a,compress=True):
    v=finite(a)
    if not len(v):return {'x':[],'cdf':[],'n':0}
    x,c=np.unique(v,return_counts=True);cdf=np.cumsum(c)/len(v)
    if compress and len(x)>2002:
        # The step's omitted cumulative mass is bounded by 0.001; endpoints retained.
        keep=np.unique(np.r_[0,np.searchsorted(cdf,np.linspace(0,1,2001)),len(x)-1]);keep=keep[keep<len(x)]
        x,cdf=x[keep],cdf[keep]
    return {'x':x.tolist(),'cdf':cdf.tolist(),'n':len(v),'display_max_cdf_error':.001 if compress else 0}

def correlation(x,y):
    x,y=np.asarray(x,float),np.asarray(y,float);good=np.isfinite(x)&np.isfinite(y);x,y=x[good],y[good]
    reason='insufficient_n' if len(x)<3 else 'constant_variable' if np.ptp(x)==0 or np.ptp(y)==0 else None
    return {'n':len(x),'rho':None if reason else float(spearmanr(x,y).statistic),'reason':reason}

def conditional(x,y,k=4):
    x,y=np.asarray(x,float),np.asarray(y,float);good=np.isfinite(x)&np.isfinite(y);x,y=x[good],y[good]
    if not len(x):return []
    edges=np.unique(np.quantile(x,np.linspace(0,1,k+1)));idx=np.searchsorted(edges[1:-1],x,side='right')
    groups=[]
    for i in range(max(1,len(edges)-1)):
        use=idx==i
        if not use.any():continue
        groups.append({'group_id':i,'left':float(edges[i]),'right':float(edges[min(i+1,len(edges)-1)]),'right_closed':i==max(0,len(edges)-2),'n':int(use.sum()),'x_median':float(np.median(x[use])),'quantiles':np.quantile(y[use],[.05,.1,.25,.5,.75,.9,.95]).tolist(),'summary':summary(y[use]),'ecdf':ecdf(y[use]),'_members':np.flatnonzero(good)[use]})
    assert sum(g['n'] for g in groups)==len(x)
    return groups

def percentile(a):
    a=np.asarray(a,float);good=np.isfinite(a);r=np.full(len(a),np.nan)
    if good.any():r[good]=100*rankdata(a[good],method='average')/good.sum()
    return r
