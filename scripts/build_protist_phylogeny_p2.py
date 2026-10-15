from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "protist_phylogeny_v1"
PHYLO_ROOT = PROJECT_ROOT / "data" / "phylogeny" / RELEASE_ID
QC_ROOT = Path(r"F:\新物种数据\全组学\protists下载质检\condex运行_第二阶段终筛")
QC_WHITELIST = QC_ROOT / "species_whitelist_final.csv"
P0_WHITELIST = PHYLO_ROOT / "stage0_source" / "p0_protist_whitelist_species_freeze.csv"
TIP_MAP = PHYLO_ROOT / "stage1_standardized" / "tip_mapping.csv"
P1_REGISTRY = PHYLO_ROOT / "stage6_platform_registry" / "phylogeny_registry.json"
FINGERPRINTS = PROJECT_ROOT / "data" / "protist_real_pipeline" / "stage5_artifacts" / "compare" / "species_fingerprints.csv"
ANALYSIS_GRADE_SEQUENCE_SUMMARY = PHYLO_ROOT / "stage0_source" / "analysis_grade_sequence_inputs" / "analysis_grade_sequence_input_summary.json"

FEATURES = [
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
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


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


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean(value: Any) -> str:
    return str(value or "").strip()


def to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def lineage_tokens(row: dict[str, str]) -> list[str]:
    lineage = clean(row.get("full_lineage"))
    if not lineage:
        return []
    return [clean(item) for item in lineage.split(";") if clean(item)]


def taxonomy_distance(left: list[str], right: list[str]) -> int:
    shared = 0
    for a, b in zip(left, right):
        if a == b:
            shared += 1
        else:
            break
    return (len(left) - shared) + (len(right) - shared)


def main() -> None:
    stage0 = PHYLO_ROOT / "stage0_source"
    stage2 = PHYLO_ROOT / "stage2_validation"
    stage3 = PHYLO_ROOT / "stage3_analysis_matrix"
    stage5 = PHYLO_ROOT / "stage5_artifacts"
    stage6 = PHYLO_ROOT / "stage6_platform_registry"
    for path in [stage0, stage2, stage3, stage5, stage6]:
        path.mkdir(parents=True, exist_ok=True)

    p1_registry = json.loads(P1_REGISTRY.read_text(encoding="utf-8"))
    qc_rows = read_csv(QC_WHITELIST)
    p0_rows = read_csv(P0_WHITELIST)
    tip_rows = read_csv(TIP_MAP)
    fingerprint_rows = read_csv(FINGERPRINTS)

    qc_by_species = {row["species"]: row for row in qc_rows}
    p0_species = {row["species_id"] for row in p0_rows}
    qc_species = set(qc_by_species)
    analysis_species = p0_species & qc_species
    tip_by_species = {row["species_id"]: row for row in tip_rows}
    trait_by_species = {row["species_id"]: row for row in fingerprint_rows}

    whitelist_compare = []
    for species_id in sorted(p0_species | qc_species):
        qc = qc_by_species.get(species_id, {})
        whitelist_compare.append(
            {
                "species_id": species_id,
                "in_p0_freeze": str(species_id in p0_species).lower(),
                "in_download_qc_final_whitelist": str(species_id in qc_by_species).lower(),
                "in_p2_analysis_set": str(species_id in analysis_species).lower(),
                "qc_status_pre_download": qc.get("qc_status_pre_download", ""),
                "file_status": qc.get("file_status", ""),
                "assembly_accession": qc.get("assembly_accession", ""),
                "taxonomy_id": qc.get("taxonomy_id", ""),
            }
        )

    trait_rows = []
    for species_id in sorted(analysis_species):
        tip = tip_by_species.get(species_id, {})
        trait = trait_by_species.get(species_id, {})
        row = {
            "release_id": RELEASE_ID,
            "species_id": species_id,
            "tip_label": tip.get("tip_label", ""),
            "display_name": trait.get("display_name") or tip.get("display_name", ""),
            "tax_id_current": tip.get("tax_id_current", ""),
            "phylum": tip.get("phylum", ""),
            "class": tip.get("class", ""),
            "order": tip.get("order", ""),
            "family": tip.get("family", ""),
            "genus": tip.get("genus", ""),
            "trait_status": "complete" if all(to_float(trait.get(feature)) is not None for feature in FEATURES) else "partial",
        }
        for feature in FEATURES:
            row[feature] = trait.get(feature, "")
        trait_rows.append(row)

    lineage_by_species = {row["species_id"]: lineage_tokens(row) for row in tip_rows}
    distance_rows = []
    species_order = sorted(analysis_species)
    for left in species_order:
        left_lineage = lineage_by_species.get(left, [])
        for right in species_order:
            if left > right:
                continue
            right_lineage = lineage_by_species.get(right, [])
            distance_rows.append(
                {
                    "species_id_1": left,
                    "species_id_2": right,
                    "taxonomy_path_distance": taxonomy_distance(left_lineage, right_lineage),
                    "distance_type": "taxonomy_path_distance_not_phylogenetic_branch_length",
                }
            )

    trait_coverage = []
    for feature in FEATURES:
        values = [to_float(row.get(feature)) for row in trait_rows]
        complete = [value for value in values if value is not None]
        trait_coverage.append(
            {
                "feature": feature,
                "n_complete": len(complete),
                "n_missing": len(values) - len(complete),
                "coverage_pct": round(len(complete) / len(values) * 100.0, 4) if values else 0,
                "min": min(complete) if complete else "",
                "max": max(complete) if complete else "",
                "mean": round(sum(complete) / len(complete), 6) if complete else "",
            }
        )

    branch_lengths_present = bool(p1_registry.get("summary", {}).get("branch_lengths_present"))
    pgls_eligible = bool(p1_registry.get("summary", {}).get("pgls_eligible"))
    blocker = "" if pgls_eligible else "no_complete_branch_lengths_in_active_protist_phylogeny_release"
    signal_rows = []
    for item in trait_coverage:
        signal_rows.append(
            {
                "release_id": RELEASE_ID,
                "feature": item["feature"],
                "n": item["n_complete"],
                "lambda": "",
                "p_value": "",
                "q_value": "",
                "status": "blocked_no_branch_lengths",
                "blocker": blocker,
            }
        )

    pgls_rows = [
        {
            "release_id": RELEASE_ID,
            "formula": "proteome_n_per_aa ~ genome_gc + transcript_gc",
            "n": min(item["n_complete"] for item in trait_coverage),
            "ols_status": "available_via_runtime_when_requested",
            "pgls_status": "blocked_no_branch_lengths",
            "lambda": "",
            "blocker": blocker,
        },
        {
            "release_id": RELEASE_ID,
            "formula": "proteome_s_per_aa ~ proteome_gravy + proteome_pi",
            "n": min(item["n_complete"] for item in trait_coverage),
            "ols_status": "available_via_runtime_when_requested",
            "pgls_status": "blocked_no_branch_lengths",
            "lambda": "",
            "blocker": blocker,
        },
    ]

    case1 = {
        "release_id": RELEASE_ID,
        "generated_at": utc_now(),
        "case_id": "case1",
        "status": "phylogeny_ready_but_pgls_blocked",
        "trait_species_count": len(trait_rows),
        "tree_tip_count": len(tip_rows),
        "matched_species_count": sum(1 for row in trait_rows if row["tip_label"]),
        "core_features": FEATURES,
        "branch_lengths_present": branch_lengths_present,
        "pgls_eligible": pgls_eligible,
        "blocker": blocker,
        "allowed_interpretation": "Use lineage-aware grouping, tree display readiness, and taxonomy path distance diagnostics only.",
        "forbidden_interpretation": "Do not report Pagel lambda, PGLS, phylogenetic signal, or evolutionary-rate conclusions for the active taxonomy reference topology.",
    }

    write_csv(stage0 / "download_qc_whitelist_comparison.csv", whitelist_compare, list(whitelist_compare[0].keys()))
    write_csv(stage3 / "species_trait_matrix.csv", trait_rows, list(trait_rows[0].keys()))
    write_csv(stage3 / "taxonomy_path_distance_matrix_long.csv", distance_rows, list(distance_rows[0].keys()))
    write_csv(stage3 / "trait_coverage.csv", trait_coverage, list(trait_coverage[0].keys()))
    write_json(
        stage3 / "branch_length_readiness.json",
        {
            "release_id": RELEASE_ID,
            "generated_at": utc_now(),
            "branch_lengths_present": branch_lengths_present,
            "pgls_eligible": pgls_eligible,
            "blocker": blocker,
            "tree_kind": p1_registry.get("tree_kind"),
            "requirements_for_lambda_pgls": [
                "rooted tree",
                "complete non-negative branch lengths",
                "unique species-to-tip mapping",
                "numeric trait matrix with at least 10 matched species per tested feature",
            ],
        },
    )
    write_csv(stage5 / "phylogenetic_signal_readiness.csv", signal_rows, list(signal_rows[0].keys()))
    write_csv(stage5 / "pgls_readiness.csv", pgls_rows, list(pgls_rows[0].keys()))
    write_json(stage5 / "case1_phylogeny_readiness.json", case1)

    sequence_summary = read_json(ANALYSIS_GRADE_SEQUENCE_SUMMARY)
    p2_registry = {
        "schema_version": "phylogeny_registry.p2.v1",
        "release_id": RELEASE_ID,
        "generated_at": utc_now(),
        "scope": "protists",
        "whitelist_source": str(QC_WHITELIST),
        "p0_species_count": len(p0_species),
        "download_qc_final_whitelist_count": len(qc_by_species),
        "whitelist_overlap_count": len(analysis_species),
        "p2_analysis_species_count": len(analysis_species),
        "p0_only_species": sorted(p0_species - qc_species),
        "download_qc_only_species": sorted(qc_species - p0_species),
        "trait_matrix": {
            "path": str((stage3 / "species_trait_matrix.csv").relative_to(PROJECT_ROOT)),
            "sha256": sha256_file(stage3 / "species_trait_matrix.csv"),
            "species_count": len(trait_rows),
            "features": FEATURES,
        },
        "analysis_grade_sequence_inputs": sequence_summary,
        "taxonomy_distance": {
            "path": str((stage3 / "taxonomy_path_distance_matrix_long.csv").relative_to(PROJECT_ROOT)),
            "distance_type": "taxonomy_path_distance_not_phylogenetic_branch_length",
            "pair_rows": len(distance_rows),
        },
        "analysis_readiness": {
            "branch_lengths_present": branch_lengths_present,
            "pgls_eligible": pgls_eligible,
            "blocker": blocker,
            "signal_readiness_path": str((stage5 / "phylogenetic_signal_readiness.csv").relative_to(PROJECT_ROOT)),
            "pgls_readiness_path": str((stage5 / "pgls_readiness.csv").relative_to(PROJECT_ROOT)),
        },
        "case1_phylogeny": {
            "path": str((stage5 / "case1_phylogeny_readiness.json").relative_to(PROJECT_ROOT)),
            "status": case1["status"],
        },
        "limitations": [
            "The active protist release remains a taxonomy reference topology without branch lengths.",
            "P2 backend can run lambda/PGLS only when a future analysis-grade branch-length tree is supplied.",
            "Current platform artifacts are readiness and controlled-blocker outputs, not phylogenetic signal results.",
        ],
    }
    write_json(stage6 / "phylogeny_p2_registry.json", p2_registry)
    print(
        json.dumps(
            {
                "release_id": RELEASE_ID,
                "p0_species_count": len(p0_species),
                "download_qc_final_whitelist_count": len(qc_by_species),
                "p2_analysis_species_count": len(analysis_species),
                "trait_species_count": len(trait_rows),
                "taxonomy_distance_rows": len(distance_rows),
                "pgls_eligible": pgls_eligible,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
