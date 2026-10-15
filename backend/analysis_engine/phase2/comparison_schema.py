from __future__ import annotations

import pandas as pd


COMPARISON_SCHEMA_VERSION = "hvg_nonhvg_v2"
LEGACY_COMPARISON_SCHEMA_VERSION = "hvg_nonhvg_v1"
EVIDENCE_RULE_VERSION = "evidence_rule_v1"
COMPARISON_STATUSES = {
    "complete",
    "partial",
    "unavailable",
    "failed",
    "legacy_not_generated",
}

AUDIT_COLUMNS = [
    "registry_version", "schema_id", "schema_version", "comparison_schema_version",
    "omics_layer", "scope",
    "feature_name", "feature_key", "display_name", "family", "unit",
    "description", "scaling_hint", "transform_hint",
    "bounded_min", "bounded_max",
    "semantic_type", "ml_role", "applicability", "zero_semantics",
    "composition_group", "redundancy_group", "source_block",
    "provenance_resolution", "source_column", "status", "reason",
    "duplicate_of", "n_hvg", "n_nonhvg", "missing_hvg", "missing_nonhvg",
    "missing_rate_hvg", "missing_rate_nonhvg", "missing_rate", "nonfinite_n",
    "out_of_range_n", "warnings", "registered", "source_resolved",
    "source_dataset_id", "source_schema_version", "materialized", "discovered",
    "block_status", "raw_match_rate", "applicable_match_rate",
    "analysis_status", "analysis_reason", "n_applicable_total",
    "n_applicable_hvg", "n_applicable_non_hvg", "n_valid_hvg",
    "n_valid_non_hvg",
]

COMPARISON_COLUMNS = [
    "feature_key", "omics_layer", "feature_name", "display_name", "family", "unit",
    "semantic_type", "source_column", "n_hvg", "n_nonhvg", "missing_hvg",
    "missing_nonhvg", "missing_rate_hvg", "missing_rate_nonhvg", "mean_hvg",
    "mean_nonhvg", "sd_hvg", "sd_nonhvg", "median_hvg", "median_nonhvg",
    "q1_hvg", "q3_hvg", "q1_nonhvg", "q3_nonhvg", "iqr_hvg", "iqr_nonhvg",
    "median_diff", "mean_diff", "relative_diff", "effect_type", "effect_value",
    "effect_ci_low", "effect_ci_high", "test_name", "statistic", "p_value",
    "global_fdr", "omics_fdr", "family_fdr", "direction", "evidence_level",
    "hypothesis_status", "proportion_hvg", "proportion_nonhvg", "proportion_diff",
    "odds_ratio", "category_counts_hvg", "category_counts_nonhvg",
    "composition_group", "redundancy_group", "applicability", "zero_semantics",
    "warnings", "analysis_status", "analysis_reason", "n_applicable_total",
    "n_applicable_hvg", "n_applicable_non_hvg", "n_valid_hvg", "n_valid_non_hvg",
]

ADJUSTED_COLUMNS = [
    "feature_key", "omics_layer", "feature_name", "source_column", "n_total", "n_used", "n_hvg",
    "n_nonhvg", "coefficient_per_sd", "adjusted_odds_ratio", "effect_ci_low",
    "effect_ci_high", "p_value", "adjusted_global_fdr", "covariates", "covariates_used",
    "standardization", "condition_number", "collinearity_action", "adjusted_status",
    "fit_status", "reason", "failure_reason", "warnings", "policy_version",
    "covariates_requested", "covariates_fallback", "adjustment_transform", "composition_group",
]

QUANTILE_COLUMNS = [
    "feature_key", "omics_layer", "feature_name", "group", "n", "min", "q05", "q25",
    "median", "q75", "q95", "max",
]

FAMILY_SUMMARY_COLUMNS = [
    "omics_layer", "family", "registry_fields", "discovered_fields", "tested_fields",
    "significant_fields", "moderate_strong_fields", "higher_in_hvg", "lower_in_hvg",
    "median_effect", "max_abs_effect", "warnings",
]


def empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)
