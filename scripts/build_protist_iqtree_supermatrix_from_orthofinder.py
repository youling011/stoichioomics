from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "protist_phylogeny_v1"
PHYLO_ROOT = PROJECT_ROOT / "data" / "phylogeny" / RELEASE_ID
TRAIT_MATRIX = PHYLO_ROOT / "stage3_analysis_matrix" / "species_trait_matrix.csv"
DEFAULT_OUT = PHYLO_ROOT / "stage7_analysis_grade" / "iqtree_supermatrix"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fasta_iter(path: Path) -> Iterable[tuple[str, str]]:
    header = ""
    chunks: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if header:
                    yield header, "".join(chunks)
                header = line[1:].strip()
                chunks = []
            else:
                chunks.append(line)
    if header:
        yield header, "".join(chunks)


def write_fasta(path: Path, records: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for header, seq in records:
            handle.write(f">{header}\n")
            for i in range(0, len(seq), 80):
                handle.write(seq[i : i + 80] + "\n")


def infer_species(header: str, species_ids: list[str]) -> str:
    token = header.split()[0].strip()
    if "|" in token:
        prefix = token.split("|", 1)[0]
        if prefix in species_ids:
            return prefix
    for species_id in species_ids:
        if token == species_id or token.startswith(species_id + "_") or token.startswith(species_id + "|"):
            return species_id
    return ""


def locate_results(explicit: str) -> Path:
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else PROJECT_ROOT / path
    candidates = sorted((PHYLO_ROOT / "stage7_analysis_grade").glob("orthofinder_run_*/Results_*"))
    if not candidates:
        raise FileNotFoundError("No OrthoFinder Results_* directory found.")
    return max(candidates, key=lambda item: item.stat().st_mtime)


def candidate_fastas(results_dir: Path, species_ids: list[str], min_taxon_fraction: float, max_loci: int) -> list[Path]:
    gene_count_path = results_dir / "Orthogroups" / "Orthogroups.GeneCount.tsv"
    seq_dir = results_dir / "Orthogroup_Sequences"
    if gene_count_path.exists() and seq_dir.exists():
        with gene_count_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        min_taxa = max(4, int(len(species_ids) * min_taxon_fraction + 0.999999))
        ranked = []
        for row in rows:
            counts = [int(row.get(species, "0") or 0) for species in species_ids]
            present_single = sum(1 for value in counts if value == 1)
            if present_single >= min_taxa and all(value <= 1 for value in counts):
                fasta = seq_dir / f"{row['Orthogroup']}.fa"
                if not fasta.exists():
                    fasta = seq_dir / f"{row['Orthogroup']}.faa"
                if fasta.exists():
                    ranked.append((present_single, int(row.get("Total") or present_single), fasta))
        ranked.sort(key=lambda item: (item[0], -item[1], item[2].name), reverse=True)
        return [item[2] for item in ranked]

    preferred = sorted(results_dir.glob("Single_Copy_Orthologue_Sequences/*"))
    preferred = [path for path in preferred if path.suffix.lower() in {".fa", ".faa", ".fasta"}]
    if preferred:
        return preferred[:max_loci]
    fallback = sorted(results_dir.glob("Orthogroup_Sequences/*"))
    return [path for path in fallback if path.suffix.lower() in {".fa", ".faa", ".fasta"}][:max_loci]


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=str(cwd), check=True)


