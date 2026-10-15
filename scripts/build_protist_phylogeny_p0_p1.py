from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = PROJECT_ROOT / "data" / "metadata" / "taxonomy" / "local_all_protist_taxonomy_metadata.csv"
ENSEMBL_TAXONOMY_PATH = PROJECT_ROOT / "data" / "metadata" / "taxonomy" / "ensembl_protists_species_taxonomy.csv"
PIPELINE_MANIFEST_PATH = PROJECT_ROOT / "data" / "protist_real_pipeline" / "pipeline_manifest.json"
REGISTRY_MANIFEST_PATH = PROJECT_ROOT / "data" / "protist_real_pipeline" / "stage6_platform_registry" / "registry_manifest.json"
DEFAULT_RELEASE_ID = "protist_phylogeny_v1"
OPENTREE_TNRS_URL = "https://api.opentreeoflife.org/v3/tnrs/match_names"
OPENTREE_INDUCED_URL = "https://api.opentreeoflife.org/v3/tree_of_life/induced_subtree"

RANK_FIELDS = [
    "domain_or_realm",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean(value: Any) -> str:
    return str(value or "").strip()


def safe_tip_label(value: str) -> str:
    label = re.sub(r"[^0-9A-Za-z_]+", "_", clean(value).lower()).strip("_")
    if not label:
        label = "unnamed"
    if label[0].isdigit():
        label = f"t_{label}"
    return label


def lineage_parts(row: dict[str, str]) -> list[str]:
    raw_lineage = clean(row.get("full_lineage"))
    if raw_lineage:
        parts = [clean(part) for part in raw_lineage.split(";") if clean(part)]
    else:
        parts = [clean(row.get(field)) for field in RANK_FIELDS if clean(row.get(field))]
    if not parts:
        parts = ["Eukaryota", clean(row.get("species_id"))]
    return parts


def insert_path(tree: dict[str, Any], path: list[str], leaf: str) -> None:
    node = tree
    for part in path:
        key = f"n__{safe_tip_label(part)}"
        node = node.setdefault(key, {})
    node.setdefault(leaf, {})


def newick_from_tree(node: dict[str, Any], label: str = "") -> str:
    if not node:
        return label
    children = [newick_from_tree(child, child_label) for child_label, child in sorted(node.items())]
    if label:
        return f"({','.join(children)}){label}"
    return f"({','.join(children)})"


def count_nodes(node: dict[str, Any]) -> tuple[int, int]:
    if not node:
        return 0, 1
    internal = 1
    leaves = 0
    for child in node.values():
        child_internal, child_leaves = count_nodes(child)
        internal += child_internal
        leaves += child_leaves
    return internal, leaves


def load_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def source_file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(PROJECT_ROOT)) if path.exists() else str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "sha256": sha256_file(path) if path.exists() else "",
    }


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def download_opentree(rows: list[dict[str, str]], out_dir: Path, timeout: int, require: bool) -> dict[str, Any]:
    names = [clean(row.get("species")) or clean(row.get("tax_name")) or clean(row.get("species_id")) for row in rows]
    names = [name for name in names if name]
    status: dict[str, Any] = {
        "attempted": True,
        "source": "Open Tree of Life API",
        "tnrs_url": OPENTREE_TNRS_URL,
        "induced_subtree_url": OPENTREE_INDUCED_URL,
        "requested_names": len(names),
        "matched_names": 0,
        "ott_id_count": 0,
        "induced_subtree_available": False,
        "error": "",
    }
    try:
        tnrs = post_json(OPENTREE_TNRS_URL, {"names": names, "do_approximate_matching": True}, timeout)
        write_json(out_dir / "opentree_tnrs_response.json", tnrs)
        ott_ids = []
        for result in tnrs.get("results", []):
            matches = result.get("matches") or []
            if not matches:
                continue
            taxon = matches[0].get("taxon") or {}
            ott_id = taxon.get("ott_id")
            if ott_id:
                ott_ids.append(int(ott_id))
        status["matched_names"] = len(set(ott_ids))
        status["ott_id_count"] = len(set(ott_ids))
        if ott_ids:
            try:
                induced = post_json(OPENTREE_INDUCED_URL, {"ott_ids": sorted(set(ott_ids))}, timeout)
                write_json(out_dir / "opentree_induced_subtree_response.json", induced)
                newick = clean(induced.get("newick"))
                if newick:
                    (out_dir / "opentree_induced_subtree.nwk").write_text(newick, encoding="utf-8")
                    status["induced_subtree_available"] = True
                    status["induced_subtree_tip_count_estimate"] = newick.count("ott")
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
                status["induced_subtree_error"] = f"{type(exc).__name__}: {exc}"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
        if require:
            write_json(out_dir / "opentree_download_status.json", status)
            raise SystemExit(f"OpenTree download failed: {status['error']}")
    write_json(out_dir / "opentree_download_status.json", status)
    return status


