#!/usr/bin/env python3
"""Map platform protist IDs to external NCBI/UniProt-compatible identifiers.

The platform's primary gene/transcript/protein IDs come from Ensembl Genomes
annotation files. This script keeps that internal mapping intact and enriches it
with external identifiers that are already embedded in the downloaded feature
tables, especially UniProtKB accessions in protein descriptions and NCBI/INSDC
accessions in source protein/region fields.
"""

from __future__ import annotations

import csv
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODEX_ROOT = PROJECT_ROOT.parents[1]
SOURCE_ROOT = CODEX_ROOT / "\u539f\u751f\u751f\u7269"
PROTEOME_DIR = SOURCE_ROOT / "\u86cb\u767d\u8d28\u7ec4"
GENOME_DIR = SOURCE_ROOT / "\u57fa\u56e0\u7ec4"
METADATA_DIR = SOURCE_ROOT / "\u5143\u6570\u636e"
ID_MAPPING_DIR = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping"

INTERNAL_MAPPING = ID_MAPPING_DIR / "protist_omics_id_mapping_all_species.csv"
TAXONOMY_METADATA = METADATA_DIR / "local_all_protist_taxonomy_metadata.csv"

WIDE_OUT = ID_MAPPING_DIR / "protist_external_id_mapping_all_species.csv"
LONG_OUT = ID_MAPPING_DIR / "protist_external_id_mapping_long.csv"
SPECIES_QC_OUT = ID_MAPPING_DIR / "protist_external_id_mapping_species_qc.csv"
SPECIES_STANDARD_OUT = ID_MAPPING_DIR / "protist_species_standard_ids.csv"
SUMMARY_OUT = ID_MAPPING_DIR / "protist_external_id_mapping_summary.json"
REPORT_OUT = ID_MAPPING_DIR / "protist_external_id_mapping_result_report.md"


WIDE_FIELDS = [
    "species_id",
    "tax_id",
    "tax_name",
    "assembly_accession",
    "ensembl_release",
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
    "source_protein_id",
    "external_mapping_status",
    "external_mapping_confidence",
    "external_mapping_evidence",
]


LONG_FIELDS = [
    "species_id",
    "tax_id",
    "internal_gene_id",
    "internal_transcript_id",
    "internal_protein_id",
    "external_database",
    "external_id",
    "external_id_type",
    "mapping_source",
    "mapping_method",
    "mapping_confidence",
    "evidence_level",
    "source_release",
]


SPECIES_QC_FIELDS = [
    "species_id",
    "tax_id",
    "tax_name",
    "assembly_accession",
    "total_internal_rows",
    "rows_with_uniprot",
    "rows_with_ncbi_gene",
    "rows_with_ncbi_protein",
    "rows_with_refseq_protein",
    "rows_with_insdc_protein",
    "rows_with_refseq_transcript",
    "rows_with_sequence_region",
    "rows_with_any_external_gene_or_protein_id",
    "rows_species_standard_only",
    "rows_unmapped_external_gene_or_protein_id",
    "protein_index_rows_with_external_id",
    "external_mapping_grade",
]


SPECIES_STANDARD_FIELDS = [
    "species_id",
    "tax_id",
    "tax_name",
    "assembly_accession",
    "ensembl_name",
    "ensembl_display_name",
    "ensembl_release",
    "ncbi_taxonomy_status",
    "standard_id_note",
]


UNIPROT_SOURCE_RE = re.compile(
    r"\[Source:UniProtKB/(?P<section>Swiss-Prot|TrEMBL);Acc:(?P<acc>[A-Z0-9]+(?:-\d+)?)\]"
)
GENEID_RE = re.compile(r"\b(?:GeneID|EntrezGene|NCBI_Gene)[:=](\d+)\b", re.IGNORECASE)
REFSEQ_PROTEIN_RE = re.compile(r"\b(?:[NXWAYZ]P|WP|AP|YP|XP|NP|ZP)_\d+(?:\.\d+)?\b")
REFSEQ_TRANSCRIPT_RE = re.compile(r"\b(?:NM|XM|NR|XR)_\d+(?:\.\d+)?\b")
LEGACY_INSDC_PROTEIN_RE = re.compile(r"\b[A-Z]{3}\d{5}(?:\.\d+)?\b")
WGS_INSDC_PROTEIN_RE = re.compile(r"\b[A-Z]{4,6}\d{6,10}(?:\.\d+)?\b")
SEQUENCE_REGION_RE = re.compile(
    r"\b(?:[A-Z]{1,2}\d{5,8}|[A-Z]{4,6}\d{6,10})(?:\.\d+)?\b"
)


def clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def split_values(value: str) -> list[str]:
    return [item for item in value.split(";") if item]


def join_values(values: set[str] | list[str]) -> str:
    return ";".join(sorted(values))


def load_taxonomy() -> dict[str, dict[str, str]]:
    taxonomy: dict[str, dict[str, str]] = {}
    with TAXONOMY_METADATA.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            species_id = clean(row.get("species_id"))
            if not species_id:
                continue
            taxonomy[species_id] = {
                "tax_id": clean(row.get("tax_id_current") or row.get("tax_id_original")),
                "tax_name": clean(row.get("tax_name") or row.get("species")),
                "assembly_accession": clean(row.get("assembly_accession")),
                "ensembl_name": clean(row.get("ensembl_name")),
                "ensembl_display_name": clean(row.get("ensembl_display_name")),
                "ensembl_release": clean(row.get("ensembl_release")),
                "ncbi_taxonomy_status": clean(row.get("tax_id_status")),
            }
    return taxonomy


def discover_proteome_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in PROTEOME_DIR.glob("*.proteome_features.full.csv"):
        species_id = path.name[: -len(".proteome_features.full.csv")]
        files[species_id] = path
    for path in PROTEOME_DIR.glob("*.proteome_features.core.csv"):
        species_id = path.name[: -len(".proteome_features.core.csv")]
        files.setdefault(species_id, path)
    return dict(sorted(files.items()))


def discover_genome_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in GENOME_DIR.glob("*.genome_features.csv"):
        if path.name.endswith(".genome_features.core.csv"):
            continue
        species_id = path.name[: -len(".genome_features.csv")]
        files[species_id] = path
    for path in GENOME_DIR.glob("*.genome_features.core.csv"):
        species_id = path.name[: -len(".genome_features.core.csv")]
        files.setdefault(species_id, path)
    return dict(sorted(files.items()))


def get_text_candidates(row: dict[str, str]) -> str:
    return " ".join(
        clean(row.get(field))
        for field in ("description", "header_raw", "source_protein_id", "protein_id")
    )


def extract_external_ids(row: dict[str, str]) -> dict[str, set[str] | str]:
    text = get_text_candidates(row)
    source_protein_id = clean(row.get("source_protein_id"))
    source_text = f"{source_protein_id} {text}".strip()

    uniprot: set[str] = set()
    uniprot_sources: set[str] = set()
    for match in UNIPROT_SOURCE_RE.finditer(text):
        uniprot.add(match.group("acc"))
        uniprot_sources.add(f"UniProtKB/{match.group('section')}")

    gene_ids = set(GENEID_RE.findall(text))
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

    ncbi_proteins = set(refseq_proteins) | set(insdc_proteins)
    evidence: set[str] = set()
    if uniprot:
        evidence.add("protein_description_uniprot_source_acc")
    if gene_ids:
        evidence.add("protein_header_ncbi_geneid")
    if refseq_proteins:
        evidence.add("protein_header_refseq_protein_accession")
    if insdc_proteins:
        evidence.add("source_protein_id_insdc_protein_accession")
    if refseq_transcripts:
        evidence.add("protein_header_refseq_transcript_accession")
    if region_accessions:
        evidence.add("protein_header_sequence_region_accession")

    return {
        "uniprot_accessions": uniprot,
        "uniprot_source": uniprot_sources,
        "ncbi_gene_ids": gene_ids,
        "refseq_protein_accessions": refseq_proteins,
        "insdc_protein_accessions": insdc_proteins,
        "ncbi_protein_accessions": ncbi_proteins,
        "refseq_transcript_accessions": refseq_transcripts,
        "insdc_sequence_region_accessions": region_accessions,
        "source_protein_id": source_protein_id,
        "external_mapping_evidence": evidence,
    }


def compact_external_info(raw: dict[str, set[str] | str]) -> dict[str, str]:
    compact: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, set):
            compact[key] = join_values(value)
        else:
            compact[key] = clean(value)
    return compact


def has_gene_or_protein_external_id(info: dict[str, str]) -> bool:
    return bool(
        info.get("uniprot_accessions")
        or info.get("ncbi_gene_ids")
        or info.get("ncbi_protein_accessions")
    )


