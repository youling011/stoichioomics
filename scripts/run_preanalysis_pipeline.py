from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.input_adapter.merge import build_internal_dataset, export_standardized_dataset
from backend.validation.runner_core import run_validation_pipeline
from backend.mode_resolver.runner_core import run_mode_resolution_pipeline
from backend.workspace import prepare_workspace


def main():
    p = argparse.ArgumentParser(description='Run integrated phases 1-3 preanalysis pipeline')
    p.add_argument('--config', required=True, help='YAML config path with keys phase1, phase2, phase3')
    args = p.parse_args()

    cfg_path = Path(args.config)
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    phase1 = cfg['phase1']
    phase2 = cfg['phase2']
    phase3 = cfg['phase3']
    ws = prepare_workspace(phase1)
    if ws.get('enabled'):
        phase1 = dict(phase1); phase2 = dict(phase2); phase3 = dict(phase3)
        phase1['output_dir'] = ws['paths']['standardized']
        phase2['input_dir'] = ws['paths']['standardized']; phase2['output_dir'] = ws['paths']['validation']
        if phase1.get('stoich', {}).get('file'):
            phase2['raw_stoich_file'] = str((Path(phase1['input_dir']) / phase1['stoich']['file']).resolve())
        phase3['validation_dir'] = ws['paths']['validation']; phase3['output_dir'] = ws['paths']['mode_resolution']

    ds, manifest, validation = build_internal_dataset(phase1)
    export_standardized_dataset(ds, phase1['output_dir'], manifest, validation, phase1)
    res2 = run_validation_pipeline(phase2)
    res3 = run_mode_resolution_pipeline(phase3)

    print(json.dumps({'phase1_output_dir': str(Path(phase1['output_dir']).resolve()), 'phase2': res2, 'phase3': res3, 'workspace': ws}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
