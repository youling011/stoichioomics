from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.input_adapter.merge import build_internal_dataset, export_standardized_dataset
from backend.workspace import prepare_workspace


def main():
    p = argparse.ArgumentParser(description='Run generalized HVG input adapter phase 1')
    p.add_argument('--config', required=True, help='YAML config path')
    args = p.parse_args()

    cfg_path = Path(args.config)
    with open(cfg_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    ws = prepare_workspace(config)
    if ws.get('enabled'):
        config = dict(config)
        config['output_dir'] = ws['paths']['standardized']

    ds, manifest, validation = build_internal_dataset(config)
    export_standardized_dataset(ds, config['output_dir'], manifest, validation, config)
    print(f"[OK] standardized dataset written to {Path(config['output_dir']).resolve()}")
    print(json.dumps({
        'case_id': config.get('case_id'),
        'n_cells': int(ds.X.shape[0]),
        'n_genes': int(ds.X.shape[1]),
        'source_format': ds.source_format,
        'stoich_present': validation.get('stoich_present', False),
        'n_genes_overlap': validation.get('n_genes_overlap'),
        'workspace': ws,
    }, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
