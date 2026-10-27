"""Design-specific complete descriptive views, independent of the scientific engines."""
from copy import deepcopy
import re
import numpy as np
import pandas as pd
from . import panels as P
from .contracts import clean,counts,digest
from .statistics import numeric,quantiles,q_coordinates
from .presentation_specs import DESIGN_REVISION

DISPLAY={'pI':'Isoelectric point (pI)','C_atoms_per_aa':'Carbon atoms / residue','atoms_per_nt_C':'Carbon atoms / nucleotide',
 'exon_atoms_C_per_base':'Exon carbon atoms / base','exon_gc_percent':'Exon GC (%)','promoter_gc_percent':'Promoter GC (%)',
 'hvg_score':'Saved HVG score','dropout_rate':'Dropout fraction','pct_cells_detected':'Detected-cell fraction',
 'strategy_cluster':'Saved strategy composition','priority_tier':'Candidate evidence tier','annotated':'Annotation availability',
 'adjusted_status':'Adjustment fit status','failure_reason':'Adjustment exclusion reasons','analysis_status':'Core analysis disposition',
 'final_status':'Core field disposition','nes_status':'NES availability','reason':'Eligibility reasons',
 'q_global':'Saved global BH q','effect':'Saved Cliff effect','beta':'Saved log odds coefficient',
 'selection_frequency':'Bootstrap selection frequency','mean_abs_importance':'Mean absolute importance',
 'n_pairs':'Matched pairs','matched_H_fraction':'Fraction of HVGs matched'}

def label(value):
    text=str(value or '')
    if text in DISPLAY:return DISPLAY[text]
    text=re.sub(r'^AA_([A-Z])_pct$',r'\1 (%)',text)
    text=re.sub(r'^aa_([A-Z])_freq$',r'\1 (fraction)',text)
    return text.replace('::',' · ').replace('_',' ')

def frame(b,key):return b.sources.get(key,pd.DataFrame()).copy()
def reset_panels(b):b.packet['data']['panels']=[]
def append(b,p,f=None):b.add(p,f);return b.packet['data']['panels'][-1]
def matrix_counts(p):
    rows=p.get('rows',[]);xs=list(dict.fromkeys(str(r.get('group','All')) for r in rows));ys=list(dict.fromkeys(str(r['category']) for r in rows))
    return {**p,'type':'status_matrix','x_categories':xs,'y_categories':ys,'value_key':'Original count',
      'x_label':'Context','y_label':'','color_domain':[0,max([r['count'] for r in rows],default=1)],
      'rows':[{'x':str(r.get('group','All')),'y':str(r['category']),'value':r['count']} for r in rows]}

def transpose(p):
    q=deepcopy(p);q['x_categories'],q['y_categories']=q.get('y_categories',[]),q.get('x_categories',[])
    q['x_label'],q['y_label']=q.get('y_label',''),q.get('x_label','')
    q['rows']=[{**r,'x':r['y'],'y':r['x']} for r in q.get('rows',[])]
    return q

def quantile_companion(b,p):
    rows=[]
    for c in p['curves']:
        q=c['quantiles'];rows.append({'group':c['name'],'field':p.get('x_label',''),'q05':q['q05'],'q25':q['q25'],
            'q50':q['q50'],'q75':q['q75'],'q95':q['q95'],'n':q['n']})
    q={**p,'type':'quantile_intervals','panel_id':p['panel_id']+'_quantiles','title':'5–95% range and interquartile interval',
       'rows':rows,'plot_rows':rows,'x_label':p.get('x_label',''),'y_label':'','role':'primary'}
    append(b,q,b.records.get(p['panel_id']))

