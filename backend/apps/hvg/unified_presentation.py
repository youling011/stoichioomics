"""Read-only presentation of the unified workflow's original mode outputs."""
import json
import pandas as pd
from backend.analysis_engine.hvg_research.artifacts import clean
def comparison_payload(run,m,params):
    if params.get('context_id','global')!='global':
        return {'status':'unavailable','reason':'The original comparison uses the global baseline; select global. Research comparisons remain context-specific.'}
    root=run/'work/analysis_phase2'
    def js(name):
        p=root/name
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
    def csv(name):
        p=root/name
        if not p.exists():return []
        try:return clean(pd.read_csv(p,engine='python').to_dict('records'))
        except pd.errors.EmptyDataError:return []
    return clean({**js('hvg_nonhvg_summary.json'),'analysis_run_id':m['analysis_run_id'],
        'audit':csv('hvg_nonhvg_feature_audit.csv'),'features':csv('hvg_nonhvg_feature_comparison.csv'),
        'adjusted':csv('hvg_nonhvg_adjusted_comparison.csv'),
        'quantiles':csv('hvg_nonhvg_distribution_quantiles.csv'),
        'plots':js('hvg_nonhvg_plots_payload.json'),
        'status':js('hvg_nonhvg_summary.json').get('comparison_status','unavailable'),
        'reason':js('hvg_nonhvg_summary.json').get('reason') or ('No original comparison was saved for this run.' if not (root/'hvg_nonhvg_summary.json').exists() else None)})
