from __future__ import annotations
from pathlib import Path
from typing import Iterable, Dict, Any, List
import json
import pandas as pd


def _read_json(path: Path):
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return None


def compare_cases(case_entries: Iterable[Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for c in case_entries:
        base = Path(c['base_dir'])
        p1 = _read_json(base / 'analysis_phase1' / 'phase1_mode_summary.json') or {}
        p2 = _read_json(base / 'analysis_phase2' / 'hvg_summary.json') or {}
        p2_model = _read_json(base / 'analysis_phase2' / 'hvg_stoich_model.json') or {}
        cc = p2.get('class_counts', {})
        model_info = p2.get('model_info') or {}
        model_metrics = model_info.get('model_metrics') or p2_model.get('model_metrics') or {}
        baseline_metrics = model_info.get('baseline_metrics') or p2_model.get('baseline_metrics') or {}
        delta_metrics = model_info.get('delta_metrics') or p2_model.get('delta_metrics') or {}
        mapping = p2.get('mapping_summary') or p2_model.get('mapping_summary') or {}
        rows.append({
            'case_id': c.get('case_id', base.name),
            'label': c.get('label', base.name),
            'source': c.get('source', 'unknown'),
            'recommended_mode': p1.get('analysis_mode'),
            'hvg_method': (p1.get('method_metadata') or {}).get('hvg_method'),
            'total_genes': p2.get('total_genes'),
            'total_hvgs': p2.get('total_hvgs'),
            'canonical_hvg': cc.get('canonical_hvg'),
            'stoich_explained_hvg': cc.get('stoich_explained_hvg'),
            'stoich_excess_hvg': cc.get('stoich_excess_hvg'),
            'stoich_constrained_stable': cc.get('stoich_constrained_stable'),
            'background_gene': cc.get('background_gene'),
            'model_task_type': model_metrics.get('task_type'),
            'model_type': model_metrics.get('model_type'),
            'cv_r2_mean': model_metrics.get('cv_r2_mean'),
            'cv_roc_auc_mean': model_metrics.get('cv_roc_auc_mean'),
            'baseline_cv_r2_mean': baseline_metrics.get('cv_r2_mean'),
            'baseline_cv_roc_auc_mean': baseline_metrics.get('cv_roc_auc_mean'),
            'delta_cv_r2': delta_metrics.get('delta_cv_r2'),
            'delta_cv_roc_auc': delta_metrics.get('delta_cv_roc_auc'),
            'predictive_confidence': model_metrics.get('predictive_confidence'),
            'match_rate': mapping.get('match_rate'),
            'matched_hvgs': mapping.get('matched_hvgs'),
            'unmatched_hvgs': mapping.get('unmatched_hvgs'),
            'base_dir': str(base),
        })
    return pd.DataFrame(rows)
