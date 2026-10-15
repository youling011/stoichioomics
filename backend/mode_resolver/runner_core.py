from __future__ import annotations
from pathlib import Path
from typing import Dict, Any

from .utils import read_json, write_json
from .resolver import resolve_modes


def run_mode_resolution_pipeline(config: Dict[str, Any]) -> Dict[str, Any]:
    validation_dir = Path(config['validation_dir'])
    output_dir = Path(config['output_dir'])
    output_dir.mkdir(parents=True, exist_ok=True)

    validation_summary = read_json(validation_dir / 'validation_summary.json')
    metadata_report = read_json(validation_dir / 'metadata_check_report.json')

    resolution = resolve_modes(validation_summary, metadata_report, preferred_mode=config.get('preferred_mode'))
    presets = {
        mode: info.get('preset')
        for mode, info in resolution['available_modes'].items()
        if info.get('available') and info.get('preset') is not None
    }

    readiness = {
        'case_id': config.get('case_id'),
        'overall_status_from_validation': resolution['overall_status_from_validation'],
        'can_proceed_to_phase1_hvg': resolution['ready_for_phase1_hvg'],
        'can_proceed_to_phase2_stoich': resolution['ready_for_phase2_stoich'],
        'recommended_mode': resolution['recommended_mode'],
        'n_available_modes': sum(1 for v in resolution['available_modes'].values() if v.get('available')),
    }

    run_log = {
        'case_id': config.get('case_id'),
        'validation_dir': str(validation_dir.resolve()),
        'output_dir': str(output_dir.resolve()),
        'preferred_mode': config.get('preferred_mode'),
        'recommended_mode': resolution['recommended_mode'],
    }

    write_json(resolution, output_dir / 'mode_resolution.json')
    capability = {
        'primary_mode': resolution.get('recommended_mode'),
        'auxiliary_modes': [
            mode for mode, info in resolution.get('available_modes', {}).items()
            if info.get('available') and mode != resolution.get('recommended_mode')
        ],
        'modes': {
            mode: {
                'status': 'available' if info.get('available') else 'skipped',
                'selected_key': info.get('selected_key'),
                'reasons': info.get('reasons', []),
            }
            for mode, info in resolution.get('available_modes', {}).items()
        },
        'phase2_stoich': {
            'status': 'available' if resolution.get('ready_for_phase2_stoich') else 'skipped',
            'metadata_required': False,
        },
    }
    skipped_modes = {
        'skipped': [
            {'mode': mode, 'status': 'skipped', 'reason_code': 'missing_or_insufficient_metadata', 'reasons': info.get('reasons', [])}
            for mode, info in resolution.get('available_modes', {}).items()
            if not info.get('available')
        ]
    }
    write_json(capability, output_dir / 'capability_matrix.json')
    write_json(skipped_modes, output_dir / 'skipped_modes.json')
    write_json(presets, output_dir / 'mode_presets.json')
    write_json(readiness, output_dir / 'analysis_readiness.json')
    write_json(run_log, output_dir / 'run_log.json')

    return {
        'recommended_mode': resolution['recommended_mode'],
        'n_available_modes': readiness['n_available_modes'],
        'output_dir': str(output_dir.resolve()),
    }
