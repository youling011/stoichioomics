from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable
import json

import numpy as np
import pandas as pd


STOICH_CLASS_ORDER = [
    "canonical_hvg",
    "stoich_explained_hvg",
    "stoich_excess_hvg",
    "stoich_constrained_stable",
    "background_gene",
]

STOICH_CLASS_COLORS = {
    "canonical_hvg": "#2F77C8",
    "stoich_explained_hvg": "#10B981",
    "stoich_excess_hvg": "#EF4444",
    "stoich_constrained_stable": "#8B5CF6",
    "background_gene": "#8AA1B5",
}


def _read_json(path: Path) -> Dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _read_csv(path: Path, nrows: int | None = None) -> pd.DataFrame:
    if path.exists():
        try:
            return pd.read_csv(path, nrows=nrows)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_records(df: pd.DataFrame, limit: int | None = None) -> list[dict]:
    if df is None or df.empty:
        return []
    work = df.head(limit).copy() if limit else df.copy()
    work = work.replace([np.inf, -np.inf], np.nan).where(pd.notnull(work), None)
    return work.to_dict(orient="records")


def _csv(path: Path, df: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return str(path.resolve())


def _status_from_file(path: Path) -> str:
    if path.exists() and path.stat().st_size > 0:
        return "generated"
    return "unavailable"


def _reason_rows(base: Path, phase2_summary: Dict[str, Any], phase1_summary: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for item in phase1_summary.get("skipped_modes") or []:
        rows.append({
            "module": "phase1",
            "item": item.get("mode"),
            "status": item.get("status", "skipped"),
            "reason_code": item.get("reason_code"),
            "reason_message": item.get("message") or "; ".join(item.get("reasons") or []),
            "block_entire_job": False,
        })
    phase2_skip = phase2_summary.get("phase2_skip_reason") or {}
    if phase2_summary.get("phase2_status") == "skipped" or phase2_skip:
        rows.append({
            "module": "phase2",
            "item": "phase2_stoich",
            "status": "skipped",
            "reason_code": phase2_skip.get("reason_code") or "phase2_skipped",
            "reason_message": phase2_skip.get("reason_message") or phase2_skip.get("message") or "Phase 2 was skipped.",
            "block_entire_job": False,
        })
    for name in ["enrichment_ora.csv", "gsea_prerank_results.csv", "functional_enrichment_top_terms.csv", "ppi_module_enrichment.csv"]:
        df = _read_csv(base / "downstream" / name, nrows=5)
        if not df.empty and "status" in df.columns and str(df["status"].iloc[0]).startswith("skipped"):
            rows.append({
                "module": "downstream",
                "item": name,
                "status": "skipped",
                "reason_code": df.get("reason_code", pd.Series(["skipped"])).iloc[0] if "reason_code" in df else "skipped",
                "reason_message": df.get("reason_message", pd.Series(["Downstream resource was not configured."])).iloc[0] if "reason_message" in df else "Downstream resource was not configured.",
                "block_entire_job": False,
            })
    return pd.DataFrame(rows, columns=["module", "item", "status", "reason_code", "reason_message", "block_entire_job"])


def _overview_cards(phase1: Dict[str, Any], phase2: Dict[str, Any], validation: Dict[str, Any], mapping: Dict[str, Any], manifest: Dict[str, Any]) -> Dict[str, Any]:
    warnings = (phase2.get("warnings") or []) + (validation.get("warnings") or [])
    cards = [
        {"key": "total_genes", "label": "Total genes", "value": phase2.get("total_genes") or phase1.get("n_rows_primary"), "status": "success"},
        {"key": "total_hvgs", "label": "HVGs", "value": phase2.get("total_hvgs") or phase1.get("n_hvgs_primary"), "status": "success"},
        {"key": "match_rate", "label": "ID match rate", "value": mapping.get("strict_match_rate") or mapping.get("match_rate"), "format": "percent", "status": "success" if (mapping.get("match_rate") or 0) >= 0.8 else "warning"},
        {"key": "metadata_fields", "label": "Metadata fields", "value": len((validation.get("bundle_summary") or {}).get("metadata_fields_present", []) or []), "status": "info"},
        {"key": "predictive_confidence", "label": "Evidence", "value": ((phase2.get("model_info") or {}).get("model_metrics") or {}).get("predictive_confidence") or phase2.get("phase2_status") or "phase1_only", "status": "info"},
    ]
    workflow = [
        {"step": "Input", "status": "success", "description": (manifest.get("expression") or {}).get("detected_format") or "standardized"},
        {"step": "QC", "status": "success" if validation.get("overall_status") in {"pass", "warning"} else "warning", "description": validation.get("overall_status") or "available"},
        {"step": "Phase1", "status": "success" if phase1.get("primary_output") else "unavailable", "description": phase1.get("analysis_mode") or "global_hvg"},
        {"step": "Phase2", "status": "skipped" if phase2.get("phase2_status") == "skipped" else ("success" if phase2.get("model_info") else "unavailable"), "description": phase2.get("phase2_status") or "stoich_model"},
        {"step": "Downstream", "status": "success" if phase2.get("downstream_outputs") else "skipped", "description": "candidate and enrichment outputs"},
    ]
    return {
        "cards": cards,
        "workflow_status": workflow,
        "status_badges": [
            {"code": w.get("code") or w.get("severity") or "warning", "severity": w.get("severity") or w.get("level") or "warning", "message": w.get("message") or str(w)}
            for w in warnings
        ],
        "interpretation_text": [
            "Overview summarizes which analysis layers ran and whether inputs were sufficient for downstream interpretation.",
            "Skipped modules narrow the analysis scope but do not invalidate generated Phase 1 outputs.",
        ],
    }


def build_visualization_artifacts(base_dir: str | Path) -> Dict[str, Any]:
    base = Path(base_dir)
    vis_dir = base / "visualization"
    phase1_dir = base / "analysis_phase1"
    phase2_dir = base / "analysis_phase2"
    validation_dir = base / "validation"
    if not validation_dir.exists():
        validation_dir = base / "phase2_validation"
    downstream_dir = base / "downstream"

    phase1_summary = _read_json(phase1_dir / "phase1_mode_summary.json")
    phase2_summary = _read_json(phase2_dir / "hvg_summary.json")
    phase2_model = _read_json(phase2_dir / "hvg_stoich_model.json")
    validation_summary = _read_json(validation_dir / "validation_summary.json")
    manifest = _read_json(base / "outputs" / "input_manifest.json") or _read_json(base / "standardized" / "input_manifest.json")
    mapping_summary = phase2_summary.get("mapping_summary") or _read_json(validation_dir / "id_mapping_summary.json")

    p1 = _read_csv(phase1_dir / "hvg_baseline.csv")
    p2 = _read_csv(phase2_dir / "hvg_stoich_scores.csv")
    feature_assoc = _read_csv(phase2_dir / "feature_associations.csv")
    group_audit = _read_csv(phase2_dir / "hvg_nonhvg_feature_audit.csv")
    group_comparison = _read_csv(phase2_dir / "hvg_nonhvg_feature_comparison.csv")
    group_adjusted = _read_csv(phase2_dir / "hvg_nonhvg_adjusted_comparison.csv")
    group_family = _read_csv(phase2_dir / "hvg_nonhvg_family_summary.csv")
    group_summary = _read_json(phase2_dir / "hvg_nonhvg_summary.json")
    model_comp = _read_csv(phase2_dir / "model_comparison.csv")
    cv_pred = _read_csv(phase2_dir / "cv_predictions.csv")
    block_imp = _read_csv(phase2_dir / "feature_block_importance.csv")
    bootstrap = _read_csv(phase2_dir / "bootstrap_feature_stability.csv")
    candidate = _read_csv(phase2_dir / "candidate_gene_table.csv")
    candidate_components = _read_csv(downstream_dir / "candidate_score_components.csv")
    functional_enrichment = _read_csv(downstream_dir / "functional_enrichment_top_terms.csv")
    functional_enrichment_summary = _read_json(downstream_dir / "functional_enrichment_summary.json")
    functional_enrichment_dotplot = _read_json(downstream_dir / "functional_enrichment_dotplot.json")
    method_benchmark = _read_csv(phase1_dir / "hvg_method_benchmark.csv")
    consensus = _read_csv(phase1_dir / "hvg_consensus.csv")
    mapping_table = _read_csv(validation_dir / "mapping_table.csv")
    mapping_conflicts = _read_csv(validation_dir / "mapping_conflicts.csv")

    tables: Dict[str, Any] = {}
    table_specs = {
        "analysis_overview_table": pd.DataFrame([{
            "case_id": phase2_summary.get("case_id") or phase1_summary.get("case_id"),
            "input_mode": (manifest.get("expression") or {}).get("detected_format"),
            "analysis_mode": phase1_summary.get("analysis_mode"),
            "hvg_method": (phase1_summary.get("method_metadata") or {}).get("hvg_method"),
            "phase2_status": phase2_summary.get("phase2_status", "generated" if phase2_model else "unavailable"),
            "comparison_status": group_summary.get("comparison_status") or group_summary.get("status") or "legacy_not_generated",
            "downstream_status": "generated" if (downstream_dir / "candidate_score_components.csv").exists() else "skipped",
            "warnings_count": len(phase2_summary.get("warnings") or []),
        }]),
        "hvg_baseline_top_table": p1.sort_values("hvg_rank", ascending=True).head(100) if "hvg_rank" in p1 else p1.head(100),
        "hvg_summary_stats_table": pd.DataFrame([{
            "n_genes": int(p1.shape[0]) if not p1.empty else 0,
            "n_hvgs": int(p1["is_hvg"].fillna(False).astype(bool).sum()) if "is_hvg" in p1 else 0,
            "hvg_fraction": float(p1["is_hvg"].fillna(False).astype(bool).mean()) if "is_hvg" in p1 and not p1.empty else None,
            "mean_hvg_score": float(pd.to_numeric(p1.get("hvg_score"), errors="coerce").mean()) if not p1.empty and "hvg_score" in p1 else None,
            "hvg_score_semantics": str(p1["hvg_score_semantics"].dropna().iloc[0]) if "hvg_score_semantics" in p1.columns and p1["hvg_score_semantics"].notna().any() else None,
            "mean_normalized_dispersion": float(pd.to_numeric(p1.get("normalized_dispersion"), errors="coerce").mean()) if not p1.empty and "normalized_dispersion" in p1 else None,
        }]),
        "method_benchmark_table": method_benchmark,
        "hvg_consensus_top_table": consensus.head(100),
        "backend_status_table": pd.DataFrame((_read_json(phase1_dir / "hvg_backend_report.json").get("backends") or [])),
        "id_mapping_summary_table": pd.DataFrame([mapping_summary or {}]),
        "mapping_conflicts_top_table": mapping_conflicts.head(100),
        "hvg_stoich_class_table": p2["stoich_class"].value_counts().rename_axis("stoich_class").reset_index(name="count") if "stoich_class" in p2 else pd.DataFrame(),
        "class_definition_table": pd.DataFrame([
            {"stoich_class": "canonical_hvg", "definition": "Expression HVG not primarily assigned to stoich residual/explained classes."},
            {"stoich_class": "stoich_explained_hvg", "definition": "Observed HVG signal is close to stoich expected signal."},
            {"stoich_class": "stoich_excess_hvg", "definition": "Observed HVG signal exceeds stoich expectation."},
            {"stoich_class": "stoich_constrained_stable", "definition": "Stoich/cost signal is notable while HVG signal is constrained."},
            {"stoich_class": "background_gene", "definition": "Gene outside highlighted HVG-stoich categories."},
        ]),
        "class_top_genes_table": candidate.head(100),
        "signal_residual_table": p2[[c for c in ["gene_id", "gene_name", "observed_hvg_signal", "stoich_expected_var", "stoich_excess_var", "stoich_explained_fraction", "stoich_class"] if c in p2.columns]].head(500),
        "top_positive_residual_genes_table": p2.sort_values("stoich_excess_var", ascending=False).head(50) if "stoich_excess_var" in p2 else pd.DataFrame(),
        "top_explained_genes_table": p2.sort_values("stoich_explained_fraction", ascending=False).head(50) if "stoich_explained_fraction" in p2 else pd.DataFrame(),
        "feature_associations_table": feature_assoc,
        "hvg_nonhvg_feature_audit_table": group_audit,
        "hvg_nonhvg_feature_comparison_table": group_comparison,
        "hvg_nonhvg_adjusted_comparison_table": group_adjusted,
        "hvg_nonhvg_family_summary_table": group_family,
        "feature_importance_table": pd.DataFrame(phase2_model.get("feature_importance") or []),
        "feature_block_importance_table": block_imp,
        "model_comparison_table": model_comp,
        "cv_predictions_summary_table": cv_pred.groupby("model_id", dropna=False).agg(n_predictions=("prediction", "count"), mean_prediction=("prediction", "mean")).reset_index() if not cv_pred.empty and "model_id" in cv_pred else pd.DataFrame(),
        "evidence_assessment_table": pd.DataFrame([_read_json(phase2_dir / "evidence_assessment.json")]),
        "negative_control_table": pd.DataFrame([_read_json(phase2_dir / "negative_control_report.json")]),
        "bootstrap_feature_stability_table": bootstrap,
        "candidate_gene_table": candidate,
        "candidate_score_components_table": candidate_components,
        "enrichment_summary_table": _read_csv(downstream_dir / "enrichment_ora.csv"),
        "functional_enrichment_summary_table": pd.DataFrame([functional_enrichment_summary]) if functional_enrichment_summary else pd.DataFrame(),
        "functional_enrichment_top_terms_table": functional_enrichment,
        "top_pathways_table": _read_csv(downstream_dir / "gsea_prerank_results.csv"),
        "ppi_module_enrichment_table": _read_csv(downstream_dir / "ppi_module_enrichment.csv"),
    }
    skipped = _reason_rows(base, phase2_summary, phase1_summary)
    blocked = skipped.loc[skipped["status"].astype(str).eq("blocked")].copy() if not skipped.empty else pd.DataFrame(columns=skipped.columns)
    table_specs["skipped_reason_table"] = skipped
    table_specs["blocked_reason_table"] = blocked

    for key, df in table_specs.items():
        path = vis_dir / f"{key}.csv"
        tables[key] = {
            "status": "generated" if df is not None and not df.empty else "skipped",
            "csv": _csv(path, df if df is not None else pd.DataFrame()),
            "rows": _safe_records(df if df is not None else pd.DataFrame(), limit=300),
            "row_count": int(df.shape[0]) if df is not None else 0,
        }

    download_rows = []
    download_specs = [
        ("phase1", "hvg_baseline.csv", phase1_dir / "hvg_baseline.csv", "Primary HVG table for reuse in R/Python."),
        ("phase1", "hvg_consensus.csv", phase1_dir / "hvg_consensus.csv", "Consensus HVG ranking across enabled backends."),
        ("phase2", "hvg_stoich_scores.csv", phase2_dir / "hvg_stoich_scores.csv", "Per-gene stoich classification and residual scores."),
        ("phase2", "model_comparison.csv", phase2_dir / "model_comparison.csv", "Generic-M0/M1/M2/M3 model metrics."),
        ("phase2_comparison", "hvg_nonhvg_feature_audit.csv", phase2_dir / "hvg_nonhvg_feature_audit.csv", "Core registry field audit for the resolved Transcriptome/Proteome blocks."),
        ("phase2_comparison", "hvg_nonhvg_feature_comparison.csv", phase2_dir / "hvg_nonhvg_feature_comparison.csv", "Direct HVG versus non-HVG statistics, effect sizes, confidence intervals, and FDR."),
        ("phase2_comparison", "hvg_nonhvg_adjusted_comparison.csv", phase2_dir / "hvg_nonhvg_adjusted_comparison.csv", "Gene-level adjusted logistic association results."),
        ("phase2_comparison", "hvg_nonhvg_family_summary.csv", phase2_dir / "hvg_nonhvg_family_summary.csv", "Omics and feature-family summary."),
        ("phase2_comparison", "hvg_nonhvg_run_manifest.json", phase2_dir / "hvg_nonhvg_run_manifest.json", "Reproducible comparison universe, mapping, methods, thresholds, and versions."),
        ("downstream", "candidate_score_components.csv", downstream_dir / "candidate_score_components.csv", "Candidate score decomposition."),
        ("downstream", "enrichment_ora.csv", downstream_dir / "enrichment_ora.csv", "GO/KEGG over-representation analysis against matched same-species annotation background."),
        ("downstream", "functional_enrichment_top_terms.csv", downstream_dir / "functional_enrichment_top_terms.csv", "Top GO/KEGG enrichment terms for publication tables and figures."),
        ("downstream", "gsea_prerank_results.csv", downstream_dir / "gsea_prerank_results.csv", "Candidate-score rank enrichment over GO/KEGG terms."),
        ("downstream", "functional_enrichment_summary.json", downstream_dir / "functional_enrichment_summary.json", "Functional enrichment method and annotation coverage summary."),
        ("downstream", "functional_enrichment_dotplot.json", downstream_dir / "functional_enrichment_dotplot.json", "Frontend-ready GO/KEGG enrichment dotplot payload."),
        ("audit", "visualization_manifest.json", vis_dir / "visualization_manifest.json", "Visualization module registry."),
        ("audit", "tables_payload.json", vis_dir / "tables_payload.json", "Frontend-ready tables payload."),
    ]
    for module, name, path, desc in download_specs:
        download_rows.append({
            "file_name": name,
            "module": module,
            "description": desc,
            "required_for_reuse": module in {"phase1", "phase2", "phase2_comparison"},
            "status": _status_from_file(path),
        })
    download_manifest = pd.DataFrame(download_rows)
    tables["download_manifest_table"] = {
        "status": "generated",
        "csv": _csv(vis_dir / "download_manifest_table.csv", download_manifest),
        "rows": _safe_records(download_manifest),
        "row_count": int(download_manifest.shape[0]),
    }

    overview = _overview_cards(phase1_summary, phase2_summary, validation_summary, mapping_summary, manifest)
    figure_specs = {
        "overview_workflow": {"page": "overview", "type": "status_flow", "status": "generated", "source": "overview_cards.json"},
        "matrix_qc_summary": {"page": "input_qc", "type": "summary_cards", "status": "generated" if validation_summary else "skipped", "source": "validation_summary.json"},
        "id_mapping_donut": {"page": "input_qc", "type": "donut", "status": "generated" if mapping_summary else "skipped", "source": "id_mapping_summary.json"},
        "phase1_mean_hvg_score": {"page": "phase1", "type": "scatter", "status": "generated" if not p1.empty else "skipped", "source": "hvg_baseline.csv", "fields": ["mean_expr", "normalized_dispersion", "hvg_score", "is_hvg"]},
        "phase1_mean_dispersion": {"page": "phase1", "type": "scatter", "status": "generated" if not p1.empty else "skipped", "source": "hvg_baseline.csv", "fields": ["mean_expr", "normalized_dispersion", "is_hvg"], "compatibility_alias_for": "phase1_mean_hvg_score"},
        "phase1_top_hvg": {"page": "phase1", "type": "bar", "status": "generated" if not p1.empty else "skipped", "source": "hvg_baseline.csv"},
        "method_backend_status": {"page": "phase1", "type": "bar_table", "status": "generated" if not method_benchmark.empty else "skipped", "source": "hvg_method_benchmark.csv"},
        "stoich_class_distribution": {"page": "phase2", "type": "bar", "status": "generated" if "stoich_class" in p2 else "skipped", "source": "hvg_stoich_scores.csv"},
        "expected_observed": {"page": "phase2", "type": "identity_scatter", "status": "generated" if "stoich_expected_var" in p2 else "skipped", "source": "hvg_stoich_scores.csv"},
        "residual_distribution": {"page": "phase2", "type": "histogram", "status": "generated" if "stoich_excess_var" in p2 else "skipped", "source": "hvg_stoich_scores.csv"},
        "feature_association_forest": {"page": "phase2", "type": "forest", "status": "generated" if not feature_assoc.empty else "skipped", "source": "feature_associations.csv"},
        "hvg_nonhvg_effect_forest": {"page": "hvg_nonhvg", "type": "forest", "status": "generated" if not group_comparison.empty else group_summary.get("status", "skipped"), "source": "hvg_nonhvg_feature_comparison.csv"},
        "hvg_nonhvg_effect_fdr": {"page": "hvg_nonhvg", "type": "scatter", "status": "generated" if not group_comparison.empty else group_summary.get("status", "skipped"), "source": "hvg_nonhvg_plots_payload.json"},
        "hvg_nonhvg_family_pattern": {"page": "hvg_nonhvg", "type": "heatmap", "status": "generated" if not group_family.empty else group_summary.get("status", "skipped"), "source": "hvg_nonhvg_family_summary.csv"},
        "hvg_nonhvg_raw_adjusted": {"page": "hvg_nonhvg", "type": "scatter", "status": "generated" if not group_adjusted.empty else "skipped", "source": "hvg_nonhvg_adjusted_comparison.csv"},
        "model_comparison": {"page": "model_evidence", "type": "bar", "status": "generated" if not model_comp.empty else "skipped", "source": "model_comparison.csv"},
        "bootstrap_stability": {"page": "model_evidence", "type": "bar", "status": "generated" if not bootstrap.empty else "skipped", "source": "bootstrap_feature_stability.csv"},
        "candidate_score_bubble": {"page": "downstream", "type": "bubble", "status": "generated" if not candidate_components.empty else "skipped", "source": "candidate_score_components.csv"},
        "functional_enrichment_dotplot": {"page": "downstream", "type": "dotplot", "status": functional_enrichment_dotplot.get("status", "skipped") if functional_enrichment_dotplot else ("generated" if not functional_enrichment.empty else "skipped"), "source": "functional_enrichment_dotplot.json"},
    }
    manifest_payload = {
        "page_order": ["overview", "input_qc", "phase1", "context_patterns", "hvg_nonhvg", "phase2", "model_evidence", "downstream", "gene_explorer", "downloads"],
        "class_order": STOICH_CLASS_ORDER,
        "class_colors": STOICH_CLASS_COLORS,
        "figures": figure_specs,
        "tables": {k: {"status": v["status"], "csv": v["csv"], "row_count": v["row_count"]} for k, v in tables.items()},
        "skipped": _safe_records(skipped),
        "interpretation_text": {
            "non_causal": "Associations and predictive signals are non-causal and should be treated as prioritization evidence.",
            "fallback": "Unavailable panels are shown with skipped reasons rather than blank output.",
        },
    }
    _write_json(vis_dir / "overview_cards.json", overview)
    _write_json(vis_dir / "tables_payload.json", tables)
    _write_json(vis_dir / "visualization_manifest.json", manifest_payload)
    _csv(vis_dir / "skipped_reason_table.csv", skipped)
    _csv(vis_dir / "blocked_reason_table.csv", blocked)
    return {
        "visualization_dir": str(vis_dir.resolve()),
        "overview_cards": str((vis_dir / "overview_cards.json").resolve()),
        "tables_payload": str((vis_dir / "tables_payload.json").resolve()),
        "visualization_manifest": str((vis_dir / "visualization_manifest.json").resolve()),
    }
