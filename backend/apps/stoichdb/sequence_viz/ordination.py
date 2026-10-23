import numpy as np
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from threadpoolctl import threadpool_limits
from .statistics import robust
from .composition import clr
def fit(a,mask=None,composition=False):
    a=np.asarray(a,float);valid=np.isfinite(a).all(1)
    if mask is not None:valid&=mask
    if composition:valid&=(a>=0).all(1)&(a.sum(1)>0)
    x=a[valid]
    if len(x)<3:return {'status':'unavailable','reason_code':'insufficient_n','n_fit':len(x),'rank':0},None,valid,None
    x=clr(x) if composition else robust(x)[0];center=x-x.mean(0);rank=int(np.linalg.matrix_rank(center))
    if rank==0:return {'status':'unavailable','reason_code':'constant_matrix','n_fit':len(x),'rank':0},None,valid,x
    with threadpool_limits(limits=1):model=PCA(min(2,rank),svd_solver='full');scores=model.fit_transform(x)
    for j in range(scores.shape[1]):
        if model.components_[j,np.argmax(abs(model.components_[j]))]<0:scores[:,j]*=-1;model.components_[j]*=-1
    corr=np.zeros((x.shape[1],scores.shape[1]))
    for i in range(x.shape[1]):
        for j in range(scores.shape[1]):corr[i,j]=np.corrcoef(x[:,i],scores[:,j])[0,1] if np.std(x[:,i])>1e-14 else 0
    return {'status':'available' if rank>=2 else 'partial','reason_code':None if rank>=2 else 'rank_one','n_fit':len(x),'rank':rank,'components':model.components_.tolist(),'variance':model.explained_variance_ratio_.tolist(),'correlation_directions':corr.tolist(),'fit_dimensions':x.shape[1],'transform':'count + 0.5 CLR, center only' if composition else 'median/MAD→SD→1 then center','solver':'full SVD'},scores,valid,x
def cluster(x,context):
    if x is None or len(x)<3 or len(np.unique(x,axis=0))<3:return None,{'status':'unavailable','reason_code':'fewer_than_three_distinct_rows'}
    with threadpool_limits(limits=1):model=KMeans(n_clusters=3,n_init=10,random_state=20261020);labels=model.fit_predict(x)
    centers=[np.nanmedian(context[labels==i]) if np.isfinite(context[labels==i]).any() else np.inf for i in range(3)];order=np.argsort(centers,kind='stable');mapping=np.argsort(order);labels=mapping[labels]
    return labels,{'status':'available','algorithm':'KMeans','n_clusters':3,'n_init':10,'random_state':20261020,'iterations':model.n_iter_,'fit_dimensions':x.shape[1],'counts':np.bincount(labels,minlength=3).tolist()}
