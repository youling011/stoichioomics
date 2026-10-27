"""Full saved sequence results, presentation only. Never calls job cleanup or the engine."""
from __future__ import annotations
from backend.apps.common.workflow_visuals.presentation_specs import DESIGN_REVISION,validate_profile
import json,re
from datetime import datetime,timezone
from itertools import product
import numpy as np
import pandas as pd
from backend.apps.common.host_paths import Path
from backend.apps.common.workflow_visuals import panels as P
from backend.apps.common.workflow_visuals.contracts import Bundle,counts,digest,parameters,clean
from backend.apps.common.workflow_visuals.cache import read_frame,sha_file,packet_cache
from backend.apps.common.workflow_visuals.statistics import numeric,quantiles,percentile
from .services import _job_dir,OUTPUT_FILES
from .feature_panel_registry import get_core_panel_registry,get_core_fields,AA_CODES

TITLES=['Complete saved-column audit','All analysis features: pooled-reference percentiles','All saved PCA coordinates','Complete differential-feature evidence','Genome coordinates and composition','All 64 saved codon frequencies','All standard amino-acid distributions','Molecular element budgets','Base composition and regional context','Full feature ECDF and quantiles','Full-population joint density','Saved extreme members in the full rank background','Saved strategy composition','All signed coupling edges','Complete sample comparisons and pairing status','Training fit and cross-validation','All saved importance ranks','Complete saved ROC and PR curves','Actual embedding and fitted confidence','Original selected-feature distributions','Selected entities in a complete reference','Complete saved differential-entity pool','Proteome: all numeric field quantiles','Genome: all numeric field quantiles','Transcript sequence: all numeric field quantiles']
REGISTRY={f'S{i+1:02}':{'chart_id':f'S{i+1:02}','title':t} for i,t in enumerate(TITLES)}
META={'species_id','protein_id','gene_id','gene_name','gene_symbol','transcript_id','source_db','source_protein_id','source_gene_id','source_transcript_id','ensembl_gene_id','ensembl_transcript_id','ensembl_protein_id','description','seq_md5','entity_id','sample_id','group','condition','seqid','strand','biotype','locus_tag','chosen_transcript_source_id','chosen_transcript_reason','exon_seq_strategy','omics','source_database'}

def resolve(job_id):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',str(job_id)) or job_id in {'.','..'}:raise ValueError('Invalid job identifier')
    root=_job_dir(job_id);meta=root/'job.json'
    if not meta.is_file():raise FileNotFoundError('No saved job metadata for this identifier')
    job=json.loads(meta.read_text('utf-8-sig'))
    if job.get('job_id')!=job_id:raise ValueError('Job ownership mismatch')
    # Match the existing TTL boundary without invoking its destructive cleanup on GET.
    if job.get('expires_at'):
        try:
            expiry=datetime.fromisoformat(str(job['expires_at']).replace('Z','+00:00'))
            if expiry.tzinfo is None:expiry=expiry.replace(tzinfo=timezone.utc)
        except (ValueError,TypeError):expiry=None
        if expiry is not None and expiry<=datetime.now(timezone.utc):raise FileNotFoundError('Saved task expired')
    return root,job

class Saved:
    def __init__(self,root,job):self.root=root;self.job=job;self.files={k:root/'outputs'/v for k,v in OUTPUT_FILES.items()};self.used={}
    def frame(self,key):
        p=self.files.get(key)
        return read_frame(p) if p and p.is_file() else pd.DataFrame()
    def js(self,key):
        p=self.files.get(key)
        return json.loads(p.read_text('utf-8-sig')) if p and p.is_file() else {}
    def signature(self):return digest([self.job,[(k,sha_file(p)) for k,p in sorted(self.files.items()) if p.is_file()]])

