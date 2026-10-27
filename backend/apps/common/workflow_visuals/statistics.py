from __future__ import annotations
import numpy as np
import pandas as pd

def numeric(values):
    series=pd.Series(values)
    if pd.api.types.is_numeric_dtype(series.dtype):
        return series.to_numpy(dtype=float,na_value=np.nan)
    # Identifiers/hashes can resemble scientific notation with huge exponents.
    # Native pandas float inference can overflow its exponent parser on Linux.
    def parse(value):
        try:return float(value)
        except (ValueError,TypeError,OverflowError):return np.nan
    return np.fromiter((parse(v) for v in series),dtype=float,count=len(series))

def ecdf(values):
    a=numeric(values);a=a[np.isfinite(a)]
    x,n=np.unique(a,return_counts=True)
    return {'x':x.tolist(),'frequency':n.tolist(),'cumulative':np.cumsum(n).tolist(),
            'cdf':(np.cumsum(n)/len(a)).tolist() if len(a) else [],'n':len(a)}

def quantiles(values):
    a=numeric(values);a=a[np.isfinite(a)]
    if not len(a):return {'n':0,'min':None,'max':None,'q05':None,'q25':None,'q50':None,'q75':None,'q95':None}
    return {'n':len(a),'min':float(a.min()),'max':float(a.max()),
            **dict(zip(['q05','q25','q50','q75','q95'],map(float,np.quantile(a,[.05,.25,.5,.75,.95],method='linear'))))}

def percentile(values,value):
    a=numeric(values);a=a[np.isfinite(a)]
    return float(np.count_nonzero(a<=value)/len(a)) if len(a) and value is not None and np.isfinite(value) else None

def q_coordinates(values):
    q=numeric(values);valid=np.isfinite(q)&(q>=0)&(q<=1)
    return np.where(valid,-np.log10(np.maximum(np.where(valid,q,1),1e-300)),np.nan)

def hexagons(x,y,columns=44):
    """Pointy-top axial grid in normalized display coordinates; cube-round exactly once."""
    x,y=numeric(x),numeric(y);valid=np.isfinite(x)&np.isfinite(y);indices=np.flatnonzero(valid)
    if not len(indices):return [],{}, {'algorithm':'normalized_axial_cube_round_v1','columns':columns}
    a,b=x[valid],y[valid];lo=np.array([a.min(),b.min()]);hi=np.array([a.max(),b.max()]);span=np.where(hi>lo,hi-lo,1.)
    xy=(np.column_stack([a,b])-lo)/span;s=1/(np.sqrt(3)*columns)
    q=(np.sqrt(3)/3*xy[:,0]-xy[:,1]/3)/s;r=2/3*xy[:,1]/s
    cube=np.column_stack([q,-q-r,r]);rounded=np.round(cube);diff=np.abs(rounded-cube)
    biggest=np.argmax(diff,axis=1)
    for dim in range(3):
        m=biggest==dim;rounded[m,dim]=-rounded[m,(dim+1)%3]-rounded[m,(dim+2)%3]
    axial=rounded[:,[0,2]].astype(np.int64);members={}
    for index,(aq,ar) in zip(indices,axial):members.setdefault(f'{aq}:{ar}',[]).append(int(index))
    bins=[]
    for key,rows in sorted(members.items()):
        aq,ar=map(int,key.split(':'));cx=s*np.sqrt(3)*(aq+ar/2);cy=s*1.5*ar
        angles=np.deg2rad(np.arange(6)*60-30)
        vertices=np.column_stack([cx+s*np.cos(angles),cy+s*np.sin(angles)])*span+lo
        center=np.array([cx,cy])*span+lo
        bins.append({'bin_id':key,'x':float(center[0]),'y':float(center[1]),'count':len(rows),'vertices':vertices.tolist(),
                     'bounds':[float(vertices[:,0].min()),float(vertices[:,1].min()),float(vertices[:,0].max()),float(vertices[:,1].max())]})
    assert sum(v['count'] for v in bins)==len(indices)
    return bins,members,{'algorithm':'normalized_axial_cube_round_v1','columns':columns,'origin':lo.tolist(),'span':span.tolist(),'size':s}

def running_es(ranks,hits):
    score=numeric(ranks);hits=np.asarray(hits,dtype=bool)
    if len(score)!=len(hits) or not np.all(np.isfinite(score)):raise ValueError('Invalid saved ranking')
    weights=np.abs(score)*hits;den=weights.sum();miss=int((~hits).sum())
    if den<=0 or not miss:return None
    return np.cumsum(weights/den-(~hits)/miss)
