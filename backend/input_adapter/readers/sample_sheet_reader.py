from __future__ import annotations
from pathlib import Path
import pandas as pd

REQUIRED_MULTI_COLUMNS = {
    "h5ad_multi": ["file_name", "sample_id"],
    "tenx_multi": ["sample_id"],
}


def read_sample_sheet(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    sep = '	' if path.suffix.lower() in {'.tsv', '.txt'} else ','
    df = pd.read_csv(path, sep=sep)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def validate_sample_sheet(df: pd.DataFrame, fmt: str) -> None:
    required = REQUIRED_MULTI_COLUMNS.get(fmt, [])
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f'Sample sheet missing required columns for {fmt}: {missing}')
