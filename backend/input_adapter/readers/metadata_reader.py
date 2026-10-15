from __future__ import annotations
from pathlib import Path
import pandas as pd
from ..normalize import normalize_obs_columns


def read_metadata(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    sep = '	' if path.suffix.lower() in {'.tsv', '.txt'} else ','
    df = pd.read_csv(path, sep=sep)
    return normalize_obs_columns(df)
