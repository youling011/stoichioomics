import csv,io,json,gzip
from pathlib import Path
import numpy as np
import pandas as pd
from django.http import StreamingHttpResponse,HttpResponse
from . import artifacts as a
from .members import selection
KINDS={'source_rows','gene_matrix','gene_valid_counts','chain_rows','exact_pairs','field_profiles','chart_data','correlations','candidates','members','cohort','methods','table','native_components'}
def cell(v,text=False):
    if v is None or (isinstance(v,(float,np.floating)) and not np.isfinite(v)):return ''
    if isinstance(v,(list,dict,np.ndarray)):return json.dumps(a.clean(v),ensure_ascii=False)
    s=str(v)
    if not text and isinstance(v,str):
        try:float(s)
        except ValueError:text=True
    return "'"+s if text and s.lstrip().startswith(('=','+','-','@','\t','\r')) else s
def csv_response(f,name,identity,text_fields=None):
    return csv_frames_response(iter([f]),name,identity,text_fields)

def csv_frames_response(frames,name,identity,text_fields=None):
    def stream():
        buffer=io.StringIO();writer=csv.writer(buffer);yield '\ufeff'
        columns=None
        for f in frames:
            if columns is None:
                columns=list(f);identity_keys=[k for k in identity if k not in columns];writer.writerow(columns+identity_keys);yield buffer.getvalue();buffer.seek(0);buffer.truncate(0)
            elif set(f)!=set(columns):raise ValueError('inconsistent_member_export_schema')
            f=f.reindex(columns=columns)
            textual={k:(k in text_fields if text_fields is not None else pd.api.types.is_object_dtype(f[k]) or pd.api.types.is_string_dtype(f[k])) for k in columns}
            for values in f.itertuples(index=False,name=None):
                writer.writerow([cell(v,textual[k]) for k,v in zip(columns,values)]+[cell(identity[k],True) for k in identity_keys]);yield buffer.getvalue();buffer.seek(0);buffer.truncate(0)
    r=StreamingHttpResponse(stream(),content_type='text/csv; charset=utf-8');r['Content-Disposition']='attachment; filename="'+name+'.csv"';return r
def original_source(target,omics,manifest):
    from .contracts import META
    if omics not in ['genome','transcriptome','proteome']:raise ValueError('invalid_omics')
    audit=a.read(target/'source_audit.json')['core'].get(omics,{})
    if audit.get('status')!='available':raise ValueError('invalid_source')
    snapshot=target/'raw_sources'/(omics+'.csv.gz');path=snapshot if snapshot.exists() else Path(audit['signature']['path'])
    if not snapshot.exists():
        from .source import digest
        if digest(path)!=audit['sha256']:raise ValueError('source_hash_mismatch')
    def stream():
        op=gzip.open if snapshot.exists() else open
        with op(path,'rt',encoding='utf-8-sig',newline='') as inp:
            reader=csv.reader(inp);header=next(reader);buffer=io.StringIO();writer=csv.writer(buffer);yield '\ufeff';writer.writerow(header);yield buffer.getvalue();buffer.seek(0);buffer.truncate(0)
            for row in reader:
                writer.writerow([cell(v,k in META[omics]) for k,v in zip(header,row)]);yield buffer.getvalue();buffer.seek(0);buffer.truncate(0)
    r=StreamingHttpResponse(stream(),content_type='text/csv; charset=utf-8');r['Content-Disposition']='attachment; filename="source_rows.csv"';r['X-Artifact-Version']=manifest['artifact_version'];r['X-Source-SHA256']=audit['sha256'];r['X-Source-Row-Count']=str(audit['n_source']);return r
