"""Run-authorized, complete saved HVG evidence. No analysis execution or inference."""
from __future__ import annotations
from backend.apps.common.workflow_visuals.presentation_specs import DESIGN_REVISION,validate_profile
import json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from backend.apps.common.host_paths import Path
from backend.analysis_engine.hvg_research.artifacts import safe_path
from backend.analysis_engine.hvg_research.catalog import TABLES,FAMILIES
from backend.apps.common.workflow_visuals.contracts import Bundle,counts,digest,parameters,clean
from backend.apps.common.workflow_visuals.cache import read_frame,sha_file,packet_cache
from backend.apps.common.workflow_visuals import panels as P
from backend.apps.common.workflow_visuals.statistics import numeric,percentile,running_es,q_coordinates
from . import research_services as service
from .research_originals import ORIGINAL_TABLES

TITLES=['Analysis universe and evidence','Complete Core dispositions','All saved mean–HVG score coordinates','Full saved HVG rank background','Metadata modes and saved patterns','All raw effects across contexts','All raw feature evidence','All saved adjustment models','Complete matching sensitivity','Complete HVG/non-HVG feature distribution','All saved directional sets','All baseline enrichment hypotheses','Complete subset-enrichment families','All continuous feature–function hypotheses','All saved GSEA results','Complete selected saved-rank GSEA curve','All interaction hypotheses and states','Complete within-function evidence','Complete technical stability','Complete sensitivity-run evidence','All saved candidate priorities','Candidate functions and saved evidence links','Complete selected-gene Core profile','Historical fitted signals and classes','Historical model evidence and enrichment','Complete detection and score distributions','Core missingness and gene eligibility','All saved confidence intervals','Original non-model comparison evidence','Original full-gene HVG baseline','Original mapping and Core audit','Original complete candidate-score background']
REGISTRY={f'H{i+1:02}':{'chart_id':f'H{i+1:02}','title':t} for i,t in enumerate(TITLES)}
KINDS={'universe':'H01','annotation_coverage':'H01','context_coverage':'H01','core_disposition':'H02','core_omics':'H02','hvg_scatter':'H03','original_mean_score':'H03','original_top_hvg':'H04','original_workflow':'H05','original_pattern_counts':'H05','original_subset_counts':'H05','context_effects':'H06','feature_forest':'H28','feature_volcano':'H07','adjusted_forest':'H08','matching':'H09','distribution':'H10','sets':'H11','baseline':'H12','subset':'H13','within_hvg':'H13','feature_function':'H14','gsea':'H15','interactions':'H17','within_raw':'H18','within_adjusted':'H18','replication':'H19','feature_stability':'H19','set_stability':'H19','threshold_stability':'H19','candidate_frequency':'H21','baseline_stability':'H20','candidate_priority':'H21','candidate_tiers':'H21','candidate_ora':'H22','hvg_histogram':'H26','original_dropout':'H26','eligibility':'H27','mapping_coverage':'H27','core_missingness':'H27','original_mapping_quality':'H31','original_classes':'H24','original_expected_observed':'H24','original_residuals':'H24','original_model_associations':'H25','original_model_comparison':'H25','original_bootstrap':'H25','original_candidate_bubble':'H32','original_candidate_enrichment':'H25','original_family_heatmap':'H29','original_omics_effect':'H29','original_raw_adjusted':'H29'}
SOURCES={'H01':['labels','annotations','workflow_modes'],'H02':['core_audit'],'H03':['labels'],'H04':['labels'],'H05':['workflow_modes','workflow_subsets','workflow_patterns'],
 'H06':['feature_tests','core_audit'],'H07':['feature_tests'],'H08':['adjusted'],'H09':['matching','feature_tests'],'H10':['values','labels','feature_tests'],'H11':['sets','set_members'],
 'H12':['baseline'],'H13':['subset','within_hvg','supplementary_ora'],'H14':['feature_pathways'],'H15':['gsea'],'H16':['ranked_genes','annotations','gsea'],
 'H17':['interactions'],'H18':['within_pathways','within_adjusted'],'H19':['replication','feature_stability','set_stability','threshold_sensitivity','candidate_stability'],
 'H20':['baseline_stability','feature_sensitivity','replication'],'H21':['candidates'],'H22':['candidate_ora','gene_pathways','network_status'],'H23':['core_audit','values','core_values','labels'],
 'H24':['original_model_scores'],'H25':['original_model_associations','original_bootstrap','original_model_comparison','original_candidate_ora_full','original_candidate_gsea'],
 'H26':['labels'],'H27':['core_audit','eligibility'],'H28':['feature_tests','adjusted'],'H29':['native_raw','native_adjusted','native_family','native_quantiles'],
 'H30':['native_baseline'],'H31':['native_audit','native_mapping'],'H32':['original_candidate_components','original_model_scores']}
