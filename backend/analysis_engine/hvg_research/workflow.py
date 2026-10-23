"""The public, non-predictive HVG workflow contract."""
from copy import deepcopy
CONTRACT = 'hvg_unified_nonmodel_v1'
def normalize_workflow_config(value):
    cfg = deepcopy(value)
    cfg.setdefault('hvg_research', {})['enabled'] = True
    p = cfg.setdefault('phase1_analysis', {})
    p['primary_backend'] = 'scanpy'
    p['allow_primary_fallback'] = False
    p['run_supported_auxiliary_modes'] = True
    p.setdefault('matrix_semantics', cfg.get('input_adapter', {}).get('expression', {}).get('value_semantics', 'unknown'))
    # Old method aliases have an unambiguous standard equivalent. Matrix semantics
    # are still checked by official_hvg; counts are never silently log-transformed.
    if p.get('hvg_method') in ('dispersion', 'seurat_dispersion'):
        p['hvg_method'] = 'seurat'
    model = cfg.setdefault('phase2_stoich', {})
    model['model_enabled'] = False
    model['model_skip_reason'] = 'removed_from_unified_workflow'
    return cfg
