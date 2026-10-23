"""Run every available original metadata mode without a predictive model."""
from pathlib import Path
from copy import deepcopy
import json
import pandas as pd
from .artifacts import atomic_json, atomic_frame

MODE_FUNCS = {
 'group_aware_hvg':('group_hvg','run_group_mode'),
 'condition_aware_hvg':('condition_hvg','run_condition_mode'),
 'timecourse_hvg':('timecourse_hvg','run_timecourse_mode'),
 'sample_consensus_hvg':('sample_consensus_hvg','run_sample_consensus_mode'),
 'trajectory_hvg':('trajectory_hvg','run_trajectory_mode')}

def run_modes(run, dataset, config, global_context, run_id):
    import importlib
    resolution=json.loads((run/'work/mode_resolution/mode_resolution.json').read_text(encoding='utf-8'))
    out=run/'work/analysis_phase1';out.mkdir(parents=True,exist_ok=True)
    baseline=pd.read_parquet(global_context/'labels/hvg_labels.parquet')
    method=json.loads((global_context/'labels/hvg_method_manifest.json').read_text(encoding='utf-8'))
    var=pd.read_csv(run/'work/standardized/standardized_var.csv')
    baseline.to_csv(out/'hvg_baseline.csv',index=False)
    cfg=deepcopy(config);cfg['primary_backend']='scanpy';cfg['_standard_hvg_cache']={}
    from backend.analysis_engine.phase1.utils import filter_low_quality_genes
    filtered,_=filter_low_quality_genes(dataset,cfg.get('min_cells',3),cfg.get('min_counts',1))
    for ds in [dataset,filtered]:
        cfg['_standard_hvg_cache'][(tuple(ds.cell_ids),tuple(ds.gene_ids))]=(baseline,method)
    rows=[{'mode':'global_hvg','status':'completed','selected_key':None,'reason':None,
        'n_genes':len(baseline),'n_hvgs':int(baseline.is_hvg.sum())}]
    subsets=[]; patterns=[];members=[];outputs={};failed=[]
    for mode,(module,name) in MODE_FUNCS.items():
        info=resolution.get('available_modes',{}).get(mode,{})
        row={'mode':mode,'selected_key':info.get('selected_key')}
        if not info.get('available'):
            rows.append({**row,'status':'not_applicable','reason':'; '.join(map(str,info.get('reasons') or ['Required metadata are unavailable']))});continue
        try:
            fn=getattr(importlib.import_module('backend.analysis_engine.phase1.'+module),name)
            from backend.analysis_engine.phase1.utils import subset_dataset
            key=info['selected_key'];valid=dataset.obs[key].notna()
            if mode=='trajectory_hvg':valid &= pd.to_numeric(dataset.obs[key],errors='coerce').notna()
            mode_dataset=subset_dataset(dataset,valid.to_numpy()) if not valid.all() else dataset
            primary,summary,extras=fn(mode_dataset,var,cfg,key)
            summary['metadata_missing_cells_excluded']=int((~valid).sum())
            valid_subsets=[x for x in summary.get('subset_summaries',[]) if not x.get('skipped')]
            if len(valid_subsets)<2:raise ValueError('Fewer than two valid metadata subsets after QC; no contextual contrast is available')
            modeout=out/'auxiliary_modes'/mode;modeout.mkdir(parents=True,exist_ok=True)
            primary.to_csv(modeout/'hvg_baseline.csv',index=False)
            for filename,frame in extras.items():
                frame.to_csv(modeout/filename,index=False)
                if not frame.empty:
                    frame=frame.copy();frame['mode']=mode
                    if 'subset_value' in frame:members.append(frame)
                    else:patterns.append(frame)
            for sub in summary.get('subset_summaries',[]):
                subsets.append({**sub,'mode':mode,'selected_key':info['selected_key']})
            for key,value in summary.items():
                if key.endswith('_pattern_counts'):
                    for label,n in value.items():patterns.append(pd.DataFrame([{'mode':mode,'pattern':label,'count':n}]))
            if 'consensus_label' in primary:
                for label,n in primary.consensus_label.value_counts().items():patterns.append(pd.DataFrame([{'mode':mode,'pattern':label,'count':n}]))
            atomic_json(modeout/'summary.json',summary)
            outputs[mode]={'status':'success','summary':summary,'output':str((modeout/'hvg_baseline.csv').relative_to(run))}
            skipped=[x for x in summary.get('subset_summaries',[]) if x.get('skipped')]
            rows.append({**row,'status':'completed','reason':('Some subsets failed QC; inspect subset summaries' if skipped else None),'n_genes':len(primary),'n_hvgs':int(primary.is_hvg.sum()),'skipped_subsets':len(skipped)})
        except Exception as exc:
            message=f'{type(exc).__name__}: {exc}'
            rows.append({**row,'status':'failed','reason':message});failed.append(mode+': '+message)
    for key,frame in [('modes',pd.DataFrame(rows)),('subsets',pd.DataFrame(subsets,columns=list(dict.fromkeys(['mode','label','selected_key','n_cells','n_genes','n_hvgs','skipped','reason']+[k for r in subsets for k in r])))),('patterns',pd.concat(patterns,ignore_index=True) if patterns else pd.DataFrame(columns=['mode','pattern','count'])),('members',pd.concat(members,ignore_index=True) if members else pd.DataFrame(columns=['mode','gene_id','subset_value','is_hvg']))]:
        atomic_frame(run/f'workflow/{key}.parquet',frame)
    summary={'analysis_mode':'global_hvg','primary_backend':'scanpy','method_metadata':method,
        'analysis_run_id':run_id,'n_rows_primary':len(baseline),'n_hvgs_primary':int(baseline.is_hvg.sum()),
        'auxiliary_mode_outputs':outputs,'mode_statuses':rows,'skipped_modes':[x for x in rows if x['status']!='completed']}
    atomic_json(out/'phase1_mode_summary.json',summary)
    atomic_json(run/'workflow/mode_manifest.json',summary)
    status=run/'work/visualization/backend_status_table.csv';status.parent.mkdir(parents=True,exist_ok=True)
    pd.DataFrame([{'backend':'scanpy','status':'completed','method':config.get('hvg_method'),'role':'official labels for global and metadata subsets','fallback_allowed':False}]).to_csv(status,index=False)
    return {'status':'partial' if failed else 'completed','failed_modes':failed,'completed_modes':sum(x['status']=='completed' for x in rows),'scientific_status':'not_applicable'}
