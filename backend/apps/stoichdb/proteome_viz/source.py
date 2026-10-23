from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
try:
    import pyarrow as pa
    import pyarrow.csv as arrow_csv
except ImportError:
    pa=arrow_csv=None
from backend.apps.stoichdb.complete_core.datasource import CompleteCoreDataSource
from backend.apps.stoichdb.models import DataRelease
from .contracts import CORE_FIELDS,META,AA

def content_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def release_id():
    return DataRelease.objects.filter(is_active=True).values_list('release_id',flat=True).first() or 'registered'

def read_frame(path):
    if arrow_csv is not None:
        # Explicit string columns preserve identifier suffixes, leading zeros and literal "NA".
        frame=arrow_csv.read_csv(str(path),read_options=arrow_csv.ReadOptions(use_threads=False),convert_options=arrow_csv.ConvertOptions(column_types={f:pa.string() for f in META},strings_can_be_null=False,null_values=['','NA','N/A','NaN','nan','null','None'])).to_pandas(use_threads=False)
    else:frame=pd.read_csv(path,keep_default_na=False,low_memory=False,float_precision='round_trip',dtype={f:str for f in META})
    if 'protein_id' not in frame or frame.protein_id.astype(str).str.strip().eq('').any():raise ValueError('source_empty_protein_id')
    if frame.protein_id.duplicated().any():raise ValueError('source_duplicate_protein_id')
    return frame

def numeric(frame):
    result={}
    for field in frame.columns:
        if field in META or field in ['seq_md5']:continue
        a=pd.to_numeric(frame[field],errors='coerce').to_numpy(float)
        a[~np.isfinite(a)]=np.nan
        if np.isfinite(a).any() or field in CORE_FIELDS:result[field]=a
    return result

