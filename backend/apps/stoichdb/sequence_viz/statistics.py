import numpy as np
from scipy.ndimage import gaussian_filter
import contourpy
from backend.apps.stoichdb.proteome_viz.statistics import summary,robust,ecdf,conditional,correlation,percentile,finite
from backend.apps.stoichdb.proteome_viz.density import hexbin
def histogram(a,log=False):
    a=finite(a);a=a[a>0] if log else a
    if not len(a):return {'kind':'unavailable','counts':[],'edges':[],'n_valid':0}
    if np.ptp(a)==0:return {'kind':'point_mass','counts':[len(a)],'edges':[float(a[0])],'n_valid':len(a)}
    edges=np.geomspace(a.min(),a.max(),41) if log else np.linspace(a.min(),a.max(),41);counts,_=np.histogram(a,edges)
    assert counts.sum()==len(a)
    return {'kind':'histogram','counts':counts.tolist(),'edges':edges.tolist(),'n_valid':len(a),'axis_transform':'log10' if log else 'identity'}
def kde(a):
    v=finite(a);tol=32*np.finfo(float).eps*max(1.,np.max(abs(v))) if len(v) else 0
    if len(v)<2 or np.ptp(v)<=tol:return {'kind':'point_mass','x':[float(np.median(v))] if len(v) else [],'density':[1.] if len(v) else [],'n':len(v)}
    h=float(np.std(v,ddof=1)*len(v)**(-.2));xs=np.linspace(v.min(),v.max(),128);u,w=np.unique(v,return_counts=True);ys=np.zeros(128)
    for i in range(0,len(u),4096):ys+=np.exp(-.5*((xs[:,None]-u[None,i:i+4096])/h)**2)@w[i:i+4096]
    ys/=len(v)*h*np.sqrt(2*np.pi)
    return {'kind':'gaussian_kde','x':xs.tolist(),'density':ys.tolist(),'n':len(v),'bandwidth':h,'rule':'Scott, full N and expanded sample SD','display_domain':'all finite min/max, 128 points'}
def profile(a,field='',unit='',violin=False):
    p={**summary(a),'field':field,'unit':unit,'histogram':histogram(a),'ecdf':ecdf(a)}
    if violin:p['kde']=kde(a)
    return p
def native(a):
    a=np.asarray(a,float);med=np.nanmedian(a,axis=0);mad=np.nanmedian(abs(a-med),axis=0);return (a-med)/np.where(mad>1e-12,mad,1.)
def mean_available(a):
    a=np.asarray(a,float);n=np.isfinite(a).sum(1);return np.divide(np.nansum(a,axis=1),n,out=np.full(len(a),np.nan),where=n>0)
def smooth_contours(x,y):
    good=np.isfinite(x)&np.isfinite(y);x,y=np.asarray(x)[good],np.asarray(y)[good]
    if len(x)<3 or np.ptp(x)==0 or np.ptp(y)==0:return {'status':'unavailable','reason':'rank_lt_two','paths':[]}
    h,xe,ye=np.histogram2d(x,y,bins=70);assert int(h.sum())==len(x)
    z=gaussian_filter(h,sigma=1.2,mode='reflect',truncate=4.);flat=np.sort(z.ravel())[::-1];cum=np.cumsum(flat)/z.sum();xx=(xe[:-1]+xe[1:])/2;yy=(ye[:-1]+ye[1:])/2;gen=contourpy.contour_generator(x=xx,y=yy,z=z.T);paths=[]
    for mass in [.5,.8,.95]:
        level=float(flat[min(np.searchsorted(cum,mass),len(flat)-1)])
        paths.append({'mass':mass,'threshold':level,'region_mass':float(z[z>=level].sum()/z.sum()),'lines':[p.tolist() for p in gen.lines(level)]})
    return {'status':'available','name':'smoothed count mass, not KDE or CI','grid':[70,70],'sigma':1.2,'mode':'reflect','truncate':4.,'n_fit':len(x),'paths':paths}
def pareto(x,y):
    good=np.isfinite(x)&np.isfinite(y);out=np.zeros(len(x),bool);indices=np.flatnonzero(good);order=indices[np.lexsort((-y[indices],x[indices]))];best=-np.inf;i=0
    while i<len(order):
        j=i+1
        while j<len(order) and x[order[j]]==x[order[i]]:j+=1
        local=np.max(y[order[i:j]])
        if local>best:out[order[i:j]]=y[order[i:j]]==local
        best=max(best,local);i=j
    return out