def filter_frame(f,params):
    f=f.copy(deep=False)
    for key in ['group','species_id','sample_id','condition']:
        if params.get(key):
            if key not in f:raise ValueError('Filter is not present in this saved schema: '+key)
            f=f.loc[f[key].astype(str).eq(str(params[key]))]
    q=params.get('search') or params.get('query')
    if q:
        mask=np.zeros(len(f),bool)
        for key in [k for k in ['entity_id','gene_id','gene_name','protein_id','sample_id','species_id','group','feature_name','comparison'] if k in f]:mask|=f[key].astype(str).str.contains(str(q),case=False,regex=False,na=False).to_numpy()
        f=f.loc[mask]
    return f.reset_index(drop=True)

def audit(f,catalog):
    definitions={x.get('field',x.get('feature_name')):x for x in catalog.get('features',[])};rows=[]
    for i,key in enumerate(f):
        raw=f[key];metadata=key in META or definitions.get(key,{}).get('unit')=='metadata'
        a=np.full(len(raw),np.nan) if metadata else numeric(raw);valid=np.isfinite(a);n=int(valid.sum());nonempty=~raw.astype('string').fillna('').str.strip().isin(['','nan','NaN','None','null'])
        state='metadata' if metadata else 'empty' if not nonempty.any() else 'constant' if n and np.unique(a[valid]).size==1 else 'variable' if n else 'non_numeric'
        rows.append({'field':key,'column_index':i+1,'state':state,'n_source':len(f),'n_valid':int(nonempty.sum()) if metadata else n,'n_missing':int((~nonempty).sum()) if metadata else len(f)-n,
                     'numeric':bool(n) and not metadata,'unit':definitions.get(key,{}).get('unit','saved units'),'analysis_feature':key in definitions})
    return pd.DataFrame(rows)

def field_choice(f,params,analysis):
    key=params.get('field') or params.get('feature') or params.get('feature_key')
    if key:
        if key not in f:raise ValueError('Unknown saved field: '+str(key))
        return key
    return next((k for k in ['pI','gc_percent_display','exon_gc_percent','length_aa','length_nt',*analysis] if k in f),None)

def matrix_quantiles(b,f,fields,prefix='quantiles'):
    rows=[]
    for field in fields:
        if field not in f:continue
        q=quantiles(f[field])
        for quantile in ['q05','q25','q50','q75','q95']:
            raw=q[quantile];value=None if raw is None else 0. if q['min']==q['max'] else (raw-q['min'])/(q['max']-q['min'])
            rows.append({'field':field,'quantile':quantile,'value':value,'raw_quantile':raw,**q,'state':'empty' if not q['n'] else 'constant' if q['min']==q['max'] else 'variable'})
    frame=pd.DataFrame(rows);P.heatmap(b,frame,'quantile','field','value',prefix,'All finite values, original field units',domain=[0,1])

def composition(b,f,fields,mode='mean',prefix='composition',by='group'):
    rows=[]
    for name,sub in P.groups(f,by):
        for field in fields:
            q=quantiles(sub[field]) if field in sub else quantiles([])
            a=numeric(sub[field]) if field in sub else np.array([]);a=a[np.isfinite(a)]
            rows.append({'field':field,'group':name,'value':float(a.mean()) if mode=='mean' and len(a) else q['q50'],'estimate':q['q50'],'low':q['q25'],'high':q['q75'],**q})
    q=pd.DataFrame(rows)
    if mode=='mean':P.heatmap(b,q,'group','field','value',prefix,'Complete saved composition; unweighted means')
    else:
        b.add({'type':'composition_intervals','panel_id':prefix,'title':'Median and IQR (not mean CI)','rows':clean(rows),'plot_rows':clean(rows),'x_label':'Saved composition units','y_label':'Standard amino acids','counts':counts(len(rows),len(rows),sum(r['n']>0 for r in rows),len(rows))},q)

