#!/usr/bin/env python3
"""Analyze coverage gaps in final-whitelist ID mappings.

This script does not rebuild the large mapping CSVs. It streams the original
feature tables and reports how much the current proteome-driven mapping misses
relative to genome/transcriptome feature entities.
"""

from __future__ import annotations
import sys as _corefull_sys
from pathlib import Path as _CoreFullPath
_corefull_sys.path.insert(0, str(_CoreFullPath(__file__).resolve().parents[1]))
from backend.apps.stoichdb.feature_sources import io as feature_io

import argparse
import csv
import json
import re
import time
from collections import Counter
from backend.apps.common.host_paths import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
G_ROOT = Path("G:/stoichioomics")
FEATURE_ROOT = G_ROOT / "全组学特征数据"
DOWNLOAD_ROOT = G_ROOT / "全组学下载数据"
OUT_ROOT = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping_final_whitelist_gap_analysis"

GROUPS = {
    "bacteria": {"feature_group": "细菌", "qc_group": "bacteria下载质检"},
    "fungi": {"feature_group": "真菌", "qc_group": "fungi下载质检"},
    "metazoa": {"feature_group": "后生生物", "qc_group": "metazoa下载质检"},
    "plants": {"feature_group": "植物", "qc_group": "plants下载质检"},
}

DETAIL_FIELDS = [
    "division",
    "species_id",
    "tax_id",
    "assembly_accession",
    "has_genome_file",
    "has_transcriptome_file",
    "has_proteome_file",
    "genome_gene_count",
    "genome_coding_gene_count",
    "transcript_count",
    "transcriptome_gene_count",
    "proteome_protein_count",
    "proteome_gene_count",
    "proteome_transcript_count",
    "protein_rows_with_gene",
    "protein_rows_with_transcript",
    "protein_rows_with_any_external_id",
    "protein_rows_with_uniprot",
    "protein_rows_with_ncbi_gene",
    "protein_rows_with_refseq_protein",
    "protein_rows_with_refseq_transcript",
    "genome_genes_not_in_proteome",
    "genome_coding_genes_not_in_proteome",
    "transcriptome_genes_not_in_proteome",
    "transcripts_not_in_proteome",
    "proteome_genes_not_in_genome",
    "proteome_transcripts_not_in_transcriptome",
    "genome_gene_proteome_coverage_pct",
    "genome_coding_gene_proteome_coverage_pct",
    "transcript_proteome_coverage_pct",
    "local_external_any_pct",
    "local_uniprot_pct",
    "local_ncbi_gene_pct",
    "elapsed_seconds",
]

SUMMARY_FIELDS = [
    "division",
    "whitelist_species_count",
    "species_with_genome_file",
    "species_with_transcriptome_file",
    "species_with_proteome_file",
    "genome_gene_count",
    "genome_coding_gene_count",
    "transcript_count",
    "transcriptome_gene_count",
    "proteome_protein_count",
    "proteome_gene_count_sum",
    "proteome_transcript_count_sum",
    "protein_rows_with_gene",
    "protein_rows_with_transcript",
    "protein_rows_with_any_external_id",
    "protein_rows_with_uniprot",
    "protein_rows_with_ncbi_gene",
    "protein_rows_with_refseq_protein",
    "protein_rows_with_refseq_transcript",
    "genome_genes_not_in_proteome",
    "genome_coding_genes_not_in_proteome",
    "transcriptome_genes_not_in_proteome",
    "transcripts_not_in_proteome",
    "proteome_genes_not_in_genome",
    "proteome_transcripts_not_in_transcriptome",
    "genome_gene_proteome_coverage_pct",
    "genome_coding_gene_proteome_coverage_pct",
    "transcript_proteome_coverage_pct",
    "local_external_any_pct",
    "local_uniprot_pct",
    "local_ncbi_gene_pct",
    "elapsed_seconds",
]

UNIPROT_SOURCE_RE = re.compile(r"\[Source:UniProtKB/(?:Swiss-Prot|TrEMBL);Acc:([A-Z0-9]+(?:-\d+)?)\]")
GENEID_RE = re.compile(r"\b(?:GeneID|EntrezGene|NCBI_Gene)[:=](\d+)\b", re.IGNORECASE)
REFSEQ_PROTEIN_RE = re.compile(r"\b(?:[NXWAYZ]P|WP|AP|YP|XP|NP|ZP)_\d+(?:\.\d+)?\b")
REFSEQ_TRANSCRIPT_RE = re.compile(r"\b(?:NM|XM|NR|XR)_\d+(?:\.\d+)?\b")
INSDC_PROTEIN_RE = re.compile(r"\b(?:[A-Z]{3}\d{5}|[A-Z]{4,6}\d{6,10})(?:\.\d+)?\b")


def clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def header_index(header: list[str], names: Iterable[str]) -> int | None:
    lookup = {name: idx for idx, name in enumerate(header)}
    for name in names:
        if name in lookup:
            return lookup[name]
    return None


def cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return clean(row[idx])


def pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100.0, 4) if denominator else 0.0


def whitelist_path(group: str) -> Path:
    return DOWNLOAD_ROOT / GROUPS[group]["qc_group"] / "condex运行_第二阶段终筛" / "species_whitelist_final.csv"


def load_whitelist(group: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with feature_io.open_source(whitelist_path(group), "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            species_id = clean(row.get("species"))
            if not species_id:
                continue
            if clean(row.get("hard_fail")).lower() == "true":
                continue
            rows.append(row)
    return rows


def feature_files(group: str, species_id: str) -> dict[str, Path | None]:
    root = FEATURE_ROOT / GROUPS[group]["feature_group"]
    genome = root / "基因组" / f"{species_id}.genome_features.core.csv"
    transcriptome = root / "转录组" / f"{species_id}.transcriptome.core.v5.csv"
    proteome = root / "蛋白质组" / species_id / f"{species_id}.proteome_features.core.csv"
    if not feature_io.source_available(proteome):
        proteome = root / "蛋白质组" / species_id / f"{species_id}.proteome_features.full.csv"
    return {
        "genome": genome if feature_io.source_available(genome) else None,
        "transcriptome": transcriptome if feature_io.source_available(transcriptome) else None,
        "proteome": proteome if feature_io.source_available(proteome) else None,
    }


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y"}


def read_genome(path: Path | None) -> tuple[set[str], set[str]]:
    genes: set[str] = set()
    coding: set[str] = set()
    if not path:
        return genes, coding
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        gene_idx = header_index(header, ("gene_id", "source_gene_id"))
        biotype_idx = header_index(header, ("biotype", "gene_biotype"))
        is_coding_idx = header_index(header, ("is_coding",))
        for row in reader:
            gene_id = cell(row, gene_idx)
            if not gene_id:
                continue
            genes.add(gene_id)
            biotype = cell(row, biotype_idx).lower()
            if truthy(cell(row, is_coding_idx)) or biotype == "protein_coding":
                coding.add(gene_id)
    return genes, coding


def read_transcriptome(path: Path | None) -> tuple[set[str], set[str]]:
    transcripts: set[str] = set()
    genes: set[str] = set()
    if not path:
        return transcripts, genes
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        transcript_idx = header_index(header, ("transcript_id", "source_transcript_id"))
        gene_idx = header_index(header, ("gene_id", "source_gene_id"))
        for row in reader:
            transcript_id = cell(row, transcript_idx)
            gene_id = cell(row, gene_idx)
            if transcript_id:
                transcripts.add(transcript_id)
            if gene_id:
                genes.add(gene_id)
    return transcripts, genes


def has_uniprot(row: dict[str, str], text: str) -> bool:
    source_db = clean(row.get("source_db")).lower()
    source_protein_id = clean(row.get("source_protein_id"))
    return "uniprot" in source_db or bool(UNIPROT_SOURCE_RE.search(text)) or bool(source_protein_id and "uniprot" in text.lower())


def read_proteome(path: Path | None) -> dict[str, object]:
    genes: set[str] = set()
    transcripts: set[str] = set()
    proteins: set[str] = set()
    counters: Counter[str] = Counter()
    if not path:
        return {"genes": genes, "transcripts": transcripts, "proteins": proteins, "counters": counters}
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, [])
        protein_idx = header_index(header, ("protein_id", "ensembl_protein_id", "source_protein_id"))
        gene_idx = header_index(header, ("ensembl_gene_id", "gene_id", "source_gene_id"))
        transcript_idx = header_index(header, ("transcript_id", "ensembl_transcript_id", "source_transcript_id"))
        source_db_idx = header_index(header, ("source_db",))
        source_protein_idx = header_index(header, ("source_protein_id",))
        description_idx = header_index(header, ("description", "header_raw"))
        for row in reader:
            protein_id = cell(row, protein_idx)
            gene_id = cell(row, gene_idx)
            transcript_id = cell(row, transcript_idx)
            source_protein_id = cell(row, source_protein_idx)
            description = cell(row, description_idx)
            source_db = cell(row, source_db_idx)
            text = " ".join([protein_id, gene_id, transcript_id, source_protein_id, source_db, description])
            if protein_id:
                proteins.add(protein_id)
            if gene_id:
                genes.add(gene_id)
                counters["protein_rows_with_gene"] += 1
            if transcript_id:
                transcripts.add(transcript_id)
                counters["protein_rows_with_transcript"] += 1
            row_for_uniprot = {"source_db": source_db, "source_protein_id": source_protein_id}
            row_has_uniprot = has_uniprot(row_for_uniprot, text)
            row_has_ncbi_gene = bool(GENEID_RE.search(text))
            row_has_refseq_protein = bool(REFSEQ_PROTEIN_RE.search(text) or INSDC_PROTEIN_RE.search(source_protein_id))
            row_has_refseq_transcript = bool(REFSEQ_TRANSCRIPT_RE.search(text))
            if row_has_uniprot:
                counters["protein_rows_with_uniprot"] += 1
            if row_has_ncbi_gene:
                counters["protein_rows_with_ncbi_gene"] += 1
            if row_has_refseq_protein:
                counters["protein_rows_with_refseq_protein"] += 1
            if row_has_refseq_transcript:
                counters["protein_rows_with_refseq_transcript"] += 1
            local_any = row_has_uniprot or row_has_ncbi_gene or row_has_refseq_protein or row_has_refseq_transcript
            if local_any:
                counters["protein_rows_with_any_external_id"] += 1
    return {"genes": genes, "transcripts": transcripts, "proteins": proteins, "counters": counters}


def analyze_species(group: str, whitelist_row: dict[str, str]) -> dict[str, object]:
    species_id = clean(whitelist_row.get("species"))
    started = time.time()
    files = feature_files(group, species_id)
    genome_genes, genome_coding_genes = read_genome(files["genome"])
    transcriptome_transcripts, transcriptome_genes = read_transcriptome(files["transcriptome"])
    proteome = read_proteome(files["proteome"])
    proteome_genes: set[str] = proteome["genes"]  # type: ignore[assignment]
    proteome_transcripts: set[str] = proteome["transcripts"]  # type: ignore[assignment]
    proteome_proteins: set[str] = proteome["proteins"]  # type: ignore[assignment]
    counters: Counter[str] = proteome["counters"]  # type: ignore[assignment]

    genome_missing = genome_genes - proteome_genes
    coding_missing = genome_coding_genes - proteome_genes
    tx_gene_missing = transcriptome_genes - proteome_genes
    tx_missing = transcriptome_transcripts - proteome_transcripts

    return {
        "division": group,
        "species_id": species_id,
        "tax_id": clean(whitelist_row.get("tax_id") or whitelist_row.get("taxon_id")),
        "assembly_accession": clean(whitelist_row.get("assembly_accession")),
        "has_genome_file": bool(files["genome"]),
        "has_transcriptome_file": bool(files["transcriptome"]),
        "has_proteome_file": bool(files["proteome"]),
        "genome_gene_count": len(genome_genes),
        "genome_coding_gene_count": len(genome_coding_genes),
        "transcript_count": len(transcriptome_transcripts),
        "transcriptome_gene_count": len(transcriptome_genes),
        "proteome_protein_count": len(proteome_proteins),
        "proteome_gene_count": len(proteome_genes),
        "proteome_transcript_count": len(proteome_transcripts),
        "protein_rows_with_gene": counters["protein_rows_with_gene"],
        "protein_rows_with_transcript": counters["protein_rows_with_transcript"],
        "protein_rows_with_any_external_id": counters["protein_rows_with_any_external_id"],
        "protein_rows_with_uniprot": counters["protein_rows_with_uniprot"],
        "protein_rows_with_ncbi_gene": counters["protein_rows_with_ncbi_gene"],
        "protein_rows_with_refseq_protein": counters["protein_rows_with_refseq_protein"],
        "protein_rows_with_refseq_transcript": counters["protein_rows_with_refseq_transcript"],
        "genome_genes_not_in_proteome": len(genome_missing),
        "genome_coding_genes_not_in_proteome": len(coding_missing),
        "transcriptome_genes_not_in_proteome": len(tx_gene_missing),
        "transcripts_not_in_proteome": len(tx_missing),
        "proteome_genes_not_in_genome": len(proteome_genes - genome_genes) if genome_genes else 0,
        "proteome_transcripts_not_in_transcriptome": len(proteome_transcripts - transcriptome_transcripts) if transcriptome_transcripts else 0,
        "genome_gene_proteome_coverage_pct": pct(len(genome_genes & proteome_genes), len(genome_genes)),
        "genome_coding_gene_proteome_coverage_pct": pct(len(genome_coding_genes & proteome_genes), len(genome_coding_genes)),
        "transcript_proteome_coverage_pct": pct(len(transcriptome_transcripts & proteome_transcripts), len(transcriptome_transcripts)),
        "local_external_any_pct": pct(counters["protein_rows_with_any_external_id"], len(proteome_proteins)),
        "local_uniprot_pct": pct(counters["protein_rows_with_uniprot"], len(proteome_proteins)),
        "local_ncbi_gene_pct": pct(counters["protein_rows_with_ncbi_gene"], len(proteome_proteins)),
        "elapsed_seconds": round(time.time() - started, 3),
    }


def bool_count(rows: Iterable[dict[str, object]], field: str) -> int:
    return sum(1 for row in rows if row.get(field) in {True, "True", "true", "1", 1})


def summarize_group(group: str, detail_rows: list[dict[str, object]], elapsed: float) -> dict[str, object]:
    total = Counter()
    for row in detail_rows:
        for field in DETAIL_FIELDS:
            if field in {"division", "species_id", "tax_id", "assembly_accession", "elapsed_seconds"}:
                continue
            value = row.get(field)
            if isinstance(value, bool):
                total[field] += int(value)
            elif isinstance(value, (int, float)) and not field.endswith("_pct"):
                total[field] += int(value)
    return {
        "division": group,
        "whitelist_species_count": len(detail_rows),
        "species_with_genome_file": total["has_genome_file"],
        "species_with_transcriptome_file": total["has_transcriptome_file"],
        "species_with_proteome_file": total["has_proteome_file"],
        "genome_gene_count": total["genome_gene_count"],
        "genome_coding_gene_count": total["genome_coding_gene_count"],
        "transcript_count": total["transcript_count"],
        "transcriptome_gene_count": total["transcriptome_gene_count"],
        "proteome_protein_count": total["proteome_protein_count"],
        "proteome_gene_count_sum": total["proteome_gene_count"],
        "proteome_transcript_count_sum": total["proteome_transcript_count"],
        "protein_rows_with_gene": total["protein_rows_with_gene"],
        "protein_rows_with_transcript": total["protein_rows_with_transcript"],
        "protein_rows_with_any_external_id": total["protein_rows_with_any_external_id"],
        "protein_rows_with_uniprot": total["protein_rows_with_uniprot"],
        "protein_rows_with_ncbi_gene": total["protein_rows_with_ncbi_gene"],
        "protein_rows_with_refseq_protein": total["protein_rows_with_refseq_protein"],
        "protein_rows_with_refseq_transcript": total["protein_rows_with_refseq_transcript"],
        "genome_genes_not_in_proteome": total["genome_genes_not_in_proteome"],
        "genome_coding_genes_not_in_proteome": total["genome_coding_genes_not_in_proteome"],
        "transcriptome_genes_not_in_proteome": total["transcriptome_genes_not_in_proteome"],
        "transcripts_not_in_proteome": total["transcripts_not_in_proteome"],
        "proteome_genes_not_in_genome": total["proteome_genes_not_in_genome"],
        "proteome_transcripts_not_in_transcriptome": total["proteome_transcripts_not_in_transcriptome"],
        "genome_gene_proteome_coverage_pct": pct(total["genome_gene_count"] - total["genome_genes_not_in_proteome"], total["genome_gene_count"]),
        "genome_coding_gene_proteome_coverage_pct": pct(total["genome_coding_gene_count"] - total["genome_coding_genes_not_in_proteome"], total["genome_coding_gene_count"]),
        "transcript_proteome_coverage_pct": pct(total["transcript_count"] - total["transcripts_not_in_proteome"], total["transcript_count"]),
        "local_external_any_pct": pct(total["protein_rows_with_any_external_id"], total["proteome_protein_count"]),
        "local_uniprot_pct": pct(total["protein_rows_with_uniprot"], total["proteome_protein_count"]),
        "local_ncbi_gene_pct": pct(total["protein_rows_with_ncbi_gene"], total["proteome_protein_count"]),
        "elapsed_seconds": round(elapsed, 3),
    }


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def markdown_table(rows: list[dict[str, object]], fields: list[str]) -> str:
    lines = ["|" + "|".join(fields) + "|", "|" + "|".join(["---"] * len(fields)) + "|"]
    for row in rows:
        lines.append("|" + "|".join(str(row.get(field, "")) for field in fields) + "|")
    return "\n".join(lines)


def write_report(summary_rows: list[dict[str, object]], out_dir: Path) -> None:
    fields = [
        "division",
        "genome_gene_count",
        "genome_genes_not_in_proteome",
        "genome_gene_proteome_coverage_pct",
        "genome_coding_gene_count",
        "genome_coding_genes_not_in_proteome",
        "genome_coding_gene_proteome_coverage_pct",
        "transcript_count",
        "transcripts_not_in_proteome",
        "transcript_proteome_coverage_pct",
        "proteome_protein_count",
        "local_external_any_pct",
        "local_uniprot_pct",
        "local_ncbi_gene_pct",
    ]
    notes = [
        "# 四类群 ID 映射差距分析",
        "",
        "本报告统计当前 final-whitelist 四类群 proteome-driven coding ID chain 与更完整三组学映射之间的差距。",
        "",
        "关键口径：",
        "- `genome_genes_not_in_proteome` 表示基因组特征表中存在、但当前蛋白质组主链没有覆盖的 gene_id；这些是当前四类群映射相对原生生物完整映射主要缺失的 gene-only 候选。",
        "- `transcripts_not_in_proteome` 表示转录组特征表中存在、但当前蛋白质组主链没有覆盖的 transcript_id；这些是 transcript-only / 非编码或无蛋白证据候选。",
        "- 外部 ID 覆盖率只统计本地特征表可解析到的 UniProt、NCBI Gene、RefSeq/INSDC 证据，不代表 UniProt/NCBI 官网在线全量交叉映射后的理论上限。",
        "",
        markdown_table(summary_rows, fields),
        "",
        "联网映射差异说明：本地文件没有保存的外部交叉引用无法仅靠本地统计推出。若要得到“联网后比本地多多少”的严格比例，需要对每个内部 ID 或抽样 ID 调用 UniProt/NCBI/Ensembl xref 服务并和本表逐项比较。",
    ]
    (out_dir / "final_whitelist_id_mapping_gap_analysis_report.md").write_text("\n".join(notes), encoding="utf-8")


def analyze_group(group: str, max_species: int | None, progress_interval: int) -> tuple[dict[str, object], list[dict[str, object]]]:
    started = time.time()
    rows = load_whitelist(group)
    if max_species is not None:
        rows = rows[:max_species]
    detail_rows: list[dict[str, object]] = []
    out_dir = OUT_ROOT / group
    out_dir.mkdir(parents=True, exist_ok=True)
    detail_path = out_dir / f"{group}_id_mapping_gap_species_detail.csv"
    with detail_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        for idx, whitelist_row in enumerate(rows, start=1):
            detail = analyze_species(group, whitelist_row)
            detail_rows.append(detail)
            writer.writerow({field: detail.get(field, "") for field in DETAIL_FIELDS})
            fh.flush()
            if idx == 1 or idx == len(rows) or idx % max(1, progress_interval) == 0:
                print(
                    f"[{group}] {idx}/{len(rows)} {detail['species_id']} "
                    f"genome_missing={detail['genome_genes_not_in_proteome']} "
                    f"tx_missing={detail['transcripts_not_in_proteome']} "
                    f"elapsed={time.time() - started:.1f}s",
                    flush=True,
                )
    summary = summarize_group(group, detail_rows, time.time() - started)
    with (out_dir / f"{group}_id_mapping_gap_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return summary, detail_rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("groups", nargs="*", choices=sorted(GROUPS))
    parser.add_argument("--max-species", type=int)
    parser.add_argument("--progress-interval", type=int, default=100)
    args = parser.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    groups = args.groups or list(GROUPS)
    summary_rows: list[dict[str, object]] = []
    manifest = {
        "schema_version": "final_whitelist_id_mapping_gap_analysis.v1",
        "created_at_unix": int(time.time()),
        "groups": [],
        "notes": [
            "Statistics are computed from local genome/transcriptome/proteome feature tables.",
            "The existing four-division mapping is proteome-driven; missing genome/transcriptome entities are not necessarily biological absence.",
            "Online UniProt/NCBI uplift cannot be inferred without network xref queries.",
        ],
    }
    for group in groups:
        summary, _detail_rows = analyze_group(group, args.max_species, args.progress_interval)
        summary_rows.append(summary)
        manifest["groups"].append(summary)
    write_csv(OUT_ROOT / "final_whitelist_id_mapping_gap_summary.csv", summary_rows, SUMMARY_FIELDS)
    with (OUT_ROOT / "final_whitelist_id_mapping_gap_manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    write_report(summary_rows, OUT_ROOT)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
