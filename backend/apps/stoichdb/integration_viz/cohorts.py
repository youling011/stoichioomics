from backend.apps.stoichdb.feature_sources import io as feature_io
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage,leaves_list
from scipy.spatial.distance import pdist,squareform
from .contracts import MODES,FP,DEFAULT_SPECIES,unit
from .statistics import numbers
from .source import registry,release,digest,signature
from . import artifacts as a
def default_ids(sid):return DEFAULT_SPECIES+([sid] if sid not in DEFAULT_SPECIES else [])
def describe(sid):
    ds=registry(sid);descriptors={};signatures={};stats={}
    for m in MODES:
        d=ds[m];p=d.core_csv_path;sig=signature(p);cache=a.root()/'descriptors'/a.component(sid)/(m+'.json')
        if cache.is_file():
            saved=a.read(cache)
            if saved.get('signature')==sig and saved.get('dataset_id')==d.dataset_id:
                descriptors.update(saved['values']);stats.update(saved['stats']);signatures[m]=saved['source'];continue
        f=feature_io.read_csv(p,usecols=FP[m],low_memory=False);values={};s={}
        for k in FP[m]:
            x=numbers(f[k]).dropna().to_numpy();key=m+'__'+k
            values[key]=float(np.median(x)) if len(x) else None
            s[key]={'n_source':len(f),'n_valid':len(x),'unit':unit(m,k)}
        src={'dataset_id':d.dataset_id,'signature':sig,'sha256':digest(p)}
        if sig!=signature(p):raise ValueError('cohort_source_changed')
        a.write(cache,{'signature':sig,'dataset_id':d.dataset_id,'source':src,'values':values,'stats':s});descriptors.update(values);stats.update(s);signatures[m]=src
    return {'species_id':sid,'values':descriptors,'stats':stats,'source':signatures}
def identity(ids):
    # Cheap identity for ensure; content hashes are sealed by describe/build.
    return hashlib.sha256(json.dumps([release(),ids,[(sid,{m:(d.dataset_id,signature(d.core_csv_path)) for m,d in registry(sid).items()}) for sid in ids],a.implementation_hash()],sort_keys=True).encode()).hexdigest()
def path(key):
    if len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('invalid_cohort_key')
    return a.root()/'cohorts'/key[:16]/'result.json.gz'
def build(ids):
    key=identity(ids);rows=[];excluded=[]
    for sid in ids:
        try:rows.append(describe(sid))
        except Exception as e:excluded.append({'species_id':sid,'reason':str(e)})
    fields=[m+'__'+k for m in MODES for k in FP[m]];complete=[r for r in rows if all(r['values'][k] is not None for k in fields)]
    excluded.extend({'species_id':r['species_id'],'reason':'missing_descriptor'} for r in rows if r not in complete)
    x=np.array([[r['values'][k] for k in fields] for r in complete],float).reshape(-1,12);mu=x.mean(0) if len(x) else np.zeros(12);sd=x.std(0) if len(x) else np.zeros(12);variable=sd>1e-12;z=np.zeros_like(x)
    for i,m in enumerate(MODES):
        use=np.flatnonzero(variable&(np.arange(12)//4==i))
        if len(use):z[:,use]=(x[:,use]-mu[use])/sd[use]/np.sqrt(len(use))
    rank=int(np.linalg.matrix_rank(z,tol=1e-12)) if len(z) else 0;result={'cohort_key':key,'cohort_version':a.component([key,[(r['species_id'],r['source']) for r in rows]]),'release_id':release(),'species_ids':ids,'included_species':[r['species_id'] for r in complete],'excluded_species':excluded,'fields':fields,'descriptors':rows,'raw_matrix':x.tolist(),'matrix':z.tolist(),'means':mu.tolist(),'population_sd':sd.tolist(),'constant_fields':[fields[i] for i in np.flatnonzero(~variable)],'rank':rank,'status':'available' if rank and len(z)>=2 else 'unavailable','method':'whole-Core medians; cohort population z; variable layer 1/sqrt(k); full SVD; Euclidean distance; average linkage order'}
    if rank and len(z)>=2:
        u,s,vt=np.linalg.svd(z,full_matrices=False);scores=u*s;dist=squareform(pdist(z));order=leaves_list(linkage(pdist(z),method='average')).tolist() if len(z)>2 else list(range(len(z)))
        result.update(scores=scores[:,:2].tolist(),explained_variance=(s*s/(s*s).sum()).tolist(),loadings=vt[:2].T.tolist(),pc1_loadings_squared=(vt[0]**2).tolist(),distance=dist.tolist(),order=order,median=np.median(z,axis=0).tolist(),q25=np.quantile(z,.25,axis=0).tolist(),q75=np.quantile(z,.75,axis=0).tolist())
    feature_rows=[]
    for i,k in enumerate(fields):
        v=x[:,i];q=np.quantile(v,[.25,.5,.75]) if len(v) else [np.nan]*3;fallback=abs(q[1])<=1e-12
        feature_rows.append({'field':k,'mean':mu[i] if len(v) else None,'population_sd':sd[i] if len(v) else None,'min':float(v.min()) if len(v) else None,'max':float(v.max()) if len(v) else None,'range':float(np.ptp(v)) if len(v) else None,'median':q[1],'IQR':q[2]-q[0],'relative_IQR':(q[2]-q[0])/(1 if fallback else abs(q[1])),'denominator_fallback':bool(fallback),'n':len(v),'unit':unit(*k.split('__',1))})
    result['feature_ranking']=feature_rows
    if key!=identity(ids):raise ValueError('cohort_source_changed_before_publish')
    a.write(path(key),result);return result
