
from __future__ import annotations
import numpy as np
import pandas as pd


def coerce_numeric(df: pd.DataFrame, columns):
    out = df.copy()
    for c in columns:
        out[c] = pd.to_numeric(out[c], errors='coerce')
    return out


def winsorize_df(df: pd.DataFrame, columns, q: float = 0.01):
    out = df.copy()
    q = float(q)
    if q <= 0:
        return out
    for c in columns:
        s = pd.to_numeric(out[c], errors='coerce')
        lo = s.quantile(q)
        hi = s.quantile(1.0 - q)
        out[c] = s.clip(lower=lo, upper=hi)
    return out


def compute_cost_index(df: pd.DataFrame) -> pd.Series:
    needed = ['length_nt', 'n_per_nt', 'p_per_nt']
    if any(c not in df.columns for c in needed):
        return pd.Series(np.nan, index=df.index, name='cost_index')
    parts = []
    for c in needed:
        s = pd.to_numeric(df[c], errors='coerce')
        mu, sd = s.mean(), s.std(ddof=0)
        z = pd.Series(0.0, index=df.index) if (not np.isfinite(sd) or sd == 0) else (s - mu) / sd
        parts.append(z)
    return (parts[0] + parts[1] + parts[2]).rename('cost_index')


def safe_fraction(numer: pd.Series, denom: pd.Series) -> pd.Series:
    numer = pd.to_numeric(numer, errors='coerce')
    denom = pd.to_numeric(denom, errors='coerce')
    out = numer / denom.replace(0, np.nan)
    out = out.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out.clip(lower=0.0, upper=1.0)


def fit_closeness(observed: pd.Series, expected: pd.Series) -> pd.Series:
    observed = pd.to_numeric(observed, errors='coerce').clip(lower=0.0)
    expected = pd.to_numeric(expected, errors='coerce').clip(lower=0.0)
    denom = observed + expected
    out = 1.0 - (observed - expected).abs() / denom.replace(0, np.nan)
    out = out.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out.clip(lower=0.0, upper=1.0)


def zscore_series(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors='coerce')
    mu, sd = s.mean(), s.std(ddof=0)
    if not np.isfinite(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


def build_signal_from_raw(raw: pd.Series):
    raw = pd.to_numeric(raw, errors='coerce')
    min_val = float(raw.min())
    shift = abs(min_val) + 1e-6 if min_val <= 0 else 0.0
    signal = (raw + shift).clip(lower=0.0)
    return signal, shift