def strip_facets(b,p,group_field,strip=True):
    result=[]
    for name in dict.fromkeys(str(r.get(group_field,'Core')) for r in p.get('rows',[])):
        selected=[r for r in p['rows'] if str(r.get(group_field,'Core'))==name]
        xs=list(dict.fromkeys(r['y'] for r in selected));q={**p,'panel_id':p['panel_id']+'_'+digest(name)[:7],
          'title':label(name)+' · '+str(len(xs))+' fields','x_categories':xs,'y_categories':p['x_categories'],
          'x_label':'Every original registered field','y_label':'','rows':[{**r,'x':r['y'],'y':r['x']} for r in selected],
          'counts':counts(len(selected),len(selected),sum(r.get('value') is not None for r in selected),len(selected))}
        if not strip:q.update(x_categories=p['x_categories'],y_categories=xs,rows=selected,x_label='Context',y_label='Original registered features')
        append(b,q,b.records.get(p['panel_id']));result.append(q)
    return result

def rebuild_h29(b,profile):
    raw,adjusted,family,quant=[frame(b,k) for k in ['native_raw','native_adjusted','native_family','native_quantiles']]
    reset_panels(b)
    if profile in ['', 'original_omics_effect']:
        P.evidence(b,raw,'effect_value','global_fdr','omics_layer','original_raw','All original feature effects and global FDR')
    if profile in ['', 'original_forest']:
        P.intervals(b,raw,'effect_value','effect_ci_low','effect_ci_high','effect_type','original_forest','All saved original effects and confidence intervals')
    if profile in ['', 'original_family_heatmap']:
        P.scatter(b,family,'tested_fields','significant_fields','omics_layer','family_tested_significant','Every family: tested and significant fields')
    if profile in ['', 'original_raw_adjusted']:
        st=P.column(adjusted,'adjusted_status','fit_status');P.categories(b,adjusted,st or '',prefix='original_adjustment_states',title='Saved adjustment fits')
        P.categories(b,adjusted,'failure_reason',prefix='original_failure_reasons',title='Fit exclusions and their actual reasons')
        finite=np.isfinite(P.num(adjusted,'coefficient_per_sd'))
        # State semantics are source-specific; finite values alone do not certify a successful fit.
        valid=adjusted.loc[finite & adjusted[st].isin(['estimated','success','succeeded','tested'])] if st else adjusted.iloc[:0]
        if len(valid) and 'feature_key' in raw and 'feature_key' in valid:
            keys=[k for k in ['feature_key','omics_layer'] if k in raw and k in valid]
            joined=valid.merge(raw[keys+['effect_value']],on=keys,how='inner',validate='one_to_one')
            P.scatter(b,joined,'effect_value','coefficient_per_sd','omics_layer','original_adjusted','Raw Cliff effect and saved adjusted coefficient: distinct estimands')
        if not len(valid) or not profile:
            q=quant.copy();lo=P.num(q,'min');hi=P.num(q,'max');span=hi-lo
            q['_range_fraction']=np.where(span>0,(P.num(q,'q95')-P.num(q,'q05'))/np.where(span>0,span,1),np.nan)
            P.distribution(b,q,['_range_fraction'],'group','original_quantile_spread','Complete saved group quantile ranges')
            if len(b.packet['data']['panels']):b.packet['data']['panels'][-1]['x_label']='(q95 − q05) / (max − min), within each field'
    if profile=='original_quantiles':
        selected=b.packet['scope']['filters'].get('feature_key')
        if not selected and len(quant):selected=str(quant.feature_key.iloc[0])
        q=quant.loc[quant.feature_key.astype(str).eq(str(selected))] if 'feature_key' in quant else quant.iloc[:0]
        rows=[{'group':str(r.get('group','Saved group')),'field':str(selected),'q05':r.get('q05'),'q25':r.get('q25'),
            'q50':r.get('median'),'q75':r.get('q75'),'q95':r.get('q95'),'n':r.get('n',r.get('n_valid'))} for r in q.to_dict('records')]
        if rows:append(b,{'type':'quantile_intervals','panel_id':'original_quantiles','title':'Saved group quantiles · '+label(selected),
          'rows':rows,'plot_rows':rows,'x_label':'Saved original feature units','y_label':'','counts':counts(len(quant),len(q),len(q),len(q))},q)

