from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import ElasticNet, LinearRegression, LogisticRegression, Ridge
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    f1_score,
    mean_absolute_error,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import KFold, StratifiedKFold, cross_validate
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .model_prep import (
    build_signal_from_raw,
    compute_cost_index,
    fit_closeness,
    safe_fraction,
    zscore_series,
)
from .schemas import ModelArtifacts


@dataclass
class _FitResult:
    model_type: str
    task_type: str
    feature_columns: List[str]
    valid_mask: pd.Series
    y_valid: pd.Series
    pred_valid: np.ndarray
    pred_prob_valid: np.ndarray | None
    train_metrics: Dict[str, Any]
    cv_metrics: Dict[str, Any]
    feature_importance: pd.DataFrame
    permutation_importance: pd.DataFrame
    row_associated_feature: pd.Series


def _normalize_model_type(task_type: str, model_type: str) -> str:
    m = (model_type or '').strip().lower()
    if task_type == 'classification':
        if m in {'logistic', 'logistic_regression'}:
            return 'logistic'
        if m in {'elasticnet_logistic', 'logistic_elasticnet', 'elasticnet'}:
            return 'elasticnet_logistic'
        if m in {'rf', 'random_forest', 'balanced_random_forest'}:
            return 'random_forest'
        if m in {'gb', 'gradient_boosting', 'gbrt'}:
            return 'gradient_boosting'
        return 'logistic'
    if m in {'linear', 'linear_regression'}:
        return 'linear'
    if m in {'ridge'}:
        return 'ridge'
    if m in {'elasticnet', 'elastic_net'}:
        return 'elasticnet'
    if m in {'rf', 'random_forest'}:
        return 'random_forest'
    if m in {'gb', 'gradient_boosting', 'gbrt'}:
        return 'gradient_boosting'
    return 'ridge'


def _build_estimator(task_type: str, model_type: str, ridge_alpha: float, random_state: int) -> Pipeline:
    model_type = _normalize_model_type(task_type, model_type)
    if task_type == 'classification':
        if model_type == 'logistic':
            model = LogisticRegression(
                solver='liblinear',
                max_iter=2000,
                class_weight='balanced',
                random_state=random_state,
            )
        elif model_type == 'elasticnet_logistic':
            model = LogisticRegression(
                solver='saga',
                max_iter=3000,
                penalty='elasticnet',
                l1_ratio=0.5,
                C=max(1e-6, 1.0 / max(float(ridge_alpha), 1e-6)),
                class_weight='balanced',
                random_state=random_state,
            )
        elif model_type == 'random_forest':
            model = RandomForestClassifier(
                n_estimators=300,
                min_samples_leaf=2,
                class_weight='balanced_subsample',
                random_state=random_state,
                n_jobs=None,
            )
        elif model_type == 'gradient_boosting':
            model = GradientBoostingClassifier(random_state=random_state)
        else:
            raise ValueError(f'Unsupported classification model_type: {model_type}')
    else:
        if model_type == 'linear':
            model = LinearRegression()
        elif model_type == 'ridge':
            model = Ridge(alpha=float(ridge_alpha), random_state=random_state)
        elif model_type == 'elasticnet':
            model = ElasticNet(alpha=max(1e-6, float(ridge_alpha)), l1_ratio=0.5, random_state=random_state, max_iter=5000)
        elif model_type == 'random_forest':
            model = RandomForestRegressor(
                n_estimators=300,
                min_samples_leaf=2,
                random_state=random_state,
                n_jobs=None,
            )
        elif model_type == 'gradient_boosting':
            model = GradientBoostingRegressor(random_state=random_state)
        else:
            raise ValueError(f'Unsupported regression model_type: {model_type}')
    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('scaler', StandardScaler()),
        ('model', model),
    ])


