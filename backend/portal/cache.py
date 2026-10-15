from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
import json
import pandas as pd


def _read_json(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return None


def _read_csv(path: Path, nrows: int | None = None):
    if path.exists():
        return pd.read_csv(path, nrows=nrows)
    return None


def build_case_cache(base_dir: str | Path) -> Dict[str, Any]:
    base = Path(base_dir)
    p1 = _read_csv(base / 'analysis_phase1' / 'hvg_baseline.csv')
    p1_summary = _read_json(base / 'analysis_phase1' / 'phase1_mode_summary.json') or {}
    p2 = _read_csv(base / 'analysis_phase2' / 'hvg_stoich_scores.csv')
    p2_summary = _read_json(base / 'analysis_phase2' / 'hvg_summary.json') or {}
    p2_model = _read_json(base / 'analysis_phase2' / 'hvg_stoich_model.json') or {}

    cache: Dict[str, Any] = {
        'base_dir': str(base.resolve()),
        'has_phase1': p1 is not None,
        'has_phase2': p2 is not None,
        'phase1_summary': p1_summary,
        'phase2_summary': p2_summary,
        'phase1_metrics': {},
        'phase2_metrics': {},
        'top_tables': {},
    }

    if p1 is not None and not p1.empty:
        cache['phase1_metrics'] = {
            'n_genes': int(len(p1)),
            'n_hvgs': int(p1['is_hvg'].fillna(False).astype(bool).sum()) if 'is_hvg' in p1.columns else None,
            'mean_dispersion': float(p1['normalized_dispersion'].mean()) if 'normalized_dispersion' in p1.columns else None,
        }
        sort_col = 'hvg_rank' if 'hvg_rank' in p1.columns else ('normalized_dispersion' if 'normalized_dispersion' in p1.columns else None)
        if sort_col:
            asc = sort_col == 'hvg_rank'
            cols = [c for c in ['gene_id', 'gene_name', 'hvg_rank', 'normalized_dispersion', 'mean_expr', 'is_hvg'] if c in p1.columns]
            cache['top_tables']['phase1_top_hvgs'] = p1.sort_values(sort_col, ascending=asc).head(20)[cols].to_dict(orient='records')

    if p2 is not None and not p2.empty:
        class_counts = p2['stoich_class'].value_counts(dropna=False).to_dict() if 'stoich_class' in p2.columns else {}
        model_info = p2_summary.get('model_info') or {}
        mapping = p2_summary.get('mapping_summary') or p2_model.get('mapping_summary') or {}
        cache['phase2_metrics'] = {
            'n_scored_genes': int(len(p2)),
            'class_counts': class_counts,
            'mean_cost_index': float(p2['cost_index'].mean()) if 'cost_index' in p2.columns else None,
            'mean_excess_var': float(p2['stoich_excess_var'].mean()) if 'stoich_excess_var' in p2.columns else None,
            'model_type': (model_info.get('model_metrics') or {}).get('model_type'),
            'predictive_confidence': (model_info.get('model_metrics') or {}).get('predictive_confidence'),
            'delta_cv_r2': (model_info.get('delta_metrics') or {}).get('delta_cv_r2'),
            'delta_cv_roc_auc': (model_info.get('delta_metrics') or {}).get('delta_cv_roc_auc'),
            'match_rate': mapping.get('match_rate'),
        }
        for name, filt, sort_col, ascending in [
            ('top_excess', (p2['stoich_class'] == 'stoich_excess_hvg') if 'stoich_class' in p2.columns else None, 'stoich_excess_var', False),
            ('top_explained', (p2['stoich_class'] == 'stoich_explained_hvg') if 'stoich_class' in p2.columns else None, 'stoich_explained_fraction', False),
            ('top_constrained', (p2['stoich_class'] == 'stoich_constrained_stable') if 'stoich_class' in p2.columns else None, 'cost_index', False),
        ]:
            if sort_col in p2.columns:
                sub = p2.loc[filt] if filt is not None else p2
                cols = [c for c in ['gene_id', 'gene_name', 'stoich_class', 'stoich_associated_feature', 'stoich_excess_var', 'stoich_explained_fraction', 'cost_index', 'observed_hvg_signal'] if c in p2.columns]
                cache['top_tables'][name] = sub.sort_values(sort_col, ascending=ascending).head(20)[cols].to_dict(orient='records')

    out = base / 'case_cache.json'
    out.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    return cache
