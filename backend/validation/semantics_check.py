from __future__ import annotations
from typing import Dict, Any
import numpy as np

from .schemas import StandardizedBundle
from .utils import is_integer_like, sample_nonzero_values


def _heuristic_semantics(values: np.ndarray) -> Dict[str, Any]:
    if values.size == 0:
        return {'inferred_semantics': 'empty_matrix', 'confidence': 'low', 'notes': ['No non-zero values detected.']}
    frac_int = is_integer_like(values)
    max_v = float(values.max())
    min_v = float(values.min())
    mean_v = float(values.mean())

    notes = [f'integer_like_fraction={frac_int:.4f}', f'min={min_v:.4f}', f'max={max_v:.4f}', f'mean={mean_v:.4f}']
    if min_v < 0:
        return {'inferred_semantics': 'contains_negative_values', 'confidence': 'high', 'notes': notes}
    if frac_int > 0.98:
        return {'inferred_semantics': 'raw_counts_like', 'confidence': 'high', 'notes': notes}
    if frac_int < 0.5 and max_v < 20:
        return {'inferred_semantics': 'log_or_normalized_like', 'confidence': 'medium', 'notes': notes}
    if frac_int < 0.8:
        return {'inferred_semantics': 'normalized_like', 'confidence': 'medium', 'notes': notes}
    return {'inferred_semantics': 'unknown_mixed', 'confidence': 'low', 'notes': notes}


def build_semantics_check_report(bundle: StandardizedBundle) -> Dict[str, Any]:
    declared = bundle.uns.get('matrix_semantics', bundle.phase1_validation.get('matrix_semantics', 'unknown'))
    sampled = sample_nonzero_values(bundle.X)
    inferred = _heuristic_semantics(sampled)
    return {
        'declared_matrix_semantics': declared,
        'heuristic_inference': inferred,
        'compatible_with_standard_hvg_counts_workflow': inferred['inferred_semantics'] in {'raw_counts_like', 'unknown_mixed'} or declared in {'raw_counts', 'raw_counts_like'},
    }
