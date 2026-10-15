from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.workspace import prepare_workspace


def main():
    p = argparse.ArgumentParser(description='Initialize workspace/job directory tree for HVG generalized framework')
    p.add_argument('--config', required=True, help='YAML config path containing at least case_id and workspace section')
    args = p.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
    ws = prepare_workspace(cfg.get('input_adapter', cfg))
    print(json.dumps(ws, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
