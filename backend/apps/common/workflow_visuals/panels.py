"""Shared descriptive panels. Every series has an explicit population and original unit."""
import numpy as np
import pandas as pd
from .statistics import numeric,ecdf,quantiles,hexagons,q_coordinates
from .contracts import counts,clean

def column(frame,*names):return next((n for n in names if n in frame),None)
def num(frame,name):return numeric(frame[name]) if name in frame else np.full(len(frame),np.nan)
def groups(frame,by=None):
    keys=[k for k in ([by] if isinstance(by,str) else by or []) if k in frame]
    if not keys:return [('All',frame)]
    return [(' · '.join(map(str,key if isinstance(key,tuple) else (key,))),sub) for key,sub in frame.groupby(keys[0] if len(keys)==1 else keys,dropna=False,sort=True)]

def distribution(bundle,frame,fields,by=None,prefix='distribution',title=None):
    for field in fields:
        if field not in frame:continue
        curves=[];finite=0;plot=[]
        for name,sub in groups(frame,by):
            e=ecdf(sub[field]);q=quantiles(sub[field]);finite+=e['n']
            curves.append({'name':name,**e,'quantiles':q})
            plot.extend({'group':name,'field':field,'x':x,'frequency':n,'cumulative':c,'cdf':f} for x,n,c,f in zip(e['x'],e['frequency'],e['cumulative'],e['cdf']))
        bundle.add({'type':'ecdf','panel_id':prefix+'_'+field,'title':title or field,'x_label':field+' (saved units)','y_label':'Cumulative fraction',
                    'unit':'records with finite '+field,'curves':curves,'plot_rows':plot,'counts':counts(len(frame),len(frame),finite,len(plot)),
                    'reason_code':'no_finite_values' if not finite else None},frame)

def scatter(bundle,frame,x,y,by=None,prefix='scatter',title=None,density=False,x_values=None,y_values=None,x_label=None,y_label=None):
    frame=frame.reset_index(drop=True);a=num(frame,x) if x_values is None else np.asarray(x_values,float);b=num(frame,y) if y_values is None else np.asarray(y_values,float)
    valid=np.isfinite(a)&np.isfinite(b);n=int(valid.sum());category=frame[by].astype(str).tolist() if by in frame else ['All']*len(frame)
    base={'panel_id':prefix,'title':title or (str(x)+' vs '+str(y)),'x_label':x_label or str(x),'y_label':y_label or str(y),'unit':'saved rows',
          'excluded':{'missing_or_nonfinite_coordinates':int((~valid).sum())},'source_fields':[x,y], 'counts':counts(len(frame),len(frame),n,n)}
    if density or n>20000:
        bins,members,grid=hexagons(a,b)
        base.update(type='hexbin',bins=bins,grid=grid,plot_rows=bins)
        base['counts']['marks']=len(bins)
        bundle.add(base,frame,members)
    else:
        ids=np.flatnonzero(valid)
        points=[[float(a[i]),float(b[i]),category[i],str(i)] for i in ids]
        base.update(type='scatter',points=points,categories=list(dict.fromkeys(category)),plot_rows=[{'x':p[0],'y':p[1],'group':p[2],'record_id':p[3]} for p in points])
        bundle.add(base,frame)

def rank(bundle,frame,value,by=None,prefix='rank',title=None,rank_field=None,label=None,highlight=None):
    if value not in frame:return
    frame=frame.reset_index(drop=True);frame=frame.copy();frame['_source_i']=np.arange(len(frame))
    curves=[];plot=[];finite=0
    for name,sub in groups(frame,by):
        sub=sub.copy();sub['_display_value']=num(sub,value)
        tie=[k for k in ['context_id','feature_key','feature_name','gene_id','entity_id','term_key','run_id','model'] if k in sub]
        order=[rank_field] if rank_field in sub else ['_display_value']
        sub=sub.sort_values(order+[k for k in tie if k not in order],ascending=[True if rank_field in sub else False]+[True for k in tie if k not in order],kind='stable')
        points=[]
        for i,(_,row) in enumerate(sub.iterrows()):
            v=row['_display_value'];x=row.get(rank_field) if rank_field in sub else i+1
            if not np.isfinite(v):continue
            try:x=float(x)
            except (ValueError,TypeError):x=i+1
            key=str(row.get(label) or row.get('gene_id') or row.get('feature_key') or row.get('feature_name') or row.get('entity_id') or i)
            high=bool(row.get(highlight,False)) if isinstance(highlight,str) else key in highlight if highlight else False
            points.append([x,float(v),key,high,int(row['_source_i'])]);plot.append({'group':name,'display_rank':x,'value':v,'id':key,'highlight':high,'record_id':int(row['_source_i'])})
        finite+=len(points);curves.append({'name':name,'points':points})
    bundle.add({'type':'rank','panel_id':prefix,'title':title or value,'x_label':rank_field or 'Display rank (saved value; stable order)',
        'y_label':value,'identity_field':label,'curves':curves,'plot_rows':clean(plot),'counts':counts(len(frame),len(frame),finite,len(plot))},frame.drop(columns=['_source_i']))

