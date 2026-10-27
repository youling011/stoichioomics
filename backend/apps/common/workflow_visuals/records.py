from .contracts import clean

def selected_frame(bundle,params,require_selection=True):
    signature=params.get('plot_signature')
    if signature and signature!=bundle.packet['plot_signature']:raise RuntimeError('stale_plot')
    if (params.get('bin_id') or params.get('record_id')) and not signature:raise ValueError('plot_signature is required for point/bin details')
    panel=params.get('panel_id')
    if panel not in bundle.records:raise ValueError('Unknown panel_id')
    frame=bundle.records[panel]
    if params.get('bin_id') is not None:
        key=params['bin_id'];members=bundle.members.get(panel,{})
        if key not in members:raise ValueError('Unknown bin_id')
        return frame.iloc[members[key]]
    if params.get('record_id') is not None:
        try:index=int(params['record_id'])
        except (ValueError,TypeError):raise ValueError('Invalid record_id')
        if index<0 or index>=len(frame):raise ValueError('Unknown record_id')
        return frame.iloc[[index]]
    if require_selection:raise ValueError('Select an exact bin_id or record_id')
    return frame

def records(bundle,params):
    page=int(params.get('page',1));size=int(params.get('page_size',50))
    if page<1 or not 1<=size<=200:raise ValueError('page>=1 and page_size=1..200 required')
    frame=selected_frame(bundle,params)
    return {'rows':clean(frame.iloc[(page-1)*size:page*size].to_dict('records')),'total':len(frame),'page':page,'page_size':size,
            'plot_signature':bundle.packet['plot_signature'],'panel_id':params.get('panel_id'),'bin_id':params.get('bin_id')}
