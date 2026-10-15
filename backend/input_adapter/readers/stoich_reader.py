from __future__ import annotations
from pathlib import Path
import pandas as pd
from ..normalize import normalize_var_columns, coerce_numeric_columns

CORE_NUMERIC = ['gc_content','length_nt','nt_entropy','at_skew','gc_skew','c_per_nt','n_per_nt','p_per_nt']


def read_stoich_table(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    sep = '	' if path.suffix.lower() in {'.tsv', '.txt'} else ','
    df = pd.read_csv(path, sep=sep)
    df = normalize_var_columns(df)
    df = coerce_numeric_columns(df, CORE_NUMERIC)
    return df
