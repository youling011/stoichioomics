#!/usr/bin/env python3
"""Build ID mapping tables for final-whitelist non-protist divisions.

Inputs are the G: drive final post-download QC whitelists and feature tables.
The script streams species one by one and writes:
1. internal gene-transcript-protein mappings
2. internal Ensembl/platform ID to external standard ID mappings
"""

from __future__ import annotations
import sys as _corefull_sys
from pathlib import Path as _CoreFullPath
_corefull_sys.path.insert(0, str(_CoreFullPath(__file__).resolve().parents[1]))
from backend.apps.stoichdb.feature_sources import io as feature_io

import csv
import json
import re
import argparse
import sys
import time
from collections import Counter
from backend.apps.common.host_paths import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
G_ROOT = Path("G:/stoichioomics")
FEATURE_ROOT = G_ROOT / "全组学特征数据"
DOWNLOAD_ROOT = G_ROOT / "全组学下载数据"
OUT_ROOT = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping_final_whitelist"


GROUPS = {
    "metazoa": {
        "label_cn": "后生生物",
        "download_qc": DOWNLOAD_ROOT / "metazoa下载质检" / "condex运行_第二阶段终筛",
        "feature_group": "后生生物",
    },
    "bacteria": {
        "label_cn": "细菌",
        "download_qc": DOWNLOAD_ROOT / "bacteria下载质检" / "condex运行_第二阶段终筛",
        "feature_group": "细菌",
    },
    "fungi": {
        "label_cn": "真菌",
        "download_qc": DOWNLOAD_ROOT / "fungi下载质检" / "condex运行_第二阶段终筛",
        "feature_group": "真菌",
    },
    "plants": {
        "label_cn": "植物",
        "download_qc": DOWNLOAD_ROOT / "plants下载质检" / "condex运行_第二阶段终筛",
        "feature_group": "植物",
    },
}


INTERNAL_FIELDS = [
    "division",
    "species_id",
    "tax_id",
    "assembly_accession",
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


EXTERNAL_FIELDS = [
    "division",
    "species_id",
    "tax_id",
    "assembly_accession",
    "gene_id",
    "transcript_id",
    "protein_id",
    "mapping_level",
    "internal_mapping_status",
    "internal_mapping_confidence",
    "uniprot_accessions",
    "uniprot_source",
    "ncbi_gene_ids",
    "refseq_protein_accessions",
    "insdc_protein_accessions",
    "ncbi_protein_accessions",
    "refseq_transcript_accessions",
    "insdc_sequence_region_accessions",
    "source_db",
    "source_protein_id",
    "external_mapping_status",
    "external_mapping_confidence",
    "external_mapping_evidence",
]


QC_FIELDS = [
    "division",
    "species_id",
    "tax_id",
    "assembly_accession",
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
    "conflict_count",
    "rows_with_any_external_id",
    "mapping_grade",
]


UNIPROT_SOURCE_RE = re.compile(
    r"\[Source:UniProtKB/(?P<section>Swiss-Prot|TrEMBL);Acc:(?P<acc>[A-Z0-9]+(?:-\d+)?)\]"
)
GENEID_RE = re.compile(r"\b(?:GeneID|EntrezGene|NCBI_Gene)[:=](\d+)\b", re.IGNORECASE)
REFSEQ_PROTEIN_RE = re.compile(r"\b(?:[NXWAYZ]P|WP|AP|YP|XP|NP|ZP)_\d+(?:\.\d+)?\b")
REFSEQ_TRANSCRIPT_RE = re.compile(r"\b(?:NM|XM|NR|XR)_\d+(?:\.\d+)?\b")
LEGACY_INSDC_PROTEIN_RE = re.compile(r"\b[A-Z]{3}\d{5}(?:\.\d+)?\b")
WGS_INSDC_PROTEIN_RE = re.compile(r"\b[A-Z]{4,6}\d{6,10}(?:\.\d+)?\b")
SEQUENCE_REGION_RE = re.compile(r"\b(?:[A-Z]{1,2}\d{5,8}|[A-Z]{4,6}\d{6,10})(?:\.\d+)?\b")


def clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100.0, 4) if denominator else 0.0


def join_values(values: set[str]) -> str:
    return ";".join(sorted(v for v in values if v))


def whitelist_path(group: str) -> Path:
    return GROUPS[group]["download_qc"] / "species_whitelist_final.csv"


