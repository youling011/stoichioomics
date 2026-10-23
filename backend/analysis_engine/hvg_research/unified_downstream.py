"""Non-model comparisons and candidate functions, with explicit provenance."""
import json
import pandas as pd
from .artifacts import atomic_json,atomic_frame,member_hash

def run_original_comparison(run,cfg):
    from backend.apps.hvg.feature_context import build_hvg_multiomics_feature_context
    from backend.analysis_engine.phase2.group_comparison import run_hvg_nonhvg_comparison,write_unavailable_comparison
    p=dict(cfg['phase2_stoich']);out=run/'work/analysis_phase2';out.mkdir(parents=True,exist_ok=True)
    baseline=run/'work/analysis_phase1/hvg_baseline.csv'
    try:
        context=build_hvg_multiomics_feature_context(baseline_csv=str(baseline),output_dir=str(out),
            species_id=p['species_id'],requested_omics=p.get('comparison_omics') or ['genome','transcriptome','proteome'],config=p)
        p.update(comparison_schema_version='hvg_nonhvg_v2',comparison_input_csv=context.get('comparison_input_csv'),
            comparison_feature_provenance_path=context.get('feature_provenance_csv'),
            comparison_mapping_summary_path=context.get('mapping_summary_json'),
            comparison_context_manifest_path=context.get('assembly_manifest_json'),
            comparison_block_coverage_path=context.get('block_coverage_csv'),comparison_block_status=context.get('block_status') or {})
        path=context.get('comparison_input_csv')
        if not path:raise ValueError('No validated multi-omics comparison context was produced')
        result=run_hvg_nonhvg_comparison(pd.read_csv(path),p,output_dir=out)
        return {'status':result['summary'].get('status') or result['summary'].get('comparison_status'),'output_dir':'work/analysis_phase2','model_executed':False}
    except Exception as exc:
        reason=f'{type(exc).__name__}: {exc}'
        write_unavailable_comparison(out,status='failed',reason=reason,config=p)
        return {'status':'failed','reason':reason,'model_executed':False}

def run_candidate_functions(run,contexts,cfg):
    from .enrichment import ora
    from .statistics import fdr
    frames=[]
    for info in contexts:
        ctx=run/info['directory'];L=pd.read_parquet(ctx/'labels/hvg_labels.parquet')
        C=pd.read_parquet(ctx/'candidates/candidate_genes.parquet')
        A=pd.read_parquet(ctx/'annotations/gene_term_membership.parquet');T=pd.read_parquet(ctx/'annotations/terms.parquet')
        for source,g in A.groupby('source'):
            bg=set(g.gene_id)&set(L.gene_id);query=set(C.gene_id)&bg
            frames.append(ora(query,bg,A,T[T.source.eq(source)],min_term=cfg['enrichment']['min_term_size'],
                max_term=cfg['enrichment']['max_term_size'],min_query=cfg['gene_sets']['min_annotated_query'],
                fields={'context_id':info['context_id'],'query_scope':'research_candidates','family_id':'F9_candidates'}))
    frame=pd.concat(frames,ignore_index=True) if frames else pd.DataFrame(columns=['context_id','source','term_key','term_name','p_value','fold_enrichment','status'])
    frame['q_global']=fdr(frame.p_value);frame['q_global_by']=fdr(frame.p_value,'by')
    atomic_frame(run/'workflow/candidate_ora.parquet',frame)
    hp=run/'reports/hypothesis_manifest.parquet'
    from .artifacts import content_hash
    entries=[]
    for i,row in frame.iterrows():
        h={k:row.get(k) for k in ['context_id','source','term_key','p_value','q_global','q_global_by','status','background_id']}
        h.update(family_id='F9_candidates',included_in_fdr=bool(pd.notna(row.get('p_value'))),hypothesis_id=content_hash(['candidate_ora',i,h]))
        entries.append(h)
    if entries:
        old=pd.read_parquet(hp) if hp.exists() else pd.DataFrame()
        atomic_frame(hp,pd.concat([old,pd.DataFrame(entries)],ignore_index=True))
    # Existing PPI utility never reads network edges; report this honestly rather
    # than treating model classes or research tiers as network modules.
    atomic_frame(run/'workflow/network_status.parquet',pd.DataFrame([{'status':'not_available','reason':'No validated PPI edge input or network inference is available in this workflow. Candidate tiers are not PPI modules.'}]))
    return {'status':'completed','tested':int(frame.p_value.notna().sum()),'significant':int(frame.q_global.lt(cfg['feature_tests']['alpha']).sum())}
