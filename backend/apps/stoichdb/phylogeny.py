from __future__ import annotations

import csv
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings

from . import phylogeny_analysis

PHYLOGENY_ROOT = Path(settings.BASE_DIR) / "data" / "phylogeny"
DEFAULT_RELEASE_ID = "protist_phylogeny_v1"
ALLOWED_P2_FEATURES = {
    "genome_gc",
    "promoter_gc",
    "genome_n_per_base",
    "transcript_gc",
    "transcript_entropy",
    "transcript_coupling",
    "proteome_n_per_aa",
    "proteome_s_per_aa",
    "proteome_pi",
    "proteome_gravy",
}


class PhylogenyNotFound(Exception):
    pass


def _release_root(release_id: str = "") -> Path:
    return PHYLOGENY_ROOT / (release_id or DEFAULT_RELEASE_ID)


def _registry_path(release_id: str = "") -> Path:
    return _release_root(release_id) / "stage6_platform_registry" / "phylogeny_registry.json"


def _p2_registry_path(release_id: str = "") -> Path:
    return _release_root(release_id) / "stage6_platform_registry" / "phylogeny_p2_registry.json"


def _read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _read_csv(path: Path, limit: int | None = None) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if limit is not None:
        return rows[:limit]
    return rows


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(settings.BASE_DIR)).replace("\\", "/")
    except ValueError:
        return str(path)


def _file_payload(path: Path, label: str, kind: str, description: str) -> dict[str, Any]:
    return {
        "label": label,
        "kind": kind,
        "description": description,
        "path": _relative(path),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "exists": path.exists(),
    }


@lru_cache(maxsize=8)
def registry_payload(release_id: str = "") -> dict[str, Any]:
    registry = _read_json(_registry_path(release_id))
    if not registry:
        return {
            "available": False,
            "release_id": release_id or DEFAULT_RELEASE_ID,
            "message": "No phylogeny P0/P1 registry is available.",
        }
    registry["available"] = True
    p2 = _read_json(_p2_registry_path(release_id))
    if p2:
        registry["p2"] = p2
    return registry


def release_payload(release_id: str = "") -> dict[str, Any]:
    registry = registry_payload(release_id)
    if not registry.get("available"):
        return registry
    summary = registry.get("summary") or {}
    tree = registry.get("tree") or {}
    return {
        "available": True,
        "release_id": registry.get("release_id"),
        "label": registry.get("label"),
        "scope": registry.get("scope"),
        "tree_kind": registry.get("tree_kind"),
        "is_active": registry.get("is_active"),
        "generated_at": registry.get("generated_at"),
        "summary": summary,
        "tree": tree,
        "qc": registry.get("qc") or {},
        "p2": registry.get("p2") or {},
        "limitations": registry.get("limitations") or [],
        "endpoints": [
            "/api/stoichdb/phylogeny/releases/",
            "/api/stoichdb/phylogeny/releases/{release_id}/tree/",
            "/api/stoichdb/phylogeny/releases/{release_id}/validation/",
            "/api/stoichdb/phylogeny/signal/",
            "/api/stoichdb/phylogeny/pgls/",
            "/api/stoichdb/case-studies/case1/phylogeny/",
            "/api/stoichdb/species/{species_id}/phylogeny/",
        ],
    }


def releases_payload() -> dict[str, Any]:
    releases = []
    if PHYLOGENY_ROOT.exists():
        for child in sorted(PHYLOGENY_ROOT.iterdir()):
            if child.is_dir():
                payload = release_payload(child.name)
                if payload.get("available"):
                    releases.append(payload)
    if not releases:
        fallback = release_payload(DEFAULT_RELEASE_ID)
        if fallback.get("available"):
            releases.append(fallback)
    return {
        "active_release_id": DEFAULT_RELEASE_ID if any(item.get("release_id") == DEFAULT_RELEASE_ID for item in releases) else "",
        "count": len(releases),
        "items": releases,
    }