def load_whitelist(group: str) -> list[dict[str, str]]:
    path = whitelist_path(group)
    rows: list[dict[str, str]] = []
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            species_id = clean(row.get("species"))
            if not species_id:
                continue
            if clean(row.get("hard_fail")).lower() == "true":
                continue
            rows.append(row)
    return rows


def group_feature_root(group: str) -> Path:
    return FEATURE_ROOT / GROUPS[group]["feature_group"]


def feature_files(group: str, species_id: str) -> dict[str, Path | None]:
    root = group_feature_root(group)
    genome = root / "基因组" / f"{species_id}.genome_features.core.csv"
    transcript = root / "转录组" / f"{species_id}.transcriptome.core.v5.csv"
    proteome_dir = root / "蛋白质组" / species_id
    proteome = proteome_dir / f"{species_id}.proteome_features.core.csv"
    if not feature_io.source_available(proteome):
        proteome = proteome_dir / f"{species_id}.proteome_features.full.csv"
    return {
        "genome": genome if feature_io.source_available(genome) else None,
        "transcriptome": transcript if feature_io.source_available(transcript) else None,
        "proteome": proteome if feature_io.source_available(proteome) else None,
    }


def read_genome(path: Path | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    genes: dict[str, dict[str, str]] = {}
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as fh:
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
                    "gene_biotype": clean(row.get("biotype") or row.get("gene_biotype")),
                    "chosen_transcript_source_id": clean(row.get("chosen_transcript_source_id")),
                    "transcript_count": clean(row.get("transcript_count")),
                },
            )
    return genes


def read_transcripts(path: Path | None) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    if not path:
        return {}, {}
    transcripts: dict[str, dict[str, str]] = {}
    gene_to_transcripts: dict[str, set[str]] = {}
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as fh:
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
                    "gene_symbol": clean(row.get("gene_symbol") or row.get("gene_name")),
                    "gene_biotype": clean(row.get("gene_biotype")),
                    "transcript_biotype": clean(row.get("transcript_biotype")),
                },
            )
            if gene_id:
                gene_to_transcripts.setdefault(gene_id, set()).add(transcript_id)
    return transcripts, gene_to_transcripts


def extract_external_ids(row: dict[str, str]) -> dict[str, str]:
    text = " ".join(
        clean(row.get(field))
        for field in ("description", "header_raw", "source_protein_id", "protein_id", "ensembl_protein_id")
    )
    source_protein_id = clean(row.get("source_protein_id"))
    source_text = f"{source_protein_id} {text}".strip()

    uniprot: set[str] = set()
    uniprot_sources: set[str] = set()
    for match in UNIPROT_SOURCE_RE.finditer(text):
        uniprot.add(match.group("acc"))
        uniprot_sources.add(f"UniProtKB/{match.group('section')}")

    ncbi_gene_ids = set(GENEID_RE.findall(text))
    refseq_proteins = set(REFSEQ_PROTEIN_RE.findall(source_text))
    refseq_transcripts = set(REFSEQ_TRANSCRIPT_RE.findall(source_text))

    insdc_proteins: set[str] = set()
    if source_protein_id and not refseq_proteins:
        for pattern in (LEGACY_INSDC_PROTEIN_RE, WGS_INSDC_PROTEIN_RE):
            if pattern.fullmatch(source_protein_id):
                insdc_proteins.add(source_protein_id)

    region_accessions: set[str] = set()
    header = clean(row.get("header_raw"))
    for token in re.split(r"[:\s,;|]", header):
        token = token.strip()
        if not token or token in refseq_proteins or token in insdc_proteins:
            continue
        if SEQUENCE_REGION_RE.fullmatch(token):
            region_accessions.add(token)

    ncbi_proteins = refseq_proteins | insdc_proteins
    evidence: set[str] = set()
    if uniprot:
        evidence.add("protein_description_uniprot_source_acc")
    if ncbi_gene_ids:
        evidence.add("protein_header_ncbi_geneid")
    if refseq_proteins:
        evidence.add("protein_or_source_refseq_protein_accession")
    if insdc_proteins:
        evidence.add("source_protein_id_insdc_protein_accession")
    if refseq_transcripts:
        evidence.add("protein_or_source_refseq_transcript_accession")
    if region_accessions:
        evidence.add("protein_header_sequence_region_accession")

    return {
        "uniprot_accessions": join_values(uniprot),
        "uniprot_source": join_values(uniprot_sources),
        "ncbi_gene_ids": join_values(ncbi_gene_ids),
        "refseq_protein_accessions": join_values(refseq_proteins),
        "insdc_protein_accessions": join_values(insdc_proteins),
        "ncbi_protein_accessions": join_values(ncbi_proteins),
        "refseq_transcript_accessions": join_values(refseq_transcripts),
        "insdc_sequence_region_accessions": join_values(region_accessions),
        "source_db": clean(row.get("source_db")),
        "source_protein_id": source_protein_id,
        "external_mapping_evidence": join_values(evidence),
    }


