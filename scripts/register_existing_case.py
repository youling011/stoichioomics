from __future__ import annotations
from pathlib import Path
import argparse, json, sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from backend.portal.library import register_case


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-dir', required=True)
    ap.add_argument('--label', default=None)
    ap.add_argument('--source', default='manual')
    ap.add_argument('--tags', default='')
    args = ap.parse_args()
    res = register_case(PROJECT_ROOT, args.base_dir, label=args.label, source=args.source, tags=[t.strip() for t in args.tags.split(',') if t.strip()])
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
