from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

from Bio import Phylo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "protist_phylogeny_v1"
PHYLO_ROOT = PROJECT_ROOT / "data" / "phylogeny" / RELEASE_ID
P2_REGISTRY = PHYLO_ROOT / "stage6_platform_registry" / "phylogeny_p2_registry.json"
TRAIT_MATRIX = PHYLO_ROOT / "stage3_analysis_matrix" / "species_trait_matrix.csv"
SIGNAL_READINESS = PHYLO_ROOT / "stage5_artifacts" / "phylogenetic_signal_readiness.csv"
PGLS_READINESS = PHYLO_ROOT / "stage5_artifacts" / "pgls_readiness.csv"
CASE1_READINESS = PHYLO_ROOT / "stage5_artifacts" / "case1_phylogeny_readiness.json"
FINAL_DIR = PHYLO_ROOT / "stage7_analysis_grade" / "final"
FINAL_TREE = FINAL_DIR / "protist_analysis_grade.branch_length.nwk"
VALIDATION_JSON = FINAL_DIR / "analysis_grade_tree_validation.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_tip(name: str) -> str:
    out = str(name or "").strip().strip("'\"")
    for suffix in (".faa", ".fa", ".fasta", ".pep"):
        if out.endswith(suffix):
            out = out[: -len(suffix)]
    return out


def tree_has_complete_branch_lengths(tree) -> bool:
    for clade in tree.find_clades(order="level"):
        if clade is tree.root:
            continue
        if clade.branch_length is None:
            return False
        if not math.isfinite(float(clade.branch_length)):
            return False
        if float(clade.branch_length) < 0:
            return False
    return True


def parse_tree(path: Path):
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Empty Newick tree: {path}")
    tree = Phylo.read(StringIO(text), "newick")
    for terminal in tree.get_terminals():
        terminal.name = normalize_tip(terminal.name)
    return tree


def locate_tree(explicit: str) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    candidates = [
        *sorted((PHYLO_ROOT / "stage7_analysis_grade").glob("orthofinder_run_*/Results_*/Species_Tree/SpeciesTree_rooted.txt")),
        *sorted((PHYLO_ROOT / "stage7_analysis_grade").glob("orthofinder_run_*/Results_*/Species_Tree/SpeciesTree_unrooted.txt")),
        *sorted((PHYLO_ROOT / "stage7_analysis_grade").glob("**/*.treefile")),
        *sorted((PHYLO_ROOT / "stage7_analysis_grade").glob("**/*.contree")),
    ]
    if not candidates:
        raise FileNotFoundError("No OrthoFinder/IQ-TREE Newick tree was found under stage7_analysis_grade.")
    return max(candidates, key=lambda item: item.stat().st_mtime)


def update_readiness_files(features: list[str], n: int) -> None:
    signal_rows = []
    for feature in features:
        signal_rows.append(
            {
                "release_id": RELEASE_ID,
                "feature": feature,
                "n": n,
                "lambda": "",
                "p_value": "",
                "q_value": "",
                "status": "ready_runtime",
                "blocker": "",
            }
        )
    write_csv(SIGNAL_READINESS, signal_rows, list(signal_rows[0].keys()))

    pgls_rows = [
        {
            "release_id": RELEASE_ID,
            "formula": "proteome_n_per_aa ~ genome_gc + transcript_gc",
            "n": n,
            "ols_status": "available_runtime",
            "pgls_status": "ready_runtime",
            "lambda": "",
            "blocker": "",
        },
        {
            "release_id": RELEASE_ID,
            "formula": "proteome_s_per_aa ~ proteome_gravy + proteome_pi",
            "n": n,
            "ols_status": "available_runtime",
            "pgls_status": "ready_runtime",
            "lambda": "",
            "blocker": "",
        },
    ]
    write_csv(PGLS_READINESS, pgls_rows, list(pgls_rows[0].keys()))


