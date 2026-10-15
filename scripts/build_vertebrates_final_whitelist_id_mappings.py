#!/usr/bin/env python3
"""Build final-whitelist ID mappings for vertebrates/chordates.

The earlier final-whitelist ID mapping run covered bacteria, fungi, metazoa,
and plants.  Vertebrates use the same schema, but their whitelist has two valid
QC batches and their proteome feature tables are stored per species.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping_final_whitelist"
GROUP = "vertebrates"
LABEL_CN = "\u810a\u7d22\u52a8\u7269"
WHITELIST_ROOT = Path("F:/") / "\u65b0\u7269\u79cd\u6570\u636e" / "\u5168\u7ec4\u5b66" / "vertebrates\u4e0b\u8f7d\u8d28\u68c0"
WHITELIST_BATCHES = [
    WHITELIST_ROOT / "condex\u8fd0\u884c_\u7b2c\u4e8c\u9636\u6bb5\u7ec8\u7b5b" / "species_whitelist_final.csv",
    WHITELIST_ROOT / "condex\u8fd0\u884c_\u7b2c\u4e8c\u9636\u6bb5\u975e\u767d\u540d\u5355\u590d\u7b5b_20260710" / "species_whitelist_final.csv",
]
FEATURE_ROOT = Path("G:/") / "stoichioomics" / "\u5168\u7ec4\u5b66\u7279\u5f81\u6570\u636e" / "\u810a\u7d22\u52a8\u7269"


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

UNIPROT_SOURCE_RE = re.compile(r"\[Source:UniProtKB/(?P<section>Swiss-Prot|TrEMBL);Acc:(?P<acc>[A-Z0-9]+(?:-\d+)?)\]")
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
    return ";".join(sorted(value for value in values if value))


def load_whitelist() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for batch_no, path in enumerate(WHITELIST_BATCHES, start=1):
        if not path.exists():
            raise FileNotFoundError(f"missing whitelist batch: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                species_id = clean(row.get("species"))
                if not species_id or clean(row.get("hard_fail")).lower() == "true":
                    continue
                if species_id in seen:
                    continue
                row["whitelist_batch"] = f"batch{batch_no}"
                row["source_whitelist"] = str(path)
                rows.append(row)
                seen.add(species_id)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def feature_files(species_id: str) -> dict[str, Path | None]:
    genome = FEATURE_ROOT / "\u57fa\u56e0\u7ec4" / f"{species_id}.genome_features.core.csv"
    transcript = FEATURE_ROOT / "\u8f6c\u5f55\u7ec4" / f"{species_id}.transcriptome.core.v5.csv"
    proteome_dir = FEATURE_ROOT / "\u86cb\u767d\u8d28\u7ec4" / species_id
    proteome = proteome_dir / f"{species_id}.proteome_features.core.csv"
    if not proteome.exists():
        proteome = proteome_dir / f"{species_id}.proteome_features.full.csv"
    return {
        "genome": genome if genome.exists() else None,
        "transcriptome": transcript if transcript.exists() else None,
        "proteome": proteome if proteome.exists() else None,
    }


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


def iter_protein_id_rows(path: Path):
    with path.open("rb") as fh:
        header_line = fh.readline().decode("utf-8-sig", "replace").rstrip("\r\n")
        header = header_line.split(",")
        index = {name: idx for idx, name in enumerate(header)}
        wanted = [
            "protein_id",
            "gene_id",
            "gene_symbol",
            "transcript_id",
            "source_db",
            "source_protein_id",
            "ensembl_gene_id",
            "ensembl_transcript_id",
            "ensembl_protein_id",
            "description",
            "header_raw",
        ]
        max_idx = max(index.get(name, -1) for name in wanted)
        for raw in fh:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                continue
            parts = line.split(",", max_idx if max_idx > 0 else 10)
            row = {}
            for name in wanted:
                idx = index.get(name)
                row[name] = parts[idx] if idx is not None and idx < len(parts) else ""
            yield row


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


def confidence_for(mapping_level: str, conflict_reason: str) -> str:
    if conflict_reason:
        return "low"
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
        "division": GROUP,
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
    whitelist_row: dict[str, str],
    internal_writer: csv.DictWriter,
    external_writer: csv.DictWriter,
) -> dict[str, Any]:
    species_id = clean(whitelist_row.get("species"))
    tax_id = clean(whitelist_row.get("taxon_id"))
    assembly_accession = clean(whitelist_row.get("assembly_accession"))
    files = feature_files(species_id)
    counters: Counter[str] = Counter()
    proteome_path = files["proteome"]
    if proteome_path:
        for protein_row in iter_protein_id_rows(proteome_path):
            counters["proteome_protein_count"] += 1
            protein_id = clean(
                protein_row.get("protein_id")
                or protein_row.get("ensembl_protein_id")
                or protein_row.get("source_protein_id")
            )
            gene_id = clean(protein_row.get("gene_id") or protein_row.get("ensembl_gene_id"))
            transcript_id = clean(protein_row.get("transcript_id") or protein_row.get("ensembl_transcript_id"))
            gene_symbol = clean(protein_row.get("gene_symbol"))
            if gene_id:
                counters["protein_rows_with_gene"] += 1
            if transcript_id:
                counters["protein_rows_with_transcript"] += 1
            mapping_level = (
                "gene_transcript_protein"
                if gene_id and transcript_id and protein_id
                else ("gene_protein" if gene_id and protein_id else "protein_only")
            )
            mapping_row = {
                "division": GROUP,
                "species_id": species_id,
                "tax_id": tax_id,
                "assembly_accession": assembly_accession,
                "gene_id": gene_id,
                "transcript_id": transcript_id,
                "protein_id": protein_id,
                "gene_symbol": gene_symbol,
                "gene_biotype": "",
                "transcript_biotype": "",
                "mapping_level": mapping_level,
                "mapping_source": "proteome_feature_table_fast_whitelist_qc",
                "mapping_status": "ok",
                "mapping_confidence": confidence_for(mapping_level, ""),
                "gene_in_genome": "",
                "transcript_in_transcriptome": "",
                "protein_in_proteome": "True",
                "transcript_gene_consistent": "",
                "protein_gene_consistent": "",
                "protein_transcript_consistent": "True" if protein_id else "",
                "genome_chosen_transcript_match": "",
                "genome_transcript_count": "",
                "conflict_reason": "",
            }
            write_internal(internal_writer, mapping_row)
            external_info = extract_external_ids(protein_row)
            if external_status(external_info)[0] != "species_standard_only":
                counters["rows_with_any_external_id"] += 1
            write_external(external_writer, mapping_row, external_info)
            counters["protein_mapping_rows"] += 1
            counters["total_mapping_rows"] += 1
    grade = "A" if files["proteome"] and counters["total_mapping_rows"] else "D"
    return {
        "division": GROUP,
        "species_id": species_id,
        "tax_id": tax_id,
        "assembly_accession": assembly_accession,
        "has_genome_file": str(bool(files["genome"])),
        "has_transcriptome_file": str(bool(files["transcriptome"])),
        "has_proteome_file": str(bool(files["proteome"])),
        "genome_gene_count": 0,
        "transcript_count": 0,
        "proteome_protein_count": counters["proteome_protein_count"],
        "protein_mapping_rows": counters["protein_mapping_rows"],
        "transcript_only_rows": 0,
        "gene_only_rows": 0,
        "total_mapping_rows": counters["total_mapping_rows"],
        "protein_rows_with_gene_pct": pct(counters["protein_rows_with_gene"], counters["proteome_protein_count"]),
        "protein_rows_with_transcript_pct": pct(counters["protein_rows_with_transcript"], counters["proteome_protein_count"]),
        "protein_gene_in_genome_pct": 0.0,
        "protein_transcript_in_transcriptome_pct": 0.0,
        "conflict_count": 0,
        "rows_with_any_external_id": counters["rows_with_any_external_id"],
        "mapping_grade": grade,
    }


def update_manifest(summary: dict[str, Any]) -> None:
    manifest_path = OUT_ROOT / "final_whitelist_id_mapping_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "schema_version": "final_whitelist_id_mapping.v1",
            "created_at_unix": int(time.time()),
            "groups": [],
            "internal_fields": INTERNAL_FIELDS,
            "external_fields": EXTERNAL_FIELDS,
            "qc_fields": QC_FIELDS,
            "notes": [],
        }
    groups = [item for item in manifest.get("groups", []) if item.get("division") != GROUP]
    groups.append(summary)
    manifest["groups"] = groups
    manifest["updated_at_unix"] = int(time.time())
    manifest["internal_fields"] = INTERNAL_FIELDS
    manifest["external_fields"] = EXTERNAL_FIELDS
    manifest["qc_fields"] = QC_FIELDS
    notes = set(manifest.get("notes") or [])
    notes.add("Vertebrates/chordates scope merges the stage-2 final whitelist and the non-whitelist rescreen final whitelist.")
    manifest["notes"] = sorted(notes)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(summary: dict[str, Any]) -> None:
    report_path = OUT_ROOT / GROUP / "vertebrates_id_mapping_result_report.md"
    totals = summary["totals"]
    lines = [
        "# Vertebrates Final-Whitelist ID Mapping Report",
        "",
        f"- Whitelist species: {summary['whitelist_species_count']}",
        f"- Internal omics mapping rows: {totals.get('total_mapping_rows', 0)}",
        f"- Rows with any local external ID evidence: {totals.get('rows_with_any_external_id', 0)}",
        f"- Runtime seconds: {summary['elapsed_seconds']}",
        "",
        "Outputs follow the existing final_whitelist_id_mapping.v1 schema used by bacteria, fungi, metazoa and plants.",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(max_species: int | None = None, progress_interval: int = 10) -> dict[str, Any]:
    start = time.time()
    rows = load_whitelist()
    if max_species is not None:
        rows = rows[:max_species]
    out_dir = OUT_ROOT / GROUP
    out_dir.mkdir(parents=True, exist_ok=True)
    merged_whitelist = out_dir / "vertebrates_species_whitelist_final_merged.csv"
    if rows:
        fields = list(rows[0].keys())
        write_csv(merged_whitelist, rows, fields)

    internal_path = out_dir / "vertebrates_omics_id_mapping_final_whitelist.csv"
    external_path = out_dir / "vertebrates_external_id_mapping_final_whitelist.csv"
    qc_path = out_dir / "vertebrates_id_mapping_species_qc.csv"
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
            summary = build_species(whitelist_row, internal_writer, external_writer)
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
                print(
                    f"[vertebrates] {idx}/{len(rows)} {summary['species_id']} "
                    f"species_rows={summary['total_mapping_rows']} total_rows={totals['total_mapping_rows']} "
                    f"external_rows={totals['rows_with_any_external_id']} "
                    f"species_elapsed={time.time() - species_start:.1f}s elapsed={time.time() - start:.1f}s",
                    flush=True,
                )
    result = {
        "division": GROUP,
        "label_cn": LABEL_CN,
        "whitelist_species_count": len(rows),
        "outputs": {
            "merged_whitelist_csv": str(merged_whitelist),
            "internal_mapping_csv": str(internal_path),
            "external_mapping_csv": str(external_path),
            "species_qc_csv": str(qc_path),
        },
        "totals": dict(totals),
        "elapsed_seconds": round(time.time() - start, 3),
        "source_whitelists": [str(path) for path in WHITELIST_BATCHES],
        "feature_root": str(FEATURE_ROOT),
        "include_unmatched_gene_or_transcript_rows": False,
    }
    (out_dir / "vertebrates_id_mapping_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    update_manifest(result)
    write_report(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-species", type=int, default=None)
    parser.add_argument("--progress-interval", type=int, default=10)
    args = parser.parse_args()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    result = build(max_species=args.max_species, progress_interval=args.progress_interval)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
