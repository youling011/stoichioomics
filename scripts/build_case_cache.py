from __future__ import annotations
from pathlib import Path
import argparse, json, sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from backend.portal.cache import build_case_cache


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-dir', required=True)
    args = ap.parse_args()
    res = build_case_cache(args.base_dir)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