def external_status(info: dict[str, str]) -> tuple[str, str]:
    has_uniprot = bool(info.get("uniprot_accessions"))
    has_ncbi_gene = bool(info.get("ncbi_gene_ids"))
    has_ncbi_protein = bool(info.get("ncbi_protein_accessions"))
    has_region = bool(info.get("insdc_sequence_region_accessions"))

    if has_uniprot and (has_ncbi_gene or has_ncbi_protein):
        return "mapped_uniprot_and_ncbi", "high"
    if has_uniprot:
        return "mapped_uniprot", "high"
    if has_ncbi_gene or has_ncbi_protein:
        return "mapped_ncbi_gene_or_protein", "high"
    if has_region:
        return "species_and_region_only", "medium"
    return "species_standard_only", "low"


def build_external_protein_index() -> tuple[dict[tuple[str, str], dict[str, str]], dict[str, Counter]]:
    protein_index: dict[tuple[str, str], dict[str, str]] = {}
    protein_species_counts: dict[str, Counter] = defaultdict(Counter)
    for species_id, path in discover_proteome_files().items():
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                protein_id = clean(row.get("protein_id") or row.get("ensembl_protein_id") or row.get("source_protein_id"))
                if not protein_id:
                    continue
                raw_info = extract_external_ids(row)
                info = compact_external_info(raw_info)
                if not info.get("external_mapping_evidence"):
                    continue
                protein_index[(species_id, protein_id)] = info
                protein_species_counts[species_id]["protein_index_rows_with_external_id"] += 1
                if info.get("uniprot_accessions"):
                    protein_species_counts[species_id]["protein_index_rows_with_uniprot"] += 1
                if info.get("ncbi_protein_accessions"):
                    protein_species_counts[species_id]["protein_index_rows_with_ncbi_protein"] += 1
                if info.get("ncbi_gene_ids"):
                    protein_species_counts[species_id]["protein_index_rows_with_ncbi_gene"] += 1
    return protein_index, protein_species_counts


def extract_geneid_from_genome() -> dict[tuple[str, str], str]:
    gene_ids: dict[tuple[str, str], str] = {}
    for species_id, path in discover_genome_files().items():
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                gene_id = clean(row.get("gene_id"))
                if not gene_id:
                    continue
                text = " ".join(clean(row.get(field)) for field in ("source_gene_id", "gene_name", "locus_tag"))
                found = sorted(set(GENEID_RE.findall(text)))
                if found:
                    gene_ids[(species_id, gene_id)] = ";".join(found)
    return gene_ids


def write_species_standard_ids(taxonomy: dict[str, dict[str, str]]) -> None:
    with SPECIES_STANDARD_OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SPECIES_STANDARD_FIELDS)
        writer.writeheader()
        for species_id, tax in sorted(taxonomy.items()):
            writer.writerow(
                {
                    "species_id": species_id,
                    "tax_id": tax.get("tax_id", ""),
                    "tax_name": tax.get("tax_name", ""),
                    "assembly_accession": tax.get("assembly_accession", ""),
                    "ensembl_name": tax.get("ensembl_name", ""),
                    "ensembl_display_name": tax.get("ensembl_display_name", ""),
                    "ensembl_release": tax.get("ensembl_release", ""),
                    "ncbi_taxonomy_status": tax.get("ncbi_taxonomy_status", ""),
                    "standard_id_note": "NCBI Taxonomy and INSDC/NCBI Assembly are species-level standards, not gene-level cross-references.",
                }
            )


