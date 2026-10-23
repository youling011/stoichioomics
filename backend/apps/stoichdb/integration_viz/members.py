import pandas as pd
from . import artifacts as a
def page_frame(f,params,max_size=200):
    page=int(params.get('page',1));size=int(params.get('page_size',50))
    if page<1 or size<1 or size>max_size:raise ValueError('pagination_out_of_range')
    search=str(params.get('search','')).strip()
    if search and len(f):
        cols=[k for k in ['gene_id','gene_name','entity_id','transcript_id','protein_id','field','field_id','feature_a','feature_b'] if k in f]
        if cols:f=f[f[cols].astype(str).apply(lambda s:s.str.contains(search,case=False,regex=False)).any(axis=1)]
    sort=params.get('sort')
    if sort:
        key=sort.removeprefix('-')
        if key not in f.columns:raise ValueError('invalid_sort')
        f=f.sort_values([key]+(['gene_id'] if key!='gene_id' and 'gene_id' in f else []),ascending=[not sort.startswith('-')]+([True] if key!='gene_id' and 'gene_id' in f else []),kind='stable',na_position='last')
    return {'items':f.iloc[(page-1)*size:page*size].to_dict('records'),'total':len(f),'page':page,'page_size':size,'sort':sort or 'artifact_order','search':search}
def candidates(target,params):
    f=a.table(target,'candidates');math=a.read(target/'math.json');eligible=len(f)
    selected=str(params.get('selected','true')).lower()
    if selected not in ['true','false']:raise ValueError('invalid_selected')
    if selected=='true' and len(f):f=f[f.candidate.eq(True)]
    for k in ['resource_percentile','GC_percentile','pI_percentile']:
        if params.get('min_'+k) is not None:
            v=float(params['min_'+k])
            if not 0<=v<=1:raise ValueError('percentile_filter_out_of_range')
            f=f[f[k]>=v]
    return {**page_frame(f,params),'eligible_n':eligible,'threshold':math.get('candidate_threshold'),'selected':selected=='true'}
def selection(target,params):
    key=params.get('selection_id')
    if not key and params.get('bin_id'):key=params.get('chart_id','')+':bin:'+params['bin_id']
    if key and key.startswith('pair:'):
        parts=key.split(':')
        if len(parts)!=3:raise ValueError('invalid_pair_selection')
        fa,fb=parts[1:];m=a.read(target/'manifest.json');allowed={omics+'__'+r['field'] for omics,rows in m['catalog'].items() for r in rows}
        if fa not in allowed or fb not in allowed:raise ValueError('invalid_pair_fields')
        f=a.table(target,'gene_matrix');good=f[fa].notna()&f[fb].notna();ids=f.loc[good,'gene_id'].tolist()
        return pd.DataFrame({'entity_id':ids,'entity_type':'gene','feature_a':fa,'feature_b':fb}),key
    members=a.read(target/'members.json.gz')
    if key not in members:raise ValueError('unknown_selection_id')
    cid=key.split(':')[0];kind='transcript' if cid=='CX11' else 'gene';ids=members[key]
    return pd.DataFrame({'entity_id':ids,'entity_type':kind}),key
