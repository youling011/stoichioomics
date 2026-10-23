"""Lossless source cells and per-field support counts for existing gene means."""
import gzip,hashlib
from pathlib import Path
import pandas as pd
from . import artifacts as a
from .contracts import MODES,KEY
from .statistics import numbers
def attach(target):
    target=Path(target);manifest=a.read(target/'manifest.json');source=a.read(target/'source_audit.json');mapping=a.table(target,'x0_mapping');blocks=[]
    for m in MODES:
        audit=source['core'].get(m,{})
        if audit.get('status')!='available':continue
        p=Path(audit['signature']['path']);out=target/'raw_sources'/(m+'.csv.gz');out.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256()
        with p.open('rb') as inp,gzip.open(out,'wb',compresslevel=1) as zipped:
            for chunk in iter(lambda:inp.read(4*1024*1024),b''):h.update(chunk);zipped.write(chunk)
        if h.hexdigest()!=audit['sha256']:raise ValueError('source_changed_during_raw_snapshot')
        if mapping.empty or 'omics' not in mapping:continue
        fields=[r['field'] for r in manifest['catalog'].get(m,[])];f=pd.read_parquet(target/'tables'/('source_'+m+'.parquet'),columns=[KEY[m]]+fields)
        for k in fields:f[k]=numbers(f[k])
        mm=mapping[mapping.omics.eq(m)].set_index('entity_id').gene_id;gene=f[KEY[m]].map(mm).fillna('');keep=gene.ne('');counts=f.loc[keep,fields].groupby(gene[keep],sort=True).count();counts.columns=[m+'__'+k for k in counts];blocks.append(counts)
    if blocks:
        order=pd.read_parquet(target/'tables/gene_matrix.parquet',columns=['gene_id']).gene_id
        counts=pd.concat(blocks,axis=1).reindex(order).fillna(0).astype('uint32');counts.index.name='gene_id';counts.reset_index().to_parquet(target/'tables/gene_valid_counts.parquet',index=False,compression='zstd')
    elif all(v.get('status')=='available' for v in source['core'].values()) and (target/'tables/gene_matrix.parquet').exists():
        columns=['gene_id']+[m+'__'+r['field'] for m,rows in manifest['catalog'].items() for r in rows];empty=pd.DataFrame(columns=columns);empty.to_parquet(target/'tables/gene_valid_counts.parquet',index=False,compression='zstd')
    manifest.update(storage_version=3,support_counts={'kind':'gene_valid_counts','status':'available' if blocks else 'unavailable','definition':'finite original Core records per anchored gene and numeric field; same masks as gene means'},raw_source_snapshots='lossless original CSV bytes, gzipped; safe CSV export preserves original cell tokens')
    a.write(target/'manifest.json',manifest)