def write_long_rows(
    writer: csv.DictWriter,
    base: dict[str, str],
    info: dict[str, str],
    confidence: str,
    source_release: str,
) -> int:
    rows = 0
    mapping_source = "local_feature_tables"
    entries = [
        ("UniProtKB", "uniprot_accessions", "protein_accession", "description_source_acc"),
        ("NCBI Gene", "ncbi_gene_ids", "gene_id", "header_or_feature_geneid"),
        ("NCBI Protein", "refseq_protein_accessions", "refseq_protein_accession", "header_refseq_accession"),
        ("NCBI Protein", "insdc_protein_accessions", "insdc_protein_accession", "source_protein_id_accession"),
        ("NCBI Transcript", "refseq_transcript_accessions", "refseq_transcript_accession", "header_refseq_accession"),
        ("INSDC/NCBI Sequence", "insdc_sequence_region_accessions", "sequence_region_accession", "header_region_accession"),
    ]
    for database, info_key, id_type, method in entries:
        for external_id in split_values(info.get(info_key, "")):
            writer.writerow(
                {
                    "species_id": base["species_id"],
                    "tax_id": base["tax_id"],
                    "internal_gene_id": base["gene_id"],
                    "internal_transcript_id": base["transcript_id"],
                    "internal_protein_id": base["protein_id"],
                    "external_database": database,
                    "external_id": external_id,
                    "external_id_type": id_type,
                    "mapping_source": mapping_source,
                    "mapping_method": method,
                    "mapping_confidence": confidence,
                    "evidence_level": "direct_annotation_xref",
                    "source_release": source_release,
                }
            )
            rows += 1
    return rows


def grade_species(counts: Counter) -> str:
    total = counts["total_internal_rows"]
    if not total:
        return "D"
    pct_gene_or_protein = counts["rows_with_any_external_gene_or_protein_id"] / total * 100.0
    pct_uniprot = counts["rows_with_uniprot"] / total * 100.0
    pct_ncbi = counts["rows_with_ncbi_protein"] / total * 100.0
    if pct_gene_or_protein >= 60 and pct_uniprot >= 30:
        return "A"
    if pct_gene_or_protein >= 25:
        return "B"
    if pct_gene_or_protein > 0 or pct_ncbi > 0:
        return "C"
    return "D"