NATIVE={'native_mapping':'validation/id_mapping_summary.json','workflow_modes':'analysis_phase1/phase1_mode_summary.json','workflow_subsets':'analysis_phase1/phase1_mode_summary.json','workflow_patterns':'analysis_phase1/variability_patterns.csv','native_baseline':'analysis_phase1/hvg_baseline.csv','native_audit':'analysis_phase2/hvg_nonhvg_feature_audit.csv','native_raw':'analysis_phase2/hvg_nonhvg_feature_comparison.csv',
 'native_adjusted':'analysis_phase2/hvg_nonhvg_adjusted_comparison.csv','native_family':'analysis_phase2/hvg_nonhvg_family_summary.csv','native_quantiles':'analysis_phase2/hvg_nonhvg_distribution_quantiles.csv',
 'original_model_scores':'analysis_phase2/hvg_stoich_scores.csv','original_model_associations':'visualization/feature_associations_table.csv','original_bootstrap':'analysis_phase2/bootstrap_feature_stability.csv',
 'original_model_comparison':'analysis_phase2/model_comparison.csv','original_candidate_components':'visualization/candidate_score_components_table.csv','original_candidate_ora_full':'downstream/enrichment_ora.csv','original_candidate_gsea':'downstream/gsea_prerank_results.csv'}
PROTECTED={'H01','H02','H03','H04','H05','H23','H26','H27','H30','H31','H24','H25','H32','H29'}
FUNCTIONAL={'H14','H15','H16'}
MODELS={'H24','H25','H32'}

def resolve(identifier,token=None,params=None):
    base=service.authorize(identifier,token)
    try:run,m=service.load_run(base,(params or {}).get('analysis_run_id'))
    except FileNotFoundError:
        if (params or {}).get('analysis_run_id'):raise
        return Source(base,{'analysis_run_id':None,'contexts':[{'context_id':'global'}],'schema_version':'legacy_native'},False)
    return Source(run,m,True)

class Source:
    def __init__(self,root,manifest,research=True):self.root=Path(root);self.m=manifest;self.research=research;self.last_source_rows={}
    def paths(self,key):
        if key in NATIVE:
            if not self.research:return [safe_path(self.root,NATIVE[key])]
            if key.startswith('native_'):return [safe_path(self.root,'work/'+NATIVE[key])]
        if key in ORIGINAL_TABLES:return [safe_path(self.root,ORIGINAL_TABLES[key])]
        rel=TABLES.get(key)
        if not rel:raise ValueError('Unsupported saved table '+key)
        p=safe_path(self.root,rel+'.parquet')
        if p.is_file():return [p]
        return [safe_path(self.root,c['directory'])/(rel+'.parquet') for c in self.m.get('contexts',[]) if c.get('directory')]
    def signature(self,chart):
        files=[]
        for key in SOURCES[chart]:
            for index,p in enumerate(self.paths(key)):
                if p.is_file():files.append((key,index,p.name,sha_file(p)))
        manifest=self.root/'run_manifest.json'
        return digest([self.m,sha_file(manifest) if manifest.is_file() else None,files])
    def read(self,key,params=None):
        params=params or {};paths=self.paths(key);existing=[p for p in paths if p.is_file()]
        if not self.research and key in ['workflow_modes','workflow_subsets'] and existing:
            data=json.loads(existing[0].read_text('utf-8-sig'))
            rows=data.get('subset_summaries',[]) if key=='workflow_subsets' else [{'mode':data.get('analysis_mode','saved original mode'),'status':data.get('validation_overall_status','saved'),'reason':None},*[{'mode':name,'status':r.get('status'),'reason':r.get('reason')} for name,r in data.get('auxiliary_mode_outputs',{}).items()],*[{'mode':r.get('mode','unspecified'),'status':'not_applicable','reason':r.get('reason')} for r in data.get('skipped_modes',[]) if isinstance(r,dict)]]
            f=pd.DataFrame(rows);self.last_source_rows[key]=len(f);return f
        if key=='native_mapping' and existing:
            f=pd.DataFrame([json.loads(existing[0].read_text('utf-8-sig'))]);self.last_source_rows[key]=1;return f
        self.last_source_rows[key]=sum(pq.ParquetFile(p).metadata.num_rows if p.suffix=='.parquet' else len(read_frame(p)) for p in existing)
        if not existing:return pd.DataFrame()
        if self.research and key in TABLES:
            # Use the repository's whitelist/Parquet predicate semantics, including old context layouts.
            return service.read_table(self.root,key,params).reset_index(drop=True)
        frames=[read_frame(p) for p in existing];f=pd.concat(frames,ignore_index=True) if len(frames)>1 else frames[0]
        if self.research and params.get('context_id','global')!='global':return f.iloc[:0]
        return filter_native(f,params)