def _metric_dict(task_type: str, y_true: pd.Series, y_pred: np.ndarray, y_prob: np.ndarray | None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if task_type == 'classification':
        yt = y_true.astype(int).to_numpy()
        yp = np.asarray(y_pred).astype(int)
        score = np.asarray(y_prob) if y_prob is not None else np.asarray(y_pred).astype(np.float64)
        out['in_sample_balanced_accuracy'] = float(balanced_accuracy_score(yt, yp))
        out['in_sample_f1'] = float(f1_score(yt, yp, zero_division=0))
        try:
            out['in_sample_roc_auc'] = float(roc_auc_score(yt, score))
        except Exception:
            out['in_sample_roc_auc'] = None
        try:
            out['in_sample_pr_auc'] = float(average_precision_score(yt, score))
        except Exception:
            out['in_sample_pr_auc'] = None
        return out

    out['in_sample_r2'] = float(r2_score(y_true, y_pred))
    out['in_sample_mae'] = float(mean_absolute_error(y_true, y_pred))
    return out


def _run_cv(
    pipe: Pipeline,
    X_valid: pd.DataFrame,
    y_valid: pd.Series,
    task_type: str,
    n_cv_folds: int,
    random_state: int,
) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {'cv_n_splits': 0}
    if task_type == 'classification':
        y_int = y_valid.astype(int)
        class_counts = y_int.value_counts()
        if class_counts.shape[0] < 2:
            return metrics
        max_splits = int(class_counts.min())
        n_splits = min(int(n_cv_folds), max(2, max_splits))
        if len(y_valid) < 8 or n_splits < 2:
            return metrics
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
        scoring = {
            'roc_auc': 'roc_auc',
            'pr_auc': 'average_precision',
            'balanced_accuracy': 'balanced_accuracy',
            'f1': 'f1',
        }
    else:
        n_splits = min(int(n_cv_folds), max(2, int(len(y_valid) // 2)))
        if len(y_valid) < max(6, n_splits):
            return metrics
        cv = KFold(n_splits=n_splits, shuffle=True, random_state=random_state)
        scoring = {'r2': 'r2', 'mae': 'neg_mean_absolute_error'}

    try:
        cv_scores = cross_validate(
            pipe,
            X_valid,
            y_valid,
            scoring=scoring,
            cv=cv,
            n_jobs=None,
            error_score='raise',
        )
    except Exception:
        return metrics

    metrics['cv_n_splits'] = int(n_splits)
    for key, values in cv_scores.items():
        if not key.startswith('test_'):
            continue
        metric = key.replace('test_', '')
        vals = np.asarray(values, dtype=np.float64)
        if metric == 'mae':
            vals = -vals
        metrics[f'cv_{metric}_mean'] = float(np.mean(vals))
        metrics[f'cv_{metric}_std'] = float(np.std(vals))
    return metrics


def _extract_feature_importance(pipe: Pipeline, feature_columns: List[str]) -> pd.DataFrame:
    model = pipe.named_steps['model']
    if hasattr(model, 'coef_'):
        coef = np.asarray(model.coef_).reshape(-1)
        if coef.shape[0] != len(feature_columns):
            coef = np.resize(coef, len(feature_columns))
        fi = pd.DataFrame({
            'feature': feature_columns,
            'coefficient': coef,
            'abs_coefficient': np.abs(coef),
        })
        return fi.sort_values(['abs_coefficient', 'feature'], ascending=[False, True]).reset_index(drop=True)
    if hasattr(model, 'feature_importances_'):
        imp = np.asarray(model.feature_importances_, dtype=np.float64).reshape(-1)
        if imp.shape[0] != len(feature_columns):
            imp = np.resize(imp, len(feature_columns))
        fi = pd.DataFrame({
            'feature': feature_columns,
            'importance': imp,
            'abs_coefficient': np.abs(imp),
        })
        return fi.sort_values(['importance', 'feature'], ascending=[False, True]).reset_index(drop=True)
    return pd.DataFrame({'feature': feature_columns, 'importance': np.zeros(len(feature_columns), dtype=np.float64)})


def _extract_row_associated_feature(pipe: Pipeline, X_valid: pd.DataFrame, feature_columns: List[str]) -> pd.Series:
    X_imp = pipe.named_steps['imputer'].transform(X_valid)
    X_scaled = pipe.named_steps['scaler'].transform(X_imp)
    model = pipe.named_steps['model']
    if hasattr(model, 'coef_'):
        coef = np.asarray(model.coef_).reshape(-1)
        if coef.shape[0] != len(feature_columns):
            coef = np.resize(coef, len(feature_columns))
        contrib = np.abs(X_scaled * coef.reshape(1, -1))
    elif hasattr(model, 'feature_importances_'):
        imp = np.asarray(model.feature_importances_, dtype=np.float64).reshape(-1)
        if imp.shape[0] != len(feature_columns):
            imp = np.resize(imp, len(feature_columns))
        contrib = np.abs(X_scaled) * imp.reshape(1, -1)
    else:
        contrib = np.abs(X_scaled)
    contrib_df = pd.DataFrame(contrib, columns=feature_columns, index=X_valid.index)
    return contrib_df.idxmax(axis=1)


def _extract_permutation_importance(
    pipe: Pipeline,
    X_valid: pd.DataFrame,
    y_valid: pd.Series,
    task_type: str,
    random_state: int,
    permutation_repeats: int,
) -> pd.DataFrame:
    if len(y_valid) < 20 or permutation_repeats <= 0:
        return pd.DataFrame(columns=['feature', 'importance_mean', 'importance_std'])
    scoring = 'r2' if task_type == 'regression' else 'roc_auc'
    try:
        result = permutation_importance(
            pipe,
            X_valid,
            y_valid,
            scoring=scoring,
            n_repeats=permutation_repeats,
            random_state=random_state,
            n_jobs=None,
        )
        return pd.DataFrame({
            'feature': X_valid.columns.tolist(),
            'importance_mean': result.importances_mean,
            'importance_std': result.importances_std,
        }).sort_values('importance_mean', ascending=False).reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=['feature', 'importance_mean', 'importance_std'])


def _fit_model(
    df: pd.DataFrame,
    feature_columns: List[str],
    y: pd.Series,
    task_type: str,
    model_type: str,
    ridge_alpha: float,
    n_cv_folds: int,
    random_state: int,
    permutation_repeats: int,
) -> _FitResult:
    valid_mask = y.notna()
    if task_type == 'classification':
        y = y.astype('float64')
    min_rows = 4 if task_type == 'classification' else 2
    if int(valid_mask.sum()) < min_rows:
        raise ValueError(f'Too few valid rows for phase2 modeling ({valid_mask.sum()} < {min_rows}).')
    X_valid = df.loc[valid_mask, feature_columns].copy()
    y_valid = y.loc[valid_mask].copy()
    if task_type == 'classification':
        y_valid = y_valid.astype(int)
        if y_valid.nunique() < 2:
            raise ValueError('HVG label contains fewer than two classes; classification is not possible.')

    normalized_type = _normalize_model_type(task_type, model_type)
    pipe = _build_estimator(task_type, normalized_type, ridge_alpha=ridge_alpha, random_state=random_state)
    cv_metrics = _run_cv(pipe, X_valid, y_valid, task_type, n_cv_folds, random_state)
    pipe.fit(X_valid, y_valid)
    pred = pipe.predict(X_valid)
    if task_type == 'classification':
        model = pipe.named_steps['model']
        if hasattr(model, 'predict_proba'):
            pred_prob = pipe.predict_proba(X_valid)[:, 1]
        elif hasattr(model, 'decision_function'):
            decision = np.asarray(pipe.decision_function(X_valid), dtype=np.float64)
            lo, hi = np.nanmin(decision), np.nanmax(decision)
            if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                pred_prob = (decision - lo) / (hi - lo)
            else:
                pred_prob = np.full(decision.shape[0], 0.5, dtype=np.float64)
        else:
            pred_prob = pred.astype(np.float64)
    else:
        pred_prob = None

    in_sample = _metric_dict(task_type, y_valid, pred, pred_prob)
    feature_importance = _extract_feature_importance(pipe, feature_columns)
    row_associated_feature = _extract_row_associated_feature(pipe, X_valid, feature_columns)
    perm = _extract_permutation_importance(
        pipe,
        X_valid,
        y_valid,
        task_type=task_type,
        random_state=random_state,
        permutation_repeats=int(permutation_repeats),
    )
    return _FitResult(
        model_type=normalized_type,
        task_type=task_type,
        feature_columns=feature_columns,
        valid_mask=valid_mask,
        y_valid=y_valid,
        pred_valid=np.asarray(pred, dtype=np.float64),
        pred_prob_valid=np.asarray(pred_prob, dtype=np.float64) if pred_prob is not None else None,
        train_metrics=in_sample,
        cv_metrics=cv_metrics,
        feature_importance=feature_importance,
        permutation_importance=perm,
        row_associated_feature=row_associated_feature,
    )


def _delta_metrics(task_type: str, baseline: Dict[str, Any], augmented: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if task_type == 'classification':
        for metric in ['roc_auc', 'pr_auc', 'balanced_accuracy', 'f1']:
            b = baseline.get(f'cv_{metric}_mean')
            a = augmented.get(f'cv_{metric}_mean')
            out[f'delta_cv_{metric}'] = (float(a) - float(b)) if (b is not None and a is not None) else None
    else:
        b = baseline.get('cv_r2_mean')
        a = augmented.get('cv_r2_mean')
        out['delta_cv_r2'] = (float(a) - float(b)) if (b is not None and a is not None) else None
        b_mae = baseline.get('cv_mae_mean')
        a_mae = augmented.get('cv_mae_mean')
        out['delta_cv_mae'] = (float(a_mae) - float(b_mae)) if (b_mae is not None and a_mae is not None) else None
    return out


def _model_confidence(task_type: str, delta: Dict[str, Any]) -> str:
    if task_type == 'classification':
        auc_delta = delta.get('delta_cv_roc_auc')
        if auc_delta is None:
            return 'exploratory_hypothesis'
        if auc_delta >= 0.08:
            return 'predictive_strong'
        if auc_delta >= 0.03:
            return 'predictive_moderate'
        if auc_delta >= 0.01:
            return 'predictive_weak'
        return 'descriptive_only'
    r2_delta = delta.get('delta_cv_r2')
    if r2_delta is None:
        return 'exploratory_hypothesis'
    if r2_delta >= 0.12:
        return 'predictive_strong'
    if r2_delta >= 0.05:
        return 'predictive_moderate'
    if r2_delta >= 0.01:
        return 'predictive_weak'
    return 'descriptive_only'


def fit_stoich_model(
    df: pd.DataFrame,
    feature_columns: List[str],
    target_col: str = 'normalized_dispersion',
    hvg_flag_col: str = 'is_hvg',
    model_type: str = 'ridge',
    ridge_alpha: float = 1.0,
    n_cv_folds: int = 5,
    random_state: int = 42,
    hvg_target_type: str = 'score',
    confounder_columns: List[str] | None = None,
    permutation_repeats: int = 8,
) -> Tuple[pd.DataFrame, ModelArtifacts]:
    target_mode = (hvg_target_type or 'score').strip().lower()
    if target_mode in {'label', 'classification', 'binary'}:
        task_type = 'classification'
    elif target_mode in {'auto'}:
        task_type = 'classification' if model_type.lower() in {'logistic', 'elasticnet_logistic'} else 'regression'
    else:
        task_type = 'regression'

    confounder_columns = list(dict.fromkeys([c for c in (confounder_columns or []) if c in df.columns]))
    stoich_columns = list(dict.fromkeys([c for c in feature_columns if c in df.columns]))
    if not stoich_columns:
        raise ValueError('No stoichiometric features available for modeling.')
    baseline_features = confounder_columns if confounder_columns else ['mean_expr'] if 'mean_expr' in df.columns else [stoich_columns[0]]
    augmented_features = list(dict.fromkeys(baseline_features + stoich_columns))

    if task_type == 'classification':
        if hvg_flag_col not in df.columns:
            raise ValueError(f'hvg_flag_col not found for classification target: {hvg_flag_col}')
        y = df[hvg_flag_col].fillna(False).astype(bool).astype(int)
    else:
        if target_col not in df.columns:
            raise ValueError(f'target_col not found for regression target: {target_col}')
        y = pd.to_numeric(df[target_col], errors='coerce')

    base_fit = _fit_model(
        df=df,
        feature_columns=baseline_features,
        y=y,
        task_type=task_type,
        model_type='logistic' if task_type == 'classification' else 'ridge',
        ridge_alpha=ridge_alpha,
        n_cv_folds=n_cv_folds,
        random_state=random_state,
        permutation_repeats=max(3, int(permutation_repeats) // 2),
    )
    aug_fit = _fit_model(
        df=df,
        feature_columns=augmented_features,
        y=y,
        task_type=task_type,
        model_type=model_type,
        ridge_alpha=ridge_alpha,
        n_cv_folds=n_cv_folds,
        random_state=random_state,
        permutation_repeats=permutation_repeats,
    )

    out = df.copy()
    out['model_task_type'] = task_type
    out['hvg_target_type'] = 'label' if task_type == 'classification' else 'score'
    out['observed_target_raw'] = np.nan
    out.loc[aug_fit.valid_mask, 'observed_target_raw'] = aug_fit.y_valid
    out['stoich_expected_raw'] = np.nan
    out.loc[aug_fit.valid_mask, 'stoich_expected_raw'] = aug_fit.pred_valid

    if task_type == 'classification':
        expected_signal = pd.Series(aug_fit.pred_prob_valid, index=aug_fit.y_valid.index, dtype=np.float64)
        observed_signal = pd.Series(aug_fit.y_valid.astype(float), index=aug_fit.y_valid.index)
    else:
        observed_signal, shift = build_signal_from_raw(aug_fit.y_valid)
        expected_signal = (pd.Series(aug_fit.pred_valid, index=aug_fit.y_valid.index) + shift).clip(lower=0.0)

    out['observed_hvg_signal'] = np.nan
    out.loc[aug_fit.valid_mask, 'observed_hvg_signal'] = observed_signal
    out['stoich_expected_var'] = np.nan
    out.loc[aug_fit.valid_mask, 'stoich_expected_var'] = expected_signal
    out['stoich_excess_var'] = np.nan
    out.loc[aug_fit.valid_mask, 'stoich_excess_var'] = observed_signal - expected_signal
    out['stoich_explained_fraction'] = np.nan
    out.loc[aug_fit.valid_mask, 'stoich_explained_fraction'] = safe_fraction(expected_signal, observed_signal.clip(lower=1e-6))
    out['stoich_fit_closeness'] = np.nan
    out.loc[aug_fit.valid_mask, 'stoich_fit_closeness'] = fit_closeness(observed_signal, expected_signal)
    out['cost_index'] = compute_cost_index(out)
    out['cost_volatility_index'] = zscore_series(out['cost_index']) + zscore_series(out['observed_hvg_signal'])
    out['stoich_associated_feature'] = None
    out.loc[aug_fit.valid_mask, 'stoich_associated_feature'] = aug_fit.row_associated_feature.astype(str)

    baseline_metrics = {
        'task_type': task_type,
        'model_type': base_fit.model_type,
        **base_fit.train_metrics,
        **base_fit.cv_metrics,
    }
    model_metrics = {
        'task_type': task_type,
        'model_type': aug_fit.model_type,
        'ridge_alpha': float(ridge_alpha),
        **aug_fit.train_metrics,
        **aug_fit.cv_metrics,
    }
    delta = _delta_metrics(task_type, baseline_metrics, model_metrics)
    confidence = _model_confidence(task_type, delta)

    model_metrics['predictive_confidence'] = confidence
    model_metrics['target_col'] = target_col if task_type == 'regression' else None
    model_metrics['target_label_col'] = hvg_flag_col if task_type == 'classification' else None

    numeric_summary = {
        'n_rows_total': int(df.shape[0]),
        'n_modeled_rows': int(aug_fit.valid_mask.sum()),
        'n_stoich_features': int(len(stoich_columns)),
        'n_baseline_features': int(len(baseline_features)),
        'n_augmented_features': int(len(augmented_features)),
    }
    if task_type == 'regression':
        numeric_summary['target_raw_min'] = float(np.nanmin(aug_fit.y_valid.to_numpy()))
        numeric_summary['target_raw_max'] = float(np.nanmax(aug_fit.y_valid.to_numpy()))
    else:
        numeric_summary['n_hvg_positive'] = int(aug_fit.y_valid.sum())
        numeric_summary['n_hvg_negative'] = int((1 - aug_fit.y_valid).sum())

    corr = out[stoich_columns].corr(method='spearman').replace([np.inf, -np.inf], np.nan)
    high_corr_pairs = []
    for i, col_i in enumerate(stoich_columns):
        for j in range(i + 1, len(stoich_columns)):
            col_j = stoich_columns[j]
            v = corr.iloc[i, j]
            if pd.notna(v) and abs(float(v)) >= 0.85:
                high_corr_pairs.append({'feature_a': col_i, 'feature_b': col_j, 'spearman_r': float(v)})
    high_corr_pairs = sorted(high_corr_pairs, key=lambda x: abs(x['spearman_r']), reverse=True)[:40]

    artifacts = ModelArtifacts(
        feature_columns=stoich_columns,
        confounder_columns=confounder_columns,
        baseline_feature_columns=baseline_features,
        augmented_feature_columns=augmented_features,
        numeric_summary=numeric_summary,
        model_metrics=model_metrics,
        baseline_metrics=baseline_metrics,
        delta_metrics=delta,
        feature_importance=aug_fit.feature_importance.to_dict(orient='records'),
        permutation_importance=aug_fit.permutation_importance.to_dict(orient='records'),
        model_diagnostics={
            'predictive_confidence': confidence,
            'evidence_scope': 'cross_validated_non_causal_association',
            'high_collinearity_pairs': high_corr_pairs,
            'high_collinearity_pair_count': len(high_corr_pairs),
        },
    )
    return out, artifacts