def capability(root,job):
    saved=Saved(root,job);raw=saved.frame('features');catalog=saved.js('feature_catalog');columns=audit(raw,catalog);omics=job.get('omics_type') or saved.js('summary').get('omics_type')
    panels=get_core_panel_registry(omics);core=get_core_fields(omics)
    return {'schema_version':'workflow_viz_v2','job_id':job['job_id'],'source_signature':saved.signature(),'charts':list(REGISTRY.values()),'fields':clean(columns.to_dict('records')),
        'core_fields':[{'field':k,'present':k in raw,'disposition':'saved' if k in raw else 'not_saved_or_unmapped'} for k in core],
        'expected_features':len(core),'present_features':sum(k in raw for k in core),'classified_features':len(core),'core_panels':panels,'source_kind':'sequence_saved','enabled':True}

def build(root,job,chart,params=None):
    if chart not in REGISTRY:raise ValueError('Unknown sequence chart ID')
    params=parameters(params or {});validate_profile(chart,params,'sequence');saved=Saved(root,job);signature=saved.signature()
    return packet_cache(digest([DESIGN_REVISION,'seq',str(root),signature,chart,params]),lambda:_build(saved,chart,params,signature))

def _build(saved,chart,params,signature):
    b=Bundle(chart,REGISTRY[chart]['title'],signature,params,'sequence_saved',saved.job['job_id'])
    if saved.job.get('status')!='SUCCEEDED':b.unavailable('The task has not completed. Only fully published saved results can be read.','task_not_complete','running' if saved.job.get('status') in ['RUNNING','READY','QUEUED'] else 'not_generated');return b.finish()
    allf=saved.frame('features');f=filter_frame(allf,params);catalog=saved.js('feature_catalog');summary=saved.frame('feature_summary_csv');analysis=summary.feature_name.tolist() if 'feature_name' in summary else [x.get('field',x.get('feature_name')) for x in catalog.get('features',[])]
    key=field_choice(f,params,analysis);by='group' if 'group' in f else None;omics=saved.job.get('omics_type') or saved.js('summary').get('omics_type')
    def source(name):
        q=saved.frame(name);scope=filter_frame(q,params) if name in ['features','differential_entities','ml_predictions','top_low_entities_csv'] else q
        b.add_source(name,scope,len(q));return scope
    if f.empty:
        b.add_source('features',f,len(allf));b.unavailable('No rows in the current saved scope.','empty_scope','not_estimable');return b.finish()
    b.packet['provenance']['source_schema_version']=saved.js('job_manifest').get('schema_version')
    b.packet['provenance']['feature_schema']=omics
    panel_id=params.get('panel_id_core')
    if panel_id:
        panel=next((r for r in get_core_panel_registry(omics) if r['panel_id']==panel_id),None)
        if not panel:raise ValueError('Unknown Core panel ID for this omics')
        fields=panel['fields'];b.add_source('features',f,len(allf));a=audit(f,catalog);b.packet['data']['field_dispositions']=[{'field':k,'state':a.loc[a.field.eq(k),'state'].iloc[0] if k in f else 'not_saved_or_unmapped'} for k in fields]
        b.packet['data']['core_panel_id']=panel_id
        if 'annotation_overview' in panel_id:
            for k in fields:
                if k in f and f[k].nunique(dropna=False)<32 and not k.endswith('_id'):P.categories(b,f,k,by,'category_'+k)
            a=a[a.field.isin(fields)].copy();a['context']='Saved fields';states=list(dict.fromkeys(a.state));a['value']=a.state.map({k:i for i,k in enumerate(states)});P.heatmap(b,a,'field','context','value','audit','Field dispositions',domain=[0,max(1,len(states)-1)]);b.packet['data']['state_legend']=states
            if states:b.packet['data']['panels'][-1]['category_states']=states
        elif 'dinucleotide' in panel_id:composition(b,f,fields, prefix=panel_id)
        elif 'codon' in panel_id:composition(b,f,[f'codon_{"".join(c)}_freq' for c in product('ACGU' if omics=='transcriptome' else 'ACGT',repeat=3)],prefix=panel_id);matrix_quantiles(b,f,[k for k in fields if k in f and not k.startswith('codon_')],panel_id+'_context')
        elif 'translated_aa' in panel_id or 'aa_percentage' in panel_id:
            aa=[f'AA_{a}_pct' for a in AA_CODES] if omics=='proteome' else [f'aa_{a}_freq' for a in AA_CODES]
            composition(b,f,aa,'interval',panel_id);matrix_quantiles(b,f,[k for k in fields if k in f and k not in aa],panel_id+'_other')
        else:
            matrix_quantiles(b,f,[k for k in fields if k in f],panel_id+'_quantiles')
            P.distribution(b,f,[k for k in fields if k in f],by,panel_id)
            if panel_id=='genome_region_quality':coordinate_panels(b,f)
            if panel_id=='transcriptome_rna_base_complexity':composition(b,f,['frac_'+base for base in 'ACGU'],prefix='rna_base_means')
        if panel_id=='transcriptome_orf_translated_aa' and any('codon_'+''.join(c)+'_freq' in f for c in product('ACGU',repeat=3)):
            composition(b,f,['codon_'+''.join(c)+'_freq' for c in product('ACGU',repeat=3)],prefix='all_rna_codons')
        return b.finish()
    if chart=='S01':
        a=audit(f,catalog);b.add_source('column_audit',a);a['context']='Every saved column';states=['metadata','empty','constant','variable','non_numeric'];a['value']=a.state.map({s:i for i,s in enumerate(states)})
        P.heatmap(b,a,'field','context','value','column_audit','All original saved columns',domain=[0,4]);b.packet['data']['state_legend']=states
        b.packet['data']['panels'][-1]['category_states']=states
    elif chart=='S02':
        b.add_source('features',f,len(allf));rows=[]
        for field in analysis:
            for group,sub in P.groups(f,by):
                q=quantiles(sub[field]) if field in f else quantiles([]);rows.append({'field':field,'group':group,'median':q['q50'],'value':percentile(f[field],q['q50']) if field in f else None,'n_valid':q['n'],'reference_n':int(np.isfinite(numeric(f[field])).sum()) if field in f else 0})
        P.heatmap(b,pd.DataFrame(rows),'group','field','value','pooled_percentiles','Group medians in the same-field complete pooled reference',domain=[0,1])
    elif chart=='S03':
        points=pd.DataFrame(saved.js('plots').get('pca_scatter',[]));b.add_source('saved_pca',points)
        if len(points)!=len(allf):b.unavailable('Saved PCA coordinates do not cover the complete saved input.','incomplete_saved_coordinates','not_generated')
        else:
            points=filter_frame(points,params);P.scatter(b,points,'pc1','pc2','group','pca','All saved PCA coordinates')
    elif chart=='S04':
        q=source('differential_features');metric='importance' if 'importance' in q and np.isfinite(P.num(q,'importance')).any() else P.column(q,'cliffs_delta','effect_size','statistic')
        if metric:P.rank(b,q,metric,'comparison','differential','Every saved differential feature',label='feature_name')
        for col in ['p_value','fdr']:
            if col in q:
                state=pd.DataFrame({'availability':np.where(np.isfinite(P.num(q,col)),'finite saved '+col,'unavailable '+col)})
                P.categories(b,state,'availability',prefix='availability_'+col)
    elif chart=='S05':
        b.add_source('features',f,len(allf));needed=['species_id','seqid','start_1','end_1','exon_gc_percent']
        if all(k in f for k in needed):
            coordinate_panels(b,f)
        else:b.unavailable('Full annotation coordinates were not saved.','missing_annotation_coordinates')
    elif chart in ['S06','S07']:
        b.add_source('features',f,len(allf))
        if chart=='S06':
            fields=[f'codon_{"".join(c)}_freq' for c in product('ACGU' if omics=='transcriptome' else 'ACGT',repeat=3)]
            if any(k in f for k in fields):composition(b,f,fields)
            else:b.unavailable('This saved schema contains no codon frequencies.','codon_fields_not_saved','not_applicable')
        else:composition(b,f,[f'AA_{a}_pct' for a in AA_CODES] if omics=='proteome' else [f'aa_{a}_freq' for a in AA_CODES],'interval');P.distribution(b,f,['AA_other_pct'],by)
    elif chart in ['S08','S09','S10','S11','S12','S13','S21','S23','S24','S25']:
        b.add_source('features',f,len(allf))
        if chart=='S08':P.distribution(b,f,[params.get('field') or {'genome':'exon_atoms_C_per_base','transcriptome':'atoms_per_nt_C','proteome':'C_atoms_per_aa'}.get(omics,'C_atoms_per_aa')],by)
        elif chart=='S09':
            P.distribution(b,f,['exon_gc_percent','promoter_gc_percent'],by)
            if omics=='transcriptome':composition(b,f,['frac_'+base for base in 'ACGU'])
        elif chart=='S10' and key:P.distribution(b,f,[key],by)
        elif chart=='S11':
            x=params.get('x_field') or next((k for k in ['C_atoms_per_aa','exon_atoms_C_per_base','atoms_per_nt_C',*analysis] if k in f),None);y=params.get('y_field') or key
            if x not in f or y not in f:raise ValueError('Unknown scatter field')
            for name,sub in P.groups(f,by):P.scatter(b,sub,x,y,by,'joint_'+digest(name)[:8],name,True)
        elif chart=='S12' and key:
            extreme=saved.frame('top_low_entities_csv');ids=set(extreme.loc[extreme.feature_name.eq(key),'entity_id'].astype(str)) if all(k in extreme for k in ['feature_name','entity_id']) else set()
            P.rank(b,f,key,by,'rank_background','All records; original Top/Low highlighted',label='entity_id',highlight=ids)
        elif chart=='S13':P.categories(b,f,'strategy_cluster',by)
        elif chart=='S21':
            ids=[x.strip() for x in str(params.get('entities','')).split(',') if x.strip()];selected=f[f.entity_id.astype(str).isin(ids)] if 'entity_id' in f else f.iloc[:0]
            fields=[x for x in str(params.get('fields','')).split(',') if x] or analysis
            if not ids:b.unavailable('Select entity IDs in the existing comparison form.','select_entities','not_applicable')
            elif len(selected)!=len(ids) or selected.entity_id.duplicated().any():b.unavailable('Entity IDs are absent or ambiguous; select species/sample to identify them.','ambiguous_or_missing_entity','not_estimable')
            else:
                rows=[]
                for field in fields:
                    if field not in f:raise ValueError('Unknown comparison field')
                    for _,r in selected.iterrows():
                        raw=pd.to_numeric(pd.Series([r[field]]),errors='coerce').iloc[0];rows.append({'field':field,'entity':r['entity_id'],'value':percentile(f[field],raw),'raw_value':raw,'reference_n':int(np.isfinite(numeric(f[field])).sum())})
                P.heatmap(b,pd.DataFrame(rows),'entity','field','value','selected_entities','Selected records; complete same-field reference',domain=[0,1])
        elif chart in ['S23','S24','S25']:
            expected={'S23':'proteome','S24':'genome','S25':'transcriptome'}[chart]
            if omics!=expected:b.unavailable('This quantile atlas belongs to '+expected+'.','different_omics','not_applicable')
            else:
                a=audit(f,catalog);matrix_quantiles(b,f,a.loc[a.numeric,'field'].tolist());b.packet['data']['field_audit']=clean(a.to_dict('records'))
    elif chart=='S14':
        q=pd.DataFrame(saved.js('analysis').get('coupling_edges',[]));b.add_source('coupling_edges',q)
        if len(q):b.add({'type':'network','panel_id':'coupling','title':'All saved signed coupling edges','rows':q.to_dict('records'),'plot_rows':q.to_dict('records'),'counts':counts(len(q),len(q)),'method':'Saved Spearman; no new correlation tests'},q)
    elif chart=='S15':
        q=source('differential_features');payload=saved.js('sample_comparison');b.packet['data']['matched_n']=payload.get('matched_n',0)
        if all(k in q for k in ['case_median','reference_median','feature_name','comparison']):
            q=q.copy();q['raw_delta']=P.num(q,'case_median')-P.num(q,'reference_median');scale=q.groupby('feature_name').raw_delta.transform(lambda s:np.nanmax(abs(s)) if np.isfinite(s).any() else np.nan);q['value']=q.raw_delta/scale.replace(0,1)
            P.heatmap(b,q,'comparison','feature_name','value','sample_deltas','Saved median differences; within-feature display scale',color_kind='diverging',domain=[-1,1])
        paired=pd.DataFrame(payload.get('paired_scatter',[]))
        if payload.get('matched_n',0)>0 and len(paired) and 'gene_key' in f and 'group' in f:
            fields=[params['field']] if params.get('field') else list(dict.fromkeys(paired.feature_name))
            records=[]
            for ref,case in paired[['reference_group','case_group']].drop_duplicates().itertuples(index=False,name=None):
                for field in fields:
                    if field not in f:continue
                    left=f[f.group.astype(str).eq(str(ref))].groupby('gene_key')[field].median(numeric_only=True)
                    right=f[f.group.astype(str).eq(str(case))].groupby('gene_key')[field].median(numeric_only=True)
                    for gene in left.index.intersection(right.index):records.append({'gene_key':gene,'feature_name':field,'reference_group':ref,'case_group':case,'reference_value':left.loc[gene],'case_value':right.loc[gene]})
            paired=pd.DataFrame(records)
            for name,sub in P.groups(paired,['feature_name','case_group']):P.scatter(b,sub,'reference_value','case_value',prefix='saved_matched_pairs_'+digest(name)[:8],title='Complete original gene-key pairing · '+name)
            b.packet['data']['pairing_definition']='Original gene_key group medians, all shared keys; no row-order pairing or inferential calculation'
        else:P.distribution(b,f,[key] if key else [],by,prefix='unpaired')
    elif chart=='S22':
        q=source('differential_entities');P.rank(b,q,'score',prefix='entity_pool',title='Complete saved result pool, not all input tested',label='entity_id');P.categories(b,q,'top_feature',prefix='contribution_sources')
    else:
        ml=saved.js('ml_discrimination')
        if not ml.get('available'):b.unavailable(ml.get('reason') or 'No complete saved ML diagnosis.','saved_ml_unavailable','not_generated');return b.finish()
        if params.get('label_field') and params['label_field']!=ml.get('label_field','group'):
            b.unavailable('No persisted complete diagnostics for this label field. Use the saved label view or the existing explicitly requested legacy diagnosis.','selected_ml_label_not_saved','not_generated');return b.finish()
        b.packet['method']['name']='Saved fitted/training diagnosis and saved CV; no model refit'
        if chart=='S16':
            rows=[]
            for model,obj in ml.get('models',{}).items():
                cvkey='rf_balanced_accuracy_cv_mean' if model=='random_forest' else 'logistic_balanced_accuracy_cv_mean'
                rows.append({'model':model,'train':obj.get('metrics',{}).get('balanced_accuracy'),'cv':ml.get('validation',{}).get(cvkey)})
            q=pd.DataFrame(rows);b.add_source('saved_model_metrics',q);b.add({'type':'dumbbell','panel_id':'training_cv','title':'Training fit vs saved CV mean','rows':rows,'plot_rows':rows,'counts':counts(len(q),len(q))},q)
            cm=ml.get('confusion_matrix',{});matrix=cm.get('matrix',cm.get('values',[]));labels=cm.get('labels',ml.get('classes',[]));r=[{'truth':labels[i],'prediction':labels[j],'value':n} for i,row in enumerate(matrix) for j,n in enumerate(row)]
            P.heatmap(b,pd.DataFrame(r),'prediction','truth','value','training_confusion','Saved fitted confusion matrix');b.packet['data']['confusion_total']=int(sum(sum(row) for row in matrix))
        elif chart=='S17':
            q=source('ml_feature_importance');metrics=[c for c in ['rf_importance','logistic_abs_coef','permutation_importance_mean'] if c in q];rows=[]
            ranks=q[metrics].apply(pd.to_numeric,errors='coerce').rank(ascending=False,method='min')
            for i,r in q.iterrows():
                for k in metrics:rows.append({'feature':r.get('feature_name'),'metric':k,'rank':ranks.loc[i,k],'raw_value':r[k]})
            b.add({'type':'parallel_ranks','panel_id':'importance_ranks','title':'Every importance definition ranked separately','metrics':metrics,'rows':clean(rows),'plot_rows':clean(rows),'counts':counts(len(q),len(q),len(q),len(rows))},q)
        elif chart=='S18':
            rp=ml.get('roc_pr',{})
            if not rp.get('available'):b.unavailable(rp.get('reason') or 'No saved ROC/PR for this classification.','roc_pr_not_saved','not_applicable')
            for kind,x,y in [('roc_curve','fpr','tpr'),('pr_curve','recall','precision')]:
                q=pd.DataFrame(rp.get(kind,[]));b.add_source(kind,q)
                if len(q):
                    points=clean([[r[x],r[y]] for r in q.to_dict('records')]);b.add({'type':'curve','panel_id':kind,'title':'Saved fitted '+kind,'x_label':x,'y_label':y,'points':points,'plot_rows':q.to_dict('records'),'positive_class':rp.get('positive_class'),'baseline':float(f.group.eq(rp.get('positive_class')).mean()) if 'group' in f else None,'counts':counts(len(q),len(q))},q)
        elif chart=='S19':
            emb=ml.get('class_separation_embedding',{});q=pd.DataFrame(emb.get('points',[]));b.add_source('saved_embedding',q)
            if len(q)==len(allf):P.scatter(b,filter_frame(q,params),'x','y','group','embedding','Saved method: '+str(emb.get('method')))
            else:b.unavailable('Saved embedding is incomplete.','incomplete_saved_coordinates')
            pred=source('ml_predictions');P.distribution(b,pred,['rf_confidence'],'true_label','confidence')
        elif chart=='S20':
            source('features');keys=[r.get('feature_name',r.get('feature')) for r in ml.get('top_feature_distributions',[])];P.distribution(b,f,[k for k in keys if k in f],by,'original_selected')
    profile=params.get('panel_profile')
    if profile in ['roc_curve','pr_curve','sample_deltas','unpaired','paired']:
        b.packet['data']['panels']=[p for p in b.packet['data']['panels'] if p['panel_id'].startswith('saved_matched_pairs' if profile=='paired' else profile)]
    return b.finish()

def coordinate_panels(b,f):
    required=['species_id','seqid','start_1','end_1','exon_gc_percent']
    if not all(k in f for k in required):return
    boundaries=[]
    for species,sub in f.groupby('species_id',sort=True):
        q=sub.reset_index(drop=True);x=np.full(len(q),np.nan);offset=0.
        for seqid,part in q.groupby('seqid',sort=True):
            start=P.num(part,'start_1');end=P.num(part,'end_1');valid=np.isfinite(start)&np.isfinite(end)&(start>=1)&(end>=start)
            x[part.index[valid]]=offset+(start[valid]+end[valid])/2
            width=float(np.max(end[valid])) if valid.any() else 0.;boundaries.append({'species_id':species,'seqid':seqid,'offset':offset,'range_end':offset+width});offset+=width
        P.scatter(b,q,'start_1','exon_gc_percent','species_id','coordinate_'+digest(species)[:8],str(species)+' · cumulative annotation coordinates, not assembly size',True,x_values=x,x_label='Cumulative annotation position (bp)')
    b.packet['data']['coordinate_boundaries']=boundaries
