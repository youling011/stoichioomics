from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable
import json

import pandas as pd
from django.conf import settings

from backend.apps.jobs.models import AnalysisJob
from backend.input_adapter.format_detector import detect_uploaded_files
from backend.input_adapter.orientation_detector import detect_tabular_orientation
from backend.input_adapter.matrix_semantics_detector import detect_tabular_matrix_semantics
from backend.mode_resolver.capability_matrix import build_capability_matrix
from backend.portal.config_builder import build_full_pipeline_config, build_preanalysis_config
from backend.validation.metadata_automap import automap_metadata_fields
from backend.validation.stoich_readiness import inspect_stoich_readiness
from backend.apps.jobs.stoich_registry_resolver import resolve_registry_stoich_for_job, write_registry_resolution_report


PROFILE_DEFAULTS = {
    "quick_exploratory": {
        "phase1_analysis": {"hvg_method": "seurat_v3", "n_top_genes": 1000, "loess_span": 0.3},
        "phase2_stoich": {
            "model_type": "ridge",
            "n_cv_folds": 3,
            "permutation_repeats": 3,
            "bootstrap_repeats": 10,
            "enable_functional_enrichment": True,
            "functional_enrichment_top_n": 200,
            "functional_enrichment_min_overlap": 2,
            "functional_enrichment_min_term_size": 3,
            "functional_enrichment_max_term_size": 500,
            "functional_enrichment_fdr": 0.05,
            "functional_gsea_permutations": 20,
        },
    },
    "standard_guided": {
        "phase1_analysis": {"hvg_method": "seurat_v3", "n_top_genes": 2000, "loess_span": 0.3, "enable_scanpy_backend": False},
        "phase2_stoich": {
            "model_type": "elasticnet",
            "n_cv_folds": 5,
            "permutation_repeats": 8,
            "bootstrap_repeats": 40,
            "enable_functional_enrichment": True,
            "functional_enrichment_top_n": 300,
            "functional_enrichment_min_overlap": 2,
            "functional_enrichment_min_term_size": 3,
            "functional_enrichment_max_term_size": 500,
            "functional_enrichment_fdr": 0.05,
            "functional_enrichment_report_terms": 200,
            "functional_enrichment_plot_terms": 30,
            "functional_gsea_permutations": 100,
        },
    },
    "publication_grade": {
        "phase1_analysis": {"hvg_method": "seurat_v3", "n_top_genes": 3000, "loess_span": 0.3, "enable_scanpy_backend": False, "enable_seurat_r_backend": False},
        "phase2_stoich": {
            "model_type": "elasticnet",
            "n_cv_folds": 5,
            "permutation_repeats": 25,
            "bootstrap_repeats": 80,
            "strict_phase2_id_mapping": True,
            "enable_functional_enrichment": True,
            "functional_enrichment_top_n": 500,
            "functional_enrichment_min_overlap": 2,
            "functional_enrichment_min_term_size": 3,
            "functional_enrichment_max_term_size": 500,
            "functional_enrichment_fdr": 0.05,
            "functional_enrichment_report_terms": 300,
            "functional_enrichment_plot_terms": 40,
            "functional_gsea_permutations": 1000,
        },
    },
}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_dict(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in (updates or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def _read_expression_gene_ids(raw_dir: Path, expression: Dict[str, Any], orientation: str | None) -> list[str]:
    fmt = expression.get("detected_format")
    filename = expression.get("file")
    if not filename:
        return []
    path = raw_dir / filename
    try:
        if fmt in {"csv", "tsv"}:
            sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
            df = pd.read_csv(path, sep=sep, nrows=100000)
            if orientation == "cell_by_gene":
                return [str(c) for c in df.columns[1:]]
            first = df.columns[0]
            return df[first].astype(str).tolist()
        if fmt == "h5ad":
            import anndata as ad
            adata = ad.read_h5ad(path, backed="r")
            return [str(x) for x in adata.var_names.tolist()]
        if fmt == "tenx":
            features = raw_dir / "features.tsv"
            if not features.exists():
                features = raw_dir / "genes.tsv"
            if features.exists():
                fdf = pd.read_csv(features, sep="\t", header=None)
                return fdf.iloc[:, 0].astype(str).tolist()
    except Exception:
        return []
    return []


def _build_skipped_outputs(capability: Dict[str, Any]) -> Dict[str, Any]:
    rows = []
    for mode, item in (capability.get("modes") or {}).items():
        if item.get("status") == "skipped":
            rows.append({
                "mode": mode,
                "status": "skipped",
                "reason_code": item.get("reason_code"),
                "block_entire_job": False,
            })
    return {"skipped": rows}


def _detect_h5ad_matrix_semantics(path: Path) -> Dict[str, Any]:
    import anndata as ad

    adata = ad.read_h5ad(path, backed="r")
    try:
        nested = adata.uns.get("stoichioomics_input") or {}
        semantics = adata.uns.get("matrix_semantics") or nested.get("matrix_semantics")
    finally:
        if getattr(adata, "file", None) is not None:
            adata.file.close()
    if semantics in {"raw_counts", "normalized", "log_normalized"}:
        return {
            "matrix_semantics": semantics,
            "confidence": "high",
            "need_user_confirmation": False,
            "evidence": ["h5ad_uns_matrix_semantics"],
        }
    return {
        "matrix_semantics": "unknown",
        "confidence": "medium",
        "need_user_confirmation": False,
        "evidence": ["h5ad_semantics_requires_user_or_uns_context"],
    }


def build_job_auto_config(
    job: AnalysisJob,
    profile: str = "standard_guided",
    user_overrides: Dict[str, Any] | None = None,
    pipeline_type: str = "full",
    write_config: bool = True,
) -> Dict[str, Any]:
    profile = profile if profile in PROFILE_DEFAULTS else "standard_guided"
    user_overrides = user_overrides or {}
    job_dir = Path(job.workspace_path)
    raw_dir = job_dir / "raw"
    cfg_dir = job_dir / "configs"
    logs_dir = job_dir / "logs"
    detect = detect_uploaded_files(raw_dir)

    expr = detect.get("expression") or {}
    expression_file = expr.get("file")
    orientation_report = {"orientation": "auto", "confidence": "low", "need_user_confirmation": True, "evidence": []}
    semantics_report = {"matrix_semantics": "auto", "confidence": "low", "need_user_confirmation": True, "evidence": []}
    if expr.get("status") == "ready" and expr.get("detected_format") in {"csv", "tsv"} and expression_file:
        expression_path = raw_dir / expression_file
        orientation_report = detect_tabular_orientation(expression_path)
        semantics_report = detect_tabular_matrix_semantics(expression_path)
    elif expr.get("status") == "ready" and expr.get("detected_format") == "tenx":
        orientation_report = {"orientation": "cell_by_gene", "confidence": "high", "need_user_confirmation": False, "evidence": ["10x_matrix_contract"]}
        semantics_report = {"matrix_semantics": "raw_counts", "confidence": "high", "need_user_confirmation": False, "evidence": ["10x_counts_contract"]}
    elif expr.get("status") == "ready" and expr.get("detected_format") == "h5ad":
        orientation_report = {"orientation": "cell_by_gene", "confidence": "high", "need_user_confirmation": False, "evidence": ["h5ad_anndata_contract"]}
        semantics_report = _detect_h5ad_matrix_semantics(raw_dir / expression_file)

    metadata_file = (detect.get("metadata") or {}).get("file")
    metadata_mapping = automap_metadata_fields(raw_dir / metadata_file if metadata_file else None)
    expression_gene_ids = _read_expression_gene_ids(raw_dir, expr, orientation_report.get("orientation"))
    stoich_file = (detect.get("stoich") or {}).get("file")
    stoich_registry_resolution = resolve_registry_stoich_for_job(
        job,
        raw_dir,
        user_overrides=user_overrides,
        expression_gene_ids=expression_gene_ids,
        existing_stoich_file=stoich_file,
    )
    if not stoich_file and stoich_registry_resolution.get("status") in {"registry_feature_materialized", "sequence_feature_materialized"}:
        stoich_file = str(stoich_registry_resolution.get("file") or "")
        detect["stoich"] = {
            "status": "ready",
            "file": stoich_file,
            "confidence": "high",
            "evidence": [f"{stoich_registry_resolution.get('source')}_feature_materialized"],
            "source": stoich_registry_resolution.get("source") or "auto_materialized",
            "registry_resolution": stoich_registry_resolution,
        }
    write_registry_resolution_report(job, stoich_registry_resolution)
    stoich_readiness = inspect_stoich_readiness(raw_dir / stoich_file if stoich_file else None, expression_gene_ids=expression_gene_ids)
    if stoich_registry_resolution.get("status") in {"registry_feature_materialized", "sequence_feature_materialized"}:
        stoich_readiness = {
            **stoich_readiness,
            "source": stoich_registry_resolution.get("source") or "auto_materialized",
            "registry_resolution": stoich_registry_resolution,
        }
    capability = build_capability_matrix(expr.get("status") == "ready", metadata_mapping, stoich_readiness)

    input_format = expr.get("detected_format") or "auto"
    expression_cfg: Dict[str, Any] = {"value_semantics": semantics_report.get("matrix_semantics") or "unknown"}
    if expression_file:
        expression_cfg["file"] = expression_file
    if input_format in {"csv", "tsv"}:
        expression_cfg["orientation"] = orientation_report.get("orientation") or "auto"
        expression_cfg["gene_id_col"] = "gene_id"
    if input_format == "tenx":
        expression_cfg = {"matrix_file": "matrix.mtx", "features_file": "features.tsv", "barcodes_file": "barcodes.tsv", "value_semantics": "raw_counts"}
    metadata_cfg_file = metadata_file if metadata_file else None
    stoich_cfg = {"file": stoich_file, "require": False} if stoich_file else {"require": False}

    overrides = _merge_dict(PROFILE_DEFAULTS[profile], user_overrides)
    overrides.setdefault('hvg_research', {})['enabled'] = True
    overrides.setdefault('phase2_stoich', {})['model_enabled'] = False
    overrides['phase2_stoich']['model_skip_reason'] = 'removed_from_unified_workflow'
    overrides.setdefault('phase1_analysis', {})['run_supported_auxiliary_modes'] = True
    if (overrides.get('hvg_research') or {}).get('enabled'):
        overrides.setdefault('phase1_analysis',{}).setdefault('primary_backend','scanpy')
        overrides['phase1_analysis'].setdefault('matrix_semantics',expression_cfg.get('value_semantics','unknown'))
        from backend.apps.jobs.stoich_registry_resolver import _resolve_species_id
        declared=_resolve_species_id((job.metadata_json or {}).get('species_id') or '')
        if declared:
            if resolved := stoich_registry_resolution.get('species_id'):
                if resolved != declared:raise ValueError('Declared and resolved species conflict')
            overrides.setdefault('phase2_stoich',{})['species_id']=declared
    resolved_species_id = stoich_registry_resolution.get("species_id")
    resolved_omics = stoich_registry_resolution.get("omics")
    resolved_feature_set = stoich_registry_resolution.get("feature_set")
    if resolved_species_id:
        overrides = _merge_dict(overrides, {
            "phase2_stoich": {
                "species_id": resolved_species_id,
                "omics": resolved_omics or "transcriptome",
                "feature_set": resolved_feature_set or "core",
                "stoich_feature_source": stoich_registry_resolution.get("source") or "not_resolved",
            }
        })
    if capability["modes"].get("phase2_stoich", {}).get("status") != "available":
        # Stoich model readiness must not suppress the independent
        # HVG/non-HVG comparison branch.
        overrides = _merge_dict(overrides, {
            "phase2_stoich": {
                "enabled": True,
                "model_enabled": False,
                "model_skip_reason": stoich_readiness.get("reason_code") or "phase2_not_ready",
            }
        })
    if capability.get("primary_mode"):
        overrides = _merge_dict(overrides, {"phase1_analysis": {"analysis_mode": capability["primary_mode"]}})

    if pipeline_type == "preanalysis":
        effective_config = build_preanalysis_config(settings.BASE_DIR, settings.WORKSPACE_ROOT, job.job_id, input_format, expression_cfg, metadata_cfg_file, stoich_cfg)
    else:
        effective_config = build_full_pipeline_config(settings.BASE_DIR, settings.WORKSPACE_ROOT, job.job_id, input_format, expression_cfg, metadata_cfg_file, stoich_cfg, overrides)
    if metadata_cfg_file and "input_adapter" in effective_config:
        effective_config["input_adapter"].setdefault("metadata", {})["field_mapping"] = metadata_mapping

    warnings = []
    warnings.extend(detect.get("warnings") or [])
    warnings.extend(metadata_mapping.get("warnings") or [])
    if metadata_mapping.get("status") == "missing":
        warnings.append({"code": "NO_METADATA_GLOBAL_ONLY", "severity": "info", "message": "未检测到 metadata，将运行全局 HVG；metadata 相关模式会跳过。"})
    if not stoich_readiness.get("phase2_ready"):
        warnings.append({"code": "PHASE2_MODEL_SKIPPED", "severity": "info", "message": stoich_readiness.get("message")})
    if stoich_registry_resolution.get("sequence_upload_required"):
        warnings.append({
            "code": "SEQUENCE_FEATURE_UPLOAD_REQUIRED",
            "severity": "info",
            "message": stoich_registry_resolution.get("message") or "No registry stoich feature table was resolved; upload sequence data in the sequence analysis workflow or provide a stoich feature table.",
            "action": {
                "label": "Open sequence upload workflow",
                "to": stoich_registry_resolution.get("sequence_upload_endpoint") or "/sequence-analysis",
            },
        })
    blocking_errors = [w for w in warnings if w.get("severity") == "error"]
    model_will_run = False
    comparison_cfg = (overrides.get("phase2_stoich") or {})
    comparison_will_run = bool(comparison_cfg.get("enable_hvg_nonhvg_comparison", True)) and bool(comparison_cfg.get("comparison_context_enabled", True))
    recommended_run_plan = {
        "profile": profile,
        "expression_matrix": expr,
        "metadata": {
            "status": metadata_mapping.get("status"),
            "detected_fields": metadata_mapping.get("detected_fields", []),
            "unavailable_fields": metadata_mapping.get("unavailable_fields", []),
        },
        "stoich_features": stoich_readiness,
        "stoich_registry_resolution": stoich_registry_resolution,
        "phase1": {
            "will_run": expr.get("status") == "ready",
            "primary_mode": capability.get("primary_mode"),
            "auxiliary_modes": capability.get("auxiliary_modes", []),
        },
        "phase2": {
            "will_run": model_will_run,
            "target_col": "normalized_dispersion",
            "model_type": (overrides.get("phase2_stoich") or {}).get("model_type", "elasticnet"),
        },
        "model": {
            "will_run": model_will_run,
            "status": "removed",
            "reason": "removed_from_unified_workflow",
        },
        "comparison": {
            "will_run": comparison_will_run,
            "status": "planned" if comparison_will_run else "disabled",
            "schema_version": comparison_cfg.get("comparison_schema_version", "hvg_nonhvg_v2"),
            "requested_omics": comparison_cfg.get("comparison_omics", ["genome", "transcriptome", "proteome"]),
            "scope": "core",
        },
        "skipped": _build_skipped_outputs(capability)["skipped"],
    }
    auto_detect_report = {
        **detect,
        "orientation": orientation_report,
        "matrix_semantics": semantics_report,
        "expression_gene_count_sampled": len(expression_gene_ids),
        "stoich_registry_resolution": stoich_registry_resolution,
    }
    _write_json(cfg_dir / "auto_detect_report.json", auto_detect_report)
    _write_json(cfg_dir / "metadata_field_mapping.json", metadata_mapping)
    _write_json(cfg_dir / "capability_matrix.json", capability)
    _write_json(cfg_dir / "recommended_run_plan.json", recommended_run_plan)
    _write_json(cfg_dir / "effective_config.json", effective_config)
    _write_json(cfg_dir / "user_overrides.json", user_overrides)
    _write_json(logs_dir / "skipped_outputs.json", _build_skipped_outputs(capability))
    _write_json(logs_dir / "user_warnings.json", {"warnings": warnings})

    config_path = None
    if write_config and not blocking_errors:
        from .research_config_guard import validate_job_research_config
        validate_job_research_config(job,effective_config)
        import yaml
        cfg_path = cfg_dir / f"{pipeline_type}_pipeline.yaml"
        cfg_path.write_text(yaml.safe_dump(effective_config, sort_keys=False, allow_unicode=True), encoding="utf-8")
        job.config_path = str(cfg_path)
        job.pipeline_type = pipeline_type
        job.status = AnalysisJob.Status.READY
        job.save(update_fields=["config_path", "pipeline_type", "status", "updated_at"])
        config_path = str(cfg_path)

    return {
        "auto_detect_report": auto_detect_report,
        "metadata_field_mapping": metadata_mapping,
        "capability_matrix": capability,
        "recommended_run_plan": recommended_run_plan,
        "effective_config": effective_config,
        "warnings": warnings,
        "blocking_errors": blocking_errors,
        "effective_config_path": config_path,
        "ready_to_run": bool(config_path and not blocking_errors),
    }