def external_status(info: dict[str, str]) -> tuple[str, str]:
    direct = any(
        info.get(field)
        for field in (
            "uniprot_accessions",
            "ncbi_gene_ids",
            "refseq_protein_accessions",
            "insdc_protein_accessions",
            "ncbi_protein_accessions",
            "refseq_transcript_accessions",
        )
    )
    if direct:
        return "mapped_external_gene_or_protein", "medium"
    if info.get("insdc_sequence_region_accessions"):
        return "species_region_only", "low"
    return "species_standard_only", "low"


def confidence_for(mapping_level: str, conflict_reason: str, has_genome: bool, has_transcriptome: bool) -> str:
    if conflict_reason:
        return "low"
    if mapping_level == "gene_transcript_protein" and has_genome and has_transcriptome:
        return "high"
    if mapping_level == "gene_transcript_protein":
        return "high"
    if mapping_level in {"gene_transcript", "gene_protein"}:
        return "medium"
    return "low"


def write_internal(writer: csv.DictWriter, row: dict[str, Any]) -> None:
    writer.writerow({field: row.get(field, "") for field in INTERNAL_FIELDS})


def write_external(writer: csv.DictWriter, row: dict[str, Any], external: dict[str, str]) -> None:
    status, confidence = external_status(external)
    out = {
        "division": row.get("division", ""),
        "species_id": row.get("species_id", ""),
        "tax_id": row.get("tax_id", ""),
        "assembly_accession": row.get("assembly_accession", ""),
        "gene_id": row.get("gene_id", ""),
        "transcript_id": row.get("transcript_id", ""),
        "protein_id": row.get("protein_id", ""),
        "mapping_level": row.get("mapping_level", ""),
        "internal_mapping_status": row.get("mapping_status", ""),
        "internal_mapping_confidence": row.get("mapping_confidence", ""),
        **external,
        "external_mapping_status": status,
        "external_mapping_confidence": confidence,
    }
    writer.writerow({field: out.get(field, "") for field in EXTERNAL_FIELDS})


