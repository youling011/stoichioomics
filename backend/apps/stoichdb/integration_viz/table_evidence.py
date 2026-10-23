import pandas as pd
from . import artifacts as a
def enrich(target,items):
    if not items:return items
    genes={str(r['gene_id']) for r in items if r.get('gene_id')};mapping=a.table(target,'x0_mapping');mapping=mapping[mapping.gene_id.isin(genes)]
    member={m:f.groupby('gene_id').entity_id.agg(list).to_dict() for m,f in mapping.groupby('omics')}
    p=target/'tables/source_genome.parquet';g=pd.read_parquet(p,columns=['gene_id','exon_seq_strategy']).set_index('gene_id').exon_seq_strategy.to_dict() if p.exists() else {}
    for r in items:
        gene=r.get('gene_id')
        if gene:
            r['exon_seq_strategy']=g.get(gene,'')
            for m in ['genome','transcriptome','proteome']:r[m+'_ids']=member.get(m,{}).get(gene,[])
    return items
