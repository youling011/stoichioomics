from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd

from backend.portal.results import load_case_outputs
from backend.apps.jobs.models import AnalysisJob
from backend.apps.registry.services import list_cases
from backend.apps.common.json_safe import sanitize_for_json


def _resolve_case_base(identifier: str) -> Path | None:
    job = AnalysisJob.objects.filter(job_id=identifier).first()
    if job and job.workspace_path:
        return Path(job.workspace_path)

    for case in list_cases():
        if case["case_id"] == identifier:
            return Path(case["base_dir"])

    return None


def get_case_outputs(identifier: str) -> Dict[str, Any]:
    base = _resolve_case_base(identifier)
    if base is None:
        raise FileNotFoundError(f"Unknown case/job: {identifier}")
    return load_case_outputs(base)


def get_phase1_summary(identifier: str) -> Dict[str, Any]:
    payload = get_case_outputs(identifier).get("phase1_summary") or {}
    return sanitize_for_json(payload)


def get_phase2_summary(identifier: str) -> Dict[str, Any]:
    outputs = get_case_outputs(identifier)
    payload = outputs.get("phase2_summary") or {}
    model = outputs.get("phase2_model") or {}
    if payload and model:
        payload.setdefault("model_info", {})
        payload["model_info"].setdefault("baseline_metrics", model.get("baseline_metrics") or {})
        payload["model_info"].setdefault("model_metrics", model.get("model_metrics") or {})
        payload["model_info"].setdefault("delta_metrics", model.get("delta_metrics") or {})
        payload["model_info"].setdefault("model_diagnostics", model.get("model_diagnostics") or {})
        payload.setdefault("mapping_summary", model.get("mapping_summary") or payload.get("mapping_summary") or {})
        if not payload.get("top_associated_features"):
            payload["top_associated_features"] = model.get("feature_association_top") or []
        payload.setdefault("model_comparison", model.get("model_comparison") or [])
        payload.setdefault("feature_block_importance", model.get("feature_block_importance") or [])
        payload.setdefault("bootstrap_feature_stability", model.get("bootstrap_feature_stability") or [])
        payload.setdefault("negative_control_report", model.get("negative_control_report") or {})
        payload.setdefault("evidence_assessment", model.get("evidence_assessment") or {})
        payload.setdefault("downstream_outputs", payload.get("downstream_outputs") or {})
    payload.setdefault("overview_cards", outputs.get("overview_cards") or {})
    payload.setdefault("tables_payload", outputs.get("tables_payload") or {})
    payload.setdefault("visualization_manifest", outputs.get("visualization_manifest") or {})
    payload.setdefault("hvg_multiomics_mapping_summary", outputs.get("hvg_multiomics_mapping_summary") or {})
    payload.setdefault("hvg_multiomics_assembly_manifest", outputs.get("hvg_multiomics_assembly_manifest") or {})
    coverage = outputs.get("hvg_nonhvg_block_coverage")
    payload.setdefault(
        "hvg_nonhvg_block_coverage",
        sanitize_for_json(coverage.to_dict(orient="records")) if coverage is not None and not coverage.empty else [],
    )
    payload.setdefault("hvg_group_comparison", outputs.get("hvg_nonhvg_summary") or {
        "status": "legacy_not_generated",
        "comparison_status": "legacy_not_generated",
        "reason": "This historical result predates the HVG/non-HVG comparison schema.",
    })
    return sanitize_for_json(payload)


