import csv,io,json
import pandas as pd
from django.http import StreamingHttpResponse
from rest_framework.negotiation import DefaultContentNegotiation
from .contracts import clean
from .records import selected_frame

class ExportNegotiation(DefaultContentNegotiation):
    def filter_renderers(self,renderers,format):return renderers

def cell(value):
    value=clean(value)
    if isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False,allow_nan=False)
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):value="'"+value
    return value

def export(bundle,params):
    fmt=params.get('format','csv');scope=params.get('export_scope','plot')
    if fmt not in ['csv','tsv'] or scope not in ['plot','source']:raise ValueError('Use format=csv/tsv and export_scope=plot/source')
    signature=params.get('plot_signature')
    if signature and signature!=bundle.packet['plot_signature']:raise RuntimeError('stale_plot')
    if scope=='source':
        tables={'selected_members':selected_frame(bundle,params)} if params.get('bin_id') or params.get('record_id') else bundle.sources
    else:tables={p['panel_id']:pd.DataFrame(p.get('plot_rows',[])) for p in bundle.packet['data']['panels']}
    columns=list(dict.fromkeys(k for f in tables.values() for k in f.columns))
    common={'chart_id':bundle.packet['chart_id'],'source_signature':bundle.packet['source_signature'],'plot_signature':bundle.packet['plot_signature'],
            'export_scope':scope,'analysis_run_id':bundle.packet['analysis_run_id'],'context_id':bundle.packet['context_id'],'analysis_filters':json.dumps(bundle.packet['scope']['filters'],ensure_ascii=False,sort_keys=True)}
    names=list(common)+['_source_table']+[k for k in columns if k not in common and k!='_source_table']
    def stream():
        buf=io.StringIO(newline='');writer=csv.DictWriter(buf,fieldnames=names,delimiter=',' if fmt=='csv' else '\t',lineterminator='\n',extrasaction='ignore')
        writer.writeheader();yield buf.getvalue();buf.seek(0);buf.truncate(0)
        for name,frame in tables.items():
            cols=list(frame.columns)
            for values in frame.itertuples(index=False,name=None):
                writer.writerow({k:cell(v) for k,v in {**dict(zip(cols,values)),**common,'_source_table':name}.items()});yield buf.getvalue();buf.seek(0);buf.truncate(0)
    response=StreamingHttpResponse(stream(),content_type=('text/csv' if fmt=='csv' else 'text/tab-separated-values')+'; charset=utf-8')
    response['Content-Disposition']='attachment; filename="'+bundle.packet['chart_id']+'_'+scope+'.'+fmt+'"'
    response['X-Plot-Signature']=bundle.packet['plot_signature']
    return response
