import numpy as np,pandas as pd,warnings
from scipy import stats
from backend.analysis_engine.phase2.comparison_stats import cliffs_delta_from_u
def fdr(values,method='bh'):
    a=np.asarray(values,dtype=float);out=np.full(a.shape,np.nan)
    ok=np.isfinite(a)
    if ok.any():out[ok]=stats.false_discovery_control(np.clip(a[ok],0,1),method=method)
    return out

def add_fdr(df,p='p_value',q='q_global'):
    if p not in df:df[p]=np.nan
    df[q]=fdr(df[p].to_numpy());df[q+'_by']=fdr(df[p].to_numpy(),'by')
    return df

def zscore(x):
    x=np.asarray(x,float);s=np.nanstd(x)
    return (x-np.nanmean(x))/s if s>1e-12 else np.full_like(x,np.nan)

def delta(x,y):
    a=np.sort(np.asarray(y,float));x=np.asarray(x,float)
    return float((np.searchsorted(a,x,'left').sum()-(len(a)-np.searchsorted(a,x,'right')).sum())/(len(x)*len(a)))

def delta_ci(x,y):
    x=np.asarray(x,float);y=np.asarray(y,float)
    sx=np.sort(x);sy=np.sort(y)
    px=(np.searchsorted(sy,x,'left')+np.searchsorted(sy,x,'right'))/(2*len(y))
    py=(len(x)-(np.searchsorted(sx,y,'left')+np.searchsorted(sx,y,'right'))/2)/len(x)
    auc=px.mean();se=2*np.sqrt(np.var(px,ddof=1)/len(x)+np.var(py,ddof=1)/len(y))
    return max(-1,2*auc-1-1.96*se),min(1,2*auc-1+1.96*se)

def bootstrap_delta(x,y,repeats=500,seed=42):
    x=np.asarray(x,float);y=np.asarray(y,float)
    support=np.unique(np.r_[x,y]);nx=len(x);ny=len(y)
    px=np.bincount(np.searchsorted(support,x),minlength=len(support))/nx
    py=np.bincount(np.searchsorted(support,y),minlength=len(support))/ny
    rng=np.random.default_rng(seed);vals=[]
    for begin in range(0,repeats,25):
        b=min(25,repeats-begin)
        cx=rng.multinomial(nx,px,size=b);cy=rng.multinomial(ny,py,size=b)
        u=(cx*(np.cumsum(cy,axis=1)-0.5*cy)).sum(axis=1)
        vals.extend(2*u/(nx*ny)-1)
    return tuple(np.quantile(vals,[.025,.975]))

def rank_test(x,y,boot=False,seed=42,min_group_n=20,repeats=500):
    x=np.asarray(x,float);y=np.asarray(y,float);x=x[np.isfinite(x)];y=y[np.isfinite(y)]
    if min(len(x),len(y))<min_group_n:return {'n1':len(x),'n0':len(y),'status':'insufficient_group_n','p_value':np.nan}
    if np.ptp(np.r_[x,y])==0:return {'n1':len(x),'n0':len(y),'effect':0.,'ci_low':0.,'ci_high':0.,'p_value':1.,'status':'constant'}
    test=stats.mannwhitneyu(x,y,alternative='two-sided',method='asymptotic')
    d=cliffs_delta_from_u(test.statistic,len(x),len(y))
    lo,hi=bootstrap_delta(x,y,repeats=repeats,seed=seed) if boot else delta_ci(x,y)
    return {'n1':len(x),'n0':len(y),'median1':np.median(x),'median0':np.median(y),'effect':d,'ci_low':lo,'ci_high':hi,'p_value':test.pvalue,'status':'tested','ci_method':('nonparametric_full_gene_bootstrap_'+str(repeats)) if boot else 'DeLong_AUC_asymptotic'}

def glm(y,X,target=-1):
    import statsmodels.api as sm
    from scipy.special import expit
    y=np.asarray(y,float);X=np.asarray(X,float)
    ok=np.isfinite(X).all(axis=1)&np.isfinite(y);y=y[ok];X=X[ok]
    if len(y)<40 or min(np.sum(y==1),np.sum(y==0))<10:return {'status':'insufficient_group_n','p_value':np.nan,'n_used':len(y)}
    if np.linalg.matrix_rank(X)<X.shape[1]:return {'status':'rank_deficient','p_value':np.nan,'n_used':len(y)}
    try:
        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter('always')
            fit=sm.GLM(y,X,family=sm.families.Binomial()).fit(maxiter=60,tol=1e-8)
        if not fit.converged or any('separation' in str(w.message).lower() for w in ws):return {'status':'separation_or_nonconvergence','p_value':np.nan,'n_used':len(y)}
        b=float(fit.params[target]);se=float(fit.bse[target]);p=float(fit.pvalues[target])
        if not np.isfinite([b,se,p]).all() or abs(b)>25 or se>10:return {'status':'unstable_fit','p_value':np.nan,'n_used':len(y)}
        return {'status':'estimated','beta':b,'se':se,'odds_ratio':np.exp(b),'ci_low':np.exp(b-1.96*se),'ci_high':np.exp(b+1.96*se),'p_value':p,'n_used':len(y)}
    except Exception as e:return {'status':'fit_failed_'+type(e).__name__,'p_value':np.nan,'n_used':len(y)}
