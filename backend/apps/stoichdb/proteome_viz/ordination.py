import numpy as np
from sklearn.decomposition import PCA
from scipy.spatial.distance import pdist,squareform
from scipy.cluster.hierarchy import linkage,leaves_list
from .statistics import robust
from .contracts import FINGERPRINT

def pca(a,scale=True):
    a=np.asarray(a,float);mask=np.isfinite(a).all(1);x=a[mask]
    if len(x)<3:return {'status':'unavailable','reason':'insufficient_n','n':len(x),'mask':mask}
    if scale:x,scales=robust(x)
    else:scales={'transform':'pretransformed input; no additional robust scaling'}
    rank=np.linalg.matrix_rank(x-x.mean(0),tol=1e-12);k=min(2,rank)
    if k==0:return {'status':'unavailable','reason':'constant_matrix','n':len(x),'mask':mask}
    model=PCA(k,svd_solver='full');scores=model.fit_transform(x);components=model.components_.copy()
    for j in range(k):
        if components[j,np.argmax(abs(components[j]))]<0:scores[:,j]*=-1;components[j]*=-1
    directions=np.full((x.shape[1],k),np.nan)
    for j in range(x.shape[1]):
        if np.ptp(x[:,j])>0:
            for c in range(k):directions[j,c]=np.corrcoef(x[:,j],scores[:,c])[0,1]
    return {'status':'available' if k==2 else 'partial','reason':None if k==2 else 'rank_one','n':len(x),'mask':mask,'coordinates':scores,'components':components,'directions':directions,'variance':model.explained_variance_ratio_,'scaling':scales,'rank':int(rank)}

def cohort(rows):
    x=np.array([[r['means'].get(f,np.nan) for f in FINGERPRINT] for r in rows],float)
    if not len(x):return {'status':'unavailable','reason':'no_fingerprints'}
    raw=x.copy()
    x[:,8]=np.where(x[:,8]>0,np.log10(x[:,8]),np.nan)
    if not np.isfinite(x).all():return {'status':'unavailable','reason':'incomplete_species_fingerprint','unavailable_species':[r['species_id'] for i,r in enumerate(rows) if not np.isfinite(x[i]).all()]}
    z,sc=robust(x);w=z/np.sqrt(np.array([3]*3+[6]*6+[1,1]))
    d=squareform(pdist(w))/2 if len(rows)>1 else np.zeros((1,1))
    tree=linkage(squareform(d,checks=False),method='average',optimal_ordering=True) if len(rows)>1 else np.empty((0,4))
    order=leaves_list(tree).tolist() if len(rows)>1 else [0]
    p=pca(w,scale=False)
    return {'status':'available' if len(rows)>=3 else 'partial','species':rows,'fields':FINGERPRINT,'weighted':w,'z':z,'distance':d,'order':order,'linkage':tree,'dispersion':z.std(0),'raw_summary':[{'field':f,'min':float(raw[:,i].min()),'max':float(raw[:,i].max()),'sd':float(raw[:,i].std()),'n_species':len(rows)} for i,f in enumerate(FINGERPRINT)],'pca':p,'scaling':sc,'families':[3]*3+[6]*6+[1,1]}
