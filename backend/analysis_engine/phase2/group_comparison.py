from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .comparison_adjustment import compute_adjusted_comparison
from .comparison_qc import coerce_hvg_mask, run_comparison_qc
from .comparison_schema import (
    ADJUSTED_COLUMNS,
    AUDIT_COLUMNS,
    COMPARISON_COLUMNS,
    COMPARISON_SCHEMA_VERSION,
    EVIDENCE_RULE_VERSION,
    FAMILY_SUMMARY_COLUMNS,
    QUANTILE_COLUMNS,
    empty_frame,
)
from .comparison_schema import LEGACY_COMPARISON_SCHEMA_VERSION
from .comparison_selector import load_registry_payload, resolve_comparison_features
from .comparison_stats import compute_comparison_statistics


ARTIFACTS = {
    "feature_audit": "hvg_nonhvg_feature_audit.csv",
    "feature_comparison": "hvg_nonhvg_feature_comparison.csv",
    "adjusted_comparison": "hvg_nonhvg_adjusted_comparison.csv",
    "distribution_quantiles": "hvg_nonhvg_distribution_quantiles.csv",
    "family_summary": "hvg_nonhvg_family_summary.csv",
    "plots_payload": "hvg_nonhvg_plots_payload.json",
    "summary": "hvg_nonhvg_summary.json",
    "run_manifest": "hvg_nonhvg_run_manifest.json",
}

CONTEXT_ARTIFACTS = {
    "context": "hvg_multiomics_core_features.csv",
    "provenance": "hvg_multiomics_feature_provenance.csv",
    "mapping": "hvg_multiomics_mapping_table.csv",
    "mapping_summary": "hvg_multiomics_mapping_summary.json",
    "assembly_manifest": "hvg_multiomics_assembly_manifest.json",
    "block_coverage": "hvg_nonhvg_block_coverage.csv",
}


def _update_block_coverage(
    output_dir: Path,
    config: dict[str, Any],
    audit: pd.DataFrame,
    comparison: pd.DataFrame,
) -> str:
    """Refresh block-level tested/significance counts without changing QC."""
    configured = config.get("comparison_block_coverage_path")
    path = Path(str(configured)) if configured else output_dir / CONTEXT_ARTIFACTS["block_coverage"]
    if path.exists():
        try:
            coverage = pd.read_csv(path)
        except Exception:
            coverage = pd.DataFrame()
    else:
        coverage = pd.DataFrame()
    if coverage.empty:
        rows = []
        for omics in sorted(set(audit.get("omics_layer", pd.Series(dtype=str)).dropna().astype(str))):
            rows.append({"omics": omics, "block_status": "unknown"})
        coverage = pd.DataFrame(rows)
    if coverage.empty:
        return str(path)
    for column in ("tested_fields", "descriptive_only_fields", "skipped_candidate_fields", "significant_fields"):
        if column not in coverage:
            coverage[column] = 0
    for index, row in coverage.iterrows():
        omics = str(row.get("omics") or "")
        scoped = audit.loc[audit["omics_layer"].astype(str).eq(omics)] if not audit.empty else audit
        scoped_comparison = comparison.loc[comparison["omics_layer"].astype(str).eq(omics)] if not comparison.empty else comparison
        coverage.loc[index, "tested_fields"] = int(scoped["status"].eq("tested").sum()) if not scoped.empty else 0
        coverage.loc[index, "descriptive_only_fields"] = int(scoped["status"].eq("descriptive_only").sum()) if not scoped.empty else 0
        coverage.loc[index, "skipped_candidate_fields"] = int((
            scoped["status"].eq("skipped")
            & scoped["ml_role"].isin(["eligible", "conditional"])
        ).sum()) if not scoped.empty else 0
        coverage.loc[index, "significant_fields"] = int((
            pd.to_numeric(scoped_comparison.get("global_fdr"), errors="coerce") < 0.05
        ).sum()) if not scoped_comparison.empty else 0
    path.parent.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(path, index=False)
    return str(path)


