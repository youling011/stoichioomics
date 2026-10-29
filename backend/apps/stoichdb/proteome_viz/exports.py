from .artifacts import variant_folder
import csv,io,json
import numpy as np
from django.http import StreamingHttpResponse,HttpResponse
from .artifacts import read_bundle,read_json,read_matrix,read_metadata,read_arrays,clean

class Echo:
    def write(self,value):return value

def download(target,chart_id,kind='chart',delimiter=',',variant_id=''):
    manifest=read_json(target/'manifest.json');bundle=read_bundle(str(target));cid=bundle.get(chart_id,{}).get('chart_ref',chart_id)
    if cid not in bundle:raise ValueError('unknown_chart_id')
    figure=bundle[cid]
    if variant_id:
        import re
        if cid!='B15' or not re.fullmatch('[0-9a-f]{64}',variant_id):raise ValueError('invalid_export_variant')
        figure=read_json(variant_folder(target)/(variant_id[:16]+'.json'))
        if figure['variant_id']!=variant_id:raise ValueError('variant_identity_conflict')
        for field in figure['fields']:field['unit']=next(f['unit'] for f in manifest['fields'] if f['key']==field['key'])
    if kind=='method':return HttpResponse(json.dumps(clean({'manifest':manifest,'figure':figure}),ensure_ascii=False),content_type='application/json; charset=utf-8')
    matrix=read_matrix(str(target));metadata=read_metadata(str(target));arrays=read_arrays(str(target));n=manifest['n_source']
    if kind in ['pca','loadings'] and cid+'_coordinates' not in arrays:raise ValueError('pca_coordinates_unavailable')
    def records():
        yield '\ufeff'
        writer=csv.writer(Echo(),delimiter=delimiter)
        if kind=='pca':
            if cid+'_coordinates' not in arrays:raise ValueError('pca_coordinates_unavailable')
            co=arrays[cid+'_coordinates'];idx=arrays[cid+'_row_index'];yield writer.writerow(['protein_id']+[f'PC{i+1}' for i in range(co.shape[1])])
            for i,row in zip(idx,co):yield writer.writerow([metadata['protein_id'][i],*row])
        elif kind=='loadings':
            fields=bundle[cid]['data']['input_fields'];components=arrays[cid+'_components'];directions=arrays[cid+'_directions'];yield writer.writerow(['field']+[f'PC{i+1}_coefficient' for i in range(len(components))]+[f'PC{i+1}_correlation_direction' for i in range(len(components))])
            for j,f in enumerate(fields):yield writer.writerow([f,*components[:,j],*directions[j]])
        elif kind in ['candidates','percentiles']:
            names=bundle['D15']['data']['modules'];a=arrays['candidate_scores' if kind=='candidates' else 'candidate_percentiles'];evidence=bundle['D14']['data']['evidence'];coverage={}
            for name in names:
                fs=evidence.get(name,{}).get('fields',['gravy' if name=='Hydropathy' else 'disulfide_density']);coverage[name]=np.isfinite(matrix['matrix'][:,[matrix['fields'].index(f) for f in fs]]).sum(1)
            yield writer.writerow(['protein_id','gene_id',*names,*[name+'_components_available' for name in names]])
            for i in range(n):yield writer.writerow([metadata['protein_id'][i],metadata['gene_id'][i],*[float(x) if np.isfinite(x) else '' for x in a[i]],*[int(coverage[name][i]) for name in names]])
        elif kind=='partial_candidates':
            yield writer.writerow(['module','protein_id','available_component_score','component_n','primary_ranking'])
            for name in ['Resource','S-rich','AA_anomaly','Redox']:
                key='partial_'+name
                if key+'_rows' not in arrays:continue
                for i,s,c in zip(arrays[key+'_rows'],arrays[key+'_scores'],arrays[key+'_component_n']):yield writer.writerow([name,metadata['protein_id'][i],float(s) if np.isfinite(s) else '',int(c),'excluded: incomplete components'])
        elif kind in ['raw','structure']:
            fs=matrix['fields'];yield writer.writerow([*metadata,*fs])
            order=arrays['D07_order'] if kind=='structure' else range(n)
            for i in order:yield writer.writerow([*[metadata[k][i] for k in metadata],*[float(x) if np.isfinite(x) else '' for x in matrix['matrix'][i]]])
        elif kind=='ecdf':
            fields=[f['key'] for f in figure['fields']];yield writer.writerow(['field','value','count','cdf'])
            for f in fields:
                if f not in matrix['fields']:continue
                v=matrix['matrix'][:,matrix['fields'].index(f)];v=v[np.isfinite(v)];values,counts=np.unique(v,return_counts=True);cs=np.cumsum(counts)
                for x,c,s in zip(values,counts,cs):yield writer.writerow([f,float(x),int(c),float(s/len(v))])
        elif kind=='chart':
            data=figure['data']
            if cid in ['B13','B14']:
                profiles=read_json(target/'profiles.json.gz');yield writer.writerow(['field','unit','n_source','n_valid','n_missing','n_zero','min','p05','p25','median','p75','p95','max','mean'])
                for f in manifest['fields']:
                    p=profiles[f['key']];yield writer.writerow([f['key'],f['unit'],n,p['n_valid'],p['n_missing'],p['n_zero'],*(p['quantiles'] or ['']*7),p['mean']])
            elif 'hex' in data:
                yield writer.writerow(['bin_id','x','y','count','polygon_json'])
                for b in data['hex']['bins']:yield writer.writerow([b['bin_id'],*b['center'],b['count'],json.dumps(b['polygon'])])
            else:
                yield writer.writerow(['chart_id','section','semantic_json'])
                for key,value in data.items():yield writer.writerow([cid,key,json.dumps(clean(value),ensure_ascii=False)])
        else:raise ValueError('invalid_export_kind')
    response=StreamingHttpResponse(records(),content_type='text/csv; charset=utf-8')
    name=f'{manifest["species_id"]}_{manifest["primary_scope"]}_{chart_id}_{kind}_{manifest["artifact_version"]}'
    response['Content-Disposition']=f'attachment; filename="{name}.{"tsv" if delimiter==chr(9) else "csv"}"'
    response['X-Artifact-Version']=manifest['artifact_version'];response['X-Source-Hash']=manifest['source_hash']
    return response
