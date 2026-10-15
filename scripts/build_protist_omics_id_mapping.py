#!/usr/bin/env python3
"""Build gene-transcript-protein ID mappings from existing protist feature files."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(r"G:\stoichioomics\全组学特征数据\原生生物")
GENOME_DIR = SOURCE_ROOT / "基因组"
TRANSCRIPTOME_DIR = SOURCE_ROOT / "转录组"
PROTEOME_DIR = SOURCE_ROOT / "蛋白质组"
OUT_DIR = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping"


MAPPING_FIELDS = [
    "species_id",
    "gene_id",
    "transcript_id",
    "protein_id",
    "gene_symbol",
    "gene_biotype",
    "transcript_biotype",
    "mapping_level",
    "mapping_source",
    "mapping_status",
    "mapping_confidence",
    "gene_in_genome",
    "transcript_in_transcriptome",
    "protein_in_proteome",
    "transcript_gene_consistent",
    "protein_gene_consistent",
    "protein_transcript_consistent",
    "genome_chosen_transcript_match",
    "genome_transcript_count",
    "conflict_reason",
]


QC_FIELDS = [
    "species_id",
    "has_genome_file",
    "has_transcriptome_file",
    "has_proteome_file",
    "genome_gene_count",
    "transcript_count",
    "proteome_protein_count",
    "protein_mapping_rows",
    "transcript_only_rows",
    "gene_only_rows",
    "total_mapping_rows",
    "protein_rows_with_gene_pct",
    "protein_rows_with_transcript_pct",
    "protein_gene_in_genome_pct",
    "protein_transcript_in_transcriptome_pct",
    "protein_gene_consistency_pct",
    "protein_transcript_consistency_pct",
    "transcript_gene_in_genome_pct",
    "conflict_count",
    "mapping_grade",
]


CONFLICT_FIELDS = [
    "species_id",
    "gene_id",
    "transcript_id",
    "protein_id",
    "conflict_type",
    "conflict_reason",
    "mapping_source",
]


def species_from_name(path: Path, suffix: str) -> str:
    return path.name[: -len(suffix)]


def discover_species() -> dict[str, dict[str, Path]]:
    species: dict[str, dict[str, Path]] = {}
    for path in GENOME_DIR.glob("*.genome_features.core.csv"):
        species.setdefault(species_from_name(path, ".genome_features.core.csv"), {})["genome"] = path
    for path in TRANSCRIPTOME_DIR.glob("*.transcriptome.core.v5.csv"):
        species.setdefault(species_from_name(path, ".transcriptome.core.v5.csv"), {})["transcriptome"] = path
    for path in PROTEOME_DIR.glob("*.proteome_features.core.csv"):
        species.setdefault(species_from_name(path, ".proteome_features.core.csv"), {})["proteome"] = path
    return dict(sorted(species.items()))


def clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100.0, 4) if denominator else 0.0


def read_genome(path: Path | None) -> dict[str, dict[str, str]]:
    if not path or not path.exists():
        return {}
    genes: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            gene_id = clean(row.get("gene_id") or row.get("source_gene_id"))
            if not gene_id:
                continue
            genes.setdefault(
                gene_id,
                {
                    "gene_id": gene_id,
                    "gene_name": clean(row.get("gene_name")),
                    "gene_biotype": clean(row.get("biotype")),
                    "chosen_transcript_source_id": clean(row.get("chosen_transcript_source_id")),
                    "transcript_count": clean(row.get("transcript_count")),
                    "is_coding": clean(row.get("is_coding")),
                },
            )
    return genes


def read_transcripts(path: Path | None) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    if not path or not path.exists():
        return {}, {}
    transcripts: dict[str, dict[str, str]] = {}
    gene_to_transcripts: dict[str, set[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            transcript_id = clean(row.get("transcript_id"))
            gene_id = clean(row.get("gene_id"))
            if not transcript_id:
                continue
            transcripts.setdefault(
                transcript_id,
                {
                    "transcript_id": transcript_id,
                    "gene_id": gene_id,
                    "gene_symbol": clean(row.get("gene_symbol")),
                    "gene_biotype": clean(row.get("gene_biotype")),
                    "transcript_biotype": clean(row.get("transcript_biotype")),
                },
            )
            if gene_id:
                gene_to_transcripts.setdefault(gene_id, set()).add(transcript_id)
    return transcripts, gene_to_transcripts


def row_status(parts: list[str]) -> str:
    return "ok" if not parts else "conflict"


def confidence_for(mapping_level: str, conflict_reason: str, has_genome: bool, has_transcriptome: bool) -> str:
    if conflict_reason:
        return "low"
    if mapping_level == "gene_transcript_protein" and has_genome and has_transcriptome:
        return "high"
    if mapping_level in {"gene_transcript", "gene_protein"}:
        return "medium"
    return "low"


def write_mapping_row(writer: csv.DictWriter, row: dict[str, object]) -> None:
    writer.writerow({field: row.get(field, "") for field in MAPPING_FIELDS})


def build_species_mapping(
    species_id: str,
    files: dict[str, Path],
    mapping_writer: csv.DictWriter,
    conflict_writer: csv.DictWriter,
) -> dict[str, object]:
    genome = read_genome(files.get("genome"))
    transcripts, gene_to_transcripts = read_transcripts(files.get("transcriptome"))
    protein_count = 0
    protein_rows_with_gene = 0
    protein_rows_with_transcript = 0
    protein_gene_in_genome = 0
    protein_tx_in_transcriptome = 0
    protein_gene_consistent = 0
    protein_tx_consistent = 0
    protein_mapping_rows = 0
    conflict_count = 0
    mapped_transcripts: set[str] = set()
    mapped_genes: set[str] = set()

    proteome_path = files.get("proteome")
    if proteome_path and proteome_path.exists():
        with proteome_path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                protein_count += 1
                protein_id = clean(row.get("protein_id") or row.get("ensembl_protein_id") or row.get("source_protein_id"))
                gene_id = clean(row.get("gene_id") or row.get("ensembl_gene_id"))
                transcript_id = clean(row.get("transcript_id") or row.get("ensembl_transcript_id"))
                gene_symbol = clean(row.get("gene_symbol"))
                conflict_parts: list[str] = []
                if gene_id:
                    protein_rows_with_gene += 1
                if transcript_id:
                    protein_rows_with_transcript += 1
                gene_in_genome = bool(gene_id and gene_id in genome)
                tx_in_transcriptome = bool(transcript_id and transcript_id in transcripts)
                if gene_in_genome:
                    protein_gene_in_genome += 1
                if tx_in_transcriptome:
                    protein_tx_in_transcriptome += 1
                transcript_gene_consistent = ""
                if tx_in_transcriptome and gene_id:
                    transcript_gene = transcripts[transcript_id].get("gene_id", "")
                    transcript_gene_consistent = str(transcript_gene == gene_id)
                    if transcript_gene == gene_id:
                        protein_gene_consistent += 1
                    else:
                        conflict_parts.append(f"transcript_gene_mismatch:{transcript_gene}")
                elif transcript_id and not tx_in_transcriptome:
                    conflict_parts.append("transcript_missing_from_transcriptome")
                if gene_id and not gene_in_genome:
                    conflict_parts.append("gene_missing_from_genome")
                if protein_id:
                    protein_tx_consistent += 1
                chosen_match = ""
                if gene_id in genome and transcript_id:
                    chosen = genome[gene_id].get("chosen_transcript_source_id", "")
                    chosen_match = "True" if chosen == transcript_id else ("False" if chosen else "")
                mapping_level = "gene_transcript_protein" if gene_id and transcript_id and protein_id else (
                    "gene_protein" if gene_id and protein_id else "protein_only"
                )
                conflict_reason = ";".join(conflict_parts)
                if conflict_reason:
                    conflict_count += 1
                    for part in conflict_parts:
                        conflict_writer.writerow({
                            "species_id": species_id,
                            "gene_id": gene_id,
                            "transcript_id": transcript_id,
                            "protein_id": protein_id,
                            "conflict_type": part.split(":", 1)[0],
                            "conflict_reason": part,
                            "mapping_source": "proteome_feature",
                        })
                mapped_genes.add(gene_id) if gene_id else None
                mapped_transcripts.add(transcript_id) if transcript_id else None
                protein_mapping_rows += 1
                write_mapping_row(mapping_writer, {
                    "species_id": species_id,
                    "gene_id": gene_id,
                    "transcript_id": transcript_id,
                    "protein_id": protein_id,
                    "gene_symbol": gene_symbol,
                    "gene_biotype": transcripts.get(transcript_id, {}).get("gene_biotype", "") or genome.get(gene_id, {}).get("gene_biotype", ""),
                    "transcript_biotype": transcripts.get(transcript_id, {}).get("transcript_biotype", ""),
                    "mapping_level": mapping_level,
                    "mapping_source": "proteome_feature",
                    "mapping_status": row_status(conflict_parts),
                    "mapping_confidence": confidence_for(mapping_level, conflict_reason, bool(genome), bool(transcripts)),
                    "gene_in_genome": str(gene_in_genome),
                    "transcript_in_transcriptome": str(tx_in_transcriptome),
                    "protein_in_proteome": "True",
                    "transcript_gene_consistent": transcript_gene_consistent,
                    "protein_gene_consistent": "True" if gene_id else "",
                    "protein_transcript_consistent": "True" if transcript_id else "",
                    "genome_chosen_transcript_match": chosen_match,
                    "genome_transcript_count": genome.get(gene_id, {}).get("transcript_count", ""),
                    "conflict_reason": conflict_reason,
                })

    transcript_only_rows = 0
    for transcript_id, tx in transcripts.items():
        if transcript_id in mapped_transcripts:
            continue
        gene_id = tx.get("gene_id", "")
        mapped_genes.add(gene_id) if gene_id else None
        transcript_only_rows += 1
        conflict_parts = []
        if gene_id and gene_id not in genome:
            conflict_parts.append("gene_missing_from_genome")
            conflict_count += 1
            conflict_writer.writerow({
                "species_id": species_id,
                "gene_id": gene_id,
                "transcript_id": transcript_id,
                "protein_id": "",
                "conflict_type": "gene_missing_from_genome",
                "conflict_reason": "gene_missing_from_genome",
                "mapping_source": "transcriptome_feature",
            })
        write_mapping_row(mapping_writer, {
            "species_id": species_id,
            "gene_id": gene_id,
            "transcript_id": transcript_id,
            "protein_id": "",
            "gene_symbol": tx.get("gene_symbol", ""),
            "gene_biotype": tx.get("gene_biotype", ""),
            "transcript_biotype": tx.get("transcript_biotype", ""),
            "mapping_level": "gene_transcript",
            "mapping_source": "transcriptome_feature",
            "mapping_status": row_status(conflict_parts),
            "mapping_confidence": confidence_for("gene_transcript", ";".join(conflict_parts), bool(genome), True),
            "gene_in_genome": str(bool(gene_id and gene_id in genome)),
            "transcript_in_transcriptome": "True",
            "protein_in_proteome": "False",
            "transcript_gene_consistent": "True" if gene_id else "",
            "protein_gene_consistent": "",
            "protein_transcript_consistent": "",
            "genome_chosen_transcript_match": "",
            "genome_transcript_count": genome.get(gene_id, {}).get("transcript_count", ""),
            "conflict_reason": ";".join(conflict_parts),
        })

    gene_only_rows = 0
    for gene_id, gene in genome.items():
        if gene_id in mapped_genes or gene_id in gene_to_transcripts:
            continue
        gene_only_rows += 1
        write_mapping_row(mapping_writer, {
            "species_id": species_id,
            "gene_id": gene_id,
            "transcript_id": gene.get("chosen_transcript_source_id", ""),
            "protein_id": "",
            "gene_symbol": gene.get("gene_name", ""),
            "gene_biotype": gene.get("gene_biotype", ""),
            "transcript_biotype": "",
            "mapping_level": "gene_only",
            "mapping_source": "genome_feature",
            "mapping_status": "ok",
            "mapping_confidence": "low",
            "gene_in_genome": "True",
            "transcript_in_transcriptome": "False",
            "protein_in_proteome": "False",
            "transcript_gene_consistent": "",
            "protein_gene_consistent": "",
            "protein_transcript_consistent": "",
            "genome_chosen_transcript_match": "",
            "genome_transcript_count": gene.get("transcript_count", ""),
            "conflict_reason": "",
        })

    total_rows = protein_mapping_rows + transcript_only_rows + gene_only_rows
    protein_denominator = protein_count or 0
    transcript_gene_in_genome = sum(1 for tx in transcripts.values() if tx.get("gene_id") in genome)
    high_quality = (
        pct(protein_tx_in_transcriptome, protein_denominator) >= 95
        and pct(protein_gene_in_genome, protein_denominator) >= 95
        and conflict_count == 0
    )
    usable = (
        pct(protein_tx_in_transcriptome, protein_denominator) >= 85
        and pct(protein_gene_in_genome, protein_denominator) >= 85
    )
    grade = "A" if high_quality else ("B" if usable else ("C" if protein_denominator else "D"))
    return {
        "species_id": species_id,
        "has_genome_file": str(bool(files.get("genome"))),
        "has_transcriptome_file": str(bool(files.get("transcriptome"))),
        "has_proteome_file": str(bool(files.get("proteome"))),
        "genome_gene_count": len(genome),
        "transcript_count": len(transcripts),
        "proteome_protein_count": protein_count,
        "protein_mapping_rows": protein_mapping_rows,
        "transcript_only_rows": transcript_only_rows,
        "gene_only_rows": gene_only_rows,
        "total_mapping_rows": total_rows,
        "protein_rows_with_gene_pct": pct(protein_rows_with_gene, protein_denominator),
        "protein_rows_with_transcript_pct": pct(protein_rows_with_transcript, protein_denominator),
        "protein_gene_in_genome_pct": pct(protein_gene_in_genome, protein_denominator),
        "protein_transcript_in_transcriptome_pct": pct(protein_tx_in_transcriptome, protein_denominator),
        "protein_gene_consistency_pct": pct(protein_gene_consistent, protein_rows_with_transcript),
        "protein_transcript_consistency_pct": pct(protein_tx_consistent, protein_denominator),
        "transcript_gene_in_genome_pct": pct(transcript_gene_in_genome, len(transcripts)),
        "conflict_count": conflict_count,
        "mapping_grade": grade,
    }


def main() -> int:
    started = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    species_files = discover_species()
    mapping_path = OUT_DIR / "protist_omics_id_mapping_all_species.csv"
    qc_path = OUT_DIR / "protist_omics_id_mapping_species_qc.csv"
    conflict_path = OUT_DIR / "protist_omics_id_mapping_conflicts.csv"
    summary_path = OUT_DIR / "protist_omics_id_mapping_summary.json"

    qc_rows = []
    with mapping_path.open("w", encoding="utf-8-sig", newline="") as mapping_fh, conflict_path.open("w", encoding="utf-8-sig", newline="") as conflict_fh:
        mapping_writer = csv.DictWriter(mapping_fh, fieldnames=MAPPING_FIELDS)
        conflict_writer = csv.DictWriter(conflict_fh, fieldnames=CONFLICT_FIELDS)
        mapping_writer.writeheader()
        conflict_writer.writeheader()
        for index, (species_id, files) in enumerate(species_files.items(), start=1):
            print(f"[{index}/{len(species_files)}] {species_id}", flush=True)
            qc_rows.append(build_species_mapping(species_id, files, mapping_writer, conflict_writer))

    with qc_path.open("w", encoding="utf-8-sig", newline="") as qc_fh:
        writer = csv.DictWriter(qc_fh, fieldnames=QC_FIELDS)
        writer.writeheader()
        writer.writerows(qc_rows)

    summary = {
        "generated_at_unix": int(time.time()),
        "source_root": str(SOURCE_ROOT),
        "species_count": len(qc_rows),
        "total_mapping_rows": sum(int(row["total_mapping_rows"]) for row in qc_rows),
        "total_conflicts": sum(int(row["conflict_count"]) for row in qc_rows),
        "grade_counts": {
            grade: sum(1 for row in qc_rows if row["mapping_grade"] == grade)
            for grade in ["A", "B", "C", "D"]
        },
        "outputs": {
            "mapping": str(mapping_path),
            "species_qc": str(qc_path),
            "conflicts": str(conflict_path),
            "summary": str(summary_path),
        },
        "runtime_seconds": round(time.time() - started, 2),
        "method": (
            "Primary mapping from existing proteome feature rows: protein_id + gene_id + transcript_id. "
            "Transcriptome feature rows validate transcript_id to gene_id and add transcript-only rows. "
            "Genome feature rows validate gene_id and chosen_transcript_source_id and add gene-only rows."
        ),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
