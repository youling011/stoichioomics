from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "protist_phylogeny_v1"
PHYLO_ROOT = PROJECT_ROOT / "data" / "phylogeny" / RELEASE_ID
INPUT_ROOT = PHYLO_ROOT / "stage0_source" / "analysis_grade_sequence_inputs"
FULL_ORTHOFINDER_MANIFEST = INPUT_ROOT / "orthofinder_proteome_manifest.csv"
FULL_BUSCO_MANIFEST = INPUT_ROOT / "busco_protein_manifest.csv"
FULL_SEQUENCE_MANIFEST = INPUT_ROOT / "analysis_grade_sequence_manifest.csv"
FULL_TRAIT_MATRIX = PHYLO_ROOT / "stage3_analysis_matrix" / "species_trait_matrix.csv"
TIP_MAP = PHYLO_ROOT / "stage1_standardized" / "tip_mapping.csv"
SUBSET_ROOT = PHYLO_ROOT / "stage7_analysis_grade" / "subset30"
SUBSET_ORTHOFINDER_DIR = SUBSET_ROOT / "orthofinder_proteomes"
SUBSET_BUSCO_DIR = SUBSET_ROOT / "busco_protein_inputs"


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


def percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[idx]


def rel(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a reproducible random 30-species protist subset for analysis-grade phylogeny.")
    parser.add_argument("--seed", type=int, default=20260717)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--max-quantile", type=float, default=0.75, help="Prefer species with sequence_count <= this quantile.")
    parser.add_argument("--force", action="store_true", help="Recreate subset FASTA directory and manifests.")
    args = parser.parse_args()

    if args.force and SUBSET_ROOT.exists():
        shutil.rmtree(SUBSET_ROOT)
    SUBSET_ORTHOFINDER_DIR.mkdir(parents=True, exist_ok=True)
    SUBSET_BUSCO_DIR.mkdir(parents=True, exist_ok=True)

    orthofinder_rows = read_csv(FULL_ORTHOFINDER_MANIFEST)
    seq_rows = {row["species_id"]: row for row in read_csv(FULL_SEQUENCE_MANIFEST)}
    busco_rows = {row["species_id"]: row for row in read_csv(FULL_BUSCO_MANIFEST)}
    trait_rows = {row["species_id"]: row for row in read_csv(FULL_TRAIT_MATRIX)}
    tip_rows = {row["species_id"]: row for row in read_csv(TIP_MAP)}

    eligible = []
    for row in orthofinder_rows:
        species_id = row["species_id"]
        src = PROJECT_ROOT / row["proteome_fasta"]
        if not src.exists() or species_id not in trait_rows or species_id not in tip_rows:
            continue
        item = dict(row)
        item["sequence_count_int"] = int(row.get("sequence_count") or 0)
        item["aa_total_int"] = int(row.get("aa_total") or 0)
        eligible.append(item)

    if len(eligible) < args.count:
        raise SystemExit(f"Only {len(eligible)} eligible species are available; requested {args.count}.")

    threshold = percentile([row["sequence_count_int"] for row in eligible], args.max_quantile)
    preferred = [row for row in eligible if row["sequence_count_int"] <= threshold]
    pool = preferred if len(preferred) >= args.count else eligible
    rng = random.Random(args.seed)
    selected = sorted(rng.sample(pool, args.count), key=lambda row: row["species_id"])
    selected_ids = {row["species_id"] for row in selected}

    subset_orthofinder = []
    subset_busco = []
    subset_sequence = []
    subset_traits = []
    subset_tips = []
    for row in selected:
        species_id = row["species_id"]
        src = PROJECT_ROOT / row["proteome_fasta"]
        dst = SUBSET_ORTHOFINDER_DIR / src.name
        shutil.copy2(src, dst)
        busco_dst = SUBSET_BUSCO_DIR / src.name
        shutil.copy2(src, busco_dst)
        subset_orthofinder.append(
            {
                "species_id": species_id,
                "proteome_fasta": rel(dst),
                "sequence_count": row["sequence_count"],
                "aa_total": row["aa_total"],
            }
        )
        subset_busco.append(
            {
                "species_id": species_id,
                "mode": "proteins",
                "input_fasta": rel(busco_dst),
                "recommended_lineage": (busco_rows.get(species_id) or {}).get("recommended_lineage", "eukaryota_odb10"),
            }
        )
        seq = dict(seq_rows.get(species_id) or {})
        seq["subset30_selected"] = "true"
        seq["subset30_normalized_proteome_path"] = rel(dst)
        subset_sequence.append(seq)
        subset_traits.append(trait_rows[species_id])
        subset_tips.append(tip_rows[species_id])

    write_csv(SUBSET_ROOT / "subset30_species.csv", selected, list(selected[0].keys()))
    write_csv(SUBSET_ROOT / "orthofinder_proteome_manifest_subset30.csv", subset_orthofinder, ["species_id", "proteome_fasta", "sequence_count", "aa_total"])
    write_csv(SUBSET_ROOT / "busco_protein_manifest_subset30.csv", subset_busco, ["species_id", "mode", "input_fasta", "recommended_lineage"])
    write_csv(SUBSET_ROOT / "analysis_grade_sequence_manifest_subset30.csv", subset_sequence, list(subset_sequence[0].keys()))
    write_csv(SUBSET_ROOT / "species_trait_matrix_subset30.csv", subset_traits, list(next(iter(trait_rows.values())).keys()))
    write_csv(SUBSET_ROOT / "tip_mapping_subset30.csv", subset_tips, list(next(iter(tip_rows.values())).keys()))

    summary = {
        "release_id": RELEASE_ID,
        "generated_at": utc_now(),
        "seed": args.seed,
        "requested_count": args.count,
        "selected_count": len(selected),
        "eligible_species_count": len(eligible),
        "preferred_pool_count": len(preferred),
        "max_quantile": args.max_quantile,
        "sequence_count_threshold": threshold,
        "total_sequences": sum(int(row["sequence_count"]) for row in subset_orthofinder),
        "total_amino_acids": sum(int(row["aa_total"]) for row in subset_orthofinder),
        "orthofinder_input_dir": rel(SUBSET_ORTHOFINDER_DIR),
        "busco_input_dir": rel(SUBSET_BUSCO_DIR),
        "trait_matrix": rel(SUBSET_ROOT / "species_trait_matrix_subset30.csv"),
        "species": [row["species_id"] for row in selected],
    }
    write_json(SUBSET_ROOT / "subset30_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