def categories(bundle,frame,field,by=None,prefix='categories',title=None):
    if field not in frame:return
    rows=[]
    for name,sub in groups(frame,by):
        c=sub[field].astype('string').fillna('unassigned').replace('','unassigned').value_counts(sort=False)
        rows.extend({'group':name,'category':str(k),'count':int(v)} for k,v in c.items())
    assert sum(r['count'] for r in rows)==len(frame)
    bundle.add({'type':'categories','panel_id':prefix,'title':title or field,'x_label':'Saved categories','y_label':'Count of saved rows','rows':rows,'plot_rows':rows,'counts':counts(len(frame),len(frame),len(frame),len(rows))},frame)

def heatmap(bundle,frame,x,y,value,prefix='matrix',title=None,color_kind='sequential',domain=None,label=None):
    if any(c not in frame for c in [x,y,value]):return
    xs=list(dict.fromkeys(frame[x].astype(str)));ys=list(dict.fromkeys(frame[y].astype(str)));rows=[];finite=0
    for i,r in enumerate(frame.to_dict('records')):
        raw=r.get(value)
        try:v=float(raw);v=v if np.isfinite(v) else None
        except (ValueError,TypeError):v=None
        finite+=v is not None
        rows.append({'x':str(r[x]),'y':str(r[y]),'value':v,'record_id':str(i),'label':r.get(label) if label else None,**r})
    vals=[r['value'] for r in rows if r['value'] is not None]
    if domain is None:
        lim=max(map(abs,vals),default=1) or 1
        domain=[-lim,lim] if color_kind=='diverging' else [min(vals,default=0),max(vals,default=1)]
    bundle.add({'type':'heatmap','panel_id':prefix,'title':title or value,'x_label':x,'y_label':y,'x_categories':xs,'y_categories':ys,'value_key':value,
                'rows':rows,'plot_rows':rows,'unit':'matrix cells; source-table denominators remain separate','color_kind':color_kind,'color_domain':domain,'counts':counts(len(frame),len(frame),finite,len(rows))},frame)

def intervals(bundle,frame,effect,low,high,by=None,prefix='interval',title=None,or_ci=False):
    if effect not in frame:return
    f=frame.reset_index(drop=True).copy();f['_record_index']=np.arange(len(f));f['_estimate']=num(f,effect);l=num(f,low);h=num(f,high)
    if or_ci:l=np.where(l>0,np.log(np.where(l>0,l,1)),np.nan);h=np.where(h>0,np.log(np.where(h>0,h,1)),np.nan)
    f['_lo']=l;f['_hi']=h;points=[];finite=0
    for name,sub in groups(f,by):
        sub=sub.sort_values('_estimate',kind='stable',na_position='last')
        for i,r in enumerate(sub.to_dict('records')):
            valid=all(np.isfinite(r[k]) for k in ['_estimate','_lo','_hi']) and r['_lo']<=r['_hi']
            finite+=valid
            points.append({'group':name,'rank':i+1,'estimate':r['_estimate'],'low':r['_lo'],'high':r['_hi'],'ci_available':bool(valid),
                           'feature_key':r.get('feature_key',r.get('feature_name')),'record_id':str(r['_record_index'])})
    bundle.add({'type':'intervals','panel_id':prefix,'title':title or effect,'x_label':'Display rank','y_label':'log odds ratio (ln saved OR CI)' if or_ci else effect,
                'rows':clean(points),'plot_rows':clean(points),'counts':counts(len(f),len(f),finite,finite),'ci_transform':'ln(OR)' if or_ci else 'original'},frame)

def evidence(bundle,frame,effect='effect',q='q_global',by='context_id',prefix='evidence',title=None,density=False):
    if effect not in frame:return
    if q in frame:scatter(bundle,frame,effect,q,by,prefix,title,density,y_values=q_coordinates(frame[q]),y_label='−log10(saved '+q+'); q=0 floor 1e−300')
    else:rank(bundle,frame,effect,by,prefix,title)
    status=column(frame,'status','adjusted_status','analysis_status','final_status','nes_status')
    if status:categories(bundle,frame,status,by,prefix+'_states','Saved estimability states')
