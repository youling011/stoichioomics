from backend.apps.common.host_paths import Path
import csv,hashlib,json
import numpy as np
import pandas as pd
from backend.apps.stoichdb.models import DataRelease,OmicsDataset,Species
from .contracts import MODES,META,KEY,CORE,EXTRA
from .statistics import numbers
def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
def release():
    ids=list(DataRelease.objects.filter(is_active=True).values_list('release_id',flat=True))
    if len(ids)!=1:raise ValueError('exactly_one_active_release_required')
    return ids[0]
def registry(sid):
    if not Species.objects.filter(species_id=sid).exists():raise LookupError('unknown_species')
    return {d.omics_type:d for d in OmicsDataset.objects.filter(species__species_id=sid)}
def signature(path):
    p=Path(path) if path else None
    try:return {'path':str(p),'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} if p and p.is_file() else {'path':str(p or ''),'missing':True}
    except OSError:return {'path':str(p or ''),'unreadable':True}
def signatures(sid):
    return {'release_id':release(),'datasets':{m:{'dataset_id':d.dataset_id,'core':signature(d.core_csv_path),**({'full':signature(d.full_csv_path)} if m=='genome' else {})} for m,d in registry(sid).items()}}
def header(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:return next(csv.reader(f))
def read(p,m,columns=None):
    # Literal text protects NA, leading-zero IDs, and version suffixes. Numeric
    # conversion occurs separately; it never modifies a retained source export.
    f=pd.read_csv(Path(p),dtype={k:str for k in META[m]},keep_default_na=False,usecols=columns,low_memory=False)
    k=KEY[m]
    if k not in f or f[k].str.strip().eq('').any():raise ValueError('empty_primary_id:'+k)
    if f[k].duplicated().any():raise ValueError('duplicate_primary_id:'+k)
    return f
def numeric_frame(f,m):
    fields=[];meta=[];a=f.copy();invalid={}
    for k in f:
        if k in META[m]:meta.append(k);continue
        x=numbers(f[k]);tokens=f[k].astype(str);nonempty=tokens.str.strip().ne('')
        if k in CORE[m] or x.notna().any():
            fields.append(k);a[k]=x;invalid[k]={'invalid_numeric':int((nonempty&x.isna()).sum()),'nonfinite':int(tokens.str.lower().isin(['inf','-inf','infinity','-infinity']).sum())}
        else:meta.append(k)
    return a,fields,meta,invalid
def supplement(g,path):
    audit={'status':'unavailable','full_columns_used':[],'missing_full_columns':EXTRA.copy()};out=g.copy()
    try:
        if not path or not Path(path).is_file():return out,audit
        before=signature(path);cols=header(path);wanted=[k for k in EXTRA if k in cols and k not in g]
        f=read(path,'genome',['gene_id']+wanted)
        if set(f.gene_id)!=set(g.gene_id):raise ValueError('full_core_id_set_mismatch')
        f=f.set_index('gene_id').reindex(g.gene_id)
        for k in wanted:out[k]=numbers(f[k]).to_numpy()
        audit.update(status='available',full_columns_used=wanted,missing_full_columns=[k for k in EXTRA if k not in out],signature=before,sha256=digest(path))
        if before!=signature(path):raise ValueError('full_changed_during_read')
    except Exception as e:audit.update(status='full_invalid',reason=str(e));out=g.copy();audit['full_columns_used']=[];audit['missing_full_columns']=EXTRA.copy()
    return out,audit
def load(sid):
    before=signatures(sid);ds=registry(sid);frames={};raw={};fields={};metadata={};audit={}
    for m in MODES:
        try:
            d=ds[m];p=d.core_csv_path;sig=signature(p);f=read(p,m);a,ks,ms,invalid=numeric_frame(f,m)
            sha=digest(p)
            if signature(p)!=sig:raise ValueError('core_changed_during_read')
            frames[m]=a;raw[m]=f;fields[m]=ks;metadata[m]=ms
            audit[m]={'status':'available','dataset_id':d.dataset_id,'signature':sig,'sha256':sha,'header_hash':hashlib.sha256(json.dumps(list(f)).encode()).hexdigest(),'header':list(f),'n_source':len(f),'registered_n':d.row_count_core,'primary_id':KEY[m],'primary_errors':0,'numeric_fields':ks,'metadata_fields':ms,'invalid_counts':invalid}
        except Exception as e:
            audit[m]={'status':'invalid_source','reason':str(e)};fields[m]=[];metadata[m]=[]
    full={'status':'unavailable','missing_full_columns':EXTRA.copy()}
    if 'genome' in frames:
        frames['genome'],full=supplement(frames['genome'],ds['genome'].full_csv_path)
    if before!=signatures(sid):raise ValueError('source_changed_during_build')
    source={'species_id':sid,'release_id':before['release_id'],'signatures':before,'core':audit,'supplement':full}
    source['source_hash']=hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest()
    return {'frames':frames,'raw':raw,'fields':fields,'metadata':metadata,'source':source}