def read_alignment(path: Path) -> dict[str, str]:
    return {header.split()[0]: seq for header, seq in fasta_iter(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build MAFFT/ClipKIT/IQ-TREE supermatrix from OrthoFinder orthogroups.")
    parser.add_argument("--orthofinder-results", default="", help="OrthoFinder Results_* directory. Defaults to latest stage7 result.")
    parser.add_argument("--trait-matrix", default=str(TRAIT_MATRIX.relative_to(PROJECT_ROOT)), help="Trait matrix defining the species/tip set.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT.relative_to(PROJECT_ROOT)))
    parser.add_argument("--min-taxon-fraction", type=float, default=0.8)
    parser.add_argument("--max-loci", type=int, default=250)
    parser.add_argument(
        "--balance-min-loci-per-species",
        type=int,
        default=1,
        help="Greedily include candidate loci so every species has at least this many non-gap loci before filling by coverage.",
    )
    parser.add_argument("--mafft-mode", choices=["auto", "fast"], default="auto", help="MAFFT strategy: auto or fast progressive mode.")
    parser.add_argument("--iqtree-model", default="MFP", help="IQ-TREE model string, e.g. MFP or LG+G4.")
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args()

    trait_matrix = Path(args.trait_matrix)
    if not trait_matrix.is_absolute():
        trait_matrix = PROJECT_ROOT / trait_matrix
    species_ids = [row["tip_label"] for row in read_csv(trait_matrix) if row.get("tip_label")]
    results_dir = locate_results(args.orthofinder_results)
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    raw_dir = out_dir / "raw_loci"
    aln_dir = out_dir / "aligned_loci"
    trim_dir = out_dir / "trimmed_loci"
    final_dir = out_dir / "final"
    for path in [raw_dir, aln_dir, trim_dir, final_dir]:
        path.mkdir(parents=True, exist_ok=True)

    loci = []
    for fasta in candidate_fastas(results_dir, species_ids, args.min_taxon_fraction, args.max_loci):
        by_species: dict[str, str] = {}
        duplicate = False
        for header, seq in fasta_iter(fasta):
            species = infer_species(header, species_ids)
            if not species:
                continue
            if species in by_species:
                duplicate = True
                break
            by_species[species] = seq.replace("*", "")
        coverage = len(by_species) / len(species_ids) if species_ids else 0
        if duplicate or coverage < args.min_taxon_fraction:
            continue
        loci.append({"path": fasta, "coverage": coverage, "species_count": len(by_species), "aa_total": sum(len(seq) for seq in by_species.values()), "records": by_species})

    loci.sort(key=lambda item: (item["coverage"], item["species_count"], item["aa_total"]), reverse=True)
    selected = []
    selected_paths = set()
    per_species_loci = {species: 0 for species in species_ids}
    balance_target = max(0, args.balance_min_loci_per_species)
    while balance_target and len(selected) < args.max_loci and min(per_species_loci.values(), default=balance_target) < balance_target:
        best = None
        best_score = None
        for locus in loci:
            if locus["path"] in selected_paths:
                continue
            helped_species = [species for species in locus["records"] if per_species_loci.get(species, 0) < balance_target]
            if not helped_species:
                continue
            score = (len(helped_species), locus["species_count"], locus["aa_total"], locus["path"].name)
            if best_score is None or score > best_score:
                best = locus
                best_score = score
        if best is None:
            break
        selected.append(best)
        selected_paths.add(best["path"])
        for species in best["records"]:
            if species in per_species_loci:
                per_species_loci[species] += 1

    for locus in loci:
        if len(selected) >= args.max_loci:
            break
        if locus["path"] in selected_paths:
            continue
        selected.append(locus)
        selected_paths.add(locus["path"])
        for species in locus["records"]:
            if species in per_species_loci:
                per_species_loci[species] += 1
    if not selected:
        raise SystemExit(f"No orthogroup loci passed min taxon fraction {args.min_taxon_fraction}.")

    partitions = []
    concat = {species: [] for species in species_ids}
    cursor = 1
    locus_manifest = []
    for idx, locus in enumerate(selected, start=1):
        locus_id = locus["path"].stem
        raw_path = raw_dir / f"{idx:04d}_{locus_id}.faa"
        aln_path = aln_dir / f"{idx:04d}_{locus_id}.mafft.faa"
        trim_path = trim_dir / f"{idx:04d}_{locus_id}.clipkit.faa"
        records = [(species, locus["records"][species]) for species in species_ids if species in locus["records"]]
        write_fasta(raw_path, records)
        mafft_cmd = ["mafft", "--auto", str(raw_path)]
        if args.mafft_mode == "fast":
            mafft_cmd = ["mafft", "--retree", "1", "--maxiterate", "0", str(raw_path)]
        with aln_path.open("w", encoding="utf-8", newline="\n") as handle:
            subprocess.run(mafft_cmd, stdout=handle, cwd=str(PROJECT_ROOT), check=True)
        run(["clipkit", str(aln_path), "-o", str(trim_path)], PROJECT_ROOT)
        aligned = read_alignment(trim_path)
        width = len(next(iter(aligned.values())))
        for species in species_ids:
            concat[species].append(aligned.get(species, "-" * width))
        partitions.append(f"LG, {idx:04d}_{locus_id} = {cursor}-{cursor + width - 1}")
        cursor += width
        locus_manifest.append(
            {
                "locus_id": locus_id,
                "source_fasta": str(locus["path"].relative_to(PROJECT_ROOT)),
                "species_count": locus["species_count"],
                "coverage": round(locus["coverage"], 6),
                "trimmed_width": width,
            }
        )

    supermatrix = final_dir / "protist_single_copy_supermatrix.faa"
    partition_file = final_dir / "protist_single_copy_supermatrix.partitions.txt"
    write_fasta(supermatrix, [(species, "".join(parts)) for species, parts in concat.items()])
    partition_file.write_text("\n".join(partitions) + "\n", encoding="utf-8")

    prefix = final_dir / "protist_iqtree"
    run(
        [
            "iqtree",
            "-s",
            str(supermatrix),
            "-m",
            args.iqtree_model,
            "-B",
            str(args.bootstrap),
            "-T",
            str(args.threads),
            "--prefix",
            str(prefix),
        ],
        PROJECT_ROOT,
    )

    summary = {
        "release_id": RELEASE_ID,
        "orthofinder_results": str(results_dir.relative_to(PROJECT_ROOT)),
        "trait_matrix": str(trait_matrix.relative_to(PROJECT_ROOT)),
        "candidate_loci": len(loci),
        "selected_loci": len(selected),
        "species_count": len(species_ids),
        "balance_min_loci_per_species": balance_target,
        "per_species_selected_loci": per_species_loci,
        "mafft_mode": args.mafft_mode,
        "iqtree_model": args.iqtree_model,
        "supermatrix": str(supermatrix.relative_to(PROJECT_ROOT)),
        "partition_file": str(partition_file.relative_to(PROJECT_ROOT)),
        "iqtree_prefix": str(prefix.relative_to(PROJECT_ROOT)),
        "treefile": str((Path(str(prefix) + ".treefile")).relative_to(PROJECT_ROOT)),
        "tools": {
            "orthofinder": "input orthogroups",
            "mafft": shutil.which("mafft") or "",
            "clipkit": shutil.which("clipkit") or "",
            "iqtree": shutil.which("iqtree") or "",
        },
        "loci": locus_manifest,
    }
    write_json(final_dir / "supermatrix_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
