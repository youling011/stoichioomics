from pathlib import Path
import hashlib,json,csv
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pc
from backend.apps.stoichdb.complete_core.datasource import CompleteCoreDataSource
from backend.apps.stoichdb.models import DataRelease
from .contracts import META,CORE,unit
def content_hash(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()
def release_id():return DataRelease.objects.filter(is_active=True).values_list('release_id',flat=True).first() or 'registered'
def signatures(ds):
    return {s:({'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} if p and p.is_file() else None) for s,p in [('core',ds.core_path),('full',ds.full_path)]}
def frame(path,m):
    # Read identifiers and annotations as literal strings, including NA and 0001.
    with Path(path).open(encoding='utf-8-sig',newline='') as f:header=next(csv.reader(f))
    string_fields=set(META[m])|{'chosen_transcript_id','source_db','raw_header','seq_md5','sequence','translation','description','gene_biotype','transcript_biotype','assembly','seq_region','element_rule','omics'}
    a=pc.read_csv(str(path),read_options=pc.ReadOptions(use_threads=False),convert_options=pc.ConvertOptions(column_types={k:pa.string() for k in header if k in string_fields},strings_can_be_null=False)).to_pandas(use_threads=False)
    key='gene_id' if m=='genome' else 'transcript_id'
    if key not in a or a[key].fillna('').astype(str).str.strip().eq('').any():raise ValueError('source_empty_'+key)
    if a[key].duplicated().any():raise ValueError('source_duplicate_'+key)
    return a
def numbers(s):return pd.to_numeric(s.replace({'True':1,'False':0,'true':1,'false':0}),errors='coerce').to_numpy(dtype=float,na_value=np.nan)
def load(sid,m,scope='core'):
    if m not in META or scope not in ['core','full']:raise ValueError('invalid_omics_or_scope')
    ds=CompleteCoreDataSource(sid,m);before=signatures(ds)
    if not before['core']:raise ValueError('source_core_file_missing')
    core=frame(ds.core_path,m);full=frame(ds.full_path,m) if before['full'] else None
    if scope=='full' and full is None:raise ValueError('full_not_registered' if not ds.dataset.full_csv_path else 'source_full_file_missing')
    a=core if scope=='core' else full;key='gene_id' if m=='genome' else 'transcript_id';ids=a[key].astype(str).tolist();n=len(a)
    original=list(a.columns);numeric=[];metadata={};values={};catalog=[];invalid={}
    def add(k,s,origin,primary=False):
        raw=numbers(s);finite=np.isfinite(raw)
        # Unknown text columns are retained in metadata. Unknown numeric columns remain accessible.
        isnum=k not in META[m] and (k in CORE[m] or pd.api.types.is_numeric_dtype(s) or finite.any())
        if isnum:
            invalid[k]=int((~finite&s.notna().to_numpy()&s.astype(str).str.strip().ne('').to_numpy()&~s.astype(str).isin(['NA','N/A','NaN','nan','None','null']).to_numpy()).sum())
            raw[~finite]=np.nan;values[k]=raw
            if primary:numeric.append(k)
        else:metadata[k]=s.fillna('').astype(str).tolist()
        catalog.append({'key':k,'role':'numeric' if isnum else 'metadata','origin':origin,'declared_feature_family':'Core' if k in CORE[m] or k in META[m] else 'Full','source_file_scope':scope if primary else 'full','unit':unit(k,m) if isnum else 'literal annotation','primary':primary})
    for k in original:add(k,a[k],scope,True)
    for k in ['coding_valid','is_coding','orf_has_stop']:
        if k in a:values[k]=numbers(a[k])
    conflicts={};joined=full.set_index(key).reindex(ids) if full is not None and scope=='core' else None
    if joined is not None:
        for k in full.columns:
            if k==key:continue
            if k not in original:add(k,joined[k],'full',False)
            elif k in values:
                other=numbers(joined[k]);good=np.isfinite(values[k])&np.isfinite(other);bad=good&~np.isclose(values[k],other,rtol=1e-10,atol=1e-8)
                if bad.any():conflicts[k]={'n':int(bad.sum()),'ids':[ids[i] for i in np.flatnonzero(bad)[:20]]}
    hashes={s:content_hash(p) if p and p.is_file() else None for s,p in [('core',ds.core_path),('full',ds.full_path)]}
    if before!=signatures(ds):raise ValueError('source_changed_during_load')
    source={'file_signatures':before,'hashes':hashes,'core_header':list(core),'full_header':list(full) if full is not None else [],'primary_header':original,'registered_core_n':ds.dataset.row_count_core,'registered_full_n':ds.dataset.row_count_full,'actual_core_n':len(core),'actual_full_n':len(full) if full is not None else None,'registry_count_mismatch':len(core)!=ds.dataset.row_count_core or (full is not None and len(full)!=ds.dataset.row_count_full),'matched_n':int(core[key].isin(full[key]).sum()) if full is not None else 0,'same_name_conflicts':conflicts,'core_nulls_preserved':True,'invalid_counts':invalid,'duplicate_id_n':0}
    source_hash=hashlib.sha256(json.dumps([hashes,original,scope,key,'strict-unique-left-append-only-v1'],sort_keys=True).encode()).hexdigest()
    metadata[key]=ids
    return {'species_id':sid,'omics':m,'scope':scope,'dataset_id':ds.dataset.dataset_id,'release_id':release_id(),'ids':ids,'key':key,'n':n,'values':values,'metadata':metadata,'fields':numeric,'catalog':catalog,'source':source,'source_hash':source_hash,'available_scopes':['core']+(['full'] if full is not None else []),'_core':core,'_full':full}
