from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, fisher_exact, mannwhitneyu

from .associations import _benjamini_hochberg
from .comparison_qc import coerce_hvg_mask
from .comparison_schema import COMPARISON_COLUMNS, QUANTILE_COLUMNS, empty_frame


def cliffs_delta_fast(x: np.ndarray, y: np.ndarray) -> float:
    if x.size == 0 or y.size == 0:
        return float("nan")
    ordered_y = np.sort(y)
    less = np.searchsorted(ordered_y, x, side="left").sum(dtype=np.int64)
    greater = (y.size - np.searchsorted(ordered_y, x, side="right")).sum(dtype=np.int64)
    return float((less - greater) / (x.size * y.size))


def cliffs_delta_from_u(u_statistic: float, n_hvg: int, n_nonhvg: int) -> float:
    if n_hvg <= 0 or n_nonhvg <= 0:
        return float("nan")
    return float(2.0 * float(u_statistic) / (n_hvg * n_nonhvg) - 1.0)


def _bootstrap_delta_ci(
    x: np.ndarray,
    y: np.ndarray,
    *,
    repeats: int,
    random_state: int,
    max_group_n: int,
) -> tuple[float, float, bool]:
    if repeats <= 1:
        return float("nan"), float("nan"), False
    rng = np.random.default_rng(random_state)
    capped = False
    if x.size > max_group_n:
        x = rng.choice(x, size=max_group_n, replace=False)
        capped = True
    if y.size > max_group_n:
        y = rng.choice(y, size=max_group_n, replace=False)
        capped = True
    values = np.empty(repeats, dtype=float)
    for idx in range(repeats):
        bx = x[rng.integers(0, x.size, size=x.size)]
        by = y[rng.integers(0, y.size, size=y.size)]
        values[idx] = cliffs_delta_fast(bx, by)
    low, high = np.quantile(values, [0.025, 0.975])
    return float(low), float(high), capped


def _seed_for_feature(base_seed: int, feature_key: str) -> int:
    suffix = int(hashlib.sha256(feature_key.encode("utf-8")).hexdigest()[:8], 16)
    return int((base_seed + suffix) % (2**32 - 1))


