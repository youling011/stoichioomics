from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet, LogisticRegression, Ridge
from sklearn.metrics import average_precision_score, balanced_accuracy_score, mean_absolute_error, r2_score, roc_auc_score
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def _task_and_target(df: pd.DataFrame, config: Dict[str, Any]) -> Tuple[str, pd.Series]:
    mode = str(config.get("hvg_target_type", "score")).lower()
    if mode in {"label", "classification", "binary"}:
        return "classification", df[config.get("hvg_flag_col", "is_hvg")].fillna(False).astype(bool).astype(int)
    return "regression", pd.to_numeric(df[config.get("target_col", "normalized_dispersion")], errors="coerce")


def _pipeline(task: str, model_name: str, random_state: int) -> Pipeline:
    if model_name == "M0":
        model = DummyClassifier(strategy="prior") if task == "classification" else DummyRegressor(strategy="mean")
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", model)])
    if task == "classification":
        if model_name == "M3":
            model = RandomForestClassifier(n_estimators=180, min_samples_leaf=2, class_weight="balanced_subsample", random_state=random_state)
            return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", model)])
        model = LogisticRegression(max_iter=2000, solver="liblinear", class_weight="balanced", random_state=random_state)
    else:
        if model_name == "M2":
            model = ElasticNet(alpha=0.05, l1_ratio=0.4, max_iter=5000, random_state=random_state)
        elif model_name == "M3":
            model = RandomForestRegressor(n_estimators=180, min_samples_leaf=2, random_state=random_state)
            return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", model)])
        else:
            model = Ridge(alpha=1.0)
    return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("model", model)])


def _generic_model_tier(model_id: str) -> str:
    return str(model_id).split("_", 1)[0].replace("Generic-", "")


def _metric_series(comparison: pd.DataFrame, metric: str, model_id: str, legacy_model_id: str) -> pd.Series:
    values = comparison.loc[comparison["model_id"] == model_id, metric]
    if values.empty:
        values = comparison.loc[comparison["model_id"] == legacy_model_id, metric]
    return values