def build_mapping() -> dict[str, object]:
    start = time.time()
    ID_MAPPING_DIR.mkdir(parents=True, exist_ok=True)
    csv.field_size_limit(1024 * 1024 * 128)

    taxonomy = load_taxonomy()
    write_species_standard_ids(taxonomy)
    protein_index, protein_index_species_counts = build_external_protein_index()
    genome_geneids = extract_geneid_from_genome()

    species_counts: dict[str, Counter] = defaultdict(Counter)
    global_counts = Counter()
    long_rows = 0

    with INTERNAL_MAPPING.open("r", encoding="utf-8-sig", newline="") as in_fh, WIDE_OUT.open(
        "w", encoding="utf-8", newline=""
    ) as wide_fh, LONG_OUT.open("w", encoding="utf-8", newline="") as long_fh:
        reader = csv.DictReader(in_fh)
        wide_writer = csv.DictWriter(wide_fh, fieldnames=WIDE_FIELDS)
        long_writer = csv.DictWriter(long_fh, fieldnames=LONG_FIELDS)
        wide_writer.writeheader()
        long_writer.writeheader()

        for row in reader:
            species_id = clean(row.get("species_id"))
            gene_id = clean(row.get("gene_id"))
            transcript_id = clean(row.get("transcript_id"))
            protein_id = clean(row.get("protein_id"))
            tax = taxonomy.get(species_id, {})
            info = protein_index.get((species_id, protein_id), {}).copy()
            if gene_id and (species_id, gene_id) in genome_geneids:
                ids = set(split_values(info.get("ncbi_gene_ids", "")))
                ids.update(split_values(genome_geneids[(species_id, gene_id)]))
                info["ncbi_gene_ids"] = join_values(ids)
                evidence = set(split_values(info.get("external_mapping_evidence", "")))
                evidence.add("genome_feature_ncbi_geneid")
                info["external_mapping_evidence"] = join_values(evidence)

            for key in (
                "uniprot_accessions",
                "uniprot_source",
                "ncbi_gene_ids",
                "refseq_protein_accessions",
                "insdc_protein_accessions",
                "ncbi_protein_accessions",
                "refseq_transcript_accessions",
                "insdc_sequence_region_accessions",
                "source_protein_id",
                "external_mapping_evidence",
            ):
                info.setdefault(key, "")

            status, confidence = external_status(info)
            base = {
                "species_id": species_id,
                "tax_id": tax.get("tax_id", ""),
                "tax_name": tax.get("tax_name", ""),
                "assembly_accession": tax.get("assembly_accession", ""),
                "gene_id": gene_id,
                "transcript_id": transcript_id,
                "protein_id": protein_id,
            }
            wide_writer.writerow(
                {
                    **base,
                    "ensembl_release": tax.get("ensembl_release", ""),
                    "mapping_level": clean(row.get("mapping_level")),
                    "internal_mapping_status": clean(row.get("mapping_status")),
                    "internal_mapping_confidence": clean(row.get("mapping_confidence")),
                    "uniprot_accessions": info.get("uniprot_accessions", ""),
                    "uniprot_source": info.get("uniprot_source", ""),
                    "ncbi_gene_ids": info.get("ncbi_gene_ids", ""),
                    "refseq_protein_accessions": info.get("refseq_protein_accessions", ""),
                    "insdc_protein_accessions": info.get("insdc_protein_accessions", ""),
                    "ncbi_protein_accessions": info.get("ncbi_protein_accessions", ""),
                    "refseq_transcript_accessions": info.get("refseq_transcript_accessions", ""),
                    "insdc_sequence_region_accessions": info.get("insdc_sequence_region_accessions", ""),
                    "source_protein_id": info.get("source_protein_id", ""),
                    "external_mapping_status": status,
                    "external_mapping_confidence": confidence,
                    "external_mapping_evidence": info.get("external_mapping_evidence", ""),
                }
            )
            source_release = f"EnsemblGenomes:{tax.get('ensembl_release', '')}".rstrip(":")
            long_rows += write_long_rows(long_writer, base, info, confidence, source_release)

            counts = species_counts[species_id]
            counts["total_internal_rows"] += 1
            global_counts["total_internal_rows"] += 1
            if info.get("uniprot_accessions"):
                counts["rows_with_uniprot"] += 1
                global_counts["rows_with_uniprot"] += 1
            if info.get("ncbi_gene_ids"):
                counts["rows_with_ncbi_gene"] += 1
                global_counts["rows_with_ncbi_gene"] += 1
            if info.get("ncbi_protein_accessions"):
                counts["rows_with_ncbi_protein"] += 1
                global_counts["rows_with_ncbi_protein"] += 1
            if info.get("refseq_protein_accessions"):
                counts["rows_with_refseq_protein"] += 1
                global_counts["rows_with_refseq_protein"] += 1
            if info.get("insdc_protein_accessions"):
                counts["rows_with_insdc_protein"] += 1
                global_counts["rows_with_insdc_protein"] += 1
            if info.get("refseq_transcript_accessions"):
                counts["rows_with_refseq_transcript"] += 1
                global_counts["rows_with_refseq_transcript"] += 1
            if info.get("insdc_sequence_region_accessions"):
                counts["rows_with_sequence_region"] += 1
                global_counts["rows_with_sequence_region"] += 1
            if has_gene_or_protein_external_id(info):
                counts["rows_with_any_external_gene_or_protein_id"] += 1
                global_counts["rows_with_any_external_gene_or_protein_id"] += 1
            else:
                counts["rows_species_standard_only"] += 1
                counts["rows_unmapped_external_gene_or_protein_id"] += 1
                global_counts["rows_species_standard_only"] += 1
                global_counts["rows_unmapped_external_gene_or_protein_id"] += 1

    with SPECIES_QC_OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SPECIES_QC_FIELDS)
        writer.writeheader()
        for species_id in sorted(species_counts):
            tax = taxonomy.get(species_id, {})
            counts = species_counts[species_id]
            index_counts = protein_index_species_counts.get(species_id, Counter())
            row = {
                "species_id": species_id,
                "tax_id": tax.get("tax_id", ""),
                "tax_name": tax.get("tax_name", ""),
                "assembly_accession": tax.get("assembly_accession", ""),
                "external_mapping_grade": grade_species(counts),
            }
            for field in SPECIES_QC_FIELDS:
                if field in row:
                    continue
                if field == "protein_index_rows_with_external_id":
                    row[field] = index_counts["protein_index_rows_with_external_id"]
                else:
                    row[field] = counts[field]
            writer.writerow(row)

    global_counts["long_external_rows"] = long_rows
    grade_counts = Counter(grade_species(counts) for counts in species_counts.values())
    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_internal_mapping": str(INTERNAL_MAPPING),
        "source_taxonomy_metadata": str(TAXONOMY_METADATA),
        "source_proteome_dir": str(PROTEOME_DIR),
        "species_count": len(species_counts),
        "protein_index_rows_with_external_id": len(protein_index),
        "genome_rows_with_ncbi_geneid": len(genome_geneids),
        "counts": dict(global_counts),
        "species_grade_counts": dict(sorted(grade_counts.items())),
        "outputs": {
            "wide_mapping": str(WIDE_OUT),
            "long_mapping": str(LONG_OUT),
            "species_qc": str(SPECIES_QC_OUT),
            "species_standard_ids": str(SPECIES_STANDARD_OUT),
            "summary": str(SUMMARY_OUT),
            "report": str(REPORT_OUT),
        },
        "runtime_seconds": round(time.time() - start, 3),
    }
    SUMMARY_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(summary)
    return summary


