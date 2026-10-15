
from __future__ import annotations
from pathlib import Path
import json
import pandas as pd


def read_baseline_csv(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    sep = '	' if p.suffix.lower() in {'.tsv', '.txt'} else ','
    return pd.read_csv(p, sep=sep)


def read_json_if_exists(path: str | Path):
    p = Path(path)
    if not p.exists():
        return None
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json(obj, path: str | Path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
