from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.validation.runner_core import run_validation_pipeline


def main():
    p = argparse.ArgumentParser(description='Run generalized HVG input validation phase 2')
    p.add_argument('--config', required=True, help='YAML config path')
    args = p.parse_args()

    cfg_path = Path(args.config)
    with open(cfg_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    result = run_validation_pipeline(config)
    print(f"[OK] validation outputs written to {result['output_dir']}")
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