def pct(value: int, total: int) -> str:
    if not total:
        return "0.00%"
    return f"{value / total * 100.0:.2f}%"


def write_report(summary: dict[str, object]) -> None:
    counts = summary["counts"]
    total = int(counts.get("total_internal_rows", 0))
    rows_with_uniprot = int(counts.get("rows_with_uniprot", 0))
    rows_with_ncbi_gene = int(counts.get("rows_with_ncbi_gene", 0))
    rows_with_ncbi_protein = int(counts.get("rows_with_ncbi_protein", 0))
    rows_with_refseq_protein = int(counts.get("rows_with_refseq_protein", 0))
    rows_with_insdc_protein = int(counts.get("rows_with_insdc_protein", 0))
    rows_with_any_gene_or_protein = int(counts.get("rows_with_any_external_gene_or_protein_id", 0))
    rows_species_standard_only = int(counts.get("rows_species_standard_only", 0))
    long_external_rows = int(counts.get("long_external_rows", 0))
    report = f"""# Protist External ID Mapping Result Report

## Task status

Completed. The platform's internal Ensembl/Ensembl-Genomes-derived gene,
transcript, and protein identifiers were enriched with external standard
identifiers available from local annotation evidence, mainly UniProtKB and
NCBI/INSDC-compatible identifiers.

## Scope

- Species covered: {summary["species_count"]}
- Internal ID rows processed: {total:,}
- Protein feature rows with at least one external evidence item: {summary["protein_index_rows_with_external_id"]:,}
- Genome feature rows with explicit NCBI GeneID evidence: {summary["genome_rows_with_ncbi_geneid"]:,}
- Long-format external mapping rows: {long_external_rows:,}

## Coverage

- Rows with UniProtKB accession: {rows_with_uniprot:,} ({pct(rows_with_uniprot, total)})
- Rows with NCBI GeneID: {rows_with_ncbi_gene:,} ({pct(rows_with_ncbi_gene, total)})
- Rows with NCBI/INSDC protein accession: {rows_with_ncbi_protein:,} ({pct(rows_with_ncbi_protein, total)})
- Rows with RefSeq protein accession: {rows_with_refseq_protein:,} ({pct(rows_with_refseq_protein, total)})
- Rows with INSDC/GenBank-style protein accession: {rows_with_insdc_protein:,} ({pct(rows_with_insdc_protein, total)})
- Rows with external gene/protein-level ID: {rows_with_any_gene_or_protein:,} ({pct(rows_with_any_gene_or_protein, total)})
- Rows with species-level standard IDs only: {rows_species_standard_only:,} ({pct(rows_species_standard_only, total)})

## Outputs

- `protist_external_id_mapping_all_species.csv`: one row per internal mapping row, with UniProt/NCBI columns.
- `protist_external_id_mapping_long.csv`: one row per external ID assertion.
- `protist_external_id_mapping_species_qc.csv`: per-species external mapping coverage and grade.
- `protist_species_standard_ids.csv`: species-level NCBI Taxonomy and assembly accession table.
- `protist_external_id_mapping_summary.json`: machine-readable summary.

## Interpretation limits

The mapping is direct evidence extracted from local Ensembl-derived annotation
feature files. UniProtKB accessions are high-confidence when Ensembl protein
descriptions explicitly contain `Source:UniProtKB/...;Acc:...`. NCBI protein
accessions are high-confidence when source protein IDs match RefSeq or
INSDC/GenBank accession patterns. NCBI Taxonomy and assembly accessions are
species-level standards and should not be treated as gene-level cross-references.

Rows without a UniProtKB/NCBI gene/protein accession remain valid internally but
cannot yet be treated as externally standardized at gene/protein level. For those
rows, the next enrichment step should use Ensembl BioMart/xref or UniProt ID
Mapping APIs in batches, with per-species QC.
"""
    REPORT_OUT.write_text(report, encoding="utf-8")


def main() -> None:
    summary = build_mapping()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
