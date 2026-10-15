from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_ID = "protist_phylogeny_v1"
PHYLO_ROOT = PROJECT_ROOT / "data" / "phylogeny" / RELEASE_ID
FINAL_WHITELIST = Path(r"F:\新物种数据\全组学\protists下载质检\condex运行_第二阶段终筛\species_whitelist_final.csv")
P0_WHITELIST = PHYLO_ROOT / "stage0_source" / "p0_protist_whitelist_species_freeze.csv"
TIP_MAP = PHYLO_ROOT / "stage1_standardized" / "tip_mapping.csv"
FINGERPRINTS = PROJECT_ROOT / "data" / "protist_real_pipeline" / "stage5_artifacts" / "compare" / "species_fingerprints.csv"

OUT_ROOT = PHYLO_ROOT / "stage0_source" / "analysis_grade_sequence_inputs"
ORTHOFINDER_DIR = OUT_ROOT / "orthofinder_proteomes"
BUSCO_DIR = OUT_ROOT / "busco_protein_inputs"


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


def clean(value: Any) -> str:
    return str(value or "").strip()


def safe_id(value: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", clean(value))
    return safe.strip("_") or "unnamed"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fasta_reader(handle: TextIO):
    header = ""
    chunks: list[str] = []
    for line in handle:
        line = line.rstrip("\n\r")
        if not line:
            continue
        if line.startswith(">"):
            if header:
                yield header, "".join(chunks)
            header = line[1:].strip()
            chunks = []
        else:
            chunks.append(line.strip())
    if header:
        yield header, "".join(chunks)


def pep_stats_and_materialize(src: Path, dst: Path | None, species_id: str) -> dict[str, Any]:
    seq_count = 0
    aa_total = 0
    longest = 0
    internal_stop = 0
    duplicate_headers = 0
    seen: set[str] = set()
    lengths: list[int] = []
    dst_handle = None
    try:
        with gzip.open(src, "rt", encoding="utf-8", errors="replace") as handle:
            if dst is not None:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst_handle = dst.open("w", encoding="utf-8", newline="\n")
            for raw_header, seq in fasta_reader(handle):
                seq_count += 1
                protein_id = safe_id(raw_header.split()[0])
                if protein_id in seen:
                    duplicate_headers += 1
                    protein_id = f"{protein_id}_{seq_count}"
                seen.add(protein_id)
                normalized = re.sub(r"[^A-Za-z*.-]", "", seq).upper()
                length = len(normalized.replace("*", ""))
                aa_total += length
                longest = max(longest, length)
                lengths.append(length)
                if "*" in normalized[:-1]:
                    internal_stop += 1
                if dst_handle is not None:
                    dst_handle.write(f">{species_id}|{protein_id} original={raw_header}\n")
                    for i in range(0, len(normalized), 80):
                        dst_handle.write(normalized[i : i + 80] + "\n")
    finally:
        if dst_handle is not None:
            dst_handle.close()
    lengths.sort(reverse=True)
    half = aa_total / 2.0
    running = 0
    n50 = 0
    for length in lengths:
        running += length
        if running >= half:
            n50 = length
            break
    return {
        "pep_sequence_count": seq_count,
        "pep_aa_total": aa_total,
        "pep_longest": longest,
        "pep_n50": n50,
        "pep_duplicate_header_count": duplicate_headers,
        "pep_internal_stop_count": internal_stop,
        "pep_valid_gzip": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare real protist protein inputs for BUSCO/OrthoFinder/IQ-TREE workflows.")
    parser.add_argument("--no-materialize", action="store_true", help="Only write manifests; do not create normalized proteome FASTA files.")
    parser.add_argument("--limit", type=int, default=0, help="Debug only: process first N final-whitelist species.")
    args = parser.parse_args()

    final_rows = read_csv(FINAL_WHITELIST)
    if args.limit:
        final_rows = final_rows[: args.limit]
    p0_species = {row["species_id"] for row in read_csv(P0_WHITELIST)}
    tip_species = {row["species_id"] for row in read_csv(TIP_MAP)}
    trait_species = {row["species_id"] for row in read_csv(FINGERPRINTS)}

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    if not args.no_materialize:
        ORTHOFINDER_DIR.mkdir(parents=True, exist_ok=True)
        BUSCO_DIR.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, Any]] = []
    orthofinder_rows: list[dict[str, Any]] = []
    busco_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    analysis_species_count = 0

    for row in final_rows:
        species_id = row["species"]
        pep_path = Path(row["pep_path"])
        dna_path = Path(row["dna_path"])
        cdna_path = Path(row["cdna_path"])
        annotation_path = Path(row["annotation_path"])
        in_platform = species_id in p0_species and species_id in tip_species and species_id in trait_species
        if in_platform:
            analysis_species_count += 1
        out_faa = ORTHOFINDER_DIR / f"{species_id}.faa" if in_platform and not args.no_materialize else None
        stats: dict[str, Any] = {}
        if pep_path.exists():
            try:
                stats = pep_stats_and_materialize(pep_path, out_faa, species_id)
            except Exception as exc:
                stats = {"pep_valid_gzip": False, "pep_error": f"{type(exc).__name__}: {exc}"}
        else:
            stats = {"pep_valid_gzip": False, "pep_error": "missing_pep_path"}
        if in_platform and out_faa is not None and out_faa.exists():
            shutil.copy2(out_faa, BUSCO_DIR / out_faa.name)

        out_size = out_faa.stat().st_size if out_faa is not None and out_faa.exists() else 0
        out_sha = sha256_file(out_faa) if out_faa is not None and out_faa.exists() else ""
        manifest = {
            "release_id": RELEASE_ID,
            "species_id": species_id,
            "taxon_id": row.get("taxon_id", ""),
            "qc_grade": row.get("qc_grade", ""),
            "quality_score": row.get("quality_score", ""),
            "in_final_download_whitelist": "true",
            "in_platform_p0": str(species_id in p0_species).lower(),
            "in_platform_tip_map": str(species_id in tip_species).lower(),
            "in_platform_trait_matrix": str(species_id in trait_species).lower(),
            "analysis_grade_input_eligible": str(in_platform and stats.get("pep_valid_gzip") is True).lower(),
            "dna_path": str(dna_path),
            "cdna_path": str(cdna_path),
            "pep_path": str(pep_path),
            "annotation_path": str(annotation_path),
            "dna_exists": str(dna_path.exists()).lower(),
            "cdna_exists": str(cdna_path.exists()).lower(),
            "pep_exists": str(pep_path.exists()).lower(),
            "annotation_exists": str(annotation_path.exists()).lower(),
            "pep_size_bytes": pep_path.stat().st_size if pep_path.exists() else 0,
            "normalized_proteome_path": str(out_faa.relative_to(PROJECT_ROOT)) if out_faa is not None and out_faa.exists() else "",
            "normalized_proteome_size_bytes": out_size,
            "normalized_proteome_sha256": out_sha,
            **stats,
        }
        manifest_rows.append(manifest)
        if manifest["analysis_grade_input_eligible"] == "true":
            orthofinder_rows.append(
                {
                    "species_id": species_id,
                    "proteome_fasta": manifest["normalized_proteome_path"],
                    "sequence_count": manifest.get("pep_sequence_count", 0),
                    "aa_total": manifest.get("pep_aa_total", 0),
                }
            )
            busco_rows.append(
                {
                    "species_id": species_id,
                    "mode": "proteins",
                    "input_fasta": manifest["normalized_proteome_path"],
                    "recommended_lineage": "eukaryota_odb10",
                }
            )
        else:
            missing_rows.append(manifest)

    fields = list(manifest_rows[0].keys())
    write_csv(OUT_ROOT / "analysis_grade_sequence_manifest.csv", manifest_rows, fields)
    write_csv(OUT_ROOT / "orthofinder_proteome_manifest.csv", orthofinder_rows, ["species_id", "proteome_fasta", "sequence_count", "aa_total"])
    write_csv(OUT_ROOT / "busco_protein_manifest.csv", busco_rows, ["species_id", "mode", "input_fasta", "recommended_lineage"])
    if missing_rows:
        write_csv(OUT_ROOT / "analysis_grade_input_exclusions.csv", missing_rows, fields)

    tool_names = ["busco", "orthofinder", "mafft", "clipkit", "iqtree2", "iqtree"]
    tool_availability = {name: shutil.which(name) or "" for name in tool_names}
    commands = [
        "# Run from the project root after installing BUSCO, OrthoFinder, MAFFT, ClipKIT and IQ-TREE.",
        "# 1. BUSCO per-proteome QC example:",
        "busco -i data/phylogeny/protist_phylogeny_v1/stage0_source/analysis_grade_sequence_inputs/busco_protein_inputs/acanthamoeba_castellanii.faa -m proteins -l eukaryota_odb10 -o acanthamoeba_busco",
        "# 2. OrthoFinder orthogroups:",
        "orthofinder -f data/phylogeny/protist_phylogeny_v1/stage0_source/analysis_grade_sequence_inputs/orthofinder_proteomes -t 16 -a 16",
        "# 3. Align selected single-copy orthogroups:",
        "mafft --auto input_single_copy_orthogroup.faa > aligned_single_copy_orthogroup.faa",
        "# 4. Trim alignment:",
        "clipkit aligned_single_copy_orthogroup.faa -o aligned_single_copy_orthogroup.trimmed.faa",
        "# 5. Build maximum-likelihood tree from concatenated trimmed supermatrix:",
        "iqtree2 -s protist_single_copy_supermatrix.faa -m MFP -B 1000 -T AUTO",
    ]
    (OUT_ROOT / "run_analysis_grade_tree_commands.ps1").write_text("\n".join(commands) + "\n", encoding="utf-8")

    total_aa = sum(int(row.get("pep_aa_total") or 0) for row in manifest_rows if row.get("analysis_grade_input_eligible") == "true")
    summary = {
        "release_id": RELEASE_ID,
        "generated_at": utc_now(),
        "final_whitelist_source": str(FINAL_WHITELIST),
        "final_whitelist_species_count": len(final_rows),
        "platform_analysis_eligible_species_count": len(orthofinder_rows),
        "raw_only_species": [row["species_id"] for row in manifest_rows if row["in_platform_p0"] == "false"],
        "missing_or_invalid_input_count": len(missing_rows),
        "materialized_proteomes": not args.no_materialize,
        "orthofinder_input_dir": str(ORTHOFINDER_DIR.relative_to(PROJECT_ROOT)),
        "busco_input_dir": str(BUSCO_DIR.relative_to(PROJECT_ROOT)),
        "total_protein_sequences": sum(int(row.get("pep_sequence_count") or 0) for row in manifest_rows if row.get("analysis_grade_input_eligible") == "true"),
        "total_amino_acids": total_aa,
        "tool_availability": tool_availability,
        "next_step_policy": "Run external BUSCO/OrthoFinder/MAFFT/ClipKIT/IQ-TREE outside this script; do not treat taxonomy topology as an analysis-grade branch-length tree.",
    }
    write_json(OUT_ROOT / "analysis_grade_sequence_input_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
