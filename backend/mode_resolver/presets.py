from __future__ import annotations
from typing import Optional, Dict, Any


def build_mode_preset(mode: str, *, selected_key: Optional[str] = None) -> Dict[str, Any]:
    common_phase2 = {
        'requires_stoich_phase2': True,
        'stoich_target_col': 'normalized_dispersion',
        'stoich_feature_set': 'core',
    }
    if mode == 'global_hvg':
        return {
            'phase1': {
                'analysis_mode': 'global_hvg',
                'groupby': None,
                'compute_global_hvg': True,
            },
            'phase2': common_phase2,
        }
    if mode == 'group_aware_hvg':
        return {
            'phase1': {
                'analysis_mode': 'group_aware_hvg',
                'groupby': selected_key,
                'compute_group_specific_hvg': True,
                'compute_global_hvg': True,
            },
            'phase2': common_phase2,
        }
    if mode == 'condition_aware_hvg':
        return {
            'phase1': {
                'analysis_mode': 'condition_aware_hvg',
                'condition_key': selected_key,
                'compute_shared_hvg': True,
                'compute_condition_specific_hvg': True,
            },
            'phase2': common_phase2,
        }
    if mode == 'timecourse_hvg':
        return {
            'phase1': {
                'analysis_mode': 'timecourse_hvg',
                'timepoint_key': selected_key or 'timepoint',
                'compute_across_time_hvg': True,
                'compute_within_timepoint_hvg': True,
            },
            'phase2': common_phase2,
        }
    if mode == 'sample_consensus_hvg':
        return {
            'phase1': {
                'analysis_mode': 'sample_consensus_hvg',
                'sample_key': selected_key,
                'consensus_strategy': 'vote',
                'compute_global_hvg': True,
            },
            'phase2': common_phase2,
        }
    if mode == 'trajectory_hvg':
        return {
            'phase1': {
                'analysis_mode': 'trajectory_hvg',
                'pseudotime_key': selected_key or 'pseudotime',
                'binning_strategy': 'quantile',
                'n_bins': 10,
            },
            'phase2': common_phase2,
        }
    raise ValueError(f'Unknown mode: {mode}')
