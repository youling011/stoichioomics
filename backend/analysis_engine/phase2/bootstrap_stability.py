from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def bootstrap_feature_stability(
    df: pd.DataFrame,
    feature_columns: List[str],
    target_col: str,
    random_state: int = 42,
    n_bootstrap: int = 40,
) -> pd.DataFrame:
    cols = [c for c in feature_columns if c in df.columns]
    if not cols or target_col not in df.columns:
        return pd.DataFrame(columns=["feature", "selection_frequency", "mean_abs_importance", "bootstrap_repeats"])
    y = pd.to_numeric(df[target_col], errors="coerce")
    valid = y.notna()
    if int(valid.sum()) < 8:
        return pd.DataFrame(columns=["feature", "selection_frequency", "mean_abs_importance", "bootstrap_repeats"])
    X = df.loc[valid, cols].copy()
    yv = y.loc[valid].copy()
    rng = np.random.default_rng(random_state)
    repeats = min(max(int(n_bootstrap), 5), 100)
    importance = {c: [] for c in cols}
    selected = {c: 0 for c in cols}
    for _ in range(repeats):
        idx = rng.integers(0, X.shape[0], size=X.shape[0])
        pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", Ridge(alpha=1.0)),
        ])
        try:
            pipe.fit(X.iloc[idx], yv.iloc[idx])
            coef = np.abs(np.asarray(pipe.named_steps["model"].coef_).reshape(-1))
        except Exception:
            rf = Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("model", RandomForestRegressor(n_estimators=80, min_samples_leaf=2, random_state=random_state)),
            ])
            rf.fit(X.iloc[idx], yv.iloc[idx])
            coef = np.abs(np.asarray(rf.named_steps["model"].feature_importances_).reshape(-1))
        if coef.shape[0] != len(cols):
            coef = np.resize(coef, len(cols))
        threshold = np.nanquantile(coef, 0.75) if np.isfinite(coef).any() else 0.0
        for col, value in zip(cols, coef):
            val = float(value) if np.isfinite(value) else 0.0
            importance[col].append(val)
            if val >= threshold and val > 0:
                selected[col] += 1
    out = pd.DataFrame({
        "feature": cols,
        "selection_frequency": [selected[c] / repeats for c in cols],
        "mean_abs_importance": [float(np.mean(importance[c])) for c in cols],
        "bootstrap_repeats": repeats,
    })
    return out.sort_values(["selection_frequency", "mean_abs_importance", "feature"], ascending=[False, False, True]).reset_index(drop=True)
