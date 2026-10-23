import csv,io,json,re
from django.http import StreamingHttpResponse,JsonResponse
import numpy as np
from . import artifacts as store
from .statistics import ecdf
class NumericToken(str):pass
def safe(value):
    if isinstance(value,NumericToken):return str(value)
    if isinstance(value,(bool,np.bool_)):return bool(value)
    if isinstance(value,(int,float,np.number)):return '' if not np.isfinite(value) else value.item() if isinstance(value,np.generic) else value
    text=str(value or '');return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text
def csv_response(rows,name,tsv=False):
    def generate():
        yield '\ufeff';buf=io.StringIO(newline='');writer=csv.writer(buf,delimiter='\t' if tsv else ',')
        for row in rows:writer.writerow([safe(v) for v in row]);yield buf.getvalue();buf.seek(0);buf.truncate(0)
    r=StreamingHttpResponse(generate(),content_type='text/tab-separated-values; charset=utf-8' if tsv else 'text/csv; charset=utf-8');r['Content-Disposition']=f'attachment; filename="{name}.{"tsv" if tsv else "csv"}"';return r
def download(request,target,manifest,kind,chart_id='',selection=None):
    fmt=request.GET.get('file_format','csv')
    if fmt not in ['csv','tsv','json']:raise ValueError('invalid_file_format')
    if kind=='chart':
        if chart_id not in store.bundle(str(target)):raise ValueError('invalid_chart_id')
        figure=store.bundle(str(target))[chart_id]
        variant_id=request.GET.get('variant_id','')
        if variant_id:
            if len(variant_id)!=64 or any(c not in '0123456789abcdef' for c in variant_id):raise ValueError('invalid_variant_id')
            path=store.variant_path(target,variant_id,'.json.gz')
            if not path.is_file():raise ValueError('variant_not_available')
            data=store.read_json(path)
            if data.get('_variant_id')!=variant_id:raise ValueError('variant_identity_mismatch')
            figure={**figure,'variant_id':variant_id,'data':data}
        if 'threshold' in request.GET and figure['data']['kind']=='threshold_network':
            threshold=float(request.GET['threshold'])
            if not 0<=threshold<=.95:raise ValueError('invalid_network_threshold')
            import hashlib
            figure={**figure,'variant_id':hashlib.sha256(json.dumps([manifest['artifact_version'],chart_id,threshold]).encode()).hexdigest(),'data':{**figure['data'],'threshold':threshold,'edges':[c for c in figure['data']['cells'] if c['x']>c['y'] and c['rho'] is not None and abs(c['rho'])>=threshold]}}
        return JsonResponse(store.clean(figure),json_dumps_params={'ensure_ascii':False,'allow_nan':False})
    if kind=='method':return JsonResponse(manifest,json_dumps_params={'ensure_ascii':False,'allow_nan':False})
    if kind=='all_fields':
        ps=store.profiles(str(target));keys=['field','unit','n_source','n_valid','n_missing','n_zero','n_invalid','mean','min','p05','p25','median','p75','p95','max']
        def rows():
            yield keys
            for k,p in ps.items():yield [k,p['unit'],*[p.get(z) for z in keys[2:7]],p['mean'],*(p['quantiles'] or [None]*7)]
    elif kind=='exact_ecdf':
        v=store.matrix(str(target));field=request.GET.get('field','')
        if field not in v:raise ValueError('invalid_field')
        value=v[field];cid=chart_id
        if request.GET.get('variant_id'):
            vid=request.GET['variant_id'];data=store.read_json(store.variant_path(target,vid,'.json.gz'))
            if data.get('_variant_id')!=vid:raise ValueError('variant_identity_mismatch')
            membership=np.load(store.variant_path(target,vid,'.npy'),allow_pickle=False);value=value[membership>=0]
        elif cid and cid not in ['GB08','GB09','TB11','TB12']:
            from .contracts import scientific_mask
            mask=scientific_mask(v,[field],manifest['omics'],manifest['n_source'])
            if cid=='TB09':mask&=v['orf_len_aa']>0
            value=value[mask]
        result=ecdf(value,compress=False)
        def rows():yield ['value','cumulative_fraction'];yield from zip(result['x'],result['cdf'])
    elif kind in ['complete_rows','coordinates','assignments','scores','members','raw_source_view']:
        meta=store.metadata(str(target));v=store.matrix(str(target));a=store.arrays(str(target));n=manifest['n_source'];indices=np.arange(n) if selection is None else np.asarray(selection,int);keys=list(meta);fields=[k for k in v if k not in meta];extra={}
        if kind=='complete_rows':
            extra['source_row_index']=dict(enumerate(range(n)))
            if chart_id+'_front' in a:extra['on_front']=dict(enumerate(a[chart_id+'_front']))
            if chart_id+'_membership' in a:extra['analysis_membership_index']=dict(enumerate(a[chart_id+'_membership']))
            if chart_id+'_rows' in a:
                fitrows=a[chart_id+'_rows'];extra['fit_included']={int(i):True for i in fitrows}
                if chart_id+'_assignments' in a:extra['analysis_cluster']=dict(zip(fitrows,a[chart_id+'_assignments']))
                if chart_id+'_scores' in a:
                    scores=a[chart_id+'_scores']
                    for j in range(scores.shape[1]):extra[f'analysis_PC{j+1}']=dict(zip(fitrows,scores[:,j]))
        if kind=='scores':
            from .candidates import rank,module_score
            indices,ranks,details=rank(v,meta[manifest['identity_field']],manifest['omics'],request.GET.get('module',''),request.GET.get('coverage','all'),request.GET.get('top_ties',0));extra={'native_rank':dict(enumerate(ranks)),'selected_module_score':dict(enumerate(module_score(v,details['module']))),'selected_native_module':{int(i):details['module'] for i in indices}}
        if kind in ['coordinates','assignments'] and chart_id:
            rk=chart_id+'_rows'
            if rk not in a:raise ValueError('coordinates_not_available')
            indices=a[rk];data=a.get(chart_id+'_scores') if kind=='coordinates' else a.get(chart_id+'_assignments')
            if data is None:raise ValueError('analysis_not_available')
            data=np.asarray(data);data=data[:,None] if data.ndim==1 else data
            extra={('cluster' if kind=='assignments' else f'PC{j+1}'):dict(zip(indices,data[:,j])) for j in range(data.shape[1])}
        if kind=='raw_source_view':
            # Immutable artifact references source content hashes. Stream source only if hash still matches.
            from backend.apps.stoichdb.complete_core.datasource import CompleteCoreDataSource
            from .source import content_hash
            ds=CompleteCoreDataSource(manifest['species_id'],manifest['omics']);p=ds.core_path if manifest['primary_scope']=='core' else ds.full_path
            if content_hash(p)!=manifest['source']['hashes'][manifest['primary_scope']]:raise ValueError('source_hash_mismatch')
            def rows():
                numeric={c['key'] for c in manifest['catalog'] if c['primary'] and c['role']=='numeric'}
                with p.open(encoding='utf-8-sig',newline='') as f:
                    reader=csv.reader(f);header=next(reader);yield header
                    for cells in reader:yield [NumericToken(value) if key in numeric and re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',value) else value for key,value in zip(header,cells)]
        else:
            def rows():
                yield keys+fields+list(extra)
                for i in indices:yield [meta[k][i] for k in keys]+[v[k][i] for k in fields]+[x.get(int(i),False if name=='fit_included' else None) for name,x in extra.items()]
    else:raise ValueError('invalid_export_kind')
    return csv_response(rows(),f'{manifest["species_id"]}_{manifest["omics"]}_{manifest["primary_scope"]}_{kind}_{manifest["artifact_version"]}',fmt=='tsv')