def build_species(
    group: str,
    whitelist_row: dict[str, str],
    internal_writer: csv.DictWriter,
    external_writer: csv.DictWriter,
    *,
    include_unmatched: bool = False,
) -> dict[str, Any]:
    species_id = clean(whitelist_row.get("species"))
    tax_id = clean(whitelist_row.get("taxon_id"))
    assembly_accession = clean(whitelist_row.get("assembly_accession"))
    files = feature_files(group, species_id)
    genome = read_genome(files["genome"]) if include_unmatched else {}
    transcripts, gene_to_transcripts = read_transcripts(files["transcriptome"]) if include_unmatched else ({}, {})
    has_genome = bool(files["genome"])
    has_transcriptome = bool(files["transcriptome"])

    mapped_transcripts: set[str] = set()
    mapped_genes: set[str] = set()
    counters: Counter[str] = Counter()

    proteome_path = files["proteome"]
    if proteome_path:
        with feature_io.open_source(proteome_path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for protein_row in reader:
                counters["proteome_protein_count"] += 1
                protein_id = clean(
                    protein_row.get("protein_id")
                    or protein_row.get("ensembl_protein_id")
                    or protein_row.get("source_protein_id")
                )
                gene_id = clean(protein_row.get("gene_id") or protein_row.get("ensembl_gene_id"))
                transcript_id = clean(protein_row.get("transcript_id") or protein_row.get("ensembl_transcript_id"))
                gene_symbol = clean(protein_row.get("gene_symbol"))
                conflict_parts: list[str] = []
                if gene_id:
                    counters["protein_rows_with_gene"] += 1
                if transcript_id:
                    counters["protein_rows_with_transcript"] += 1
                gene_in_genome = bool(gene_id and gene_id in genome) if include_unmatched else False
                transcript_in_transcriptome = bool(transcript_id and transcript_id in transcripts) if include_unmatched else False
                if gene_in_genome:
                    counters["protein_gene_in_genome"] += 1
                if transcript_in_transcriptome:
                    counters["protein_transcript_in_transcriptome"] += 1
                transcript_gene_consistent = ""
                if include_unmatched and transcript_in_transcriptome and gene_id:
                    tx_gene = transcripts[transcript_id].get("gene_id", "")
                    transcript_gene_consistent = str(tx_gene == gene_id)
                    if tx_gene != gene_id:
                        conflict_parts.append(f"transcript_gene_mismatch:{tx_gene}")
                elif include_unmatched and transcript_id and not transcript_in_transcriptome:
                    conflict_parts.append("transcript_missing_from_transcriptome")
                if include_unmatched and gene_id and has_genome and not gene_in_genome:
                    conflict_parts.append("gene_missing_from_genome")
                chosen_match = ""
                if include_unmatched and gene_id in genome and transcript_id:
                    chosen = genome[gene_id].get("chosen_transcript_source_id", "")
                    chosen_match = "True" if chosen == transcript_id else ("False" if chosen else "")

                mapping_level = "gene_transcript_protein" if gene_id and transcript_id and protein_id else (
                    "gene_protein" if gene_id and protein_id else "protein_only"
                )
                conflict_reason = ";".join(conflict_parts)
                if conflict_reason:
                    counters["conflict_count"] += 1
                mapping_row = {
                    "division": group,
                    "species_id": species_id,
                    "tax_id": tax_id,
                    "assembly_accession": assembly_accession,
                    "gene_id": gene_id,
                    "transcript_id": transcript_id,
                    "protein_id": protein_id,
                    "gene_symbol": gene_symbol or (transcripts.get(transcript_id) or {}).get("gene_symbol", ""),
                    "gene_biotype": (transcripts.get(transcript_id) or {}).get("gene_biotype", ""),
                    "transcript_biotype": (transcripts.get(transcript_id) or {}).get("transcript_biotype", ""),
                    "mapping_level": mapping_level,
                    "mapping_source": "proteome_feature_table" if include_unmatched else "proteome_feature_table_fast_whitelist_qc",
                    "mapping_status": "conflict" if conflict_reason else "ok",
                    "mapping_confidence": confidence_for(mapping_level, conflict_reason, has_genome, has_transcriptome),
                    "gene_in_genome": str(gene_in_genome) if include_unmatched else "",
                    "transcript_in_transcriptome": str(transcript_in_transcriptome) if include_unmatched else "",
                    "protein_in_proteome": "True",
                    "transcript_gene_consistent": transcript_gene_consistent,
                    "protein_gene_consistent": transcript_gene_consistent,
                    "protein_transcript_consistent": "True" if protein_id else "",
                    "genome_chosen_transcript_match": chosen_match,
                    "genome_transcript_count": genome.get(gene_id, {}).get("transcript_count", ""),
                    "conflict_reason": conflict_reason,
                }
                write_internal(internal_writer, mapping_row)
                external_info = extract_external_ids(protein_row)
                if external_status(external_info)[0] != "species_standard_only":
                    counters["rows_with_any_external_id"] += 1
                write_external(external_writer, mapping_row, external_info)
                counters["protein_mapping_rows"] += 1
                counters["total_mapping_rows"] += 1
                if transcript_id:
                    mapped_transcripts.add(transcript_id)
                if gene_id:
                    mapped_genes.add(gene_id)

    empty_external = {
        "uniprot_accessions": "",
        "uniprot_source": "",
        "ncbi_gene_ids": "",
        "refseq_protein_accessions": "",
        "insdc_protein_accessions": "",
        "ncbi_protein_accessions": "",
        "refseq_transcript_accessions": "",
        "insdc_sequence_region_accessions": "",
        "source_db": "",
        "source_protein_id": "",
        "external_mapping_evidence": "",
    }
    if include_unmatched:
        for transcript_id, tx in transcripts.items():
            if transcript_id in mapped_transcripts:
                continue
            gene_id = tx.get("gene_id", "")
            gene_in_genome = bool(gene_id and gene_id in genome)
            conflict_reason = "gene_missing_from_genome" if gene_id and has_genome and not gene_in_genome else ""
            mapping_row = {
                "division": group,
                "species_id": species_id,
                "tax_id": tax_id,
                "assembly_accession": assembly_accession,
                "gene_id": gene_id,
                "transcript_id": transcript_id,
                "protein_id": "",
                "gene_symbol": tx.get("gene_symbol", ""),
                "gene_biotype": tx.get("gene_biotype", ""),
                "transcript_biotype": tx.get("transcript_biotype", ""),
                "mapping_level": "gene_transcript" if gene_id else "transcript_only",
                "mapping_source": "transcriptome_feature_table",
                "mapping_status": "conflict" if conflict_reason else "ok",
                "mapping_confidence": confidence_for("gene_transcript", conflict_reason, has_genome, has_transcriptome),
                "gene_in_genome": str(gene_in_genome),
                "transcript_in_transcriptome": "True",
                "protein_in_proteome": "False",
                "transcript_gene_consistent": "",
                "protein_gene_consistent": "",
                "protein_transcript_consistent": "",
                "genome_chosen_transcript_match": "",
                "genome_transcript_count": genome.get(gene_id, {}).get("transcript_count", ""),
                "conflict_reason": conflict_reason,
            }
            write_internal(internal_writer, mapping_row)
            write_external(external_writer, mapping_row, empty_external)
            counters["transcript_only_rows"] += 1
            counters["total_mapping_rows"] += 1
            if gene_id:
                mapped_genes.add(gene_id)
            if conflict_reason:
                counters["conflict_count"] += 1

        for gene_id, gene in genome.items():
            if gene_id in mapped_genes:
                continue
            mapping_row = {
                "division": group,
                "species_id": species_id,
                "tax_id": tax_id,
                "assembly_accession": assembly_accession,
                "gene_id": gene_id,
                "transcript_id": "",
                "protein_id": "",
                "gene_symbol": gene.get("gene_name", ""),
                "gene_biotype": gene.get("gene_biotype", ""),
                "transcript_biotype": "",
                "mapping_level": "gene_only",
                "mapping_source": "genome_feature_table",
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
            }
            write_internal(internal_writer, mapping_row)
            write_external(external_writer, mapping_row, empty_external)
            counters["gene_only_rows"] += 1
            counters["total_mapping_rows"] += 1

    grade = "A" if counters["conflict_count"] == 0 and files["proteome"] else ("B" if files["proteome"] else "C")
    return {
        "division": group,
        "species_id": species_id,
        "tax_id": tax_id,
        "assembly_accession": assembly_accession,
        "has_genome_file": str(bool(files["genome"])),
        "has_transcriptome_file": str(bool(files["transcriptome"])),
        "has_proteome_file": str(bool(files["proteome"])),
        "genome_gene_count": len(genome),
        "transcript_count": len(transcripts),
        "proteome_protein_count": counters["proteome_protein_count"],
        "protein_mapping_rows": counters["protein_mapping_rows"],
        "transcript_only_rows": counters["transcript_only_rows"],
        "gene_only_rows": counters["gene_only_rows"],
        "total_mapping_rows": counters["total_mapping_rows"],
        "protein_rows_with_gene_pct": pct(counters["protein_rows_with_gene"], counters["proteome_protein_count"]),
        "protein_rows_with_transcript_pct": pct(counters["protein_rows_with_transcript"], counters["proteome_protein_count"]),
        "protein_gene_in_genome_pct": pct(counters["protein_gene_in_genome"], counters["proteome_protein_count"]),
        "protein_transcript_in_transcriptome_pct": pct(counters["protein_transcript_in_transcriptome"], counters["proteome_protein_count"]),
        "conflict_count": counters["conflict_count"],
        "rows_with_any_external_id": counters["rows_with_any_external_id"],
        "mapping_grade": grade,
    }


def build_group(
    group: str,
    *,
    max_species: int | None = None,
    include_unmatched: bool = False,
    progress_interval: int = 100,
) -> dict[str, Any]:
    start = time.time()
    rows = load_whitelist(group)
    if max_species is not None:
        rows = rows[:max_species]
    out_dir = OUT_ROOT / group
    out_dir.mkdir(parents=True, exist_ok=True)
    internal_path = out_dir / f"{group}_omics_id_mapping_final_whitelist.csv"
    external_path = out_dir / f"{group}_external_id_mapping_final_whitelist.csv"
    qc_path = out_dir / f"{group}_id_mapping_species_qc.csv"

    totals: Counter[str] = Counter()
    with (
        internal_path.open("w", encoding="utf-8", newline="") as internal_fh,
        external_path.open("w", encoding="utf-8", newline="") as external_fh,
        qc_path.open("w", encoding="utf-8", newline="") as qc_fh,
    ):
        internal_writer = csv.DictWriter(internal_fh, fieldnames=INTERNAL_FIELDS)
        external_writer = csv.DictWriter(external_fh, fieldnames=EXTERNAL_FIELDS)
        qc_writer = csv.DictWriter(qc_fh, fieldnames=QC_FIELDS)
        internal_writer.writeheader()
        external_writer.writeheader()
        qc_writer.writeheader()
        for idx, whitelist_row in enumerate(rows, start=1):
            species_start = time.time()
            summary = build_species(
                group,
                whitelist_row,
                internal_writer,
                external_writer,
                include_unmatched=include_unmatched,
            )
            qc_writer.writerow({field: summary.get(field, "") for field in QC_FIELDS})
            for key in (
                "genome_gene_count",
                "transcript_count",
                "proteome_protein_count",
                "protein_mapping_rows",
                "transcript_only_rows",
                "gene_only_rows",
                "total_mapping_rows",
                "conflict_count",
                "rows_with_any_external_id",
            ):
                totals[key] += int(summary.get(key) or 0)
            if idx == 1 or idx == len(rows) or idx % max(1, progress_interval) == 0:
                elapsed = time.time() - start
                species_elapsed = time.time() - species_start
                print(
                    f"[{group}] {idx}/{len(rows)} {summary['species_id']} "
                    f"species_rows={summary['total_mapping_rows']} total_rows={totals['total_mapping_rows']} "
                    f"external_rows={totals['rows_with_any_external_id']} "
                    f"species_elapsed={species_elapsed:.1f}s elapsed={elapsed:.1f}s",
                    flush=True,
                )

    result = {
        "division": group,
        "label_cn": GROUPS[group]["label_cn"],
        "whitelist_species_count": len(rows),
        "outputs": {
            "internal_mapping_csv": str(internal_path),
            "external_mapping_csv": str(external_path),
            "species_qc_csv": str(qc_path),
        },
        "totals": dict(totals),
        "elapsed_seconds": round(time.time() - start, 3),
        "source_whitelist": str(whitelist_path(group)),
        "feature_root": str(group_feature_root(group)),
        "include_unmatched_gene_or_transcript_rows": include_unmatched,
    }
    with (out_dir / f"{group}_id_mapping_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("groups", nargs="*", choices=sorted(GROUPS))
    parser.add_argument("--max-species", type=int, default=None)
    parser.add_argument("--progress-interval", type=int, default=100)
    parser.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Also read genome/transcriptome tables and append transcript-only/gene-only rows.",
    )
    args = parser.parse_args()
    groups = args.groups or list(GROUPS)
    invalid = [group for group in groups if group not in GROUPS]
    if invalid:
        raise SystemExit(f"Unknown groups: {', '.join(invalid)}")
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    all_results = []
    for group in groups:
        all_results.append(
            build_group(
                group,
                max_species=args.max_species,
                include_unmatched=args.include_unmatched,
                progress_interval=args.progress_interval,
            )
        )
    manifest = {
        "schema_version": "final_whitelist_id_mapping.v1",
        "created_at_unix": int(time.time()),
        "groups": all_results,
        "internal_fields": INTERNAL_FIELDS,
        "external_fields": EXTERNAL_FIELDS,
        "qc_fields": QC_FIELDS,
        "notes": [
            "Species scope is species_whitelist_final.csv from each division post-download QC directory.",
            "Mappings are generated from feature tables on G:/stoichioomics, not from online services.",
            "External mappings are evidence extracted from local protein feature metadata and species standard taxon/assembly fields.",
            "Default mode is proteome-driven coding ID chains. Use --include-unmatched to add transcript-only/gene-only extension rows.",
        ],
    }
    with (OUT_ROOT / "final_whitelist_id_mapping_manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
