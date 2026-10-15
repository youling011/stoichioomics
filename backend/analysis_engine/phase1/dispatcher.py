
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Tuple
import pandas as pd

from backend.validation.loader import load_standardized_bundle
from backend.analysis_engine.common import bundle_to_expression_dataset
from backend.analysis_engine.phase1.global_hvg import run_global_mode
from backend.analysis_engine.phase1.group_hvg import run_group_mode
from backend.analysis_engine.phase1.condition_hvg import run_condition_mode
from backend.analysis_engine.phase1.timecourse_hvg import run_timecourse_mode
from backend.analysis_engine.phase1.sample_consensus_hvg import run_sample_consensus_mode
from backend.analysis_engine.phase1.trajectory_hvg import run_trajectory_mode


def _read_json(path: Path):
    import json
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def resolve_mode_and_key(config: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    mode = config.get('analysis_mode', 'auto')
    mode_info = {}
    if mode != 'auto':
        return str(mode), mode_info
    mode_dir = config.get('mode_resolution_dir')
    if not mode_dir:
        return 'global_hvg', mode_info
    mode_dir = Path(mode_dir)
    mode_resolution = _read_json(mode_dir / 'mode_resolution.json')
    mode_presets = _read_json(mode_dir / 'mode_presets.json') if (mode_dir / 'mode_presets.json').exists() else {}
    recommended = mode_resolution.get('recommended_mode') or 'global_hvg'
    mode_info = mode_resolution.get('available_modes', {}).get(recommended, {})
    if recommended in mode_presets:
        mode_info['preset'] = mode_presets[recommended]
    return recommended, mode_info


def run_phase1_dispatch(config: Dict[str, Any]):
    bundle = load_standardized_bundle(config['standardized_input_dir'], config.get('raw_stoich_file'))
    dataset = bundle_to_expression_dataset(bundle)
    var_df = bundle.var.copy()
    mode, mode_info = resolve_mode_and_key(config)
    selected_key = None
    if config.get('groupby_key'):
        selected_key = config['groupby_key']
    elif mode_info.get('selected_key'):
        selected_key = mode_info['selected_key']
    elif mode_info.get('preset', {}).get('phase1'):
        p1 = mode_info['preset']['phase1']
        for key_name in ['groupby','condition_key','timepoint_key','sample_key','pseudotime_key']:
            if p1.get(key_name):
                selected_key = p1.get(key_name)
                break

    if mode == 'global_hvg':
        return mode, run_global_mode(dataset, var_df, config)
    if mode == 'group_aware_hvg':
        key = selected_key or 'cluster'
        return mode, run_group_mode(dataset, var_df, config, key)
    if mode == 'condition_aware_hvg':
        key = selected_key or 'condition'
        return mode, run_condition_mode(dataset, var_df, config, key)
    if mode == 'timecourse_hvg':
        key = selected_key or 'timepoint'
        return mode, run_timecourse_mode(dataset, var_df, config, key)
    if mode == 'sample_consensus_hvg':
        key = selected_key or 'sample_id'
        return mode, run_sample_consensus_mode(dataset, var_df, config, key)
    if mode == 'trajectory_hvg':
        key = selected_key or 'pseudotime'
        return mode, run_trajectory_mode(dataset, var_df, config, key)
    raise ValueError(f'Unsupported analysis_mode: {mode}')