def load(species_id,scope='core'):
    if scope not in ['core','full']:raise ValueError('invalid_scope')
    ds=CompleteCoreDataSource(species_id,'proteome')
    if not ds.core_path or not ds.core_path.is_file():raise ValueError('source_core_file_missing')
    core=read_frame(ds.core_path)
    full=read_frame(ds.full_path) if ds.full_path and ds.full_path.is_file() else None
    if scope=='full' and full is None:raise ValueError('full_not_registered' if not ds.dataset.full_csv_path else 'source_full_file_missing')
    primary=core if scope=='core' else full
    values=numeric(primary); original_fields=list(values)
    ids=primary.protein_id.astype(str).tolist()
    joined=full.set_index('protein_id').reindex(ids) if full is not None else None
    conflicts={}
    if joined is not None and scope=='core':
        supplement=numeric(joined)
        for f,a in supplement.items():
            if f not in values:values[f]=a
            else:
                good=np.isfinite(values[f])&np.isfinite(a)
                bad=good&~np.isclose(values[f],a,atol=1e-8,rtol=1e-10)
                if bad.any():conflicts[f]=int(bad.sum())
    n=len(primary)
    for f in CORE_FIELDS:values.setdefault(f,np.full(n,np.nan))
    invalid_values={}
    for field,a in list(values.items()):
        valid=np.isfinite(a);bad=np.zeros(n,bool)
        if field=='length_aa':bad=valid&((a<=0)|(abs(a-np.rint(a))>1e-6))
        elif field.endswith(('_atoms','_count')) or field in ['cys_count','met_count']:bad=valid&((a<0)|(abs(a-np.rint(a))>1e-6))
        elif field.endswith('_frac') or field=='aromaticity':bad=valid&((a<-1e-10)|(a>1+1e-10))
        elif field.endswith('_pct'):bad=valid&((a<-1e-10)|(a>100+1e-10))
        if bad.any():
            invalid_values[field]=[[int(i),float(a[i])] for i in np.flatnonzero(bad)];a=a.copy();a[bad]=np.nan;values[field]=a
    for ratio,denominator in [('C_N_ratio','N_atoms'),('N_S_ratio','S_atoms'),('O_C_ratio','C_atoms'),('H_C_ratio','C_atoms'),('O_N_ratio','N_atoms')]:
        if ratio in values and denominator in values:
            bad=np.isfinite(values[ratio])&(~np.isfinite(values[denominator])|(values[denominator]<=0))
            if bad.any():
                invalid_values.setdefault(ratio,[]).extend([[int(i),float(values[ratio][i])] for i in np.flatnonzero(bad)]);values[ratio]=values[ratio].copy();values[ratio][bad]=np.nan
    length=values['length_aa']; safe_length=np.where(length>0,length,np.nan)
    derived={f'{e}_atoms_per_aa':values[f'{e}_atoms']/safe_length for e in ['H','O','Se'] if f'{e}_atoms' in values}
    derived['disulfide_density']=np.floor(values['cys_count']/2)/safe_length
    derived['avg_residue_mass_da']=values['mw_da']/safe_length
    derived['O_N_ratio']=np.divide(values['O_atoms'],values['N_atoms'],out=np.full(n,np.nan),where=values['N_atoms']>0)
    for f,a in derived.items():values.setdefault(f,a)
    if scope=='core':
        for f in ['H_atoms_per_aa','O_atoms_per_aa','Se_atoms_per_aa','disulfide_density','O_N_ratio']:
            if f in derived:values[f]=derived[f]
    if 'extinction_reduced' in values and 'a280_1mgml_reduced' not in values:
        values['a280_1mgml_reduced']=np.divide(values['extinction_reduced'],values['mw_da'],out=np.full(n,np.nan),where=values['mw_da']>0)
    count_sources={}
    reconstruction=np.column_stack([values[f'AA_{a}_pct']*length/100 for a in AA]);rounded=np.rint(reconstruction)
    valid=np.isfinite(reconstruction).all(1)&(reconstruction>=0).all(1)&(abs(reconstruction-rounded)<=1e-6).all(1)&(rounded.sum(1)<=length+1e-6)&(rounded.sum(1)>0)&(length>0)
    existing=np.column_stack([values.get(f'AA_{a}_count',np.full(n,np.nan)) for a in AA]);known=np.isfinite(existing)
    consistent=(~known|(abs(existing-rounded)<=1e-6)).all(1);valid&=consistent
    for j,a in enumerate(AA):
        field=f'AA_{a}_count';arr=existing[:,j].copy();fill=~known[:,j]&valid;arr[fill]=rounded[fill,j];values[field]=arr;count_sources[a]={'direct_valid_n':int(known[:,j].sum()),'reconstructed_n':int(fill.sum()),'fallback':'validated primary pct × length; integer tolerance 1e-6'}
    standard=np.column_stack([values[f'AA_{a}_count'] for a in AA]);bad_counts=np.isfinite(standard).all(1)&((standard.sum(1)>length+1e-6)|(standard<0).any(1))
    if bad_counts.any():
        for a in AA:values[f'AA_{a}_count'][bad_counts]=np.nan
    for f in ['length_canonical_aa','unknown_residues_for_atoms']:
        if f in values:
            bad=np.isfinite(values[f])&((values[f]<0)|(values[f]>length+1e-6))
            if bad.any():
                invalid_values.setdefault(f,[]).extend([[int(i),float(values[f][i])] for i in np.flatnonzero(bad)]);values[f]=values[f].copy();values[f][bad]=np.nan
    raw_hashes={'core':content_hash(ds.core_path),'full':content_hash(ds.full_path) if full is not None else None,'scope':scope,'schema':list(primary.columns)}
    source_hash=hashlib.sha256(json.dumps(raw_hashes,sort_keys=True).encode()).hexdigest()
    metadata={f:primary[f].fillna('').astype(str).tolist() if f in primary else ['']*n for f in META}
    metadata['protein_id']=ids
    stats={'registered_core_n':ds.dataset.row_count_core,'registered_full_n':ds.dataset.row_count_full,'actual_core_n':len(core),'actual_full_n':len(full) if full is not None else 0,'matched_n':int(core.protein_id.isin(full.protein_id).sum()) if full is not None else 0,'unmatched_n':int((~core.protein_id.isin(full.protein_id)).sum()) if full is not None else len(core),'duplicate_id_n':0,'conflicts':conflicts,'hashes':raw_hashes,'aa_count_sources':count_sources,'core_header':list(core.columns),'full_header':list(full.columns) if full is not None else []}
    stats['file_signatures']={kind:{'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} if p and p.is_file() else None for kind,p in [('core',ds.core_path),('full',ds.full_path)]}
    stats['semantic_invalid_counts']={f:len(rows) for f,rows in invalid_values.items()}
    stats['csv_reader']={'name':'pyarrow' if pa is not None else 'pandas round_trip','version':pa.__version__ if pa is not None else pd.__version__,'identifier_columns':'explicit UTF-8 strings; no automatic NA coercion'}
    stats['semantic_invalid_values']=invalid_values
    return {'species_id':species_id,'dataset_id':ds.dataset.dataset_id,'release_id':release_id(),'source_hash':source_hash,'scope':scope,'n':n,'ids':ids,'metadata':metadata,'values':values,'original_fields':original_fields,'source':stats,'available_scopes':['core']+(['full'] if full is not None else []),'_full_frame':full,'_core_frame':core}