def get_group_comparison_summary(identifier: str) -> Dict[str, Any]:
    outputs = get_case_outputs(identifier)
    summary = outputs.get("hvg_nonhvg_summary")
    if not summary:
        return {
            "status": "legacy_not_generated",
            "comparison_status": "legacy_not_generated",
            "reason": "This historical case/job has not generated hvg_nonhvg_v1 artifacts.",
            "counts": {},
            "resolved_blocks": [],
            "requested_omics": [],
            "hvg_multiomics_mapping_summary": {},
            "hvg_nonhvg_block_coverage": [],
            "top_features": [],
            "family_summary": [],
            "plots": {},
        }
    payload = dict(summary)
    plots = dict(outputs.get("hvg_nonhvg_plots_payload") or {})
    # The overview is deliberately compact. Per-feature display points are
    # exposed only by get_group_comparison_feature_detail().
    plots.pop("feature_distributions", None)
    payload["plots"] = plots
    family = outputs.get("hvg_nonhvg_family_summary")
    if family is not None and not family.empty:
        payload["family_summary"] = sanitize_for_json(family.to_dict(orient="records"))
    payload["mapping_summary"] = outputs.get("hvg_multiomics_mapping_summary") or {}
    payload["assembly_manifest"] = outputs.get("hvg_multiomics_assembly_manifest") or {}
    coverage = outputs.get("hvg_nonhvg_block_coverage")
    payload["block_coverage"] = sanitize_for_json(coverage.to_dict(orient="records")) if coverage is not None and not coverage.empty else []
    provenance = outputs.get("hvg_multiomics_feature_provenance")
    payload["provenance_available"] = bool(provenance is not None and not provenance.empty)
    return sanitize_for_json(payload)


def _group_comparison_frame(outputs: Dict[str, Any]) -> pd.DataFrame:
    audit = outputs.get("hvg_nonhvg_feature_audit")
    if audit is None or audit.empty:
        return pd.DataFrame()
    work = audit.copy()
    comparison = outputs.get("hvg_nonhvg_feature_comparison")
    if comparison is not None and not comparison.empty:
        add_columns = [column for column in comparison.columns if column == "feature_key" or column not in work.columns]
        work = work.merge(comparison[add_columns], on="feature_key", how="left")
    adjusted = outputs.get("hvg_nonhvg_adjusted_comparison")
    if adjusted is not None and not adjusted.empty:
        adjusted = adjusted.rename(columns={
            "effect_ci_low": "adjusted_ci_low",
            "effect_ci_high": "adjusted_ci_high",
            "p_value": "adjusted_p_value",
            "reason": "adjusted_reason",
            "warnings": "adjusted_warnings",
            "covariates": "adjusted_covariates",
        })
        add_columns = [column for column in adjusted.columns if column == "feature_key" or column not in work.columns]
        work = work.merge(adjusted[add_columns], on="feature_key", how="left")
    return work