def tree_payload(release_id: str = "") -> dict[str, Any]:
    registry = registry_payload(release_id)
    if not registry.get("available"):
        raise PhylogenyNotFound(f"Unknown phylogeny release: {release_id or DEFAULT_RELEASE_ID}")
    tree_info = registry.get("tree") or {}
    tree_path = Path(settings.BASE_DIR) / str(tree_info.get("newick_path", ""))
    tip_map_path = Path(settings.BASE_DIR) / str(tree_info.get("tip_map_path", ""))
    newick = tree_path.read_text(encoding="utf-8") if tree_path.exists() else ""
    return {
        "release_id": registry.get("release_id"),
        "tree_kind": registry.get("tree_kind"),
        "newick": newick,
        "tree": tree_info,
        "tip_count": registry.get("summary", {}).get("tip_count", 0),
        "tips": _read_csv(tip_map_path, limit=500),
        "limitations": registry.get("limitations") or [],
    }


def validation_payload(release_id: str = "") -> dict[str, Any]:
    registry = registry_payload(release_id)
    if not registry.get("available"):
        raise PhylogenyNotFound(f"Unknown phylogeny release: {release_id or DEFAULT_RELEASE_ID}")
    qc = registry.get("qc") or {}
    report_path = Path(settings.BASE_DIR) / str(qc.get("validation_report_path", ""))
    metrics_path = Path(settings.BASE_DIR) / str(qc.get("qc_metrics_path", ""))
    rank_path = Path(settings.BASE_DIR) / str(qc.get("rank_completeness_path", ""))
    report = _read_json(report_path)
    return {
        "release_id": registry.get("release_id"),
        "status": qc.get("status", report.get("status", "")),
        "summary": registry.get("summary") or {},
        "validation_report": report,
        "qc_metrics": _read_csv(metrics_path),
        "rank_completeness": _read_csv(rank_path),
    }


def p2_payload(release_id: str = "") -> dict[str, Any]:
    registry = registry_payload(release_id)
    if not registry.get("available"):
        raise PhylogenyNotFound(f"Unknown phylogeny release: {release_id or DEFAULT_RELEASE_ID}")
    p2 = registry.get("p2") or _read_json(_p2_registry_path(release_id))
    if not p2:
        raise PhylogenyNotFound(f"No P2 artifacts are available for release: {release_id or DEFAULT_RELEASE_ID}")
    return p2


def trait_matrix(release_id: str = "") -> list[dict[str, str]]:
    p2 = p2_payload(release_id)
    path = Path(settings.BASE_DIR) / str((p2.get("trait_matrix") or {}).get("path", ""))
    return _read_csv(path)


def _active_tree_newick(release_id: str = "") -> str:
    registry = registry_payload(release_id)
    p2 = registry.get("p2") or _read_json(_p2_registry_path(release_id))
    analysis_tree = p2.get("analysis_grade_tree") or {}
    analysis_path = Path(settings.BASE_DIR) / str(analysis_tree.get("newick_path", ""))
    if analysis_path.exists():
        return analysis_path.read_text(encoding="utf-8")
    tree_path = Path(settings.BASE_DIR) / str((registry.get("tree") or {}).get("newick_path", ""))
    return tree_path.read_text(encoding="utf-8") if tree_path.exists() else ""