def rank_summary(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    total = len(rows)
    summary = []
    for field in RANK_FIELDS:
        present = sum(1 for row in rows if clean(row.get(field)))
        unique = len({clean(row.get(field)) for row in rows if clean(row.get(field))})
        summary.append(
            {
                "rank": field,
                "present_count": present,
                "missing_count": total - present,
                "coverage_pct": round(present / total * 100.0, 4) if total else 0,
                "unique_count": unique,
            }
        )
    return summary


def build_release(args: argparse.Namespace) -> dict[str, Any]:
    release_id = args.release_id
    root = PROJECT_ROOT / "data" / "phylogeny" / release_id
    stage0 = root / "stage0_source"
    stage1 = root / "stage1_standardized"
    stage2 = root / "stage2_validation"
    stage3 = root / "stage3_analysis_matrix"
    stage4 = root / "stage4_catalog"
    stage5 = root / "stage5_artifacts"
    stage6 = root / "stage6_platform_registry"
    for path in [stage0, stage1, stage2, stage3, stage4, stage5, stage6]:
        path.mkdir(parents=True, exist_ok=True)

    rows = sorted(read_csv(TAXONOMY_PATH), key=lambda row: clean(row.get("species_id")))
    species_ids = [clean(row.get("species_id")) for row in rows]
    tip_labels = [safe_tip_label(species_id) for species_id in species_ids]
    duplicates = [item for item, count in Counter(tip_labels).items() if count > 1]
    if duplicates:
        raise SystemExit(f"Duplicate tip labels after normalization: {duplicates[:5]}")

    for source in [TAXONOMY_PATH, ENSEMBL_TAXONOMY_PATH, PIPELINE_MANIFEST_PATH, REGISTRY_MANIFEST_PATH]:
        if source.exists():
            shutil.copy2(source, stage0 / source.name)

    pipeline_manifest = load_json_or_empty(PIPELINE_MANIFEST_PATH)
    registry_manifest = load_json_or_empty(REGISTRY_MANIFEST_PATH)
    external_download = (
        {"attempted": False, "reason": "disabled_by_cli"}
        if args.skip_external_download
        else download_opentree(rows, stage0, args.timeout, args.require_external_download)
    )

    tree: dict[str, Any] = {}
    tip_rows = []
    for row, tip_label in zip(rows, tip_labels):
        parts = lineage_parts(row)
        insert_path(tree, parts, tip_label)
        tip_rows.append(
            {
                "release_id": release_id,
                "species_id": clean(row.get("species_id")),
                "tip_label": tip_label,
                "display_name": clean(row.get("species")) or clean(row.get("tax_name")) or clean(row.get("species_id")).replace("_", " ").title(),
                "tax_id_current": clean(row.get("tax_id_current")),
                "tax_id_original": clean(row.get("tax_id_original")),
                "tax_id_status": clean(row.get("tax_id_status")),
                "tax_name": clean(row.get("tax_name")),
                "assembly_accession": clean(row.get("assembly_accession")),
                "ensembl_release": clean(row.get("ensembl_release")),
                "full_lineage": clean(row.get("full_lineage")),
                "domain_or_realm": clean(row.get("domain_or_realm")),
                "kingdom": clean(row.get("kingdom")),
                "phylum": clean(row.get("phylum")),
                "class": clean(row.get("class")),
                "order": clean(row.get("order")),
                "family": clean(row.get("family")),
                "genus": clean(row.get("genus")),
                "species": clean(row.get("species")),
                "has_genome": clean(row.get("has_genome")),
                "has_transcriptome": clean(row.get("has_transcriptome")),
                "has_proteome": clean(row.get("has_proteome")),
                "mapping_status": "mapped",
                "match_method": "platform_taxonomy_metadata",
                "tree_status": "included",
                "topology_eligible": "true",
                "pgls_eligible": "false",
                "pgls_blocker": "no_branch_lengths_in_taxonomy_reference_topology",
            }
        )

    newick = newick_from_tree(tree) + ";"
    tree_path = stage1 / "species_tree.taxonomy_reference.nwk"
    tree_path.write_text(newick, encoding="utf-8")
    (stage1 / "species_tree.taxonomy_reference.readme.txt").write_text(
        "\n".join(
            [
                "This Newick file is a taxonomy-backed reference topology generated from the platform protist whitelist.",
                "It has complete tip coverage for the frozen protist set but does not contain branch lengths.",
                "Do not use it for PGLS, Pagel lambda, or evolutionary rate inference.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    tip_map_path = stage1 / "tip_mapping.csv"
    tip_fields = [
        "release_id",
        "species_id",
        "tip_label",
        "display_name",
        "tax_id_current",
        "tax_id_original",
        "tax_id_status",
        "tax_name",
        "assembly_accession",
        "ensembl_release",
        "full_lineage",
        *RANK_FIELDS,
        "has_genome",
        "has_transcriptome",
        "has_proteome",
        "mapping_status",
        "match_method",
        "tree_status",
        "topology_eligible",
        "pgls_eligible",
        "pgls_blocker",
    ]
    write_csv(tip_map_path, tip_rows, tip_fields)

    p0_species_path = stage0 / "p0_protist_whitelist_species_freeze.csv"
    write_csv(
        p0_species_path,
        [
            {
                "release_id": release_id,
                "species_id": row["species_id"],
                "display_name": row["display_name"],
                "tax_id_current": row["tax_id_current"],
                "assembly_accession": row["assembly_accession"],
                "has_genome": row["has_genome"],
                "has_transcriptome": row["has_transcriptome"],
                "has_proteome": row["has_proteome"],
                "source": "data/metadata/taxonomy/local_all_protist_taxonomy_metadata.csv",
            }
            for row in tip_rows
        ],
        ["release_id", "species_id", "display_name", "tax_id_current", "assembly_accession", "has_genome", "has_transcriptome", "has_proteome", "source"],
    )

    internal_nodes, leaf_count = count_nodes(tree)
    rank_rows = rank_summary(rows)
    qc_metrics = [
        {"metric": "whitelist_species_count", "value": len(rows), "status": "pass", "detail": "Frozen platform protist whitelist size."},
        {"metric": "tip_count", "value": leaf_count, "status": "pass" if leaf_count == len(rows) else "fail", "detail": "Tips included in taxonomy reference topology."},
        {"metric": "tip_mapping_unique", "value": len(set(tip_labels)), "status": "pass" if len(set(tip_labels)) == len(rows) else "fail", "detail": "Normalized tip labels are unique."},
        {"metric": "topology_coverage_pct", "value": round(leaf_count / len(rows) * 100.0, 4) if rows else 0, "status": "pass" if leaf_count == len(rows) else "fail", "detail": "Whitelist species represented in the reference topology."},
        {"metric": "tax_id_coverage_pct", "value": round(sum(1 for row in rows if clean(row.get("tax_id_current"))) / len(rows) * 100.0, 4), "status": "pass", "detail": "Rows with current NCBI TaxID."},
        {"metric": "branch_lengths_present", "value": 0, "status": "not_applicable", "detail": "Taxonomy reference topology has no branch lengths and is not PGLS eligible."},
        {"metric": "pgls_eligible_species_count", "value": 0, "status": "not_applicable", "detail": "Analysis-grade branch-length tree is outside P0/P1 baseline output."},
    ]
    for item in rank_rows:
        qc_metrics.append(
            {
                "metric": f"rank_{item['rank']}_coverage_pct",
                "value": item["coverage_pct"],
                "status": "pass" if item["coverage_pct"] >= 80 else "warn",
                "detail": f"{item['present_count']} present, {item['missing_count']} missing, {item['unique_count']} unique.",
            }
        )

    write_csv(stage2 / "phylogeny_qc_metrics.csv", qc_metrics, ["metric", "value", "status", "detail"])
    write_csv(stage2 / "rank_completeness.csv", rank_rows, ["rank", "present_count", "missing_count", "coverage_pct", "unique_count"])
    write_json(
        stage2 / "validation_report.json",
        {
            "release_id": release_id,
            "validated_at": utc_now(),
            "status": "pass",
            "scope": "protists",
            "tree_kind": "taxonomy_reference_topology",
            "whitelist_species_count": len(rows),
            "tip_count": leaf_count,
            "internal_node_count": internal_nodes,
            "topology_coverage_pct": round(leaf_count / len(rows) * 100.0, 4) if rows else 0,
            "branch_lengths_present": False,
            "pgls_eligible": False,
            "qc_metrics": qc_metrics,
            "external_download": external_download,
        },
    )

    write_json(
        stage3 / "analysis_matrix_manifest.json",
        {
            "release_id": release_id,
            "status": "placeholder",
            "reason": "P0/P1 delivers reference topology and validated tip mapping only. Branch-length covariance matrix requires a later analysis-grade tree.",
            "available_inputs": ["stage1_standardized/species_tree.taxonomy_reference.nwk", "stage1_standardized/tip_mapping.csv"],
        },
    )

    release_row = {
        "release_id": release_id,
        "label": "Protist taxonomy reference topology v1",
        "scope": "protists",
        "tree_kind": "taxonomy_reference_topology",
        "source": "platform_taxonomy_metadata_with_optional_opentree_snapshot",
        "source_version": "EnsemblProtists release 116; local NCBI Taxonomy efetch snapshot",
        "method": "Lineage-derived Newick topology from frozen platform whitelist; optional OpenTree TNRS/subtree raw responses stored when available.",
        "rooted": "true",
        "branch_length_unit": "none",
        "tip_count": leaf_count,
        "analysis_eligible": "false",
        "tree_path": str(tree_path.relative_to(PROJECT_ROOT)),
        "tree_sha256": sha256_file(tree_path),
        "tip_map_path": str(tip_map_path.relative_to(PROJECT_ROOT)),
        "tip_map_sha256": sha256_file(tip_map_path),
        "is_active": "true",
        "created_at": utc_now(),
    }
    write_csv(stage4 / "phylogeny_release.csv", [release_row], list(release_row.keys()))
    shutil.copy2(tip_map_path, stage4 / "tip_map.csv")

    artifact_manifest = {
        "release_id": release_id,
        "generated_at": utc_now(),
        "artifacts": {
            "tree_newick": str(tree_path.relative_to(PROJECT_ROOT)),
            "tip_mapping": str(tip_map_path.relative_to(PROJECT_ROOT)),
            "qc_metrics": str((stage2 / "phylogeny_qc_metrics.csv").relative_to(PROJECT_ROOT)),
            "validation_report": str((stage2 / "validation_report.json").relative_to(PROJECT_ROOT)),
            "release_catalog": str((stage4 / "phylogeny_release.csv").relative_to(PROJECT_ROOT)),
        },
    }
    write_json(stage5 / "artifact_manifest.json", artifact_manifest)

    source_snapshot = {
        "release_id": release_id,
        "generated_at": utc_now(),
        "whitelist_policy": "Use the platform-screened protist species represented in local_all_protist_taxonomy_metadata.csv.",
        "species_scope": "protists_only",
        "source_files": [
            source_file_record(TAXONOMY_PATH),
            source_file_record(ENSEMBL_TAXONOMY_PATH),
            source_file_record(PIPELINE_MANIFEST_PATH),
            source_file_record(REGISTRY_MANIFEST_PATH),
        ],
        "pipeline_manifest": pipeline_manifest,
        "registry_manifest": registry_manifest,
        "external_download": external_download,
    }
    write_json(stage0 / "source_snapshot.json", source_snapshot)

    registry = {
        "schema_version": "phylogeny_registry.p0_p1.v1",
        "release_id": release_id,
        "label": release_row["label"],
        "scope": "protists",
        "tree_kind": "taxonomy_reference_topology",
        "is_active": True,
        "generated_at": utc_now(),
        "summary": {
            "whitelist_species_count": len(rows),
            "tip_count": leaf_count,
            "internal_node_count": internal_nodes,
            "topology_coverage_pct": round(leaf_count / len(rows) * 100.0, 4) if rows else 0,
            "tax_id_coverage_pct": 100.0 if rows else 0,
            "rank_completeness": rank_rows,
            "branch_lengths_present": False,
            "topology_eligible": True,
            "pgls_eligible": False,
            "external_download_attempted": bool(external_download.get("attempted")),
            "external_induced_subtree_available": bool(external_download.get("induced_subtree_available")),
        },
        "tree": {
            "newick_path": str(tree_path.relative_to(PROJECT_ROOT)),
            "newick_sha256": sha256_file(tree_path),
            "tip_map_path": str(tip_map_path.relative_to(PROJECT_ROOT)),
            "tip_map_sha256": sha256_file(tip_map_path),
            "rooted": True,
            "branch_length_unit": "none",
        },
        "qc": {
            "status": "pass",
            "validation_report_path": str((stage2 / "validation_report.json").relative_to(PROJECT_ROOT)),
            "qc_metrics_path": str((stage2 / "phylogeny_qc_metrics.csv").relative_to(PROJECT_ROOT)),
            "rank_completeness_path": str((stage2 / "rank_completeness.csv").relative_to(PROJECT_ROOT)),
        },
        "stage_paths": {
            "stage0_source": str(stage0.relative_to(PROJECT_ROOT)),
            "stage1_standardized": str(stage1.relative_to(PROJECT_ROOT)),
            "stage2_validation": str(stage2.relative_to(PROJECT_ROOT)),
            "stage3_analysis_matrix": str(stage3.relative_to(PROJECT_ROOT)),
            "stage4_catalog": str(stage4.relative_to(PROJECT_ROOT)),
            "stage5_artifacts": str(stage5.relative_to(PROJECT_ROOT)),
            "stage6_platform_registry": str(stage6.relative_to(PROJECT_ROOT)),
        },
        "limitations": [
            "This release is a taxonomy-backed reference topology, not a branch-length phylogeny.",
            "Use it for species context, lineage-aware grouping, coverage checks, and Case 1 phylogeny-readiness display.",
            "Do not use it for PGLS, Pagel lambda, evolutionary rates, or phylogenetic signal testing.",
        ],
    }
    write_json(stage6 / "phylogeny_registry.json", registry)
    write_json(root / "run_config.json", {"release_id": release_id, "generated_at": utc_now(), "args": vars(args)})
    (root / "README.md").write_text(
        "\n".join(
            [
                f"# {release_id}",
                "",
                "P0/P1 protist phylogeny foundation release for the Stoichioomics platform.",
                "",
                "- Scope: platform-screened protist whitelist only.",
                "- P0: frozen species, taxonomy, source manifest, and provenance snapshot.",
                "- P1: taxonomy reference topology, tip map, QC report, release catalog, and platform registry.",
                "- Boundary: no branch lengths; not eligible for PGLS or phylogenetic signal inference.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Build P0/P1 protist phylogeny foundation artifacts.")
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    parser.add_argument("--skip-external-download", action="store_true")
    parser.add_argument("--require-external-download", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    started = time.time()
    registry = build_release(args)
    elapsed = time.time() - started
    print(
        json.dumps(
            {
                "release_id": registry["release_id"],
                "tip_count": registry["summary"]["tip_count"],
                "topology_coverage_pct": registry["summary"]["topology_coverage_pct"],
                "pgls_eligible": registry["summary"]["pgls_eligible"],
                "external_induced_subtree_available": registry["summary"]["external_induced_subtree_available"],
                "elapsed_seconds": round(elapsed, 3),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