def get_group_comparison_features(
    identifier: str,
    filters: Optional[Dict[str, Any]] = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "abs_effect",
    sort_order: str = "desc",
) -> Dict[str, Any]:
    outputs = get_case_outputs(identifier)
    work = _group_comparison_frame(outputs)
    manifest = outputs.get("hvg_nonhvg_run_manifest") or {}
    configured_page_size_max = max(1, int(
        (manifest.get("limits") or {}).get("api_page_size_max", 200)
    ))
    filters = filters or {}
    allowed_sort = {
        "feature_key", "omics_layer", "family", "status", "effect_value", "global_fdr",
        "n_hvg", "n_nonhvg", "missing_rate_hvg", "missing_rate_nonhvg",
        "adjusted_odds_ratio", "adjusted_global_fdr",
    }
    if sort_by != "abs_effect" and sort_by not in allowed_sort:
        raise ValueError(f"Unsupported sort_by: {sort_by}")
    normalized_sort_order = str(sort_order).lower()
    if normalized_sort_order not in {"asc", "desc"}:
        raise ValueError(f"Unsupported sort_order: {sort_order}")
    enum_filters = {
        "omics": {"genome", "transcriptome", "proteome"},
        "status": {"tested", "descriptive_only", "skipped", "excluded"},
        "analysis_status": {"tested", "descriptive_only", "skipped", "excluded"},
        "adjustment": {"tested", "skipped", "failed"},
        "direction": {"higher_in_hvg", "lower_in_hvg", "neutral", "not_directional"},
        "evidence": {
            "descriptive", "statistical_association_weak", "statistical_association_moderate",
            "statistical_association_strong", "statistical_association_binary",
            "statistical_association_categorical",
        },
    }
    for key, allowed_values in enum_filters.items():
        value = filters.get(key)
        if value and value not in allowed_values:
            raise ValueError(f"Unsupported {key} filter: {value}")
    if filters.get("omics") and not work.empty and "omics_layer" in work.columns:
        result_omics = set(work["omics_layer"].dropna().astype(str))
        if str(filters["omics"]) not in result_omics:
            raise ValueError(f"Omics block is unavailable for this result: {filters['omics']}")
    page = max(int(page), 1)
    page_size = min(max(int(page_size), 1), configured_page_size_max)
    if work.empty:
        return {"total": 0, "page": page, "page_size": page_size, "rows": []}
    for key, column in [
        ("omics", "omics_layer"), ("family", "family"), ("evidence", "evidence_level"),
        ("direction", "direction"), ("status", "status"), ("adjustment", "adjusted_status"),
        ("analysis_status", "analysis_status" if "analysis_status" in work.columns else "status"),
    ]:
        value = filters.get(key)
        if value and column in work.columns:
            work = work.loc[work[column].fillna("").astype(str) == str(value)]
    significant = filters.get("significant")
    if significant and "global_fdr" in work.columns:
        wanted = str(significant).lower() in {"1", "true", "yes", "significant"}
        fdr = pd.to_numeric(work["global_fdr"], errors="coerce") < 0.05
        work = work.loc[fdr == wanted]
    missing_rate = filters.get("missing_rate")
    if missing_rate not in (None, ""):
        try:
            threshold = float(missing_rate)
            rates = pd.concat([
                pd.to_numeric(work.get("missing_rate_hvg"), errors="coerce"),
                pd.to_numeric(work.get("missing_rate_nonhvg"), errors="coerce"),
            ], axis=1).max(axis=1)
            work = work.loc[rates <= threshold]
        except (TypeError, ValueError):
            raise ValueError(f"Unsupported missing_rate filter: {missing_rate}")
    search = str(filters.get("search") or "").strip().lower()
    if search:
        search_columns = [column for column in ["feature_key", "feature_name", "display_name"] if column in work]
        mask = pd.Series(False, index=work.index)
        for column in search_columns:
            mask |= work[column].fillna("").astype(str).str.lower().str.contains(search, regex=False)
        work = work.loc[mask]

    if sort_by == "abs_effect":
        effect_values = work["effect_value"] if "effect_value" in work else pd.Series(np.nan, index=work.index)
        work = work.assign(_sort_value=pd.to_numeric(effect_values, errors="coerce").abs())
        sort_column = "_sort_value"
    elif sort_by in allowed_sort:
        if sort_by not in work.columns:
            raise ValueError(f"Sort field is unavailable for this result: {sort_by}")
        sort_column = sort_by
    else:
        raise ValueError(f"Unsupported sort_by: {sort_by}")
    work = work.sort_values(sort_column, ascending=normalized_sort_order == "asc", na_position="last")
    work = work.drop(columns=["_sort_value"], errors="ignore")
    total = int(work.shape[0])
    start = (page - 1) * page_size
    rows = work.iloc[start:start + page_size].copy()
    numeric_columns = rows.select_dtypes(include=[np.number]).columns
    rows.loc[:, numeric_columns] = rows.loc[:, numeric_columns].replace([np.inf, -np.inf], np.nan)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "rows": sanitize_for_json(rows.to_dict(orient="records")),
    }


