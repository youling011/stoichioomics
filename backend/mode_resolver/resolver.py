from __future__ import annotations
from typing import Dict, Any, Optional

from .rules import (
    evaluate_global, evaluate_group, evaluate_condition,
    evaluate_timecourse, evaluate_sample_consensus, evaluate_trajectory,
)
from .presets import build_mode_preset

MODE_PRIORITY = [
    'timecourse_hvg',
    'condition_aware_hvg',
    'group_aware_hvg',
    'trajectory_hvg',
    'sample_consensus_hvg',
    'global_hvg',
]


def resolve_modes(validation_summary: Dict[str, Any], metadata_report: Dict[str, Any], preferred_mode: Optional[str] = None) -> Dict[str, Any]:
    evaluations = {
        'global_hvg': evaluate_global(metadata_report, validation_summary),
        'group_aware_hvg': evaluate_group(metadata_report),
        'condition_aware_hvg': evaluate_condition(metadata_report),
        'timecourse_hvg': evaluate_timecourse(metadata_report),
        'sample_consensus_hvg': evaluate_sample_consensus(metadata_report),
        'trajectory_hvg': evaluate_trajectory(metadata_report),
    }

    available = {k: v for k, v in evaluations.items() if v['available']}
    unavailable = {k: v for k, v in evaluations.items() if not v['available']}

    recommended_mode = None
    recommendation_reason = None
    if preferred_mode and preferred_mode in available:
        recommended_mode = preferred_mode
        recommendation_reason = 'Selected because user preferred_mode is available.'
    else:
        for mode in MODE_PRIORITY:
            if mode in available:
                recommended_mode = mode
                recommendation_reason = f'Selected by default priority order among available modes: {MODE_PRIORITY}.'
                break

    available_modes = {}
    for mode, info in evaluations.items():
        payload = {
            'available': bool(info['available']),
            'selected_key': info.get('selected_key'),
            'score': float(info.get('score', 0.0)),
            'reasons': info.get('reasons', []),
        }
        if info['available']:
            payload['preset'] = build_mode_preset(mode, selected_key=info.get('selected_key'))
        available_modes[mode] = payload

    notes = list(validation_summary.get('next_steps', []))
    if recommended_mode is None:
        notes.append('No advanced HVG mode could be recommended. Review validation warnings and metadata completeness.')
    elif recommended_mode == 'global_hvg' and len(available) == 1:
        notes.append('Only global_hvg is currently available. Provide richer metadata (e.g. condition, timepoint, cluster) for advanced modes.')

    return {
        'overall_status_from_validation': validation_summary.get('overall_status'),
        'ready_for_phase1_hvg': bool(validation_summary.get('ready_for_phase1_hvg', False)),
        'ready_for_phase2_stoich': bool(validation_summary.get('ready_for_phase2_stoich', False)),
        'available_modes': available_modes,
        'recommended_mode': recommended_mode,
        'recommendation_reason': recommendation_reason,
        'preferred_mode_applied': bool(preferred_mode and preferred_mode == recommended_mode),
        'supports_analysis_modes_from_phase2': validation_summary.get('supports_analysis_modes', {}),
        'notes': notes,
    }