def export(target,params,chart_loader,cohort_loader):
    kind=params.get('kind','methods')
    if kind not in KINDS:raise ValueError('invalid_export_kind')
    m=a.read(target/'manifest.json');identity={k:m[k] for k in ['species_id','artifact_version','release_id','source_hash','method_version']};identity['registry_species_id']=m['species_id']
    if kind=='source_rows':return original_source(target,params.get('omics'),m)
    if kind in ['chart_data','methods','cohort']:
        data=chart_loader(params.get('chart_id')) if kind=='chart_data' else cohort_loader() if kind=='cohort' else {**m,'source_audit':a.read(target/'source_audit.json'),'mapping_audit':a.read(target/'mapping_audit.json'),'math':a.read(target/'math.json')}
        r=HttpResponse(json.dumps(a.clean(data),ensure_ascii=False,allow_nan=False),content_type='application/json');r['Content-Disposition']='attachment; filename="'+kind+'.json"';return r
    text_fields=None
    if kind=='table':
        key=params.get('table_id')
        if key not in {'x0_mapping','x0_conflicts','x1_shifts','x2_gc','x3_members','x4_pairs','x6_edges','x7_features'}:raise ValueError('invalid_table_id')
        f=pd.DataFrame(cohort_loader()['feature_ranking']) if key=='x7_features' else a.table(target,key)
        if key=='x3_members' and params.get('chart_id'):
            if params['chart_id'] not in ['CX08','CX09','CX10']:raise ValueError('invalid_x3_chart')
            if len(f):f=f[f.chart_id.eq(params['chart_id'])]
    elif kind=='members':
        f,key=selection(target,params);identity['selection_id']=key
        from .member_evidence import enrich
        def frames():
            if f.empty:yield f
            for offset in range(0,len(f),500):yield pd.DataFrame(enrich(target,f.iloc[offset:offset+500].to_dict('records')))
        return csv_frames_response(frames(),kind,identity)
    elif kind=='field_profiles':
        omics=params.get('omics')
        if omics not in m['catalog']:raise ValueError('invalid_omics')
        rows=[]
        for item in m['catalog'][omics]:
            if params.get('field') and item['field']!=params['field']:continue
            p=a.field_profile(target,omics,item['field'])
            for value,count,cdf in zip(p['ecdf']['values'],p['ecdf']['counts'],p['ecdf']['cdf']):rows.append({'field':p['field'],'source_unit':p['source_unit'],'value':value,'count':count,'cdf':cdf,'n_source':p['n_source'],'n_valid':p['n_valid'],'n_missing':p['n_missing']})
        f=pd.DataFrame(rows)
    elif kind=='source_rows':
        omics=params.get('omics')
        if omics not in ['genome','transcriptome','proteome']:raise ValueError('invalid_omics')
        from .contracts import META
        f=a.table(target,'source_'+omics);identity={};text_fields=set(META[omics]) # Numeric tokens keep their original sign/precision.
    else:
        key={'correlations':'x6_edges'}.get(kind,kind);f=a.table(target,key)
        if kind=='native_components' and len(f):
            raw=pd.read_parquet(target/'tables/source_genome.parquet');f=raw.merge(f,on='gene_id',how='left',validate='one_to_one');identity['policy']=m['policy'];identity['supplement_status']=m['supplement']['status']
        if kind=='candidates':
            if str(params.get('selected','true')).lower()=='true' and len(f):f=f[f.candidate.eq(True)]
            for k in ['resource_percentile','GC_percentile','pI_percentile']:
                if params.get('min_'+k) is not None:
                    v=float(params['min_'+k])
                    if not 0<=v<=1:raise ValueError('percentile_filter_out_of_range')
                    f=f[f[k]>=v]
        if kind=='correlations' and params.get('layer_pair'):
            pairs={'CGT':('genome','transcriptome'),'CGP':('genome','proteome'),'CTP':('transcriptome','proteome')}
            if params['layer_pair']=='representative':f=pd.DataFrame(a.read(target/'charts/CX13.json.gz')['data']['cells'])
            else:
                if params['layer_pair'] not in pairs:raise ValueError('invalid_layer_pair')
                x,y=pairs[params['layer_pair']];f=f[f.feature_a.str.startswith(x+'__')&f.feature_b.str.startswith(y+'__')]
    # All pages and exports share the same filter and sort semantics.
    if kind in ['candidates','table'] and len(f):
        from .members import page_frame
        # Apply the same controlled operations without slicing the population.
        search=str(params.get('search','')).strip()
        if search:
            keys=[k for k in ['gene_id','gene_name','entity_id','transcript_id','protein_id','field','feature_a','feature_b'] if k in f]
            if keys:f=f[f[keys].astype(str).apply(lambda s:s.str.contains(search,case=False,regex=False)).any(axis=1)]
        sort=params.get('sort')
        if sort:
            key=sort.removeprefix('-')
            if key not in f:raise ValueError('invalid_sort')
            f=f.sort_values([key]+(['gene_id'] if key!='gene_id' and 'gene_id' in f else []),ascending=[not sort.startswith('-')]+([True] if key!='gene_id' and 'gene_id' in f else []),kind='stable',na_position='last')
    if kind=='table' and params.get('table_id') in ['x2_gc','x3_members']:
        from .table_evidence import enrich
        def frames():
            if f.empty:yield f
            for offset in range(0,len(f),500):yield pd.DataFrame(enrich(target,f.iloc[offset:offset+500].to_dict('records')))
        return csv_frames_response(frames(),kind,identity)
    return csv_response(f,kind,identity,text_fields)