def _eligible_universe_mask(audit: pd.DataFrame, include_conditional: bool) -> pd.Series:
    if audit.empty:
        return pd.Series(dtype=bool)
    return audit["ml_role"].eq("eligible") | (
        include_conditional & audit["ml_role"].eq("conditional")
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_json(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is pd.NA or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return None
    return value


def _records(frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    work = frame.head(limit).copy() if limit else frame.copy()
    return _safe_json(work.replace([np.inf, -np.inf], np.nan).to_dict(orient="records"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(_safe_json(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: str | Path | None) -> str:
    if not path:
        return ""
    target = Path(path)
    if not target.exists() or not target.is_file():
        return ""
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config_sha256(config: dict[str, Any]) -> str:
    public = {
        key: value for key, value in config.items()
        if "password" not in str(key).lower()
    }
    encoded = json.dumps(_safe_json(public), ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _public_value(value: Any) -> Any:
    if isinstance(value, Path):
        return value.name
    if isinstance(value, dict):
        return {str(key): _public_value(item) for key, item in value.items() if "password" not in str(key).lower()}
    if isinstance(value, (list, tuple)):
        return [_public_value(item) for item in value]
    if isinstance(value, str):
        candidate = value.replace("\\", "/")
        if re.match(r"^[A-Za-z]:/", candidate) or candidate.startswith("/"):
            return Path(candidate).name
    value = _safe_json(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): _public_value(value)
        for key, value in config.items()
        if "password" not in str(key).lower()
        and str(key) not in {"input_baseline_csv", "comparison_input_csv", "output_dir", "validation_dir"}
    }


def _mapping_summary(mapping_context: dict[str, Any] | None) -> dict[str, Any]:
    context = mapping_context or {}
    ready = context.get("ready_for_phase2_stoich")
    status = context.get("mapping_status") or context.get("status")
    if not status and ready is not None:
        status = "ready" if bool(ready) else "blocked"
    return {
        "mapping_status": status or "not_reported",
        "ready_for_phase2_stoich": ready,
        "match_rate": context.get("match_rate"),
        "minimum_threshold": context.get("minimum_threshold", context.get("threshold")),
        "mapping_mode": context.get("mapping_mode", context.get("mode")),
        "mapping_warnings": context.get("warnings") or [],
        "context": context,
    }


def _family_summary(audit: pd.DataFrame, comparison: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if audit.empty:
        return empty_frame(FAMILY_SUMMARY_COLUMNS)
    for (omics, family), group in audit.groupby(["omics_layer", "family"], dropna=False):
        tested = comparison.loc[
            comparison["omics_layer"].eq(omics)
            & comparison["family"].eq(family)
            & comparison["hypothesis_status"].eq("tested")
        ] if not comparison.empty else comparison
        numeric_tested = tested.loc[tested["effect_type"].eq("cliffs_delta")] if not tested.empty else tested
        effects = pd.to_numeric(numeric_tested.get("effect_value"), errors="coerce") if not numeric_tested.empty else pd.Series(dtype=float)
        significant = tested.loc[pd.to_numeric(tested.get("global_fdr"), errors="coerce") < 0.05] if not tested.empty else tested
        rows.append({
            "omics_layer": omics,
            "family": family,
            "registry_fields": int(group.shape[0]),
            "discovered_fields": int(group["source_column"].fillna("").astype(str).ne("").sum()),
            "tested_fields": int(tested.shape[0]),
            "significant_fields": int(significant.shape[0]),
            "moderate_strong_fields": int(tested["evidence_level"].isin([
                "statistical_association_moderate", "statistical_association_strong"
            ]).sum()) if not tested.empty else 0,
            "higher_in_hvg": int(tested["direction"].eq("higher_in_hvg").sum()) if not tested.empty else 0,
            "lower_in_hvg": int(tested["direction"].eq("lower_in_hvg").sum()) if not tested.empty else 0,
            "median_effect": float(effects.median()) if effects.notna().any() else np.nan,
            "max_abs_effect": float(effects.abs().max()) if effects.notna().any() else np.nan,
            "warnings": "compositional_family" if group["composition_group"].fillna("").astype(str).ne("").any() else "",
        })
    return pd.DataFrame(rows, columns=FAMILY_SUMMARY_COLUMNS)


def _plots_payload(
    comparison: pd.DataFrame,
    adjusted: pd.DataFrame,
    family_summary: pd.DataFrame,
    distributions: dict[str, Any],
    schema_version: str = COMPARISON_SCHEMA_VERSION,
) -> dict[str, Any]:
    numeric = comparison.loc[comparison["effect_type"].eq("cliffs_delta")].copy() if not comparison.empty else comparison
    if not numeric.empty:
        numeric["abs_effect"] = pd.to_numeric(numeric["effect_value"], errors="coerce").abs()
        forest = numeric.sort_values(["abs_effect", "global_fdr"], ascending=[False, True]).head(30)
    else:
        forest = numeric
    adjusted_tested = adjusted.loc[adjusted["adjusted_status"].eq("tested")].copy() if not adjusted.empty else adjusted
    raw_adjusted = comparison.merge(
        adjusted_tested[["feature_key", "coefficient_per_sd", "adjusted_odds_ratio", "adjusted_global_fdr"]],
        on="feature_key",
        how="inner",
    ) if not adjusted_tested.empty and not comparison.empty else pd.DataFrame()
    return {
        "schema_version": schema_version,
        "effect_forest": _records(forest[[
            "feature_key", "display_name", "omics_layer", "family", "effect_value",
            "effect_ci_low", "effect_ci_high", "global_fdr", "direction", "evidence_level",
            "effect_type", "n_hvg", "n_nonhvg", "missing_rate_hvg", "missing_rate_nonhvg",
        ]] if not forest.empty else forest),
        "effect_fdr_scatter": _records(comparison[[
            "feature_key", "display_name", "omics_layer", "family", "effect_type",
            "effect_value", "global_fdr", "direction", "evidence_level", "n_hvg",
            "n_nonhvg", "missing_rate_hvg", "missing_rate_nonhvg",
        ]] if not comparison.empty else comparison),
        "family_heatmap": _records(family_summary),
        "raw_vs_adjusted": _records(raw_adjusted[[
            "feature_key", "display_name", "omics_layer", "family", "effect_value",
            "global_fdr", "coefficient_per_sd", "adjusted_odds_ratio", "adjusted_global_fdr",
            "n_hvg", "n_nonhvg", "missing_rate_hvg", "missing_rate_nonhvg", "effect_type",
        ]] if not raw_adjusted.empty else raw_adjusted),
        "feature_distributions": _safe_json(distributions),
    }


def _write_artifacts(
    output_dir: Path,
    *,
    audit: pd.DataFrame,
    comparison: pd.DataFrame,
    adjusted: pd.DataFrame,
    quantiles: pd.DataFrame,
    family_summary: pd.DataFrame,
    plots: dict[str, Any],
    summary: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output_dir / ARTIFACTS["feature_audit"], index=False)
    comparison.to_csv(output_dir / ARTIFACTS["feature_comparison"], index=False)
    adjusted.to_csv(output_dir / ARTIFACTS["adjusted_comparison"], index=False)
    quantiles.to_csv(output_dir / ARTIFACTS["distribution_quantiles"], index=False)
    family_summary.to_csv(output_dir / ARTIFACTS["family_summary"], index=False)
    _write_json(output_dir / ARTIFACTS["plots_payload"], plots)
    _write_json(output_dir / ARTIFACTS["summary"], summary)
    artifact_checksums = {
        key: _sha256(output_dir / filename)
        for key, filename in ARTIFACTS.items()
        if key != "run_manifest"
    }
    artifact_checksums["run_manifest"] = None
    manifest["artifact_checksums"] = artifact_checksums
    manifest["artifact_checksums_sha256"] = artifact_checksums
    manifest["manifest_self_checksum"] = "excluded_to_avoid_recursive_checksum"
    _write_json(output_dir / ARTIFACTS["run_manifest"], manifest)


def write_unavailable_comparison(
    output_dir: str | Path,
    *,
    status: str = "unavailable",
    reason: str,
    config: dict[str, Any] | None = None,
    mapping_context: dict[str, Any] | None = None,
    phase1_metadata: dict[str, Any] | None = None,
    registry_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timer_started = time.perf_counter()
    started = _utc_now()
    config = config or {}
    public_config = _public_config(config)
    schema_version = str(config.get("comparison_schema_version") or COMPARISON_SCHEMA_VERSION)
    audit = empty_frame(AUDIT_COLUMNS)
    resolved_blocks: list[str] = []
    registry_version = "not_resolved"
    try:
        _selected, audit, resolved_blocks, registry_version = resolve_comparison_features(
            pd.DataFrame(columns=["gene_id", str(config.get("hvg_flag_col") or "is_hvg")]),
            config,
            registry_payload,
        )
    except Exception:
        pass
    error_id = hashlib.sha256(reason.encode("utf-8")).hexdigest()[:12] if status == "failed" else None
    registry_fields = int(audit.shape[0])
    eligible_fields = int(audit["ml_role"].eq("eligible").sum()) if not audit.empty else 0
    conditional_fields = int(audit["ml_role"].eq("conditional").sum()) if not audit.empty else 0
    exclude_fields = int(audit["ml_role"].eq("exclude").sum()) if not audit.empty else 0
    skipped_fields = int(audit["status"].eq("skipped").sum()) if not audit.empty else 0
    excluded_fields = int(audit["status"].eq("excluded").sum()) if not audit.empty else 0
    summary = {
        "status": status,
        "comparison_status": status,
        "schema_version": schema_version,
        "comparison_schema_version": schema_version,
        "evidence_rule_version": EVIDENCE_RULE_VERSION,
        "reason": reason,
        "error_id": error_id,
        "counts": {
            "registry_fields": registry_fields, "audited_core_fields": registry_fields,
            "eligible_candidate_fields": eligible_fields, "conditional_fields": conditional_fields,
            "excluded_registry_fields": exclude_fields, "discovered_fields": 0,
            "materialized_candidate_fields": 0, "tested_fields": 0,
            "descriptive_only_fields": 0, "skipped_fields": skipped_fields,
            "skipped_candidate_fields": skipped_fields, "excluded_fields": excluded_fields,
            "global_fdr_lt_0_05": 0, "significant_fields": 0,
        },
        "resolved_blocks": resolved_blocks,
        "scope": {
            "requested_omics": public_config.get("comparison_omics") or ["genome", "transcriptome", "proteome"],
            "available_omics": resolved_blocks,
            "include_conditional": bool(public_config.get("comparison_include_conditional", False)),
            "source_mode": "platform_registry_core" if schema_version == COMPARISON_SCHEMA_VERSION else "legacy_user_feature",
        },
        "feature_universe": {
            "registry_fields": registry_fields,
            "discovered_fields": 0,
            "tested_fields": 0,
        },
        "artifacts": ARTIFACTS,
        "warnings": [{"code": status, "message": reason}],
        "method_boundary": "association_not_causation",
    }
    manifest = {
        "comparison_schema_version": schema_version,
        "schema_version": schema_version,
        "evidence_rule_version": EVIDENCE_RULE_VERSION,
        "registry_version": registry_version,
        "status": status,
        "comparison_status": status,
        "reason": reason,
        "error_id": error_id,
        "started_at_utc": started,
        "finished_at_utc": _utc_now(),
        "runtime_seconds": round(time.perf_counter() - timer_started, 6),
        "input_path": Path(str(config.get("comparison_input_csv") or config.get("comparison_input_path") or config.get("input_baseline_csv") or "")).name,
        "input_sha256": _sha256(config.get("comparison_input_csv") or config.get("comparison_input_path") or config.get("input_baseline_csv")),
        "case_id": _public_value(config.get("case_id")),
        "case_input_path": _public_value(config.get("case_input_path")),
        "case_input_sha256": _public_value(config.get("case_input_sha256")),
        "job_identifier": config.get("job_id") or config.get("case_id"),
        "hvg_label_source": str(config.get("hvg_flag_col") or "is_hvg"),
        "phase1_metadata": _public_value(phase1_metadata or {}),
        "mapping": _public_value(_mapping_summary(mapping_context)),
        "mapping_context": _public_value(mapping_context or {}),
        "resolved_blocks": resolved_blocks,
        "scope": {
            "requested_omics": public_config.get("comparison_omics") or ["genome", "transcriptome", "proteome"],
            "available_omics": resolved_blocks,
            "include_conditional": bool(public_config.get("comparison_include_conditional", False)),
            "source_mode": "platform_registry_core" if schema_version == COMPARISON_SCHEMA_VERSION else "legacy_user_feature",
        },
        "feature_universe": {
            "registry_fields": registry_fields,
            "discovered_fields": 0,
            "tested_fields": 0,
        },
        "feature_selection": {
            "scope": "core",
            "include_conditional": bool(public_config.get("comparison_include_conditional", False)),
            "registry_fields": registry_fields,
            "eligible_fields": eligible_fields,
            "conditional_fields": conditional_fields,
            "exclude_fields": exclude_fields,
            "discovered_fields": 0,
            "tested_fields": 0,
            "skipped_fields": skipped_fields,
            "descriptive_only_fields": 0,
            "excluded_fields": excluded_fields,
        },
        "provenance": {
            "strategy": "joined columns + registry + mapping metadata",
            "explicit_manifest_present": bool(public_config.get("comparison_feature_provenance")),
            "source_columns": [],
        },
        "qc": {
            "min_group_n": int(public_config.get("comparison_min_group_n", public_config.get("min_group_n", 20))),
            "max_missing_rate": float(public_config.get("comparison_max_missing_rate", 0.50)),
            "near_constant_rule": "numeric std(ddof=0) <= comparison_near_constant_tolerance",
            "range_policy": "out-of-range values become missing with an audit warning; no clipping",
            "duplicate_policy": "one exact representative tested; duplicates descriptive_only",
            "zero_semantics_policy": "applicability masks remove non-applicable rows; applicable numeric zero is retained",
        },
        "methods": {
            "availability": "feature-wise available-case",
            "continuous_test": "two-sided Mann-Whitney U",
            "continuous_effect": "Cliff's delta derived from U without Cartesian expansion",
            "ci": "stratified bootstrap percentile",
            "binary_test": "Fisher exact for sparse expected cells; otherwise Pearson chi-square",
            "binary_effect": "odds ratio with 95% CI; group proportions and proportion difference retained",
            "categorical_test": "Pearson chi-square when cells meet the configured minimum",
            "categorical_effect": "Cramer's V with category counts",
            "multiple_testing": "BH global primary across all tested hypotheses; omics and family secondary",
            "fdr_scopes": {"global": "all tested hypotheses", "omics": "within omics", "family": "within family across omics"},
            "adjustment": "gene-level logistic GLM with expression spline, one detection/dropout covariate, and applicable length",
        },
        "thresholds": {
            "min_group_n": int(public_config.get("comparison_min_group_n", public_config.get("min_group_n", 20))),
            "max_missing_rate": float(public_config.get("comparison_max_missing_rate", 0.50)),
        },
        "random_state": int(public_config.get("random_state", 42)),
        "limits": {
            "bootstrap_repeats": int(public_config.get("comparison_bootstrap_ci_repeats", 500)),
            "bootstrap_max_group_n": int(public_config.get("comparison_bootstrap_max_group_n", 1000)),
            "worker_count": int(public_config.get("comparison_worker_count", 1)),
            "api_page_size_max": int(public_config.get("comparison_api_page_size_max", 200)),
            "single_feature_display_point_cap": int(public_config.get("comparison_display_point_cap", 240)),
            "categorical_min_cell_count": int(public_config.get("comparison_categorical_min_cell_count", 5)),
        },
        "auto_degradations": [],
        "warnings": [{"code": status, "message": reason}],
        "config_sha256": _config_sha256(public_config),
        "code_version": public_config.get("code_version") or public_config.get("release_version") or "not_available",
        "config": public_config,
        "artifacts": ARTIFACTS,
    }
    summary["context_artifacts"] = CONTEXT_ARTIFACTS
    manifest["context_artifacts"] = CONTEXT_ARTIFACTS
    plots = {"schema_version": schema_version, "status": status, "reason": reason}
    _write_artifacts(
        Path(output_dir),
        audit=audit,
        comparison=empty_frame(COMPARISON_COLUMNS),
        adjusted=empty_frame(ADJUSTED_COLUMNS),
        quantiles=empty_frame(QUANTILE_COLUMNS),
        family_summary=empty_frame(FAMILY_SUMMARY_COLUMNS),
        plots=plots,
        summary=summary,
        manifest=manifest,
    )
    return {"summary": summary, "manifest": manifest, "plots": plots}


def run_hvg_nonhvg_comparison(
    df: pd.DataFrame,
    config: dict[str, Any],
    *,
    output_dir: str | Path | None = None,
    phase1_metadata: dict[str, Any] | None = None,
    mapping_context: dict[str, Any] | None = None,
    registry_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timer_started = time.perf_counter()
    started = _utc_now()
    hvg_flag_col = str(config.get("hvg_flag_col") or "is_hvg")
    if "gene_id" not in df.columns or hvg_flag_col not in df.columns:
        reason = "comparison requires canonical gene_id and is_hvg columns"
        if output_dir is not None:
            return write_unavailable_comparison(
                output_dir,
                reason=reason,
                config=config,
                mapping_context=mapping_context,
                phase1_metadata=phase1_metadata,
                registry_payload=registry_payload,
            )
        return {"summary": {"status": "unavailable", "comparison_status": "unavailable", "reason": reason}}
    if df["gene_id"].astype(str).duplicated().any():
        raise ValueError("comparison input contains duplicated gene_id rows")

    registry = registry_payload or load_registry_payload()
    selected, audit, resolved_blocks, registry_version = resolve_comparison_features(df, config, registry)
    if not resolved_blocks:
        reason = "No reliable gene-level Genome, Transcriptome, or Proteome Core feature block was resolved."
        if output_dir is not None:
            return write_unavailable_comparison(
                output_dir,
                reason=reason,
                config=config,
                mapping_context=mapping_context,
                phase1_metadata=phase1_metadata,
                registry_payload=registry,
            )
        return {"summary": {"status": "unavailable", "comparison_status": "unavailable", "reason": reason}}

    min_group_n = int(config.get("comparison_min_group_n", config.get("min_group_n", 20)))
    max_missing_rate = float(config.get("comparison_max_missing_rate", 0.50))
    tested, audit, prepared = run_comparison_qc(
        df,
        selected,
        audit,
        hvg_flag_col=hvg_flag_col,
        min_group_n=min_group_n,
        max_missing_rate=max_missing_rate,
        applicable_values=set(config.get("comparison_applicable_values") or ["all", "coding_only", "protein_proxy_only"]),
        near_constant_tolerance=float(config.get("comparison_near_constant_tolerance", 1e-12)),
        high_correlation_threshold=float(config.get("comparison_high_correlation_threshold", 0.995)),
    )
    comparison, quantiles, distributions, statistics_metadata = compute_comparison_statistics(
        df,
        tested,
        prepared,
        hvg_flag_col=hvg_flag_col,
        bootstrap_repeats=int(config.get("comparison_bootstrap_ci_repeats", 500)),
        random_state=int(config.get("random_state", 42)),
        bootstrap_max_group_n=int(config.get("comparison_bootstrap_max_group_n", 1000)),
        display_point_cap=int(config.get("comparison_display_point_cap", 240)),
        categorical_min_cell_count=int(config.get("comparison_categorical_min_cell_count", 5)),
    )
    if not comparison.empty:
        descriptive_keys = set(
            comparison.loc[
                comparison["hypothesis_status"].eq("descriptive_only"), "feature_key"
            ].astype(str)
        )
        if descriptive_keys:
            mask = audit["feature_key"].astype(str).isin(descriptive_keys)
            audit.loc[mask, "status"] = "descriptive_only"
            audit.loc[mask, "reason"] = "categorical_sparse"
    adjusted = compute_adjusted_comparison(
        df,
        tested,
        prepared,
        hvg_flag_col=hvg_flag_col,
        min_group_n=min_group_n,
        config=config,
    ) if bool(config.get("comparison_adjustment_enabled", True)) else empty_frame(ADJUSTED_COLUMNS)
    family_summary = _family_summary(audit, comparison)
    schema_version = str(config.get("comparison_schema_version") or COMPARISON_SCHEMA_VERSION)
    plots = _plots_payload(comparison, adjusted, family_summary, distributions, schema_version=schema_version)

    for column in AUDIT_COLUMNS:
        if column not in audit:
            audit[column] = None
    audit = audit[AUDIT_COLUMNS]
    tested_count = int(comparison["hypothesis_status"].eq("tested").sum()) if not comparison.empty else 0
    registry_count = int(audit.shape[0])
    discovered_count = int(audit["discovered"].fillna(False).astype(bool).sum())
    materialized_count = int((
        audit["materialized"].fillna(False).astype(bool)
        & audit["ml_role"].isin(["eligible", "conditional"])
    ).sum())
    skipped_count = int(audit["status"].eq("skipped").sum())
    skipped_candidate_count = int((
        audit["status"].eq("skipped")
        & audit["ml_role"].isin(["eligible", "conditional"])
    ).sum())
    excluded_count = int(audit["status"].eq("excluded").sum())
    descriptive_count = int(audit["status"].eq("descriptive_only").sum())
    hvg_mask = coerce_hvg_mask(df[hvg_flag_col])
    significant_count = int((pd.to_numeric(comparison.get("global_fdr"), errors="coerce") < 0.05).sum()) if not comparison.empty else 0
    moderate_strong = int(comparison["evidence_level"].isin([
        "statistical_association_moderate", "statistical_association_strong"
    ]).sum()) if not comparison.empty else 0
    adjusted_robust = int((
        adjusted["adjusted_status"].eq("tested")
        & (pd.to_numeric(adjusted["adjusted_global_fdr"], errors="coerce") < 0.05)
    ).sum()) if not adjusted.empty else 0
    include_conditional = bool(config.get("comparison_include_conditional", False))
    candidate_mask = _eligible_universe_mask(audit, include_conditional)
    candidate_audit = audit.loc[candidate_mask]
    closed_candidate = candidate_audit["status"].isin(["tested", "descriptive_only"]).all() if not candidate_audit.empty else False
    block_issue = any(
        str(value).lower() in {"partial", "unavailable", "failed"}
        for value in audit["block_status"].dropna().tolist()
    )
    status = "complete" if resolved_blocks and not candidate_audit.empty and closed_candidate and not block_issue else (
        "partial" if tested_count or resolved_blocks else "unavailable"
    )
    warnings: list[dict[str, str]] = []
    if status == "partial":
        warnings.append({"code": "partial_feature_universe", "message": "Some Core fields were unavailable or failed job-level QC; inspect the feature audit."})
    if audit["composition_group"].fillna("").astype(str).ne("").any():
        warnings.append({"code": "compositional_dependence", "message": "Composition members are constrained and are not independent biological findings."})
    if audit["warnings"].fillna("").astype(str).str.contains("length_related_proxy").any():
        warnings.append({"code": "length_related_proxy", "message": "Length/count/mass features require adjusted interpretation."})
    auto_degradations: list[dict[str, Any]] = []
    capped_features = statistics_metadata.get("bootstrap_capped_features") or []
    if capped_features:
        degradation = {
            "code": "bootstrap_group_cap_applied",
            "message": "Bootstrap confidence intervals used deterministic group-size caps for large features.",
            "feature_count": len(capped_features),
            "feature_keys": capped_features,
            "max_group_n": int(config.get("comparison_bootstrap_max_group_n", 1000)),
        }
        auto_degradations.append(degradation)
        warnings.append({"code": degradation["code"], "message": degradation["message"]})
    if int(config.get("comparison_bootstrap_ci_repeats", 500)) <= 1:
        degradation = {
            "code": "bootstrap_ci_disabled",
            "message": "Bootstrap confidence intervals were disabled by configuration.",
        }
        auto_degradations.append(degradation)
        warnings.append(degradation)

    tested_comparison = comparison.loc[comparison["hypothesis_status"].eq("tested")].copy() if not comparison.empty else comparison
    top = tested_comparison.assign(abs_effect=pd.to_numeric(tested_comparison.get("effect_value"), errors="coerce").abs()).sort_values(
        ["abs_effect", "global_fdr"], ascending=[False, True]
    ).head(20).drop(columns=["abs_effect"]) if not tested_comparison.empty else tested_comparison
    raw_requested = config.get("comparison_omics") or ["genome", "transcriptome", "proteome"]
    if isinstance(raw_requested, str):
        requested_omics = [item.strip().lower() for item in raw_requested.replace("+", ",").split(",") if item.strip()]
    else:
        requested_omics = [str(item).strip().lower() for item in raw_requested if str(item).strip()]
    summary = {
        "status": status,
        "comparison_status": status,
        "schema_version": schema_version,
        "comparison_schema_version": schema_version,
        "evidence_rule_version": EVIDENCE_RULE_VERSION,
        "registry_version": registry_version,
        "resolved_blocks": resolved_blocks,
        "requested_omics": requested_omics,
        "scope": {
            "requested_omics": requested_omics,
            "available_omics": resolved_blocks,
            "include_conditional": include_conditional,
            "source_mode": "platform_registry_core" if schema_version == COMPARISON_SCHEMA_VERSION else "legacy_user_feature",
        },
        "n_hvg": int(hvg_mask.sum()),
        "n_nonhvg": int((~hvg_mask).sum()),
        "counts": {
            "registry_fields": registry_count,
            "audited_core_fields": registry_count,
            "eligible_candidate_fields": int(audit["ml_role"].eq("eligible").sum()),
            "conditional_fields": int(audit["ml_role"].eq("conditional").sum()),
            "excluded_registry_fields": int(audit["ml_role"].eq("exclude").sum()),
            "discovered_fields": discovered_count,
            "materialized_candidate_fields": materialized_count,
            "tested_fields": tested_count,
            "skipped_fields": skipped_count,
            "skipped_candidate_fields": skipped_candidate_count,
            "excluded_fields": excluded_count,
            "descriptive_only_fields": descriptive_count,
            "global_fdr_lt_0_05": significant_count,
            "significant_fields": significant_count,
            "moderate_strong_fields": moderate_strong,
            "adjusted_robust_fields": adjusted_robust,
        },
        "top_features": _records(top),
        "family_summary": _records(family_summary),
        "artifacts": ARTIFACTS,
        "context_artifacts": CONTEXT_ARTIFACTS,
        "warnings": warnings,
        "auto_degradations": auto_degradations,
        "interpretation": "Direct HVG versus non-HVG association; non-causal and distinct from model importance.",
        "method_boundary": "association_not_causation",
    }
    public_config = _public_config(config)
    eligible_count = int(audit["ml_role"].eq("eligible").sum())
    conditional_count = int(audit["ml_role"].eq("conditional").sum())
    registry_exclude_count = int(audit["ml_role"].eq("exclude").sum())
    finished_at = _utc_now()
    manifest = {
        "comparison_schema_version": schema_version,
        "schema_version": schema_version,
        "evidence_rule_version": EVIDENCE_RULE_VERSION,
        "registry_version": registry_version,
        "status": status,
        "comparison_status": status,
        "code_version": public_config.get("code_version") or public_config.get("release_version") or "not_available",
        "started_at_utc": started,
        "finished_at_utc": finished_at,
        "runtime_seconds": round(time.perf_counter() - timer_started, 6),
        "input_path": Path(str(config.get("comparison_input_csv") or config.get("input_baseline_csv") or config.get("comparison_input_path") or "")).name,
        "input_sha256": _sha256(config.get("comparison_input_csv") or config.get("input_baseline_csv") or config.get("comparison_input_path")),
        "input_logical_id": public_config.get("input_logical_id"),
        "case_id": public_config.get("case_id"),
        "case_input_path": public_config.get("case_input_path"),
        "case_input_sha256": public_config.get("case_input_sha256"),
        "job_identifier": public_config.get("job_id") or public_config.get("case_id"),
        "hvg_label_source": hvg_flag_col,
        "phase1_metadata": _public_value(phase1_metadata or {}),
        "mapping": _public_value(_mapping_summary(mapping_context)),
        "mapping_context": _public_value(mapping_context or {}),
        "resolved_blocks": resolved_blocks,
        "feature_universe": {
            "registry_fields": registry_count,
            "discovered_fields": discovered_count,
            "tested_fields": tested_count,
        },
        "feature_selection": {
            "scope": "core",
            "include_conditional": bool(config.get("comparison_include_conditional", False)),
            "resolved_blocks": resolved_blocks,
            "registry_fields": registry_count,
            "eligible_fields": eligible_count,
            "conditional_fields": conditional_count,
            "exclude_fields": registry_exclude_count,
            "discovered_fields": discovered_count,
            "tested_fields": tested_count,
            "skipped_fields": skipped_count,
            "descriptive_only_fields": descriptive_count,
            "excluded_fields": excluded_count,
            "materialized_candidate_fields": materialized_count,
            "skipped_candidate_fields": skipped_candidate_count,
        },
        "provenance": {
            "strategy": "joined columns + registry + mapping metadata",
            "explicit_manifest_present": bool(config.get("comparison_feature_provenance")),
            "resolution_modes": sorted(set(audit["provenance_resolution"].dropna().astype(str))),
            "source_columns": sorted(set(audit.loc[audit["source_column"].fillna("").ne(""), "source_column"].astype(str))),
        },
        "qc": {
            "min_group_n": min_group_n,
            "max_missing_rate": max_missing_rate,
            "near_constant_rule": f"numeric std(ddof=0) <= {float(config.get('comparison_near_constant_tolerance', 1e-12))}",
            "range_policy": "out-of-range values become missing with an audit warning; no clipping",
            "unit_anomaly_policy": "majority out-of-range for bounded fraction features",
            "duplicate_policy": "one exact representative tested; duplicates descriptive_only",
            "high_correlation_threshold": float(config.get("comparison_high_correlation_threshold", 0.995)),
            "zero_semantics_policy": "applicability masks remove non-applicable rows; applicable numeric zero is retained",
            "applicability_policy": config.get("comparison_applicability_policy", "v2"),
            "applicable_values": sorted(set(config.get("comparison_applicable_values") or ["all", "coding_only", "protein_proxy_only"])),
        },
        "methods": {
            "availability": "feature-wise available-case",
            "continuous_test": "two-sided Mann-Whitney U",
            "continuous_effect": "Cliff's delta derived from U without Cartesian expansion",
            "ci": "stratified bootstrap percentile",
            "bootstrap_repeats": int(config.get("comparison_bootstrap_ci_repeats", 500)),
            "bootstrap_max_group_n": int(config.get("comparison_bootstrap_max_group_n", 1000)),
            "binary_test": "Fisher exact for sparse expected cells; otherwise Pearson chi-square",
            "binary_effect": "odds ratio with 95% CI; group proportions and proportion difference retained",
            "categorical_test": "Pearson chi-square when all observed cells meet the configured minimum",
            "categorical_effect": "Cramer's V with category counts",
            "multiple_testing": "BH global primary across all tested hypotheses; omics and family secondary",
            "fdr_scopes": {"global": "all tested hypotheses", "omics": "within omics", "family": "within family across omics"},
            "adjustment": "gene-level logistic GLM with expression spline, one detection/dropout covariate, and target-specific length",
            "adjustment_policy": config.get("comparison_adjustment_policy", "v2"),
            "composition_adjustment": config.get("comparison_composition_adjustment", "clr_v1"),
            "adjusted_fdr_family": "all successfully fitted target-feature coefficients",
            "standardization": "target and linear covariates use population-SD z scores",
            "collinearity": "condition number > 1e8 removes length then detection; persistent cases fail explicitly",
        },
        "adjustment": {
            "policy_version": config.get("comparison_adjustment_policy", "v2"),
            "composition_transform": config.get("comparison_composition_adjustment", "clr_v1"),
            "composition_pseudocount_fraction": float(config.get("comparison_composition_pseudocount_fraction", 1e-6)),
            "composition_groups": {
                str(group): sorted(audit.loc[audit["composition_group"].astype(str).eq(str(group)), "feature_key"].astype(str).tolist())
                for group in sorted(set(audit["composition_group"].fillna("").astype(str)) - {""})
            },
            "effective_rows": {
                str(row.get("feature_key")): int(row.get("n_used") or 0)
                for row in adjusted.to_dict(orient="records")
            },
        },
        "thresholds": {"min_group_n": min_group_n, "max_missing_rate": max_missing_rate},
        "random_state": int(config.get("random_state", 42)),
        "limits": {
            "bootstrap_repeats": int(config.get("comparison_bootstrap_ci_repeats", 500)),
            "bootstrap_max_group_n": int(config.get("comparison_bootstrap_max_group_n", 1000)),
            "worker_count": int(config.get("comparison_worker_count", 1)),
            "api_page_size_max": int(config.get("comparison_api_page_size_max", 200)),
            "single_feature_display_point_cap": int(config.get("comparison_display_point_cap", 240)),
            "categorical_min_cell_count": int(config.get("comparison_categorical_min_cell_count", 5)),
        },
        "auto_degradations": auto_degradations,
        "warnings": warnings,
        "config_sha256": _config_sha256(public_config),
        "config": public_config,
        "artifacts": ARTIFACTS,
        "context_artifacts": CONTEXT_ARTIFACTS,
    }
    if output_dir is not None:
        manifest["block_coverage_path"] = Path(str(config.get("comparison_block_coverage_path") or CONTEXT_ARTIFACTS["block_coverage"])).name
        coverage_path = _update_block_coverage(Path(output_dir), config, audit, comparison)
        try:
            coverage_frame = pd.read_csv(coverage_path)
            summary["block_coverage"] = _records(coverage_frame)
        except Exception:
            summary["block_coverage"] = []
    if output_dir is not None:
        _write_artifacts(
            Path(output_dir),
            audit=audit,
            comparison=comparison,
            adjusted=adjusted,
            quantiles=quantiles,
            family_summary=family_summary,
            plots=plots,
            summary=summary,
            manifest=manifest,
        )
    return {
        "summary": summary,
        "manifest": manifest,
        "plots": plots,
        "feature_audit": audit,
        "feature_comparison": comparison,
        "adjusted_comparison": adjusted,
        "distribution_quantiles": quantiles,
        "family_summary": family_summary,
    }
