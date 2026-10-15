from __future__ import annotations

import json
import warnings
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from patsy import dmatrix

from .associations import _benjamini_hochberg
from .comparison_qc import coerce_hvg_mask
from .comparison_schema import ADJUSTED_COLUMNS, empty_frame


POLICY_VERSION = "adjustment_policy_v2"
CLR_VERSION = "clr_v1"
DEFAULT_PSEUDOCOUNT = 1e-6


def _first_present(df: pd.DataFrame, names: list[str], excluded: str = "") -> str:
    excluded_key = str(excluded).casefold()
    for name in names:
        if name in df.columns and str(name).casefold() != excluded_key:
            return name
    return ""


def _namespaced(omics: str, names: list[str]) -> list[str]:
    prefixes = {
        "genome": ("genome__", "genome_"),
        "transcriptome": ("transcriptome__", "transcriptome_", "transcript_"),
        "proteome": ("proteome__", "proteome_", "protein_"),
    }.get(str(omics).lower(), ())
    return [candidate for name in names for candidate in [name, *[prefix + name for prefix in prefixes]]]


def _zscore(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    std = float(numeric.std(ddof=0))
    if not np.isfinite(std) or std <= 1e-12:
        return pd.Series(np.nan, index=series.index, dtype=float)
    return (numeric - float(numeric.mean())) / std


def _target_length_candidates(feature: dict[str, Any]) -> list[str]:
    omics = str(feature.get("omics_layer") or "").lower()
    name = str(feature.get("feature_name") or "").lower()
    if omics == "genome":
        if "promoter" in name:
            return ["promoter_length_bp", "promoter_length_acgt_bp", "locus_length_bp", "locus_length_acgt_bp"]
        if "exon" in name:
            return ["exon_length_bp", "exon_length_acgt_bp", "locus_length_bp", "locus_length_acgt_bp"]
        if any(token in name for token in ("cds", "codon", "gc1", "gc2", "gc3", "aa_")):
            return ["cds_length_bp", "locus_length_bp", "locus_length_acgt_bp"]
        return ["locus_length_bp", "locus_length_acgt_bp"]
    if omics == "transcriptome":
        if any(token in name for token in ("orf", "protein", "aa_")):
            return ["orf_len_nt", "orf_len_aa", "aa_len", "length_nt_total", "length_nt_acgu"]
        return ["length_nt_total", "length_nt_acgu", "clean_rna_len", "length_nt"]
    if omics == "proteome":
        return ["length_aa", "protein_length", "aa_len", "length"]
    return []


def _target_length_column(df: pd.DataFrame, feature: dict[str, Any]) -> str:
    source = str(feature.get("source_column") or "")
    return _first_present(df, _namespaced(str(feature.get("omics_layer") or ""), _target_length_candidates(feature)), source)


def _expression_column(df: pd.DataFrame, source: str) -> str:
    return _first_present(df, [
        "mean_expr", "mean_expression", "expression_mean",
        "transcriptome__mean_expr", "transcriptome__mean_expression",
    ], source)


def _detection_column(df: pd.DataFrame, source: str) -> str:
    return _first_present(df, [
        "pct_cells_detected", "detection_rate", "dropout_rate", "dropout_fraction",
        "transcriptome__pct_cells_detected", "transcriptome__dropout_rate",
    ], source)


def _as_fraction(series: pd.Series, unit: str) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    if "%" in str(unit or "") or str(unit or "").lower() in {"percent", "percentage"}:
        values = values / 100.0
    return values


def _clr_series(
    prepared: dict[str, pd.Series],
    components: list[dict[str, Any]],
    *,
    pseudocount: float,
) -> tuple[dict[str, pd.Series], str]:
    if len(components) < 2:
        return {}, "incomplete_composition_group"
    component_series: list[pd.Series] = []
    for component in components:
        key = str(component.get("feature_key") or "")
        values = prepared.get(key)
        if values is None:
            return {}, "incomplete_composition_group"
        component_series.append(_as_fraction(values, str(component.get("unit") or "")))
    matrix = pd.concat(component_series, axis=1)
    matrix = matrix.where(np.isfinite(matrix), np.nan)
    # The values have already passed registry-range QC.  A zero is a valid
    # composition observation; the pseudocount only prevents log(0).
    matrix = matrix.where(matrix >= 0)
    complete = matrix.notna().all(axis=1)
    matrix = matrix.where(complete)
    matrix = matrix + float(max(pseudocount, 0.0))
    log_values = np.log(matrix)
    clr = log_values.sub(log_values.mean(axis=1), axis=0)
    return {
        str(component.get("feature_key")): clr.iloc[:, index]
        for index, component in enumerate(components)
    }, ""


def _base_row(feature: dict[str, Any]) -> dict[str, Any]:
    return {
        "feature_key": feature.get("feature_key"),
        "omics_layer": feature.get("omics_layer"),
        "feature_name": feature.get("feature_name"),
        "source_column": feature.get("source_column") or "",
        "n_total": 0,
        "n_used": 0,
        "n_hvg": 0,
        "n_nonhvg": 0,
        "coefficient_per_sd": np.nan,
        "adjusted_odds_ratio": np.nan,
        "effect_ci_low": np.nan,
        "effect_ci_high": np.nan,
        "p_value": np.nan,
        "adjusted_global_fdr": np.nan,
        "covariates": "[]",
        "covariates_used": "[]",
        "standardization": "zscore_population_sd",
        "condition_number": np.nan,
        "collinearity_action": "",
        "adjusted_status": "failed",
        "fit_status": "failed",
        "reason": "",
        "failure_reason": "",
        "warnings": "",
        "policy_version": POLICY_VERSION,
        "covariates_requested": "[]",
        "covariates_fallback": "[]",
        "adjustment_transform": "identity",
        "composition_group": feature.get("composition_group") or "",
    }


def compute_adjusted_comparison(
    df: pd.DataFrame,
    tested: list[dict[str, Any]],
    prepared: dict[str, pd.Series],
    *,
    hvg_flag_col: str = "is_hvg",
    min_group_n: int = 20,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Fit target-feature gene-level adjustment models for comparison v2.

    Each target gets expression, detection/dropout and a target-specific length
    covariate when available.  Composition families use CLR coordinates and
    are only fitted when the complete registered family is materialized.
    """
    config = config or {}
    rows: list[dict[str, Any]] = []
    y = coerce_hvg_mask(df[hvg_flag_col]).astype(int)
    pseudocount = float(config.get("comparison_composition_pseudocount_fraction", DEFAULT_PSEUDOCOUNT))
    tested_by_key = {str(item.get("feature_key")): item for item in tested}
    composition_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for feature in tested:
        group = str(feature.get("composition_group") or "")
        if group:
            composition_groups.setdefault((str(feature.get("omics_layer") or ""), group), []).append(feature)

    clr_values: dict[str, pd.Series] = {}
    clr_reason: dict[str, str] = {}
    for group_features in composition_groups.values():
        anchor = group_features[0]
        expected_names = anchor.get("composition_components") or [item.get("feature_name") for item in group_features]
        expected: list[dict[str, Any]] = []
        for name in expected_names:
            key = f"{anchor.get('omics_layer')}::{name}"
            item = tested_by_key.get(key)
            if item is None:
                # It is important that a missing registered member does not
                # silently turn the family into an incomplete subcomposition.
                clr_reason.update({str(feature.get("feature_key")): "incomplete_composition_group" for feature in group_features})
                expected = []
                break
            expected.append(item)
        if not expected:
            continue
        values, reason = _clr_series(prepared, expected, pseudocount=pseudocount)
        if reason:
            clr_reason.update({str(feature.get("feature_key")): reason for feature in group_features})
        else:
            clr_values.update(values)

    for feature in tested:
        semantic = str(feature.get("semantic_type") or "continuous")
        if semantic not in {"continuous", "count", "composition"}:
            continue
        key = str(feature.get("feature_key"))
        source = str(feature.get("source_column") or "")
        base = _base_row(feature)
        target = clr_values.get(key) if semantic == "composition" else prepared.get(key)
        if target is None:
            reason = clr_reason.get(key, "missing_prepared_target")
            base.update({"adjusted_status": "skipped", "fit_status": "skipped", "reason": reason, "failure_reason": reason})
            rows.append(base)
            continue
        if semantic == "composition":
            base["adjustment_transform"] = CLR_VERSION
        target_z = _zscore(target)
        expression_col = _expression_column(df, source)
        detection_col = _detection_column(df, source)
        length_col = _target_length_column(df, feature)
        requested: list[str] = ["expression_spline", "detection_or_dropout", "target_specific_length"]
        fallback: list[str] = []
        work = pd.DataFrame({"outcome": y, "feature": target_z}, index=df.index)
        model_parts: list[pd.DataFrame] = []
        model_parts.append(pd.DataFrame({"feature": target_z}, index=df.index))
        actual_covariates: list[str] = []
        if expression_col:
            expression = pd.to_numeric(df[expression_col], errors="coerce")
            if expression.dropna().nunique() >= 4:
                work["mean_expression"] = expression
                actual_covariates.append(f"spline({expression_col})")
            else:
                fallback.append("expression_spline_unavailable")
        else:
            fallback.append("expression_missing")
        if detection_col:
            detection = _zscore(df[detection_col])
            if detection.notna().any():
                work["detection"] = detection
                actual_covariates.append(detection_col)
            else:
                fallback.append("detection_constant")
        else:
            fallback.append("detection_or_dropout_missing")
        if length_col:
            length = _zscore(df[length_col])
            if length.notna().any():
                work["length"] = length
                actual_covariates.append(length_col)
            else:
                fallback.append("target_specific_length_constant")
        else:
            fallback.append("target_specific_length_unavailable_or_self")
        base["covariates_requested"] = json.dumps(requested, ensure_ascii=False)
        base["covariates_fallback"] = json.dumps(fallback, ensure_ascii=False)
        work = work.replace([np.inf, -np.inf], np.nan).dropna()
        n_hvg = int(work["outcome"].sum())
        n_nonhvg = int(work.shape[0] - n_hvg)
        base.update({"n_total": int(work.shape[0]), "n_used": int(work.shape[0]), "n_hvg": n_hvg, "n_nonhvg": n_nonhvg})
        covariates_for_output = list(actual_covariates)
        base["covariates"] = json.dumps(covariates_for_output, ensure_ascii=False)
        base["covariates_used"] = base["covariates"]
        if n_hvg < min_group_n or n_nonhvg < min_group_n:
            base.update({"adjusted_status": "skipped", "fit_status": "skipped", "reason": "low_n_after_covariate_filter", "failure_reason": "low_n_after_covariate_filter"})
            rows.append(base)
            continue
        if not actual_covariates:
            reason = "adjustment_covariate_unavailable"
            base.update({"adjusted_status": "skipped", "fit_status": "skipped", "reason": reason, "failure_reason": reason})
            rows.append(base)
            continue
        x_parts = [pd.DataFrame({"feature": work["feature"]}, index=work.index)]
        if expression_col and "mean_expression" in work:
            unique_n = int(work["mean_expression"].nunique())
            if unique_n >= 4:
                try:
                    spline = dmatrix(
                        "bs(value, df=3, degree=3, include_intercept=False) - 1",
                        {"value": work["mean_expression"].to_numpy()},
                        return_type="dataframe",
                    )
                    spline.index = work.index
                    spline.columns = [f"mean_expression_spline_{index + 1}" for index in range(spline.shape[1])]
                    x_parts.append(spline)
                except Exception:
                    fallback.append("expression_spline_fit_fallback")
                    x_parts.append(pd.DataFrame({"mean_expression": _zscore(work["mean_expression"])}, index=work.index))
            else:
                x_parts.append(pd.DataFrame({"mean_expression": _zscore(work["mean_expression"])}, index=work.index))
        if "detection" in work:
            x_parts.append(work[["detection"]])
        if "length" in work:
            x_parts.append(work[["length"]])
        design = sm.add_constant(pd.concat(x_parts, axis=1), has_constant="add")
        try:
            condition_number = float(np.linalg.cond(design.to_numpy(dtype=float)))
        except Exception:
            condition_number = float("inf")
        removed: list[str] = []
        if not np.isfinite(condition_number) or condition_number > 1e8:
            for candidate in ("length", "detection"):
                if candidate not in design.columns:
                    continue
                design = design.drop(columns=[candidate])
                removed.append(candidate)
                try:
                    condition_number = float(np.linalg.cond(design.to_numpy(dtype=float)))
                except Exception:
                    condition_number = float("inf")
                if np.isfinite(condition_number) and condition_number <= 1e8:
                    break
        base["condition_number"] = condition_number
        if removed:
            base["collinearity_action"] = "removed:" + ",".join(removed)
            base["warnings"] = "collinearity_covariate_removed"
            retained = [item for item in actual_covariates if not (("detection" in removed and item == detection_col) or ("length" in removed and item == length_col))]
            base["covariates_used"] = json.dumps(retained, ensure_ascii=False)
        if not np.isfinite(condition_number) or condition_number > 1e8:
            reason = "severe_collinearity"
            base.update({"adjusted_status": "failed", "fit_status": "failed", "reason": reason, "failure_reason": reason})
            rows.append(base)
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                fitted = sm.GLM(work["outcome"], design, family=sm.families.Binomial()).fit()
            if not bool(getattr(fitted, "converged", True)):
                raise ValueError("convergence_failed")
            coefficient = float(fitted.params["feature"])
            ci_low, ci_high = [float(value) for value in fitted.conf_int().loc["feature"]]
            p_value = float(fitted.pvalues["feature"])
            if not np.isfinite([coefficient, ci_low, ci_high, p_value]).all() or max(abs(coefficient), abs(ci_low), abs(ci_high)) > 700:
                raise ValueError("non_finite_odds_ratio")
            base.update({
                "coefficient_per_sd": coefficient,
                "adjusted_odds_ratio": float(np.exp(coefficient)),
                "effect_ci_low": float(np.exp(ci_low)),
                "effect_ci_high": float(np.exp(ci_high)),
                "p_value": p_value,
                "adjusted_status": "tested",
                "fit_status": "tested",
                "reason": "",
                "failure_reason": "",
                "warnings": ";".join(filter(None, [base.get("warnings"), "association_not_causal"])),
            })
        except Exception as exc:
            reason = str(exc) if str(exc) in {"convergence_failed", "non_finite_odds_ratio"} else f"model_fit_failed:{type(exc).__name__}"
            base.update({"adjusted_status": "failed", "fit_status": "failed", "reason": reason, "failure_reason": reason})
        rows.append(base)

    adjusted = pd.DataFrame(rows)
    if adjusted.empty:
        return empty_frame(ADJUSTED_COLUMNS)
    tested_mask = adjusted["adjusted_status"].eq("tested")
    if tested_mask.any():
        adjusted.loc[tested_mask, "adjusted_global_fdr"] = _benjamini_hochberg(adjusted.loc[tested_mask, "p_value"])
    for column in ADJUSTED_COLUMNS:
        if column not in adjusted:
            adjusted[column] = np.nan
    return adjusted[ADJUSTED_COLUMNS]