def signal_payload(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    release_id = payload.get("release_id") or DEFAULT_RELEASE_ID
    p2 = p2_payload(release_id)
    readiness = p2.get("analysis_readiness") or {}
    requested = payload.get("features") or list(ALLOWED_P2_FEATURES)
    if isinstance(requested, str):
        requested = [item.strip() for item in requested.replace(",", "\n").splitlines() if item.strip()]
    features = [feature for feature in requested if feature in ALLOWED_P2_FEATURES]
    if not features:
        raise PhylogenyNotFound("No supported feature was requested.")
    if not readiness.get("pgls_eligible"):
        path = Path(settings.BASE_DIR) / str(readiness.get("signal_readiness_path", ""))
        rows = [row for row in _read_csv(path) if row.get("feature") in features]
        return {
            "release_id": release_id,
            "status": "blocked_no_branch_lengths",
            "blocker": readiness.get("blocker", "no_complete_branch_lengths"),
            "features": rows,
            "method": "Pagel lambda disabled for the active taxonomy reference topology.",
            "limitations": p2.get("limitations") or [],
        }

    matrix = trait_matrix(release_id)
    newick = _active_tree_newick(release_id)
    tips = [row["tip_label"] for row in matrix if row.get("tip_label")]
    tree_matrix = phylogeny_analysis.tree_matrix_from_newick(newick, requested_tips=tips)
    by_tip = {row["tip_label"]: row for row in matrix}
    results = []
    for feature in features:
        y = [float(by_tip[tip][feature]) for tip in tree_matrix.tips]
        result = phylogeny_analysis.pagel_lambda(y, tree_matrix.covariance)
        result.update({"release_id": release_id, "feature": feature, "status": "ok"})
        results.append(result)
    return {"release_id": release_id, "status": "ok", "features": results}


def pgls_payload(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    release_id = payload.get("release_id") or DEFAULT_RELEASE_ID
    formula = str(payload.get("formula") or "proteome_n_per_aa ~ genome_gc + transcript_gc").strip()
    response, predictors = phylogeny_analysis.parse_formula(formula, ALLOWED_P2_FEATURES)
    p2 = p2_payload(release_id)
    readiness = p2.get("analysis_readiness") or {}
    if not readiness.get("pgls_eligible"):
        path = Path(settings.BASE_DIR) / str(readiness.get("pgls_readiness_path", ""))
        rows = [row for row in _read_csv(path) if row.get("formula") == formula]
        return {
            "release_id": release_id,
            "formula": formula,
            "status": "blocked_no_branch_lengths",
            "blocker": readiness.get("blocker", "no_complete_branch_lengths"),
            "precomputed_readiness": rows,
            "method": "PGLS disabled for the active taxonomy reference topology.",
            "limitations": p2.get("limitations") or [],
        }

    matrix = trait_matrix(release_id)
    newick = _active_tree_newick(release_id)
    tips = [row["tip_label"] for row in matrix if row.get("tip_label")]
    tree_matrix = phylogeny_analysis.tree_matrix_from_newick(newick, requested_tips=tips)
    by_tip = {row["tip_label"]: row for row in matrix}
    y = [float(by_tip[tip][response]) for tip in tree_matrix.tips]
    x_cols = {feature: [float(by_tip[tip][feature]) for tip in tree_matrix.tips] for feature in predictors}
    ols = phylogeny_analysis.fit_linear_model(y, x_cols)
    lam = phylogeny_analysis.pagel_lambda(y, tree_matrix.covariance)["lambda"]
    pgls_cov = phylogeny_analysis.lambda_covariance(tree_matrix.covariance, lam)
    pgls = phylogeny_analysis.fit_linear_model(y, x_cols, covariance=pgls_cov)
    return {"release_id": release_id, "formula": formula, "status": "ok", "lambda": lam, "ols": ols, "pgls": pgls}


def case1_phylogeny_payload(release_id: str = "") -> dict[str, Any]:
    p2 = p2_payload(release_id)
    path = Path(settings.BASE_DIR) / str((p2.get("case1_phylogeny") or {}).get("path", ""))
    payload = _read_json(path)
    if not payload:
        raise PhylogenyNotFound("Case 1 phylogeny readiness artifact is missing.")
    return payload


def species_context(species_id: str, release_id: str = "") -> dict[str, Any]:
    registry = registry_payload(release_id)
    if not registry.get("available"):
        raise PhylogenyNotFound(f"Unknown phylogeny release: {release_id or DEFAULT_RELEASE_ID}")
    tip_map_path = Path(settings.BASE_DIR) / str((registry.get("tree") or {}).get("tip_map_path", ""))
    p2 = registry.get("p2") or _read_json(_p2_registry_path(release_id))
    p2_ready = bool((p2.get("analysis_readiness") or {}).get("pgls_eligible"))
    p2_species = {row.get("species_id") for row in trait_matrix(release_id)} if p2_ready else set()
    for row in _read_csv(tip_map_path):
        if row.get("species_id") == species_id:
            effective_pgls = p2_ready and species_id in p2_species
            tip = dict(row)
            tip["pgls_eligible"] = str(effective_pgls).lower()
            if effective_pgls:
                tip["pgls_blocker"] = ""
            return {
                "release_id": registry.get("release_id"),
                "species_id": species_id,
                "tip": tip,
                "tree_kind": registry.get("tree_kind"),
                "topology_eligible": row.get("topology_eligible") == "true",
                "pgls_eligible": effective_pgls,
                "limitations": registry.get("limitations") or [],
            }
    raise PhylogenyNotFound(f"Species is not present in the active phylogeny tip map: {species_id}")


def downloads_payload(release_id: str = "") -> list[dict[str, Any]]:
    root = _release_root(release_id)
    return [
        _file_payload(root / "stage0_source" / "p0_protist_whitelist_species_freeze.csv", "P0 protist whitelist species freeze", "phylogeny_p0_species_freeze", "Frozen platform-screened protist species list used by the P0/P1 phylogeny release."),
        _file_payload(root / "stage1_standardized" / "species_tree.taxonomy_reference.nwk", "Protist taxonomy reference topology Newick", "phylogeny_tree_newick", "Taxonomy-derived Newick topology with complete whitelist tip coverage and no branch lengths."),
        _file_payload(root / "stage1_standardized" / "tip_mapping.csv", "Protist phylogeny tip mapping", "phylogeny_tip_mapping", "Species-to-tip mapping with TaxID, lineage, and eligibility flags."),
        _file_payload(root / "stage2_validation" / "validation_report.json", "Phylogeny P0/P1 validation report", "phylogeny_validation", "Machine-readable validation result, QC metrics, and external download status."),
        _file_payload(root / "stage6_platform_registry" / "phylogeny_registry.json", "Phylogeny platform registry", "phylogeny_registry", "Small registry payload consumed by platform APIs and frontend modules."),
        _file_payload(root / "stage3_analysis_matrix" / "species_trait_matrix.csv", "P2 species trait matrix", "phylogeny_p2_trait_matrix", "Whitelist-restricted species-level stoichiometric feature matrix for lambda/PGLS readiness."),
        _file_payload(root / "stage3_analysis_matrix" / "taxonomy_path_distance_matrix_long.csv", "P2 taxonomy path distance matrix", "phylogeny_p2_taxonomy_distance", "Lineage-path distance diagnostics; not a branch-length phylogenetic distance matrix."),
        _file_payload(root / "stage5_artifacts" / "phylogenetic_signal_readiness.csv", "P2 phylogenetic signal readiness", "phylogeny_p2_signal_readiness", "Per-feature Pagel lambda readiness and controlled blockers."),
        _file_payload(root / "stage5_artifacts" / "pgls_readiness.csv", "P2 PGLS readiness", "phylogeny_p2_pgls_readiness", "Predefined PGLS formula readiness and controlled blockers."),
        _file_payload(root / "stage6_platform_registry" / "phylogeny_p2_registry.json", "P2 phylogeny analysis registry", "phylogeny_p2_registry", "P2 backend-service artifact registry."),
        _file_payload(root / "stage0_source" / "analysis_grade_sequence_inputs" / "analysis_grade_sequence_manifest.csv", "Analysis-grade sequence input manifest", "phylogeny_analysis_grade_sequence_manifest", "Final-whitelist raw-sequence manifest with platform eligibility and normalized proteome paths."),
        _file_payload(root / "stage0_source" / "analysis_grade_sequence_inputs" / "orthofinder_proteome_manifest.csv", "OrthoFinder proteome manifest", "phylogeny_orthofinder_manifest", "List of normalized protein FASTA files prepared from real final-whitelist protist proteomes."),
        _file_payload(root / "stage0_source" / "analysis_grade_sequence_inputs" / "busco_protein_manifest.csv", "BUSCO protein manifest", "phylogeny_busco_manifest", "Per-species protein FASTA inputs recommended for BUSCO proteins mode."),
        _file_payload(root / "stage0_source" / "analysis_grade_sequence_inputs" / "run_analysis_grade_tree_commands.ps1", "Analysis-grade tree command template", "phylogeny_tree_command_template", "Command template for BUSCO/OrthoFinder/MAFFT/ClipKIT/IQ-TREE execution after installing external tools."),
        _file_payload(root / "stage7_analysis_grade" / "final" / "protist_analysis_grade.branch_length.nwk", "Analysis-grade branch-length tree Newick", "phylogeny_analysis_grade_tree_newick", "Final branch-length tree used by runtime Pagel lambda and PGLS when available."),
        _file_payload(root / "stage7_analysis_grade" / "final" / "analysis_grade_tree_validation.json", "Analysis-grade tree validation report", "phylogeny_analysis_grade_tree_validation", "Tip coverage, branch-length, and platform-eligibility validation for the final branch-length tree."),
        _file_payload(root / "stage7_analysis_grade" / "final" / "analysis_grade_tool_versions.json", "Analysis-grade tool versions", "phylogeny_analysis_grade_tool_versions", "Docker image and BUSCO/OrthoFinder/MAFFT/ClipKIT/IQ-TREE versions used for the analysis-grade workflow."),
    ]


def docs_payload() -> dict[str, Any]:
    return {
        "release": release_payload(),
        "data_contracts": [
            {"name": "phylogeny_registry", "path": "data/phylogeny/protist_phylogeny_v1/stage6_platform_registry/phylogeny_registry.json", "purpose": "P0/P1 active release summary, tree metadata, QC status, and platform paths."},
            {"name": "tip_mapping", "path": "data/phylogeny/protist_phylogeny_v1/stage1_standardized/tip_mapping.csv", "purpose": "Stable species_id to Newick tip label mapping for the platform-screened protist whitelist."},
            {"name": "validation_report", "path": "data/phylogeny/protist_phylogeny_v1/stage2_validation/validation_report.json", "purpose": "Coverage, rank completeness, branch-length boundary, and external download status."},
            {"name": "species_trait_matrix", "path": "data/phylogeny/protist_phylogeny_v1/stage3_analysis_matrix/species_trait_matrix.csv", "purpose": "Whitelist-restricted species-level trait matrix used by P2 signal/PGLS services."},
            {"name": "phylogeny_p2_registry", "path": "data/phylogeny/protist_phylogeny_v1/stage6_platform_registry/phylogeny_p2_registry.json", "purpose": "P2 analysis-readiness registry, artifact paths, blockers, and feature list."},
            {"name": "analysis_grade_sequence_manifest", "path": "data/phylogeny/protist_phylogeny_v1/stage0_source/analysis_grade_sequence_inputs/analysis_grade_sequence_manifest.csv", "purpose": "Final-whitelist raw protein/cDNA/DNA/annotation paths, sequence QC, platform eligibility, and normalized proteome outputs."},
            {"name": "orthofinder_proteomes", "path": "data/phylogeny/protist_phylogeny_v1/stage0_source/analysis_grade_sequence_inputs/orthofinder_proteomes", "purpose": "169 normalized real protein FASTA files for OrthoFinder once external tools are installed."},
            {"name": "analysis_grade_tree", "path": "data/phylogeny/protist_phylogeny_v1/stage7_analysis_grade/final/protist_analysis_grade.branch_length.nwk", "purpose": "Final branch-length tree used by runtime Pagel lambda and PGLS when present and validated."},
        ],
        "endpoints": [
            {"method": "GET", "path": "/api/stoichdb/phylogeny/releases/", "purpose": "List available phylogeny P0/P1 releases."},
            {"method": "GET", "path": "/api/stoichdb/phylogeny/releases/{release_id}/tree/", "purpose": "Return the Newick reference topology and tip mapping preview."},
            {"method": "GET", "path": "/api/stoichdb/phylogeny/releases/{release_id}/validation/", "purpose": "Return validation report, QC metrics, and rank completeness."},
            {"method": "POST", "path": "/api/stoichdb/phylogeny/signal/", "purpose": "Run or return controlled Pagel lambda feature results."},
            {"method": "POST", "path": "/api/stoichdb/phylogeny/pgls/", "purpose": "Run or return controlled OLS/PGLS comparison for whitelisted formulas."},
            {"method": "GET", "path": "/api/stoichdb/case-studies/case1/phylogeny/", "purpose": "Return Case 1 P2 phylogeny readiness and interpretation boundary."},
            {"method": "GET", "path": "/api/stoichdb/species/{species_id}/phylogeny/", "purpose": "Return per-species lineage, tip label, and eligibility flags."},
        ],
        "interpretation_boundary": "P0/P1 retain the taxonomy-backed reference topology. P2 services use a validated analysis-grade branch-length tree when present; otherwise they return controlled branch-length blockers.",
    }
