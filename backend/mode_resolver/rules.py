from __future__ import annotations
from typing import Dict, Any, Iterable, Optional, Tuple
import math


PREFERRED_KEY_ORDER = {
    'group_aware_hvg': ['cell_type', 'cluster'],
    'condition_aware_hvg': ['condition', 'perturbation'],
    'timecourse_hvg': ['timepoint'],
    'sample_consensus_hvg': ['sample_id', 'donor', 'batch'],
    'trajectory_hvg': ['pseudotime'],
}


def _get_field_score(completeness: Dict[str, float], cardinality: Dict[str, int], field: str) -> float:
    comp = float(completeness.get(field, 0.0) or 0.0)
    card = int(cardinality.get(field, 0) or 0)
    card_score = min(card / 10.0, 1.0)
    return round(comp * 0.7 + card_score * 0.3, 4)


def choose_best_key(fields: Iterable[str], completeness: Dict[str, float], cardinality: Dict[str, int], preferred_order: Iterable[str]) -> Tuple[Optional[str], float]:
    ordered = [f for f in preferred_order if f in fields] + [f for f in fields if f not in preferred_order]
    best_key = None
    best_score = -1.0
    for field in ordered:
        score = _get_field_score(completeness, cardinality, field)
        if score > best_score:
            best_key = field
            best_score = score
    return best_key, max(best_score, 0.0)


def evaluate_global(metadata_report: Dict[str, Any], validation_summary: Dict[str, Any]) -> Dict[str, Any]:
    available = bool(validation_summary.get('ready_for_phase1_hvg', False) and metadata_report.get('required_cell_id_present', False) and metadata_report.get('cell_id_unique', False))
    reasons = []
    if not validation_summary.get('ready_for_phase1_hvg', False):
        reasons.append('Phase 2 validation indicates the dataset is not ready for HVG computation.')
    if not metadata_report.get('required_cell_id_present', False):
        reasons.append('Metadata does not contain cell_id.')
    if not metadata_report.get('cell_id_unique', False):
        reasons.append('cell_id values are not unique.')
    return {'available': available, 'reasons': reasons, 'selected_key': None, 'score': 1.0 if available else 0.0}


def evaluate_group(metadata_report: Dict[str, Any]) -> Dict[str, Any]:
    present = set(metadata_report.get('recommended_fields_present', []))
    completeness = metadata_report.get('field_completeness', {})
    cardinality = metadata_report.get('field_cardinality', {})
    candidates = [f for f in ['cell_type', 'cluster'] if f in present and int(cardinality.get(f, 0)) >= 2 and float(completeness.get(f, 0.0)) >= 0.5]
    reasons = []
    if not candidates:
        reasons.append('Need cluster or cell_type metadata with at least two groups and >=50% completeness.')
    best_key, score = choose_best_key(candidates, completeness, cardinality, PREFERRED_KEY_ORDER['group_aware_hvg']) if candidates else (None, 0.0)
    return {'available': bool(candidates), 'reasons': reasons, 'selected_key': best_key, 'score': score}


def evaluate_condition(metadata_report: Dict[str, Any]) -> Dict[str, Any]:
    present = set(metadata_report.get('recommended_fields_present', []))
    completeness = metadata_report.get('field_completeness', {})
    cardinality = metadata_report.get('field_cardinality', {})
    candidates = [f for f in ['condition', 'perturbation'] if f in present and int(cardinality.get(f, 0)) >= 2 and float(completeness.get(f, 0.0)) >= 0.5]
    reasons = []
    if not candidates:
        reasons.append('Need condition or perturbation metadata with at least two states and >=50% completeness.')
    best_key, score = choose_best_key(candidates, completeness, cardinality, PREFERRED_KEY_ORDER['condition_aware_hvg']) if candidates else (None, 0.0)
    return {'available': bool(candidates), 'reasons': reasons, 'selected_key': best_key, 'score': score}


def evaluate_timecourse(metadata_report: Dict[str, Any]) -> Dict[str, Any]:
    completeness = metadata_report.get('field_completeness', {})
    cardinality = metadata_report.get('field_cardinality', {})
    available = ('timepoint' in metadata_report.get('recommended_fields_present', []) and int(cardinality.get('timepoint', 0)) >= 2 and float(completeness.get('timepoint', 0.0)) >= 0.5)
    reasons = []
    if not available:
        reasons.append('Need timepoint metadata with at least two timepoints and >=50% completeness.')
    score = _get_field_score(completeness, cardinality, 'timepoint') if available else 0.0
    return {'available': available, 'reasons': reasons, 'selected_key': 'timepoint' if available else None, 'score': score}


def evaluate_sample_consensus(metadata_report: Dict[str, Any]) -> Dict[str, Any]:
    present = set(metadata_report.get('recommended_fields_present', []))
    completeness = metadata_report.get('field_completeness', {})
    cardinality = metadata_report.get('field_cardinality', {})
    candidates = [f for f in ['sample_id', 'donor', 'batch'] if f in present and int(cardinality.get(f, 0)) >= 2 and float(completeness.get(f, 0.0)) >= 0.5]
    reasons = []
    if not candidates:
        reasons.append('Need sample_id, donor, or batch metadata with at least two unique values and >=50% completeness.')
    best_key, score = choose_best_key(candidates, completeness, cardinality, PREFERRED_KEY_ORDER['sample_consensus_hvg']) if candidates else (None, 0.0)
    return {'available': bool(candidates), 'reasons': reasons, 'selected_key': best_key, 'score': score}


def evaluate_trajectory(metadata_report: Dict[str, Any]) -> Dict[str, Any]:
    completeness = metadata_report.get('field_completeness', {})
    cardinality = metadata_report.get('field_cardinality', {})
    available = ('pseudotime' in metadata_report.get('recommended_fields_present', []) and int(cardinality.get('pseudotime', 0)) >= 10 and float(completeness.get('pseudotime', 0.0)) >= 0.5)
    reasons = []
    if not available:
        reasons.append('Need pseudotime metadata with >=10 unique values and >=50% completeness.')
    score = _get_field_score(completeness, cardinality, 'pseudotime') if available else 0.0
    return {'available': available, 'reasons': reasons, 'selected_key': 'pseudotime' if available else None, 'score': score}
