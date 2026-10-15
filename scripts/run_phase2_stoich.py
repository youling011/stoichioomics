
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.analysis_engine.phase2.runner_core import run_phase2_stoich_pipeline


def main():
    p = argparse.ArgumentParser(description='Run generalized phase4 phase2 stoich analysis')
    p.add_argument('--config', required=True)
    args = p.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
    result = run_phase2_stoich_pipeline(cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
