"""Versioned exact coordinate ordering, independent of fitted descriptor models."""
import numpy as np
VERSION='start_gene_id_v1'
def apply(ds,built):
    if ds['omics']!='genome':return built
    from . import artifacts as store
    if built.get('reuse_analysis'):built['arrays']={k:a.copy() for k,a in store.arrays(built.pop('reuse_analysis')).items()}
    n=ds['n'];v=ds['values'];meta=ds['metadata'];start=v.get('start_1',np.full(n,np.nan));end=v.get('end_1',np.full(n,np.nan));ids=np.array(ds['ids']);seq=np.array(meta.get('seqid',['']*n));g=v.get('locus_count_G',np.full(n,np.nan));c=v.get('locus_count_C',np.full(n,np.nan));cumulative=np.full(n,np.nan);membership=np.full(n,-1,np.int32);tracks=[];order=[];offset=0
    for name in np.unique(seq):
        ix=np.flatnonzero((seq==name)&np.isfinite(start)&np.isfinite(end)&(end>=start));ix=ix[np.lexsort((ids[ix],start[ix]))]
        if not len(ix):continue
        order.extend(ix);valid=np.isfinite(g[ix])&np.isfinite(c[ix])&(g[ix]>=0)&(c[ix]>=0)&(abs(g[ix]-np.rint(g[ix]))<=1e-6)&(abs(c[ix]-np.rint(c[ix]))<=1e-6);available=ix[valid];cumulative[available]=np.cumsum(g[available]-c[available]);bounds=np.linspace(0,len(ix),min(300,len(ix))+1,dtype=int);bins=[]
        for a,b in zip(bounds[:-1],bounds[1:]):
            chunk=ix[a:b];ok=chunk[np.isfinite(cumulative[chunk])]
            if not len(ok):continue
            bins.append({'x':float(start[ok[-1]]),'value':float(cumulative[ok[-1]]),'min':float(cumulative[ok].min()),'max':float(cumulative[ok].max()),'count':len(chunk),'valid_increment_n':len(ok),'bin_id':offset});membership[chunk]=offset;offset+=1
        tracks.append({'seqid':str(name),'n':len(ix),'min':float(start[ix].min()),'max':float(end[ix].max()),'excluded_increment_n':int((~valid).sum()),'status':'partial' if not valid.all() else 'available','bins':bins})
    arrays=built['arrays'];arrays.update(GD02_order=np.array(order,np.int64),GD02_membership=membership,locus_gc_cumulative_count=cumulative)
    if 'GD15_order' in arrays:arrays['GD15_order']=np.array(order,np.int64)
    f=built['figures']['GD02'];f['data'].update(tracks=tracks,unplaced_n=n-len(order),n_coordinates=len(order),ordering=['seqid','start_1','gene_id'],coordinate_method_version=VERSION);f['method']['parameters'].update(coordinate_method_version=VERSION,sort_keys=['seqid','start_1','gene_id'],count_validation='finite nonnegative integer G and C; missing increments excluded, never zero-filled');f['status']='unavailable' if not np.isfinite(cumulative).any() else 'partial' if len(order)<n or any(t['excluded_increment_n'] for t in tracks) else 'available';f['reason_code']='full_G_C_counts_unavailable' if not np.isfinite(cumulative).any() else 'available_record_contributions_only' if f['status']=='partial' else None
    ds['source']['coordinate_method']={'version':VERSION,'sort_keys':['seqid','start_1','gene_id'],'n_coordinates':len(order),'n_valid_increments':int(np.isfinite(cumulative).sum()),'n_unplaced':n-len(order)}
    return built