def get_group_comparison_feature_detail(identifier: str, feature_key: str) -> Dict[str, Any]:
    outputs = get_case_outputs(identifier)
    work = _group_comparison_frame(outputs)
    if work.empty or "feature_key" not in work.columns:
        raise FileNotFoundError("HVG/non-HVG comparison artifacts are unavailable")
    match = work.loc[work["feature_key"].astype(str) == str(feature_key)]
    if match.empty:
        raise FileNotFoundError(f"Comparison feature not found: {feature_key}")
    quantiles = outputs.get("hvg_nonhvg_distribution_quantiles")
    quantile_rows = []
    if quantiles is not None and not quantiles.empty and "feature_key" in quantiles:
        quantile_rows = sanitize_for_json(
            quantiles.loc[
                quantiles["feature_key"].astype(str) == str(feature_key)
            ].to_dict(orient="records")
        )
    plots = outputs.get("hvg_nonhvg_plots_payload") or {}
    distribution = (plots.get("feature_distributions") or {}).get(str(feature_key), {})
    provenance = outputs.get("hvg_multiomics_feature_provenance")
    provenance_rows = []
    if provenance is not None and not provenance.empty and "feature_key" in provenance:
        provenance_rows = sanitize_for_json(provenance.loc[provenance["feature_key"].astype(str) == str(feature_key)].to_dict(orient="records"))
    return sanitize_for_json({
        "feature": match.iloc[0].replace([np.inf, -np.inf], np.nan).to_dict(),
        "quantiles": quantile_rows,
        "distribution": distribution,
        "provenance": provenance_rows,
        "applicability": {
            key: match.iloc[0].get(key)
            for key in ["applicability", "zero_semantics", "n_applicable_total", "n_applicable_hvg", "n_applicable_non_hvg", "n_valid_hvg", "n_valid_non_hvg"]
            if key in match.columns
        },
        "adjustment": {
            key: match.iloc[0].get(key)
            for key in ["adjusted_status", "adjusted_global_fdr", "covariates_used", "policy_version", "adjustment_transform", "composition_group"]
            if key in match.columns
        },
        "interpretation": "Direct group association only; it is not model importance or causal evidence.",
    })


def get_plots(identifier: str) -> Dict[str, Any]:
    payload = get_case_outputs(identifier).get("plots_payload") or {}
    return sanitize_for_json(payload)


def get_phase2_model(identifier: str) -> Dict[str, Any]:
    payload = get_case_outputs(identifier).get("phase2_model") or {}
    return sanitize_for_json(payload)


def get_genes(
    identifier: str,
    filters: Optional[Dict[str, Any]] = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str | None = None,
    sort_order: str = "desc",
) -> Dict[str, Any]:
    outputs = get_case_outputs(identifier)
    df = outputs.get("phase2_scores")

    if df is None or df.empty:
        return {"total": 0, "rows": []}

    work = df.copy()
    work = work.replace([np.inf, -np.inf], np.nan)
    filters = filters or {}

    stoich_class = filters.get("stoich_class")
    if stoich_class and "stoich_class" in work.columns:
        work = work.loc[work["stoich_class"].astype(str) == str(stoich_class)]

    legacy_associated_feature_key = "stoich_" + "driver"
    associated_feature = filters.get("stoich_associated_feature") or filters.get(legacy_associated_feature_key)
    if associated_feature and "stoich_associated_feature" in work.columns:
        work = work.loc[work["stoich_associated_feature"].astype(str) == str(associated_feature)]

    gene_query = filters.get("gene_query")
    if gene_query:
        q = str(gene_query).strip().lower()
        cols = [c for c in ["gene_id", "gene_name"] if c in work.columns]
        if cols:
            mask = pd.Series(False, index=work.index)
            for c in cols:
                mask = mask | work[c].fillna("").astype(str).str.lower().str.contains(q, na=False)
            work = work.loc[mask]

    if sort_by and sort_by in work.columns:
        ascending = str(sort_order).lower() == "asc"
        work = work.sort_values(by=sort_by, ascending=ascending, na_position="last")

    total = int(len(work))
    start = max(page - 1, 0) * page_size
    end = start + page_size

    page_df = work.iloc[start:end].copy()
    page_df = page_df.replace([np.inf, -np.inf], np.nan)

    preferred_cols = [
        "gene_id",
        "gene_name",
        "is_hvg",
        "hvg_rank",
        "stoich_class",
        "stoich_associated_feature",
        "stoich_excess_var",
        "stoich_expected_var",
        "observed_hvg_signal",
        "stoich_explained_fraction",
        "stoich_fit_closeness",
        "cost_index",
        "cost_volatility_index",
    ]
    keep_cols = [c for c in preferred_cols if c in page_df.columns]
    if keep_cols:
        page_df = page_df[keep_cols]

    rows = sanitize_for_json(page_df)
    return {
        "total": total,
        "rows": rows,
    }


