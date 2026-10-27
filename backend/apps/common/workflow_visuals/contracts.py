from __future__ import annotations
import hashlib,json,math
import numpy as np
import pandas as pd

VERSION='workflow_viz_v2'
PAGING={'page','page_size','offset','limit','export_scope','format','plot_signature','panel_id','bin_id','record_id','presentation'}
ALLOWED={'analysis_run_id','context_id','gene_id','feature_key','feature','x_field','y_field','field','fields','entities','group','species_id','sample_id','condition','query','search','term_key','term','source','direction','status','scope','q_max','run_id','model','omics','family','final_status','priority_tier','panel_profile','panel_id_core','mode','reference_group','case_group','label_field'}

def clean(v):
    if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple,np.ndarray)):return [clean(x) for x in v]
    if isinstance(v,np.generic):return clean(v.item())
    if isinstance(v,float) and not math.isfinite(v):return None
    if v is pd.NA or v is pd.NaT:return None
    return v

def digest(v):return hashlib.sha256(json.dumps(clean(v),sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str,allow_nan=False).encode()).hexdigest()

def parameters(params):
    if hasattr(params,'lists') and any(len(v)>1 for k,v in params.lists()):raise ValueError('Duplicate query parameters are ambiguous')
    raw=params.dict() if hasattr(params,'dict') else dict(params)
    data={k:v for k,v in raw.items() if k not in PAGING and v is not None and v!=''}
    unknown=set(data)-ALLOWED
    if unknown:raise ValueError('Unsupported visual parameter: '+', '.join(sorted(unknown)))
    if 'q_max' in data:
        q=float(data['q_max'])
        if not math.isfinite(q) or not 0<=q<=1:raise ValueError('q_max outside [0,1]')
        data['q_max']=q
    return data

def counts(source,scope,finite=None,marks=None):
    finite=scope if finite is None else finite
    return {'source_rows':int(source),'scope_rows':int(scope),'finite_rows':int(finite),'non_estimable_rows':int(scope-finite),'represented_rows':int(scope),'marks':int(finite if marks is None else marks)}

class Bundle:
    def __init__(self,chart,title,signature,params,source_kind,run=None,context=None):
        self.sources={};self.records={};self.members={}
        self.packet={'schema_version':VERSION,'chart_id':chart,'title':title,'status':'ready','reason_code':None,'reason':None,
          'source_kind':source_kind,'analysis_run_id':run,'context_id':context,'source_signature':signature,
          'scope':{'filters':params,'statistical_unit':'saved records','population':'complete filtered saved results'},
          'counts':counts(0,0),'method':{'name':'saved evidence; complete descriptive presentation','transform':'display only','unit':'original saved units','q_family':'preserved per source table'},
          'data':{'panels':[],'status_counts':[]},'exports':{},'provenance':{'source_tables':[],'source_schema_version':None,'feature_schema':None,'annotation_snapshot_id':None,'data_release_id':None}}
    def add_source(self,key,frame,source_rows=None):
        self.sources[key]=frame
        self.packet['provenance']['source_tables'].append({'table':key,'source_rows':len(frame) if source_rows is None else source_rows,'scope_rows':len(frame)})
    def add(self,panel,frame=None,members=None):
        panel.setdefault('panel_id','panel_'+str(len(self.packet['data']['panels'])+1))
        self.packet['data']['panels'].append(clean(panel))
        if frame is not None:self.records[panel['panel_id']]=frame if isinstance(frame.index,pd.RangeIndex) and frame.index.start==0 and frame.index.step==1 else frame.reset_index(drop=True)
        if members is not None:self.members[panel['panel_id']]=members
    def unavailable(self,reason,code='missing_saved_source',status='not_generated'):
        self.packet.update(status=status,reason_code=code,reason=reason)
    def finish(self):
        from .presentation import decorate
        decorate(self)
        panels=self.packet['data']['panels'];tables=self.packet['provenance']['source_tables']
        # Top-level counts describe the first declared panel only. Panel/table populations
        # are independent: field cells, genes and tests must never be added as one sample n.
        self.packet['counts']=dict(panels[0]['counts']) if panels else counts(tables[0]['source_rows'],tables[0]['scope_rows']) if tables else counts(0,0)
        self.packet['counts_basis']=panels[0]['panel_id'] if panels else 'first_source'
        self.packet['scope']['statistical_unit']='see each panel' if len(panels)>1 else (panels[0].get('unit','saved records') if panels else 'saved records')
        self.packet['plot_signature']=digest([self.packet.get('design_revision'),self.packet.get('presentation'),self.packet['source_signature'],self.packet['scope'],self.packet['chart_id'],[(p['panel_id'],p.get('grid'),p.get('x_label'),p.get('y_label')) for p in panels]])
        if not panels and self.packet['status']=='ready':self.unavailable('No applicable saved fields or complete source rows are available.')
        return self
    def public(self):
        # CSV statistics remain in the private bundle for streaming export. Do not
        # duplicate every ECDF coordinate as a wide dictionary in the HTTP packet.
        return {**self.packet,'data':{**self.packet['data'],'panels':[{k:v for k,v in p.items() if k!='plot_rows'} for p in self.packet['data']['panels']]}}