def _metric_row(task: str, y_true: pd.Series, y_score: np.ndarray, y_pred: np.ndarray) -> Dict[str, Any]:
    if task == "classification":
        row = {"balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred))}
        try:
            row["roc_auc"] = float(roc_auc_score(y_true, y_score))
        except Exception:
            row["roc_auc"] = None
        try:
            row["pr_auc"] = float(average_precision_score(y_true, y_score))
        except Exception:
            row["pr_auc"] = None
        return row
    return {"r2": float(r2_score(y_true, y_score)), "mae": float(mean_absolute_error(y_true, y_score))}


def _primary_metric(task: str, metrics: Dict[str, Any]) -> float | None:
    key = "roc_auc" if task == "classification" else "r2"
    value = metrics.get(key)
    return float(value) if value is not None and np.isfinite(float(value)) else None


def _cv(task: str, y: pd.Series, n_folds: int, random_state: int):
    if task == "classification":
        counts = y.value_counts()
        if counts.shape[0] < 2 or int(counts.min()) < 2:
            return None
        splits = min(int(n_folds), int(counts.min()))
        return StratifiedKFold(n_splits=max(2, splits), shuffle=True, random_state=random_state)
    splits = min(int(n_folds), max(2, int(y.notna().sum() // 2)))
    return KFold(n_splits=max(2, splits), shuffle=True, random_state=random_state)


def _oof_metrics(
    pipe: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
    task: str,
    cv,
) -> Dict[str, Any]:
    oof_score = np.full(X.shape[0], np.nan, dtype=float)
    oof_pred = np.full(X.shape[0], np.nan, dtype=float)
    for train_idx, test_idx in cv.split(X, y):
        pipe.fit(X.iloc[train_idx], y.iloc[train_idx])
        if task == "classification":
            if hasattr(pipe, "predict_proba"):
                score = pipe.predict_proba(X.iloc[test_idx])[:, 1]
            else:
                score = pipe.predict(X.iloc[test_idx]).astype(float)
            pred = (score >= 0.5).astype(int)
        else:
            score = pipe.predict(X.iloc[test_idx]).astype(float)
            pred = score
        oof_score[test_idx] = score
        oof_pred[test_idx] = pred
    return _metric_row(task, y, oof_score, oof_pred)


def _target_permutation_p_value(
    task: str,
    model_name: str,
    X: pd.DataFrame,
    y: pd.Series,
    cv,
    observed_metric: float | None,
    repeats: int,
    random_state: int,
) -> tuple[float | None, int, str]:
    if observed_metric is None or repeats <= 0:
        return None, 0, "skipped"
    rng = np.random.default_rng(random_state)
    repeats = int(repeats)
    null_scores: list[float] = []
    for _ in range(repeats):
        y_perm = pd.Series(rng.permutation(y.to_numpy()), index=y.index)
        pipe = _pipeline(task, model_name, random_state)
        metric = _primary_metric(task, _oof_metrics(pipe, X, y_perm, task, cv))
        if metric is not None:
            null_scores.append(metric)
    if not null_scores:
        return None, 0, "failed"
    null = np.asarray(null_scores, dtype=float)
    p = (float((null >= float(observed_metric)).sum()) + 1.0) / (float(null.size) + 1.0)
    return float(p), int(null.size), "target_permutation_refit"


def _add_interactions(df: pd.DataFrame, confounders: List[str], features: List[str]) -> Tuple[pd.DataFrame, List[str]]:
    work = df.copy()
    interaction_cols = []
    anchor = "mean_expr" if "mean_expr" in confounders else (confounders[0] if confounders else None)
    if not anchor:
        return work, []
    for col in features[:4]:
        name = f"{col}__x__{anchor}"
        work[name] = pd.to_numeric(work[col], errors="coerce") * pd.to_numeric(work[anchor], errors="coerce")
        interaction_cols.append(name)
    return work, interaction_cols


def run_model_comparison(
    df: pd.DataFrame,
    stoich_features: List[str],
    confounders: List[str],
    config: Dict[str, Any],
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    task, y = _task_and_target(df, config)
    random_state = int(config.get("random_state", 42))
    n_folds = int(config.get("n_cv_folds", 5))
    permutation_repeats = int(config.get("permutation_test_repeats", config.get("permutation_repeats", 8)))
    valid = y.notna()
    if task == "classification":
        valid = valid & y.isin([0, 1])
    work = df.loc[valid].copy()
    yv = y.loc[valid].copy()
    if work.shape[0] < 6:
        empty = pd.DataFrame()
        return empty, empty, empty, {"status": "skipped", "reason": "too_few_rows", "task_type": task}

    conf = [c for c in confounders if c in work.columns]
    stoich = [c for c in stoich_features if c in work.columns]
    work, interaction_cols = _add_interactions(work, conf, stoich)
    specs = {
        "Generic-M0": [],
        "Generic-M1_confounders": conf,
        "Generic-M2_confounders_plus_stoich": list(dict.fromkeys(conf + stoich)),
        "Generic-M3_interactions_or_nonlinear": list(dict.fromkeys(conf + stoich + interaction_cols)),
    }
    cv = _cv(task, yv, n_folds, random_state)
    if cv is None:
        empty = pd.DataFrame()
        return empty, empty, empty, {"status": "skipped", "reason": "insufficient_target_variation", "task_type": task}

    metric_rows = []
    pred_rows = []
    block_rows = []
    for model_id, cols in specs.items():
        model_name = _generic_model_tier(model_id)
        pipe = _pipeline(task, model_name, random_state)
        X = work[cols].copy() if cols else pd.DataFrame({"intercept_only": np.ones(work.shape[0])}, index=work.index)
        oof_score = np.full(work.shape[0], np.nan, dtype=float)
        oof_pred = np.full(work.shape[0], np.nan, dtype=float)
        for fold, (train_idx, test_idx) in enumerate(cv.split(X, yv), start=1):
            pipe.fit(X.iloc[train_idx], yv.iloc[train_idx])
            if task == "classification":
                if hasattr(pipe, "predict_proba"):
                    score = pipe.predict_proba(X.iloc[test_idx])[:, 1]
                else:
                    score = pipe.predict(X.iloc[test_idx]).astype(float)
                pred = (score >= 0.5).astype(int)
            else:
                score = pipe.predict(X.iloc[test_idx]).astype(float)
                pred = score
            oof_score[test_idx] = score
            oof_pred[test_idx] = pred
            ids = work.iloc[test_idx].get("gene_id", pd.Series(work.index[test_idx], index=work.index[test_idx])).astype(str).tolist()
            pred_rows.extend([
                {"model_id": model_id, "fold": fold, "gene_id": gene_id, "observed": float(obs), "prediction": float(sc)}
                for gene_id, obs, sc in zip(ids, yv.iloc[test_idx].to_numpy(), score)
            ])
        metrics = _metric_row(task, yv, oof_score, oof_pred)
        observed_primary = _primary_metric(task, metrics)
        permutation_p, effective_repeats, permutation_status = _target_permutation_p_value(
            task=task,
            model_name=model_name,
            X=X,
            y=yv,
            cv=cv,
            observed_metric=observed_primary,
            repeats=permutation_repeats if model_id in {"Generic-M2_confounders_plus_stoich", "Generic-M3_interactions_or_nonlinear"} else 0,
            random_state=random_state + len(metric_rows) + 101,
        )
        metric_rows.append({
            "model_id": model_id,
            "task_type": task,
            "feature_block": "intercept_only" if not cols else ("confounders" if model_id.startswith("Generic-M1") else "stoich_augmented"),
            "n_features": int(len(cols)),
            "n_rows": int(work.shape[0]),
            "permutation_status": permutation_status,
            "permutation_repeats": effective_repeats,
            "permutation_p_value": permutation_p,
            **metrics,
        })
        block_rows.append({
            "model_id": model_id,
            "confounder_feature_count": int(len([c for c in cols if c in conf])),
            "stoich_feature_count": int(len([c for c in cols if c in stoich])),
            "interaction_feature_count": int(len([c for c in cols if c in interaction_cols])),
            "feature_columns": "|".join(cols),
        })

    comparison = pd.DataFrame(metric_rows)
    predictions = pd.DataFrame(pred_rows)
    block_importance = pd.DataFrame(block_rows)
    assessment = {"status": "success", "task_type": task, "model_count": int(comparison.shape[0])}
    if task == "regression" and "r2" in comparison:
        m1 = _metric_series(comparison, "r2", "Generic-M1_confounders", "M1_confounders")
        m2 = _metric_series(comparison, "r2", "Generic-M2_confounders_plus_stoich", "M2_confounders_plus_stoich")
        assessment["delta_m2_vs_m1_r2"] = float(m2.iloc[0] - m1.iloc[0]) if not m1.empty and not m2.empty else None
    if task == "classification" and "roc_auc" in comparison:
        m1 = _metric_series(comparison, "roc_auc", "Generic-M1_confounders", "M1_confounders")
        m2 = _metric_series(comparison, "roc_auc", "Generic-M2_confounders_plus_stoich", "M2_confounders_plus_stoich")
        assessment["delta_m2_vs_m1_roc_auc"] = float(m2.iloc[0] - m1.iloc[0]) if not m1.empty and not m2.empty else None
    return comparison, predictions, block_importance, assessment