def decorate(b):
    if getattr(b,'_design_applied',False):return
    b._design_applied=True
    chart=b.packet['chart_id'];profile=b.packet['scope']['filters'].get('panel_profile','');data=b.packet['data']
    if chart in ['H12','H22']:
        key='baseline' if chart=='H12' else 'candidate_ora';q=frame(b,key)
        if 'q_global' in q:
            data['panels']=[p for p in data['panels'] if not p['panel_id'].startswith((key+'_q','baseline_skyline'))]
            curves=[]
            for name,sub in P.groups(q,'context_id'):
                a=P.num(sub,'q_global');a=np.sort(a[np.isfinite(a)&(a>=0)&(a<=1)])
                curves.append({'name':name,'points':[[i+1,float(v)] for i,v in enumerate(q_coordinates(a))]})
            append(b,{'type':'sequence_curve','panel_id':key+'_q_profile','title':'Every finite saved q value in evidence order',
              'curves':curves,'plot_rows':q.to_dict('records'),'x_label':'All finite saved hypotheses, ordered by q','y_label':'−log10(saved global BH q)',
              'counts':counts(len(q),len(q),sum(len(c['points']) for c in curves))},q)
            if chart=='H12':
                q=q.sort_values([k for k in ['source','term_key','context_id'] if k in q],kind='stable');q['_term_order']=np.arange(1,len(q)+1);q['_q_evidence']=q_coordinates(q.q_global)
                P.scatter(b,q,'_term_order','_q_evidence','source','baseline_skyline','Every saved functional term, in source/ID order',y_label='−log10(saved global BH q)')
    if chart=='H29' and any(k in b.sources for k in ['native_raw','native_family']):rebuild_h29(b,profile)
    if chart=='H05':
        if profile in ['', 'original_subset_counts']:
            q=frame(b,'workflow_subsets')
            if len(q):
                data['panels']=[p for p in data['panels'] if not p['panel_id'].startswith('workflow_subsets')]
                P.scatter(b,q,'n_cells','n_hvgs','mode','workflow_subsets','All saved subsets: cells and official HVGs')
    if chart=='H19' and profile in ['', 'replication']:
        q=frame(b,'replication')
        if 'jaccard_primary' in q:
            data['panels']=[p for p in data['panels'] if not p['panel_id'].startswith('replication_')]
            curves=[]
            for name,sub in P.groups(q,['context_id','kind']):
                curves.append({'name':name,'points':[[i+1,float(v)] for i,v in enumerate(P.num(sub,'jaccard_primary')) if np.isfinite(v)]})
            append(b,{'type':'sequence_curve','panel_id':'replication_saved_order','title':'Every saved technical rerun',
              'curves':curves,'plot_rows':q.to_dict('records'),'x_label':'Saved rerun order within context/type','y_label':'Jaccard with primary labels',
              'counts':counts(len(q),len(q),int(np.isfinite(P.num(q,'jaccard_primary')).sum()))},q)
    if chart=='H25':
        if profile in ['', 'original_model_associations']:
            q=frame(b,'original_model_associations')
            if 'cliffs_delta' in q:
                data['panels']=[p for p in data['panels'] if p['panel_id']!='original_model_associations']
                append(b,{'type':'effect_lollipop','panel_id':'original_model_associations','title':'Every saved model-branch feature association',
                  'rows':clean(q.to_dict('records')),'plot_rows':clean(q.to_dict('records')),'x_label':'Saved Cliff effect','y_label':'','counts':counts(len(q),len(q))},q)
        if profile in ['', 'original_bootstrap']:
            q=frame(b,'original_bootstrap')
            data['panels']=[p for p in data['panels'] if p['panel_id']!='original_bootstrap']
            P.scatter(b,q,'selection_frequency','mean_abs_importance',prefix='original_bootstrap',title='Every bootstrap feature: frequency and importance')
        if profile in ['', 'original_model_comparison']:
            q=frame(b,'original_model_comparison')
            if 'r2' in q:
                data['panels']=[p for p in data['panels'] if p['panel_id']!='original_model_comparison']
                append(b,{'type':'model_curve','panel_id':'original_model_comparison','title':'All saved model comparisons',
                  'rows':clean(q.to_dict('records')),'plot_rows':clean(q.to_dict('records')),'x_categories':q.model_id.astype(str).tolist(),
                  'x_label':'Original model blocks','y_label':'Saved model R²','counts':counts(len(q),len(q))},q)
    if chart=='H31':
        audit=frame(b,'native_audit')
        if 'missing_rate' in audit:
            data['panels']=[p for p in data['panels'] if not p['panel_id'].startswith('original_missingness')]
            P.distribution(b,audit,['missing_rate'],'omics_layer','original_missingness','Complete saved Core missing-rate distribution')
        mapping=frame(b,'native_mapping')
        if len(mapping):
            r=mapping.iloc[0];total=int(r.get('expression_genes',r.get('expression_gene_count',0)));matched=int(r.get('matched_genes',r.get('matched_gene_count',0)));conflict=int(r.get('conflict_gene_count',0))
            rows=[{'category':'Matched expression IDs','group':'Validated mapping report','count':matched},
              {'category':'Unmatched expression IDs','group':'Validated mapping report','count':max(0,total-matched)},
              {'category':'Flagged conflicts (overlap, not an exclusive class)','group':'Validated mapping report','count':conflict}]
            append(b,{'type':'categories','panel_id':'mapping_source_counts','title':'Original expression-gene mapping; conflicts may overlap',
              'rows':rows,'plot_rows':rows,'unit':'Expression gene IDs from the saved validation report','counts':counts(total,total)},mapping)
    if chart in ['H02','H06','H23','H31']:
        originals=list(data['panels'])
        for p in originals:
            if p['type']!='heatmap':continue
            group=next((k for k in ['omics','omics_layer'] if any(k in r for r in p['rows'])),None)
            if group:
                data['panels'].remove(p);strip_facets(b,p,group,strip=chart!='H06')
    if chart in ['S23','S24','S25'] or data.get('core_panel_id'):
        for p in list(data['panels']):
            if p['type']=='heatmap' and p.get('value_key')=='value' and any('quantile' in r for r in p.get('rows',[])):
                index=data['panels'].index(p);q=transpose(p);q['x_label']='Every numeric field in original column order';q['y_label']='Exact quantile';data['panels'][index]=q
                stats={r['field']:r for r in p['rows']};f=b.sources.get('features',pd.DataFrame());den=len(f)
                rows=[{'field':k,'valid_fraction':v['n']/den if den else None,'valid_n':v['n'],'source_n':den} for k,v in stats.items()]
                append(b,{'type':'validity_curve','panel_id':p['panel_id']+'_validity','title':'Finite-value fraction for every field',
                  'rows':rows,'plot_rows':rows,'x_label':'Same field order','y_label':'Valid / N','role':'secondary','counts':counts(len(rows),len(rows))},pd.DataFrame(rows))
    for p in list(data['panels']):
        if p['type']=='heatmap' and p.get('rows') and all(str(r.get('field','')).startswith('codon_') for r in p['rows']) and not any('quantile' in r for r in p['rows']):
            i=data['panels'].index(p);q=transpose(p);q['x_label']='All 64 codons in the original alphabet';q['y_label']='Group';data['panels'][i]=q
        if p['type']=='heatmap' and p.get('rows') and all(str(r.get('field','')).startswith('frac_') for r in p['rows']):
            p['type']='base_composition';p['x_label']='RNA base';p['y_label']='Mean saved per-transcript fraction'
    if 'dinucleotide' in data.get('core_panel_id',''):
        original=next((p for p in data['panels'] if p['type']=='heatmap'),None)
        if original:
            data['panels'].remove(original)
            for group in original['x_categories']:
                rows=[]
                for r in original['rows']:
                    match=re.search(r'_([ACGTU]{2})_freq$',str(r.get('field','')))
                    if r['x']==group and match:rows.append({'first':match[1][0],'second':match[1][1],'frequency':r['value'],'field':r['field'],'group':group,'n':r.get('n')})
                if rows:P.heatmap(b,pd.DataFrame(rows),'first','second','frequency','dinucleotide_'+digest(group)[:7],'Complete dinucleotide composition · '+group)
    if chart in ['S10','H10']:
        for p in list(data['panels']):
            if p['type']=='ecdf':quantile_companion(b,p)
    if chart=='H01' and profile=='context_coverage':data['panels']=[p for p in data['panels'] if p['panel_id']=='universe']
    if chart=='H16':
        for p in list(data['panels']):
            if p['type']=='gsea_curve':
                p['member_rug']=True
                append(b,{'type':'hit_rug','panel_id':'running_es_members','title':'Every saved term member',
                  'hits':p.get('hits',[]),'rank_max':max([r[0] for r in p['points']],default=1),'rows':[],
                  'plot_rows':[{'rank':x} for x in p.get('hits',[])],'x_label':'All saved gene ranks','y_label':'Members',
                  'role':'secondary','counts':counts(len(p['points']),len(p['points']),len(p.get('hits',[])),len(p.get('hits',[])))},b.records.get(p['panel_id']))
    # All category summaries are semantic. Only true composition questions get bars.
    primary_categories={'S13':{'categories'},'H01':{'universe','annotations'},'H05':{'workflow_patterns'},
      'H21':{'candidate_tiers'},'H22':{'saved_gene_function_links'},'H24':{'saved_model_classes'},'S22':{'contribution_sources'}}
    state_matrices={'H15':{'nes_availability'},'H17':set(),'H27':{'eligibility_reasons'}}
    core=bool(data.get('core_panel_id'));atlas=core and any(p['type']=='heatmap' for p in data['panels'])
    for p in data['panels']:
        p['title']=label(p.get('title') or p['panel_id']);p.setdefault('role','primary');p.setdefault('design_id',chart)
        if p['type']=='categories':
            if p['panel_id'] in primary_categories.get(chart,set()) and not core:
                p['encoding']='horizontal_composition';p['role']='secondary' if chart in ['H21','H22','S22'] else 'primary'
            elif p['panel_id'] in state_matrices.get(chart,set()) or chart=='H17' and p['panel_id'].endswith('_states'):
                p.update(matrix_counts(p));p['role']='secondary'
            else:p['encoding']='status_summary';p['role']='diagnostic'
        if core and p['type']=='ecdf':p['role']='detail'
        if chart=='S07' and p['type']=='ecdf':p['role']='detail'
        if core and p['type']=='categories':p['role']='diagnostic'
        if p['type']=='ecdf':
            p['x_label']=label(p.get('x_label','').replace(' (saved units)',''))
        if p['type']=='heatmap' and p.get('category_states'):p['encoding']='discrete_audit'
        if chart in ['S01','H02','H23','H31'] and p['type']=='heatmap':p['compact_strip']=True
        if chart=='H31' and p['type']=='categories':p['role']='diagnostic'
        if chart=='H21' and p['panel_id']=='candidate_priority':p['symbol_field']='annotated'
        if p['type']=='composition_intervals':p['x_label']='Amino-acid content (%)' if any(str(r.get('field','')).startswith('AA_') for r in p.get('rows',[])) else 'Amino-acid frequency (fraction)'
        if chart=='H22' and p['panel_id']=='candidate_enrichment':p['role']='detail'
        if p['type']=='scatter' and p.get('symbol_field'):
            f=b.records.get(p['panel_id'],pd.DataFrame());p['annotations']={str(i):bool(v) for i,v in enumerate(f.get('annotated',[]))}
    # Labels and field statistics remain separate; no total merges genes, fields, tests and links.
    b.packet['design_revision']=DESIGN_REVISION
    b.packet['presentation']={'profile':profile,'design_ids':[chart],'layout':'evidence_facets',
      'primary':[p['panel_id'] for p in data['panels'] if p['role']=='primary'],
      'secondary':[p['panel_id'] for p in data['panels'] if p['role']=='secondary'],
      'diagnostic':[p['panel_id'] for p in data['panels'] if p['role']=='diagnostic'],
      'details':[p['panel_id'] for p in data['panels'] if p['role']=='detail'],'default_view':'evidence'}
    b.packet['method']['presentation']='Complete descriptive display, design revision 3; saved scientific estimates unchanged.'