def filter_native(f,params):
    f=f.copy(deep=False)
    for k in ['gene_id','feature_key','source','direction','model','status','stoich_class','family','omics']:
        if k=='omics' and 'omics_layer' in f and params.get(k):f=f[f.omics_layer.astype(str).eq(str(params[k]))];continue
        if params.get(k) and k in f:f=f[f[k].astype(str).eq(str(params[k]))]
    q=params.get('q_max')
    if q is not None:
        field=P.column(f,'q_global','global_fdr','adjusted_global_fdr','fdr_bh')
        if field:f=f[P.num(f,field)<=float(q)]
    return f.reset_index(drop=True)

def chart_params(source,chart,params):
    params=parameters(params or {});context=params.get('context_id') or ('global' if any(r['context_id']=='global' for r in source.m.get('contexts',[])) else next(iter(source.m.get('contexts',[])),{}).get('context_id','global'))
    known={r['context_id'] for r in source.m.get('contexts',[])}
    if context not in known:raise ValueError('Unknown context for the selected analysis run')
    allowed={'analysis_run_id','context_id','panel_profile'}
    if chart not in PROTECTED:allowed|={'feature_key','term_key','source','direction','q_max','model','status','query','omics','family','run_id','priority_tier'}
    if chart in FUNCTIONAL:allowed.add('scope')
    if chart=='H23':allowed.add('gene_id')
    if chart=='H29':allowed|={'feature_key','omics','family','q_max','direction'}
    # H16 must retain the exact clicked GSEA result background.
    if chart=='H16':allowed|={'run_id','term_key','source','scope','feature_key'}
    result={k:v for k,v in params.items() if k in allowed};result['context_id']=context
    return result

def capabilities(source):
    return {'schema_version':'workflow_viz_v2','enabled':True,'analysis_run_id':source.m.get('analysis_run_id'),'source_kind':'research_saved' if source.research else 'native_saved',
            'contexts':[{'context_id':r['context_id']} for r in source.m.get('contexts',[])],'charts':list(REGISTRY.values()),'kind_dispatch':KINDS,'model_policy':source.m.get('model_policy'),
            'supports_records':True,'scope_contract':'Audits and gene profiles ignore functional filters; saved function backgrounds remain separate from export_scope.'}

def build(source,chart,params=None):
    if chart not in REGISTRY:raise ValueError('Unknown HVG chart ID')
    effective=chart_params(source,chart,params);validate_profile(chart,effective,'hvg');signature=source.signature(chart)
    return packet_cache(digest([DESIGN_REVISION,'hvg',str(source.root),chart,effective,signature]),lambda:_build(source,chart,effective,signature))