def _numeric_summary(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {key: float("nan") for key in ("mean", "sd", "median", "q1", "q3", "iqr")}
    q1, median, q3 = np.quantile(values, [0.25, 0.50, 0.75])
    return {
        "mean": float(np.mean(values)),
        "sd": float(np.std(values, ddof=1)) if values.size > 1 else 0.0,
        "median": float(median),
        "q1": float(q1),
        "q3": float(q3),
        "iqr": float(q3 - q1),
    }


def _quantile_row(feature: dict[str, Any], group: str, values: np.ndarray) -> dict[str, Any]:
    if values.size:
        q05, q25, median, q75, q95 = np.quantile(values, [0.05, 0.25, 0.50, 0.75, 0.95])
        minimum, maximum = np.min(values), np.max(values)
    else:
        minimum = q05 = q25 = median = q75 = q95 = maximum = float("nan")
    return {
        "feature_key": feature["feature_key"],
        "omics_layer": feature["omics_layer"],
        "feature_name": feature["feature_name"],
        "group": group,
        "n": int(values.size),
        "min": float(minimum),
        "q05": float(q05),
        "q25": float(q25),
        "median": float(median),
        "q75": float(q75),
        "q95": float(q95),
        "max": float(maximum),
    }


def _display_values(values: np.ndarray, limit: int = 240) -> list[float]:
    ordered = np.sort(values)
    if ordered.size <= limit:
        return [float(value) for value in ordered]
    indices = np.linspace(0, ordered.size - 1, limit, dtype=int)
    return [float(value) for value in ordered[indices]]


def _numeric_test(
    feature: dict[str, Any],
    hvg_values: np.ndarray,
    nonhvg_values: np.ndarray,
    *,
    bootstrap_repeats: int,
    random_state: int,
    bootstrap_max_group_n: int,
) -> dict[str, Any]:
    u_stat, p_value = mannwhitneyu(hvg_values, nonhvg_values, alternative="two-sided")
    delta = cliffs_delta_from_u(u_stat, hvg_values.size, nonhvg_values.size)
    ci_low, ci_high, bootstrap_capped = _bootstrap_delta_ci(
        hvg_values,
        nonhvg_values,
        repeats=bootstrap_repeats,
        random_state=_seed_for_feature(random_state, feature["feature_key"]),
        max_group_n=bootstrap_max_group_n,
    )
    hvg = _numeric_summary(hvg_values)
    nonhvg = _numeric_summary(nonhvg_values)
    median_diff = hvg["median"] - nonhvg["median"]
    relative_diff = median_diff / abs(nonhvg["median"]) if abs(nonhvg["median"]) > 1e-12 else float("nan")
    return {
        "mean_hvg": hvg["mean"], "mean_nonhvg": nonhvg["mean"],
        "sd_hvg": hvg["sd"], "sd_nonhvg": nonhvg["sd"],
        "median_hvg": hvg["median"], "median_nonhvg": nonhvg["median"],
        "q1_hvg": hvg["q1"], "q3_hvg": hvg["q3"],
        "q1_nonhvg": nonhvg["q1"], "q3_nonhvg": nonhvg["q3"],
        "iqr_hvg": hvg["iqr"], "iqr_nonhvg": nonhvg["iqr"],
        "median_diff": median_diff,
        "mean_diff": hvg["mean"] - nonhvg["mean"],
        "relative_diff": relative_diff,
        "effect_type": "cliffs_delta",
        "effect_value": delta,
        "effect_ci_low": ci_low,
        "effect_ci_high": ci_high,
        "test_name": "mann_whitney_u",
        "statistic": float(u_stat),
        "p_value": float(p_value),
        "hypothesis_status": "tested",
        "_bootstrap_capped": bootstrap_capped,
        "direction": "higher_in_hvg" if delta > 0 else ("lower_in_hvg" if delta < 0 else "neutral"),
    }


def _binary_test(hvg_values: np.ndarray, nonhvg_values: np.ndarray) -> dict[str, Any]:
    a = int(np.sum(hvg_values == 1))
    b = int(np.sum(hvg_values == 0))
    c = int(np.sum(nonhvg_values == 1))
    d = int(np.sum(nonhvg_values == 0))
    table = np.array([[a, b], [c, d]], dtype=int)
    expected = chi2_contingency(table, correction=False)[3]
    if np.any(expected < 5):
        _, p_value = fisher_exact(table, alternative="two-sided")
        test_name = "fisher_exact"
    else:
        statistic, p_value, _, _ = chi2_contingency(table, correction=False)
        test_name = "chi_square"
    corrected = table.astype(float) + (0.5 if np.any(table == 0) else 0.0)
    odds_ratio = corrected[0, 0] * corrected[1, 1] / (corrected[0, 1] * corrected[1, 0])
    se = math.sqrt(float(np.sum(1.0 / corrected)))
    log_or = math.log(odds_ratio)
    proportion_hvg = a / max(a + b, 1)
    proportion_nonhvg = c / max(c + d, 1)
    diff = proportion_hvg - proportion_nonhvg
    return {
        "mean_hvg": proportion_hvg, "mean_nonhvg": proportion_nonhvg,
        "median_hvg": float(np.median(hvg_values)), "median_nonhvg": float(np.median(nonhvg_values)),
        "mean_diff": diff, "median_diff": float(np.median(hvg_values) - np.median(nonhvg_values)),
        "relative_diff": diff / abs(proportion_nonhvg) if abs(proportion_nonhvg) > 1e-12 else float("nan"),
        "effect_type": "odds_ratio", "effect_value": odds_ratio,
        "effect_ci_low": math.exp(log_or - 1.96 * se), "effect_ci_high": math.exp(log_or + 1.96 * se),
        "test_name": test_name, "statistic": odds_ratio, "p_value": float(p_value),
        "hypothesis_status": "tested",
        "proportion_hvg": proportion_hvg, "proportion_nonhvg": proportion_nonhvg,
        "proportion_diff": diff, "odds_ratio": odds_ratio,
        "direction": "higher_in_hvg" if diff > 0 else ("lower_in_hvg" if diff < 0 else "neutral"),
    }


def _categorical_test(
    hvg_values: pd.Series,
    nonhvg_values: pd.Series,
    *,
    min_cell_count: int,
) -> dict[str, Any]:
    categories = sorted(set(hvg_values.astype(str)) | set(nonhvg_values.astype(str)))
    table = np.array([
        [int((hvg_values.astype(str) == category).sum()) for category in categories],
        [int((nonhvg_values.astype(str) == category).sum()) for category in categories],
    ])
    statistic, p_value, _, _ = chi2_contingency(table, correction=False)
    n = int(table.sum())
    cramers_v = math.sqrt(statistic / max(n * min(table.shape[0] - 1, table.shape[1] - 1), 1))
    formally_tested = bool(np.all(table >= min_cell_count))
    return {
        "effect_type": "cramers_v", "effect_value": float(cramers_v),
        "effect_ci_low": float("nan"), "effect_ci_high": float("nan"),
        "test_name": "chi_square" if formally_tested else "descriptive_counts",
        "statistic": float(statistic), "p_value": float(p_value) if formally_tested else float("nan"),
        "hypothesis_status": "tested" if formally_tested else "descriptive_only",
        "category_counts_hvg": json.dumps(
            {category: int(table[0, idx]) for idx, category in enumerate(categories)},
            ensure_ascii=False,
        ),
        "category_counts_nonhvg": json.dumps(
            {category: int(table[1, idx]) for idx, category in enumerate(categories)},
            ensure_ascii=False,
        ),
        "direction": "not_directional",
    }


def _apply_fdr(frame: pd.DataFrame) -> pd.DataFrame:
    frame["global_fdr"] = _benjamini_hochberg(frame["p_value"])
    frame["omics_fdr"] = np.nan
    frame["family_fdr"] = np.nan
    for _, indices in frame.groupby("omics_layer").groups.items():
        frame.loc[indices, "omics_fdr"] = _benjamini_hochberg(frame.loc[indices, "p_value"])
    for _, indices in frame.groupby("family").groups.items():
        frame.loc[indices, "family_fdr"] = _benjamini_hochberg(frame.loc[indices, "p_value"])
    return frame


def _evidence_level(row: pd.Series) -> str:
    fdr = row.get("global_fdr")
    effect = row.get("effect_value")
    if not np.isfinite(fdr) or not np.isfinite(effect):
        return "descriptive"
    if row.get("effect_type") == "odds_ratio":
        low, high = row.get("effect_ci_low"), row.get("effect_ci_high")
        excludes_null = np.isfinite(low) and np.isfinite(high) and (high < 1 or low > 1)
        return "statistical_association_binary" if fdr < 0.01 and excludes_null else "descriptive"
    if row.get("effect_type") == "cramers_v":
        return "statistical_association_categorical" if fdr < 0.01 and abs(float(effect)) >= 0.10 else "descriptive"
    if row.get("effect_type") != "cliffs_delta":
        return "descriptive"
    magnitude = abs(float(effect))
    if fdr < 0.01 and magnitude >= 0.33:
        return "statistical_association_strong"
    if fdr < 0.05 and magnitude >= 0.20:
        return "statistical_association_moderate"
    if fdr < 0.10 and magnitude >= 0.10:
        return "statistical_association_weak"
    return "descriptive"


def compute_comparison_statistics(
    df: pd.DataFrame,
    tested: list[dict[str, Any]],
    prepared: dict[str, pd.Series],
    *,
    hvg_flag_col: str = "is_hvg",
    bootstrap_repeats: int = 500,
    random_state: int = 42,
    bootstrap_max_group_n: int = 1000,
    display_point_cap: int = 240,
    categorical_min_cell_count: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    hvg_mask = coerce_hvg_mask(df[hvg_flag_col])
    rows: list[dict[str, Any]] = []
    quantile_rows: list[dict[str, Any]] = []
    distributions: dict[str, Any] = {}
    bootstrap_capped_features: list[str] = []

    for feature in tested:
        key = feature["feature_key"]
        values = prepared[key]
        semantic = feature.get("semantic_type")
        hvg_series = values.loc[hvg_mask].dropna()
        nonhvg_series = values.loc[~hvg_mask].dropna()
        base = {column: feature.get(column) for column in (
            "feature_key", "omics_layer", "feature_name", "display_name", "family", "unit",
            "semantic_type", "source_column", "n_hvg", "n_nonhvg", "missing_hvg",
            "missing_nonhvg", "missing_rate_hvg", "missing_rate_nonhvg", "composition_group",
            "redundancy_group", "applicability", "zero_semantics", "warnings",
            "analysis_status", "analysis_reason", "n_applicable_total", "n_applicable_hvg",
            "n_applicable_non_hvg", "n_valid_hvg", "n_valid_non_hvg",
        )}
        if semantic in {"continuous", "count", "composition"}:
            x = hvg_series.to_numpy(dtype=float)
            y = nonhvg_series.to_numpy(dtype=float)
            result = _numeric_test(
                feature, x, y,
                bootstrap_repeats=bootstrap_repeats,
                random_state=random_state,
                bootstrap_max_group_n=bootstrap_max_group_n,
            )
            if result.pop("_bootstrap_capped", False):
                bootstrap_capped_features.append(str(key))
            quantile_rows.extend([_quantile_row(feature, "hvg", x), _quantile_row(feature, "nonhvg", y)])
            distributions[key] = {
                "hvg": _display_values(x, display_point_cap),
                "nonhvg": _display_values(y, display_point_cap),
            }
        elif semantic == "binary":
            x = hvg_series.to_numpy(dtype=float)
            y = nonhvg_series.to_numpy(dtype=float)
            result = _binary_test(x, y)
            quantile_rows.extend([_quantile_row(feature, "hvg", x), _quantile_row(feature, "nonhvg", y)])
            distributions[key] = {
                "hvg": _display_values(x, display_point_cap),
                "nonhvg": _display_values(y, display_point_cap),
            }
        else:
            result = _categorical_test(
                hvg_series,
                nonhvg_series,
                min_cell_count=categorical_min_cell_count,
            )
            distributions[key] = {
                "hvg_counts": hvg_series.astype(str).value_counts().to_dict(),
                "nonhvg_counts": nonhvg_series.astype(str).value_counts().to_dict(),
            }
        rows.append({**base, **result})

    comparison = pd.DataFrame(rows)
    if comparison.empty:
        return (
            empty_frame(COMPARISON_COLUMNS),
            empty_frame(QUANTILE_COLUMNS),
            distributions,
            {"bootstrap_capped_features": [], "display_point_cap": display_point_cap},
        )
    comparison = _apply_fdr(comparison)
    comparison["evidence_level"] = comparison.apply(_evidence_level, axis=1)
    for column in COMPARISON_COLUMNS:
        if column not in comparison:
            comparison[column] = np.nan
    comparison["abs_effect"] = pd.to_numeric(comparison["effect_value"], errors="coerce").abs()
    comparison = comparison.sort_values(
        ["global_fdr", "abs_effect", "feature_key"],
        ascending=[True, False, True],
        na_position="last",
    ).drop(columns=["abs_effect"]).reset_index(drop=True)
    return (
        comparison[COMPARISON_COLUMNS],
        pd.DataFrame(quantile_rows, columns=QUANTILE_COLUMNS),
        distributions,
        {
            "bootstrap_capped_features": bootstrap_capped_features,
            "display_point_cap": display_point_cap,
        },
    )