def main() -> None:
    parser = argparse.ArgumentParser(description="Register a validated analysis-grade branch-length tree for protist P2 services.")
    parser.add_argument("--tree", default="", help="Newick tree path. If omitted, auto-detect latest OrthoFinder/IQ-TREE tree under stage7_analysis_grade.")
    parser.add_argument("--trait-matrix", default=str(TRAIT_MATRIX.relative_to(PROJECT_ROOT)), help="Trait matrix matched to the tree. Use subset30 matrix for subset analyses.")
    parser.add_argument("--source", default="orthofinder_mafft_clipkit_iqtree", help="Human-readable tree source label.")
    parser.add_argument("--allow-subset", action="store_true", help="Allow the tree to cover a validated subset of the full platform P2 species.")
    args = parser.parse_args()

    source_tree = locate_tree(args.tree)
    if not source_tree.exists():
        raise FileNotFoundError(source_tree)

    trait_matrix = Path(args.trait_matrix)
    if not trait_matrix.is_absolute():
        trait_matrix = PROJECT_ROOT / trait_matrix
    trait_rows = read_csv(trait_matrix)
    trait_tips = [row["tip_label"] for row in trait_rows if row.get("tip_label")]
    features = list((read_json(P2_REGISTRY).get("trait_matrix") or {}).get("features") or [])

    tree = parse_tree(source_tree)
    tree_tips = [terminal.name for terminal in tree.get_terminals()]
    duplicate_tips = sorted({tip for tip in tree_tips if tree_tips.count(tip) > 1})
    missing_tips = sorted(set(trait_tips) - set(tree_tips))
    extra_tips = sorted(set(tree_tips) - set(trait_tips))
    complete_branch_lengths = tree_has_complete_branch_lengths(tree)
    subset_ok = args.allow_subset and len(set(trait_tips) & set(tree_tips)) >= 4
    coverage_ok = (not missing_tips) or subset_ok
    valid = not duplicate_tips and coverage_ok and complete_branch_lengths and len(tree_tips) >= 4

    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    Phylo.write(tree, FINAL_TREE, "newick")

    validation = {
        "release_id": RELEASE_ID,
        "generated_at": utc_now(),
        "source_tree": str(source_tree.relative_to(PROJECT_ROOT)) if source_tree.is_relative_to(PROJECT_ROOT) else str(source_tree),
        "registered_tree": str(FINAL_TREE.relative_to(PROJECT_ROOT)),
        "trait_matrix": str(trait_matrix.relative_to(PROJECT_ROOT)),
        "source": args.source,
        "subset_mode": bool(args.allow_subset),
        "status": "pass" if valid else "fail",
        "tree_tip_count": len(tree_tips),
        "trait_tip_count": len(trait_tips),
        "matched_trait_tip_count": len(set(trait_tips) & set(tree_tips)),
        "missing_trait_tips": missing_tips,
        "extra_tree_tips": extra_tips[:200],
        "extra_tree_tip_count": len(extra_tips),
        "duplicate_tree_tips": duplicate_tips,
        "branch_lengths_present": complete_branch_lengths,
        "pgls_eligible": valid,
        "newick_sha256": sha256_file(FINAL_TREE),
    }
    write_json(VALIDATION_JSON, validation)
    if not valid:
        raise SystemExit(json.dumps(validation, ensure_ascii=False, indent=2))

    registry = read_json(P2_REGISTRY)
    trait_matrix_info = registry.get("trait_matrix") or {}
    trait_matrix_info.update(
        {
            "path": str(trait_matrix.relative_to(PROJECT_ROOT)),
            "sha256": sha256_file(trait_matrix),
            "species_count": len(trait_rows),
            "active_subset": "subset30" if args.allow_subset else "",
        }
    )
    registry["trait_matrix"] = trait_matrix_info
    registry["analysis_grade_tree"] = {
        "path": str(FINAL_TREE.relative_to(PROJECT_ROOT)),
        "newick_path": str(FINAL_TREE.relative_to(PROJECT_ROOT)),
        "sha256": validation["newick_sha256"],
        "source_tree": validation["source_tree"],
        "source": args.source,
        "subset_mode": bool(args.allow_subset),
        "tip_count": len(tree_tips),
        "matched_trait_tip_count": validation["matched_trait_tip_count"],
        "rooted": True,
        "branch_length_unit": "substitutions_per_site_or_source_tree_unit",
        "validation_report_path": str(VALIDATION_JSON.relative_to(PROJECT_ROOT)),
    }
    registry["analysis_readiness"] = {
        **(registry.get("analysis_readiness") or {}),
        "branch_lengths_present": True,
        "pgls_eligible": True,
        "blocker": "",
        "analysis_grade_tree_path": str(FINAL_TREE.relative_to(PROJECT_ROOT)),
        "analysis_grade_tree_validation_path": str(VALIDATION_JSON.relative_to(PROJECT_ROOT)),
    }
    registry["limitations"] = [
        "P0/P1 taxonomy topology remains available for lineage context and tree browsing.",
        "P2 signal/PGLS now use the validated analysis-grade branch-length tree for matched final-whitelist platform species.",
        "Interpret lambda/PGLS results as comparative statistical results over the current platform trait matrix and selected analysis-grade tree.",
    ]
    registry["generated_at"] = utc_now()
    write_json(P2_REGISTRY, registry)

    update_readiness_files(features, validation["matched_trait_tip_count"])

    case1 = read_json(CASE1_READINESS)
    case1.update(
        {
            "generated_at": utc_now(),
            "status": "phylogeny_analysis_grade_ready",
            "trait_species_count": len(trait_rows),
            "matched_species_count": validation["matched_trait_tip_count"],
            "branch_lengths_present": True,
            "pgls_eligible": True,
            "blocker": "",
            "analysis_grade_tree_path": str(FINAL_TREE.relative_to(PROJECT_ROOT)),
            "allowed_interpretation": "Use the validated analysis-grade branch-length tree for runtime Pagel lambda, OLS/PGLS comparison, lineage context, and Case 1 phylogeny-aware sensitivity checks.",
            "forbidden_interpretation": "Do not treat the tree as a dated chronogram or use branch lengths as absolute evolutionary time unless an explicit time-calibrated tree is supplied.",
        }
    )
    write_json(CASE1_READINESS, case1)

    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