def _build(s,chart,params,signature):
    b=Bundle(chart,REGISTRY[chart]['title'],signature,params,'research_saved' if s.research else 'native_saved',s.m.get('analysis_run_id'),params['context_id'])
    b.packet['provenance']['source_schema_version']=s.m.get('schema_version');b.packet['provenance']['annotation_snapshot_id']=s.m.get('annotation_snapshot_id');b.packet['provenance']['data_release_id']=s.m.get('data_release_id')
    if chart in MODELS and s.m.get('model_policy')=='removed':b.unavailable('Predictive models are removed for this workflow. No model is run by visualization.','model_policy_removed','not_applicable');return b.finish()
    if chart in MODELS|{'H29','H31'} and params['context_id']!='global':b.unavailable('The saved original branch is global only. Select global.','original_global_only','not_applicable');return b.finish()
    if not s.research and chart not in MODELS|{'H05','H29','H30','H31'}:b.unavailable('This native result has no Research evidence of this kind.','research_not_generated','not_applicable');return b.finish()
    def read(key,extra=None,unfiltered=False,record=True):
        filt={'context_id':params['context_id']} if unfiltered else {k:v for k,v in params.items() if k not in ['analysis_run_id','panel_profile','gene_id']}
        if extra is not None:
            for k,v in extra.items():
                if v is None:filt.pop(k,None)
                else:filt[k]=v
        f=s.read(key,filt)
        if record and key not in b.sources:b.add_source(key,f,s.last_source_rows.get(key,len(f)))
        return f
    def status(frame,prefix):
        field=P.column(frame,'status','analysis_status','adjusted_status','final_status','reason')
        if field:P.categories(b,frame,field,'context_id',prefix+'_states','Saved result states and exclusions')
    profile=params.get('panel_profile','')
    if chart=='H01':
        labels=read('labels');ann=read('annotations',unfiltered=True);rows=[]
        for context,g in labels.groupby('context_id') if 'context_id' in labels else []:
            a=ann[ann.context_id.eq(context)] if 'context_id' in ann else ann
            h=as_bool(g['is_hvg']);rows.extend([{'context':context,'category':'HVG','count':int(h.sum())},{'context':context,'category':'non-HVG','count':int((~h).sum())}])
            n=a.gene_id.nunique() if 'gene_id' in a else 0
            b.packet['data'].setdefault('annotation_counts',[]).append({'context_id':context,'unique_annotated':n,'universe':len(g),'source_counts':a.groupby('source').gene_id.nunique().to_dict() if 'source' in a else {}})
        q=pd.DataFrame(rows)
        if len(q):b.add({'type':'categories','panel_id':'universe','title':'Saved H + N = eligible universe','rows':q.rename(columns={'context':'group'}).to_dict('records'),'plot_rows':q.to_dict('records'),'counts':counts(len(labels),len(labels),len(labels),len(q))},labels)
        annotation=[]
        for r in b.packet['data'].get('annotation_counts',[]):
            annotation.extend([{'group':r['context_id'],'category':'Annotated unique genes','count':r['unique_annotated']},{'group':r['context_id'],'category':'Unannotated genes','count':r['universe']-r['unique_annotated']}])
        if annotation:b.add({'type':'categories','panel_id':'annotations','title':'Unique genes; annotation sources may overlap','rows':annotation,'plot_rows':annotation,'counts':counts(len(labels),len(labels),len(labels),len(annotation))},labels)
    elif chart=='H02':
        q=read('core_audit');audit_panel(b,q)
    elif chart in ['H03','H04','H26','H30']:
        q=read('labels' if chart!='H30' else 'native_baseline');hvg_baseline(b,q,chart,profile)
    elif chart=='H05':
        for key in ['workflow_modes','workflow_subsets','workflow_patterns']:
            q=read(key,unfiltered=True);field=P.column(q,'status' if key=='workflow_modes' else 'pattern' if key=='workflow_patterns' else 'mode','condition_pattern','mode')
            if field:P.categories(b,q,field,prefix=key)
            if key=='workflow_subsets':
                for metric in ['n_genes','n_hvgs','n_cells']:P.rank(b,q,metric,'mode',key+'_'+metric)
    elif chart=='H06':
        q=read('feature_tests',{'context_id':None});P.heatmap(b,q,'context_id','feature_key','effect','context_effects','All saved raw effects, shared signed scale','diverging')
        b.packet['scope']['population']='Complete saved feature tests across all run contexts; the cross-context panel is not subset by the context selector.'
    elif chart in ['H07','H08']:
        q=read('feature_tests' if chart=='H07' else 'adjusted');effect='effect' if chart=='H07' else 'beta'
        if chart=='H07':
            P.evidence(b,q,effect,by='strong_raw',prefix='raw_evidence',title='Saved raw effect and original strong_raw rule')
        else:
            for name,sub in P.groups(q,'model'):P.evidence(b,sub,effect,by='context_id',prefix='adjusted_'+digest(name)[:8],title=name)
    elif chart=='H09':
        q=read('matching');raw=read('feature_tests',unfiltered=True);keys=['context_id','feature_key']
        if all(k in q and k in raw for k in keys) and 'effect' in raw:
            merged=q.merge(raw[keys+['effect']],on=keys,how='left',validate='one_to_one');P.scatter(b,merged,'effect','paired_sign_effect','context_id','matching_effects','Raw Cliff effect vs paired sign effect: distinct estimands')
        P.distribution(b,q,['matched_H_fraction','n_pairs'],'context_id','matching_coverage')
    elif chart=='H10':
        key=params.get('feature_key');raw=read('feature_tests',unfiltered=True)
        if not key and 'effect' in raw and 'feature_key' in raw:
            order=raw.assign(_abs=abs(P.num(raw,'effect'))).sort_values(['_abs','feature_key'],ascending=[False,True],kind='stable');key=order.feature_key.iloc[0] if len(order) else None
        values=read('values',unfiltered=True);labels=read('labels',unfiltered=True)
        if key in values:
            q=values[['context_id','gene_id',key]].merge(labels[['context_id','gene_id','is_hvg']],on=['context_id','gene_id'],validate='one_to_one')
            q['label']=np.where(as_bool(q.is_hvg),'HVG','non-HVG');P.distribution(b,q,[key],'label');b.packet['data']['selected_feature']=key
        else:b.unavailable('Select a saved prepared numeric feature.','feature_not_prepared','not_estimable')
    elif chart=='H11':
        q=read('sets');P.distribution(b,q,['n_members'],['context_id','direction'],'set_sizes')
        keys=[c for c in ['context_id','feature_key','scope'] if c in q]
        if keys and 'direction' in q and 'n_members' in q and not q.duplicated(keys+['direction']).any():
            pair=q.pivot(index=keys,columns='direction',values='n_members').reset_index();directions=[c for c in pair if c not in keys]
            if len(directions)==2:P.scatter(b,pair,directions[0],directions[1],'context_id','set_balance','Same-feature directional sizes; no fabricated missing side')
    elif chart in ['H12','H13','H14','H15','H17','H18']:
        tables={'H12':['baseline'],'H13':['subset','within_hvg','supplementary_ora'],'H14':['feature_pathways'],'H15':['gsea'],'H17':['interactions'],'H18':['within_pathways','within_adjusted']}[chart]
        if profile=='subset':tables=['subset']
        elif profile=='within_hvg':tables=['within_hvg']
        elif profile=='within_raw':tables=['within_pathways']
        elif profile=='within_adjusted':tables=['within_adjusted']
        for key in tables:
            q=read(key);effect='nes' if key=='gsea' else 'beta' if key in ['interactions','within_adjusted'] else 'effect'
            if chart in ['H12','H13']:
                P.distribution(b,q,['q_global'],['context_id','source'],key+'_q','Saved q values, original family: '+key)
                if chart=='H12' and 'q_global' in q:
                    skyline=q.copy();skyline['_display_q']=q_coordinates(q.q_global);P.rank(b,skyline,'_display_q','source','baseline_skyline','All saved terms',label='term_key')
                status(q,key)
            elif chart=='H14':
                for name,sub in P.groups(q,'source'):P.evidence(b,sub,effect,by='context_id',prefix='function_'+digest(name)[:10],title=name,density=True)
            else:
                if 'status' in q and effect=='beta':shown=q.copy();shown.loc[~shown.status.astype(str).eq('estimated'),'beta']=np.nan
                else:shown=q
                P.evidence(b,shown,effect,by='context_id',prefix=key,title='Saved '+key,density=(len(q)>20000))
                if key=='gsea' and 'nes_status' in q:P.categories(b,q,'nes_status','context_id','nes_availability','NES availability differs from conservative p definition')
    elif chart=='H16':
        if not params.get('run_id') or not params.get('term_key'):b.unavailable('Select an actual saved GSEA row and its run/term/background.','select_gsea_result','not_applicable');return b.finish()
        result=read('gsea');ranks=read('ranked_genes');ann=read('annotations',{'feature_key':None,'run_id':None,'scope':None,'q_max':None})
        if len(result)!=1:b.unavailable('The selected GSEA result is absent or ambiguous.','ambiguous_gsea_result','not_estimable');return b.finish()
        ranks=ranks.sort_values('rank',kind='stable') if 'rank' in ranks else ranks;hits=ranks.gene_id.isin(set(ann.gene_id)) if 'gene_id' in ranks and 'gene_id' in ann else np.zeros(len(ranks),bool)
        es=running_es(ranks.rank_score,hits) if 'rank_score' in ranks else None
        if es is None:b.unavailable('Saved ranking has zero hit/miss denominator or nonfinite scores.','zero_gsea_denominator','not_estimable')
        else:
            q=ranks.copy();q['hit']=hits;q['running_es']=es;saved=float(result.es.iloc[0]);peak=float(es[np.argmax(np.abs(es))])
            b.packet['data']['es_error']=abs(peak-saved)
            if abs(peak-saved)>1e-8:b.unavailable('Saved ES does not match the selected saved ranking and annotation.','gsea_evidence_mismatch','not_estimable')
            else:b.add({'type':'gsea_curve','panel_id':'running_es','title':'All saved ranks and all annotation hits','points':[[int(i),float(v)] for i,v in zip(q['rank'],es)],'hits':[int(i) for i,h in zip(q['rank'],hits) if h],'plot_rows':clean(q.to_dict('records')),'x_label':'Complete saved rank','y_label':'Running weighted ES','counts':counts(len(q),len(q))},q)
    elif chart in ['H19','H20']:
        if chart=='H19':
            for key,fields in [('replication',['jaccard_primary']),('feature_stability',['direction_agreement','effect_mean','effect_sd']),('set_stability',['jaccard_primary']),('threshold_sensitivity',['jaccard_primary']),('candidate_stability',['hvg_resampling_frequency'])]:
                q=read(key);P.distribution(b,q,fields,['context_id','kind'] if 'kind' in q else 'context_id',key);status(q,key)
        else:
            q=read('baseline_stability');runs=read('replication',unfiltered=True)
            if 'q_within_sensitivity_run' in q:
                keys=[k for k in ['context_id','run_id'] if k in q and k in runs]
                q=q.merge(runs[keys+['kind']],on=keys,how='left',validate='many_to_one') if keys and 'kind' in runs else q
                q=q.copy();q['_passed']=P.num(q,'q_within_sensitivity_run')<.05
                group=[k for k in ['context_id','kind','source','term_key'] if k in q]
                freq=q.groupby(group,dropna=False)._passed.agg(['sum','count']).reset_index();freq['pass_frequency']=freq['sum']/freq['count'];P.distribution(b,freq,['pass_frequency'],['context_id','kind'],'baseline_frequency','Saved per-run q < .05 frequency, actual corresponding run counts')
            q=read('feature_sensitivity');P.distribution(b,q,['effect','q_within_sensitivity_run'],['context_id','kind'],'feature_sensitivity')
    elif chart=='H21':
        q=read('candidates');P.scatter(b,q,'priority_rank','hvg_resampling_frequency','context_id','candidate_priority','Original saved priority and technical frequency');P.categories(b,q,'priority_tier','context_id','candidate_tiers');P.categories(b,q,'annotated','context_id','annotation_presence')
    elif chart=='H22':
        q=read('candidate_ora');P.distribution(b,q,['q_global'],'source','candidate_ora');P.rank(b,q,'fold_enrichment','source','candidate_enrichment',label='term_key');status(q,'candidate_ora')
        links=read('gene_pathways');P.categories(b,links,'support_type' if 'support_type' in links else 'source','context_id','saved_gene_function_links','Saved gene–function links by support type');network=read('network_status');b.packet['data']['network_status']=clean(network.to_dict('records'))
    elif chart=='H23':
        gene=params.get('gene_id')
        if not gene:b.unavailable('Select a gene from this context.','select_gene','not_applicable');return b.finish()
        labels=read('labels',unfiltered=True);values=read('values',unfiltered=True);audit=read('core_audit',unfiltered=True);raw=read('core_values',unfiltered=True)
        if 'gene_id' not in labels or not labels.gene_id.astype(str).eq(str(gene)).any():raise FileNotFoundError('Gene is outside this context universe')
        if labels.duplicated(['context_id','gene_id']).any() or values.duplicated(['context_id','gene_id']).any():raise ValueError('Ambiguous gene/context identity')
        nonhvg=set(labels.loc[~as_bool(labels.is_hvg),'gene_id']);reference=values[values.gene_id.isin(nonhvg)];chosen=values[values.gene_id.eq(gene)];rv=raw[raw.gene_id.eq(gene)] if 'gene_id' in raw else raw.iloc[:0];rows=[]
        for r in audit.to_dict('records'):
            key=r['feature_key'];value=chosen.iloc[0].get(key) if len(chosen)==1 else None
            try:value=float(value)
            except (ValueError,TypeError):value=np.nan
            ref=numeric(reference[key]) if key in reference else np.array([]);ref=ref[np.isfinite(ref)]
            rawcol=r.get('context_column') or str(key).replace('::','__')
            rows.append({**r,'gene_id':gene,'raw_value':rv.iloc[0].get(rawcol) if len(rv)==1 else None,'prepared_value':value,'reference_n':len(ref),'value':percentile(ref,value),'nonhvg_reference_percentile':percentile(ref,value),'reference':'same-context non-HVG prepared values'})
        q=pd.DataFrame(rows);q['gene']=gene;P.heatmap(b,q,'gene','feature_key','value','gene_core','All audited Core fields; percentile is not gene significance',domain=[0,1]);b.packet['data']['core_feature_values']=clean(rows)
    elif chart=='H28':
        if profile!='adjusted_forest':
            q=read('feature_tests');q=q[q.status.eq('tested')] if 'status' in q else q;P.intervals(b,q,'effect','ci_low','ci_high','context_id','raw_ci','Original Cliff effect and saved CI')
        if profile!='feature_forest':
            q=read('adjusted')
            for name,sub in P.groups(q,'model'):P.intervals(b,sub,'beta','ci_low','ci_high','context_id','adjusted_ci_'+digest(name)[:8],name,or_ci=True)
            status(q,'adjusted')
    elif chart=='H29':
        raw=read('native_raw');adjusted=read('native_adjusted');family=read('native_family');quant=read('native_quantiles')
        P.evidence(b,raw,'effect_value','global_fdr','omics_layer','original_raw','Original non-model result family')
        field=P.column(adjusted,'adjusted_status','fit_status')
        if field:P.categories(b,adjusted,field,prefix='original_adjustment_states');P.categories(b,adjusted,'failure_reason',prefix='original_failure_reasons')
        shown=adjusted[adjusted[field].isin(['estimated','success','succeeded'])] if field else adjusted.iloc[:0]
        if len(shown):P.evidence(b,shown,'coefficient_per_sd','adjusted_global_fdr',prefix='original_adjusted')
        for metric in ['tested_fields','significant_fields','median_effect']:
            P.rank(b,family,metric,'omics_layer','family_'+metric,label='family')
        if len(quant):
            rows=[]
            for feature,sub in quant.groupby('feature_key',sort=False):
                lo=P.num(sub,'min');hi=P.num(sub,'max');lo=lo[np.isfinite(lo)];hi=hi[np.isfinite(hi)];minimum=float(lo.min()) if len(lo) else np.nan;maximum=float(hi.max()) if len(hi) else np.nan
                for r in sub.to_dict('records'):
                    for k in ['q05','q25','median','q75','q95']:
                        v=pd.to_numeric(pd.Series([r.get(k)]),errors='coerce').iloc[0]
                        rows.append({'field':feature,'group_quantile':str(r.get('group'))+' '+k,'raw_quantile':v,'value':(v-minimum)/(maximum-minimum) if np.isfinite(v) and maximum>minimum else 0. if np.isfinite(v) and maximum==minimum else None})
            P.heatmap(b,pd.DataFrame(rows),'group_quantile','field','value','original_quantiles','Saved quantiles; same-field saved min–max display reference',domain=[0,1])
        if profile=='original_forest':P.intervals(b,raw,'effect_value','effect_ci_low','effect_ci_high','effect_type','original_forest','Complete original effect/CI; saved estimand groups')
    elif chart=='H31':
        q=read('native_audit');read('native_mapping');audit_panel(b,q,native=True)
        P.distribution(b,q,['missing_rate_hvg','missing_rate_nonhvg'],'omics_layer','original_missingness')
    elif chart=='H27':
        q=read('core_audit');audit_panel(b,q)
        for label,missing,den in [('HVG','missing_hvg','n_hvg'),('non-HVG','missing_nonhvg','n_nonhvg')]:
            if missing in q and den in q:
                q=q.copy();d=P.num(q,den);q['missing_fraction_'+label]=np.where(d>0,P.num(q,missing)/np.where(d>0,d,1),np.nan);P.distribution(b,q,['missing_fraction_'+label],'omics','missing_'+label)
        eligible=read('eligibility');P.categories(b,eligible,'reason','context_id','eligibility_reasons','All original gene eligibility rows')
    elif chart=='H24':
        q=read('original_model_scores');P.scatter(b,q,'stoich_expected_var','observed_hvg_signal','stoich_class','expected_observed','Full saved historical fit; not cross-validation',True);P.distribution(b,q,['stoich_excess_var'],'stoich_class','model_residuals');P.categories(b,q,'stoich_class',prefix='saved_model_classes')
    elif chart=='H25':
        for key,value in [('original_model_associations','cliffs_delta'),('original_bootstrap','selection_frequency'),('original_model_comparison','r2')]:
            q=read(key);P.rank(b,q,value,prefix=key,title='Historical saved '+value,label='feature' if key!='original_model_comparison' else 'model_id')
        for key in ['original_candidate_ora_full','original_candidate_gsea']:
            q=read(key);P.distribution(b,q,['fdr_bh'],'source',key,'Original historical family, complete saved results');status(q,key)
    elif chart=='H32':
        q=read('original_candidate_components');scores=read('original_model_scores')
        if all('gene_id' in f for f in [q,scores]) and 'stoich_excess_var' in scores:
            q=q.merge(scores[['gene_id','stoich_excess_var']],on='gene_id',validate='one_to_one');P.scatter(b,q,'stoich_excess_var','candidate_score','stoich_class','candidate_background','Original saved score and residual',True)
        P.rank(b,q,'candidate_score',prefix='original_candidate_rank',title='Every scored gene in the complete saved score-components table',label='gene_id')
    # Projection keeps the original geometry and scientific question of each old slot.
    if profile:
        selected=project_panels(chart,profile,b.packet['data']['panels'])
        if selected:b.packet['data']['panels']=selected
    b.packet['method']['q_family']={k:FAMILIES.get(k,'original saved family') for k in b.sources}
    if not b.packet['data']['panels'] and s.m.get('research_status')=='running':b.unavailable('This run has not published the required result yet.','result_not_published','running')
    return b.finish()

