from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd


def _model_metric(model_comparison: pd.DataFrame, model_id: str, legacy_model_id: str, metric: str) -> pd.Series:
    values = model_comparison.loc[model_comparison["model_id"] == model_id, metric]
    if values.empty:
        values = model_comparison.loc[model_comparison["model_id"] == legacy_model_id, metric]
    return values


def build_negative_control_report(model_comparison: pd.DataFrame, config: Dict[str, Any]) -> Dict[str, Any]:
    if model_comparison.empty:
        return {"status": "skipped", "reason": "model_comparison_unavailable"}
    metric = "r2" if "r2" in model_comparison.columns else "roc_auc" if "roc_auc" in model_comparison.columns else None
    if metric is None:
        return {"status": "skipped", "reason": "no_supported_metric"}
    m0 = _model_metric(model_comparison, "Generic-M0", "M0", metric)
    m1 = _model_metric(model_comparison, "Generic-M1_confounders", "M1_confounders", metric)
    m2 = _model_metric(model_comparison, "Generic-M2_confounders_plus_stoich", "M2_confounders_plus_stoich", metric)
    observed_delta = float(m2.iloc[0] - m1.iloc[0]) if not m1.empty and not m2.empty and pd.notna(m1.iloc[0]) and pd.notna(m2.iloc[0]) else None
    return {
        "status": "success",
        "metric": metric,
        "m0_score": float(m0.iloc[0]) if not m0.empty and pd.notna(m0.iloc[0]) else None,
        "m1_score": float(m1.iloc[0]) if not m1.empty and pd.notna(m1.iloc[0]) else None,
        "m2_score": float(m2.iloc[0]) if not m2.empty and pd.notna(m2.iloc[0]) else None,
        "observed_delta_m2_vs_m1": observed_delta,
        "interpretation": (
            "stoich_features_add_predictive_signal"
            if observed_delta is not None and observed_delta > float(config.get("minimum_effect_delta", 0.01))
            else "no_clear_stoich_increment"
        ),
    }


def build_permutation_assessment(model_comparison: pd.DataFrame, config: Dict[str, Any]) -> Dict[str, Any]:
    report = build_negative_control_report(model_comparison, config)
    if model_comparison.empty or "permutation_p_value" not in model_comparison.columns:
        report.update({
            "permutation_status": "not_available",
            "effective_permutation_repeats": 0,
            "empirical_p_value": None,
            "interpretation_limit": "No target-permutation refit result was produced by model comparison.",
        })
        return report
    status = model_comparison["permutation_status"] if "permutation_status" in model_comparison.columns else pd.Series("", index=model_comparison.index)
    tested = model_comparison.loc[
        model_comparison["permutation_p_value"].notna()
        & (status == "target_permutation_refit")
    ].copy()
    if tested.empty:
        report.update({
            "permutation_status": "skipped",
            "effective_permutation_repeats": 0,
            "empirical_p_value": None,
            "interpretation_limit": "Target-permutation refit was skipped for all tested models.",
        })
        return report
    primary = tested.sort_values("permutation_p_value").iloc[0]
    repeats = int(primary.get("permutation_repeats") or 0)
    report.update({
        "permutation_status": "target_permutation_refit",
        "tested_model_id": primary.get("model_id"),
        "effective_permutation_repeats": repeats,
        "empirical_p_value": float(primary["permutation_p_value"]),
        "minimum_resolvable_p_value": float(1.0 / (repeats + 1.0)) if repeats > 0 else None,
        "interpretation_limit": "Non-causal predictive association; p-value is empirical from target permutation with full model refitting.",
    })
    return report