def get_gene_detail(identifier: str, gene_id: str) -> Dict[str, Any]:
    outputs = get_case_outputs(identifier)

    payload = outputs.get("gene_detail_payload") or {}
    if isinstance(payload, dict):
        by_gene_id = payload.get("by_gene_id") or {}
        if gene_id in by_gene_id:
            return sanitize_for_json(by_gene_id[gene_id])
        rows = payload.get("rows") or []
        for row in rows:
            if str(row.get("gene_id")) == str(gene_id):
                return sanitize_for_json(row)

    df = outputs.get("phase2_scores")
    if df is None or df.empty:
        raise FileNotFoundError("No phase2_scores available")

    row = df[df["gene_id"].astype(str) == str(gene_id)]
    if row.empty:
        raise FileNotFoundError(f"Gene not found: {gene_id}")

    row = row.replace([np.inf, -np.inf], np.nan)
    return sanitize_for_json(row.iloc[0].to_dict())


def get_downloadable_file(identifier: str, kind: str) -> Path:
    base = _resolve_case_base(identifier)
    if base is None:
        raise FileNotFoundError(f"Unknown case/job: {identifier}")

    mapping = {
        "phase1_baseline": base / "analysis_phase1" / "hvg_baseline.csv",
        "auto_detect_report": base / "configs" / "auto_detect_report.json",
        "overview_cards": base / "visualization" / "overview_cards.json",
        "tables_payload": base / "visualization" / "tables_payload.json",
        "visualization_manifest": base / "visualization" / "visualization_manifest.json",
        "download_manifest_table": base / "visualization" / "download_manifest_table.csv",
        "skipped_reason_table": base / "visualization" / "skipped_reason_table.csv",
        "blocked_reason_table": base / "visualization" / "blocked_reason_table.csv",
        "analysis_overview_table": base / "visualization" / "analysis_overview_table.csv",
        "hvg_baseline_top_table": base / "visualization" / "hvg_baseline_top_table.csv",
        "signal_residual_table": base / "visualization" / "signal_residual_table.csv",
        "metadata_field_mapping": base / "configs" / "metadata_field_mapping.json",
        "capability_matrix": base / "configs" / "capability_matrix.json",
        "recommended_run_plan": base / "configs" / "recommended_run_plan.json",
        "effective_config": base / "configs" / "effective_config.json",
        "user_overrides": base / "configs" / "user_overrides.json",
        "skipped_outputs": base / "logs" / "skipped_outputs.json",
        "user_warnings": base / "logs" / "user_warnings.json",
        "phase1_summary": base / "analysis_phase1" / "phase1_mode_summary.json",
        "phase1_method_benchmark": base / "analysis_phase1" / "hvg_method_benchmark.csv",
        "phase1_consensus": base / "analysis_phase1" / "hvg_consensus.csv",
        "phase1_backend_report": base / "analysis_phase1" / "hvg_backend_report.json",
        "mapping_table": base / "validation" / "mapping_table.csv",
        "mapping_conflicts": base / "validation" / "mapping_conflicts.csv",
        "unmatched_genes": base / "validation" / "unmatched_genes.csv",
        "id_mapping_summary": base / "validation" / "id_mapping_summary.json",
        "phase2_scores": base / "analysis_phase2" / "hvg_stoich_scores.csv",
        "phase2_summary": base / "analysis_phase2" / "hvg_summary.json",
        "phase2_model": base / "analysis_phase2" / "hvg_stoich_model.json",
        "feature_associations": base / "analysis_phase2" / "feature_associations.csv",
        "hvg_nonhvg_feature_audit": base / "analysis_phase2" / "hvg_nonhvg_feature_audit.csv",
        "hvg_nonhvg_feature_comparison": base / "analysis_phase2" / "hvg_nonhvg_feature_comparison.csv",
        "hvg_nonhvg_adjusted_comparison": base / "analysis_phase2" / "hvg_nonhvg_adjusted_comparison.csv",
        "hvg_nonhvg_distribution_quantiles": base / "analysis_phase2" / "hvg_nonhvg_distribution_quantiles.csv",
        "hvg_nonhvg_family_summary": base / "analysis_phase2" / "hvg_nonhvg_family_summary.csv",
        "hvg_nonhvg_plots": base / "analysis_phase2" / "hvg_nonhvg_plots_payload.json",
        "hvg_nonhvg_summary": base / "analysis_phase2" / "hvg_nonhvg_summary.json",
        "hvg_nonhvg_manifest": base / "analysis_phase2" / "hvg_nonhvg_run_manifest.json",
        "hvg_multiomics_core_features": base / "analysis_phase2" / "hvg_multiomics_core_features.csv",
        "hvg_multiomics_feature_provenance": base / "analysis_phase2" / "hvg_multiomics_feature_provenance.csv",
        "hvg_multiomics_mapping_table": base / "analysis_phase2" / "hvg_multiomics_mapping_table.csv",
        "hvg_multiomics_mapping_summary": base / "analysis_phase2" / "hvg_multiomics_mapping_summary.json",
        "hvg_multiomics_assembly_manifest": base / "analysis_phase2" / "hvg_multiomics_assembly_manifest.json",
        "hvg_nonhvg_block_coverage": base / "analysis_phase2" / "hvg_nonhvg_block_coverage.csv",
        "candidate_genes": base / "analysis_phase2" / "candidate_gene_table.csv",
        "model_comparison": base / "analysis_phase2" / "model_comparison.csv",
        "cv_predictions": base / "analysis_phase2" / "cv_predictions.csv",
        "feature_block_importance": base / "analysis_phase2" / "feature_block_importance.csv",
        "bootstrap_feature_stability": base / "analysis_phase2" / "bootstrap_feature_stability.csv",
        "negative_control_report": base / "analysis_phase2" / "negative_control_report.json",
        "evidence_assessment": base / "analysis_phase2" / "evidence_assessment.json",
        "phase2_skipped_report": base / "analysis_phase2" / "phase2_skipped_report.json",
        "downstream_summary": base / "analysis_phase2" / "downstream_summary.json",
        "candidate_score_components": base / "downstream" / "candidate_score_components.csv",
        "enrichment_ora": base / "downstream" / "enrichment_ora.csv",
        "functional_enrichment_top_terms": base / "downstream" / "functional_enrichment_top_terms.csv",
        "functional_enrichment_summary": base / "downstream" / "functional_enrichment_summary.json",
        "functional_enrichment_dotplot": base / "downstream" / "functional_enrichment_dotplot.json",
        "gsea_prerank_results": base / "downstream" / "gsea_prerank_results.csv",
        "ppi_module_enrichment": base / "downstream" / "ppi_module_enrichment.csv",
        "plots": base / "analysis_phase2" / "plots_payload.json",
        "gene_details": base / "analysis_phase2" / "gene_detail_payload.json",
        "cache": base / "case_cache.json",
    }

    path = mapping.get(kind)
    if path is None or not path.exists():
        raise FileNotFoundError(f"Download kind not available: {kind}")

    return path