def as_bool(series):return series.map(lambda x:x is True or isinstance(x,(np.bool_,bool)) and bool(x) or str(x).lower() in {'true','1'})

def audit_panel(b,q,native=False):
    field=P.column(q,'analysis_status','final_status','status') if native else P.column(q,'final_status','status')
    feature=P.column(q,'feature_key','feature_name','field')
    if not field or not feature:return
    states=sorted(q[field].astype(str).unique());f=q.copy();f['_value']=f[field].astype(str).map({k:i for i,k in enumerate(states)});f['_context']=f.context_id if 'context_id' in f else 'global'
    P.heatmap(b,f,'_context',feature,'_value','core_dispositions','Every audited field retains its saved disposition',domain=[0,max(1,len(states)-1)]);b.packet['data']['state_legend']=states
    b.packet['data']['panels'][-1]['category_states']=states
    P.categories(b,q,field,'omics' if 'omics' in q else 'omics_layer','core_states')

def hvg_baseline(b,q,chart,profile=''):
    if 'mean_expr' in q and 'hvg_score' in q and (chart in ['H03','H30'] or profile=='original_mean_score'):
        mean=P.num(q,'mean_expr');mean=np.where(mean>=0,np.log10(1+np.maximum(mean,0)),np.nan)
        P.scatter(b,q,'mean_expr','hvg_score','is_hvg','mean_score','Original saved HVG scores and labels',x_values=mean,x_label='log10(1 + saved mean expression)')
    if chart in ['H04','H30']:P.rank(b,q,'hvg_score','context_id','hvg_rank','All saved ranks; original HVG highlighted',rank_field='hvg_rank',label='gene_id',highlight='is_hvg')
    if chart in ['H26','H30']:
        if chart=='H30' and 'dropout_rate' not in q and 'pct_cells_detected' in q:q=q.copy();q['dropout_rate']=1-P.num(q,'pct_cells_detected')
        P.distribution(b,q,['pct_cells_detected','dropout_rate','hvg_score'],'is_hvg','baseline_distribution')

