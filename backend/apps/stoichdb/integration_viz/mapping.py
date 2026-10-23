import re,hashlib,collections
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from .statistics import numbers,finite,clean,robust,profile
from .contracts import MODES

def link(frames):
    g,t,p=[frames[m] for m in MODES];aliases=collections.defaultdict(set)
    for gene,source in g[['gene_id','source_gene_id']].itertuples(index=False,name=None):
        for s in [gene,source,clean(source).removeprefix('gene:')]:
            if clean(s):aliases[clean(s)].add(str(gene))
    amap={k:next(iter(v)) for k,v in aliases.items() if len(v)==1};versions=set()
    def anchored(value):
        s=clean(value)
        if s in amap:return amap[s]
        if re.fullmatch(r'ENS[A-Z]*G\d+\.\d+',s) and s.rsplit('.',1)[0] in amap:versions.add(s);return amap[s.rsplit('.',1)[0]]
        return ''
    t=t.copy();t['_gene']=[anchored(x) for x in t.gene_id]
    tidmap=collections.defaultdict(set)
    for tid,gene in t[['transcript_id','_gene']].itertuples(index=False,name=None):
        if gene:tidmap[str(tid)].add(gene)
    tm={k:next(iter(v)) for k,v in tidmap.items() if len(v)==1}
    pg=[];evidence=[];conflicts=[]
    for pid,gene,ens,tid,entid in p[['protein_id','gene_id','ensembl_gene_id','transcript_id','ensembl_transcript_id']].itertuples(index=False,name=None):
        direct={v for x in [gene,ens] if (v:=anchored(x))};through={tm[str(x)] for x in [tid,entid] if str(x) in tm};cc=direct|through
        pg.append(next(iter(cc)) if len(cc)==1 else '')
        evidence.append('gene_and_transcript' if direct and through and len(cc)==1 else 'gene_id' if direct and len(cc)==1 else 'transcript_id' if through and len(cc)==1 else 'conflict' if len(cc)>1 else 'unmapped')
        if len(cc)>1:conflicts.append({'protein_id':pid,'candidate_genes':sorted(cc)})
    p=p.copy();p['_gene']=pg;p['_mapping_evidence']=evidence;g=g.copy();g['_gene']=g.gene_id
    linked=dict(zip(MODES,[g,t,p]));sets={m:set(f.loc[f._gene.ne(''),'_gene']) for m,f in linked.items()};union=set.union(*sets.values());all3=set.intersection(*sets.values())
    membership=collections.Counter(''.join(str(int(k in sets[m])) for m in MODES) for k in union)
    audit={'source_rows':{m:len(f) for m,f in frames.items()},'mapped_rows':{m:int(f._gene.ne('').sum()) for m,f in linked.items()},'unique_genes':{m:len(s) for m,s in sets.items()},'union_genes':len(union),'all_three':len(all3),'G_T':len(sets['genome']&sets['transcriptome']),'T_P':len(sets['transcriptome']&sets['proteome']),'G_P':len(sets['genome']&sets['proteome']),'membership':dict(membership),'protein_conflicts':conflicts,'protein_evidence':dict(collections.Counter(evidence)),'ensembl_gene_versions_resolved':len(versions),'ambiguous_genome_alias_n':sum(len(s)>1 for s in aliases.values())}
    assert sum(membership.values())==len(union)
    return linked,audit

def aggregate(linked,fields):
    blocks=[]
    for m,f in linked.items():
        b=f[f._gene.ne('')].groupby('_gene',sort=True)[fields[m]].mean();b.columns=[m+'__'+k for k in b];blocks.append(b)
    j=pd.concat(blocks,axis=1).sort_index();j.index.name='gene_id';return j
