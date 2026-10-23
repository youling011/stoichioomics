import pandas as pd
from . import artifacts as a
from .contracts import MODES,META,KEY
def source_rows(target,m,ids):
    if len(ids)==0:return []
    p=target/'tables'/('source_'+m+'.parquet')
    if not p.exists():return []
    return pd.read_parquet(p,columns=META[m],filters=[(KEY[m],'in',list(ids))]).to_dict('records')
def enrich(target,items):
    if not items:return items
    target=__import__('pathlib').Path(target);kind=items[0]['entity_type'];ids={r['entity_id'] for r in items};mapping=a.table(target,'x0_mapping')
    if kind=='gene':
        selected=mapping[mapping.gene_id.isin(ids)];genes=ids
    else:
        selected=mapping[mapping.omics.eq('transcriptome')&mapping.entity_id.isin(ids)];genes=set(selected.gene_id);selected=mapping[mapping.gene_id.isin(genes)]
    metadata={m:{r[KEY[m]]:r for r in source_rows(target,m,selected.loc[selected.omics.eq(m),'entity_id'])} for m in MODES}
    grouped={m:f.groupby('gene_id').entity_id.agg(list).to_dict() for m,f in selected.groupby('omics')};tx_gene=mapping[mapping.omics.eq('transcriptome')].set_index('entity_id').gene_id.to_dict()
    support_path=target/'tables/gene_valid_counts.parquet';support=pd.read_parquet(support_path,filters=[('gene_id','in',list(genes))]).set_index('gene_id').to_dict('index') if support_path.exists() else {}
    means=pd.read_parquet(target/'tables/gene_matrix.parquet',filters=[('gene_id','in',list(genes))]).set_index('gene_id').to_dict('index')
    pairs=pd.read_parquet(target/'tables/exact_pairs.parquet',filters=[('transcript_id','in',list(ids))]).set_index('transcript_id').to_dict('index') if kind=='transcript' else {}
    for item in items:
        entity=item['entity_id'];gene=entity if kind=='gene' else tx_gene.get(entity,'')
        if kind=='gene':item.update(metadata['genome'].get(entity,{}))
        else:item.update(metadata['transcriptome'].get(entity,{}))
        item['anchored_gene_id']=gene;item['valid_counts']=support.get(gene,{});item['gene_means']=means.get(gene,{})
        for m in MODES:item[m+'_members']=[metadata[m][key] for key in grouped.get(m,{}).get(gene,[]) if key in metadata[m]]
        if kind=='transcript':
            item.update(pairs.get(entity,{}));item['transcriptome_members']=[metadata['transcriptome'][entity]] if entity in metadata['transcriptome'] else []
            item['proteome_members']=[r for r in item['proteome_members'] if (r.get('transcript_id') or r.get('ensembl_transcript_id'))==entity]
    return items