def project_panels(chart,profile,panels):
    patterns={'universe':['universe'],'annotation_coverage':['annotations'],'core_disposition':['core_dispositions'],'core_omics':['core_states'],'original_mean_score':['mean_score'],'original_forest':['original_forest'],'original_quantiles':['original_quantiles'],
      'original_top_hvg':['hvg_rank'],'original_dropout':['baseline_distribution_dropout','baseline_distribution_pct'],'hvg_histogram':['baseline_distribution_hvg'],
      'original_pattern_counts':['workflow_patterns'],'original_subset_counts':['workflow_subsets'],'original_workflow':['workflow_modes'],'original_classes':['saved_model_classes'],
      'original_expected_observed':['expected_observed'],'original_residuals':['model_residuals'],'candidate_tiers':['candidate_tiers'],'candidate_frequency':['candidate_priority'],
      'replication':['replication'],'feature_stability':['feature_stability'],'set_stability':['set_stability'],'threshold_stability':['threshold_sensitivity'],
      'baseline_stability':['baseline_frequency'],'original_model_associations':['original_model_associations'],'original_model_comparison':['original_model_comparison'],
      'original_bootstrap':['original_bootstrap'],'original_candidate_enrichment':['original_candidate_ora','original_candidate_gsea'],'eligibility':['eligibility'],'core_missingness':['missing_HVG','missing_non-HVG'],
      'original_omics_effect':['original_raw'],'original_family_heatmap':['family_'],'original_raw_adjusted':['original_adjustment','original_failure','original_adjusted']}
    wanted=patterns.get(profile)
    return [p for p in panels if any(p['panel_id'].startswith(x) for x in wanted)] if wanted else panels
