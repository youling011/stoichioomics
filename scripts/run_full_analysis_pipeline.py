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
from backend.analysis_engine.phase1.runner_core import run_phase1_analysis_pipeline
from backend.analysis_engine.phase2.runner_core import run_phase2_stoich_pipeline
from backend.workspace import prepare_workspace


def main():
    p = argparse.ArgumentParser(description='Run integrated phases 1-4 full analysis pipeline')
    p.add_argument('--config', required=True, help='YAML config with sections input_adapter, validation, mode_resolution, phase1_analysis, phase2_stoich')
    args = p.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))

    p1 = cfg['input_adapter']
    p2 = cfg['validation']
    p3 = cfg['mode_resolution']
    p4a = cfg['phase1_analysis']
    p4b = cfg['phase2_stoich']

    ws = prepare_workspace(p1)
    if ws.get('enabled'):
        p1 = dict(p1); p2 = dict(p2); p3 = dict(p3); p4a = dict(p4a); p4b = dict(p4b)
        p1['output_dir'] = ws['paths']['standardized']
        p2['input_dir'] = ws['paths']['standardized']; p2['output_dir'] = ws['paths']['validation']
        if p1.get('stoich', {}).get('file'):
            p2['raw_stoich_file'] = str((Path(p1['input_dir']) / p1['stoich']['file']).resolve())
        p3['validation_dir'] = ws['paths']['validation']; p3['output_dir'] = ws['paths']['mode_resolution']
        p4a['standardized_input_dir'] = ws['paths']['standardized']; p4a['validation_dir'] = ws['paths']['validation']; p4a['mode_resolution_dir'] = ws['paths']['mode_resolution']; p4a['output_dir'] = ws['paths']['analysis_phase1']
        p4b['input_baseline_csv'] = str(Path(ws['paths']['analysis_phase1']) / 'hvg_baseline.csv')
        p4b['input_phase1_summary_json'] = str(Path(ws['paths']['analysis_phase1']) / 'phase1_mode_summary.json')
        p4b['output_dir'] = ws['paths']['analysis_phase2']

    ds, manifest, validation = build_internal_dataset(p1)
    export_standardized_dataset(ds, p1['output_dir'], manifest, validation, p1)
    r2 = run_validation_pipeline(p2)
    r3 = run_mode_resolution_pipeline(p3)
    r4 = run_phase1_analysis_pipeline(p4a)
    r5 = run_phase2_stoich_pipeline(p4b)

    print(json.dumps({'input_adapter_output': str(Path(p1['output_dir']).resolve()), 'validation': r2, 'mode_resolution': r3, 'phase1_analysis': r4, 'phase2_stoich': r5, 'workspace': ws}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
