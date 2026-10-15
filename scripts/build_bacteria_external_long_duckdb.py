#!/usr/bin/env python3
"""Build the complete bacteria external-ID long table with DuckDB.

This is the non-degraded path for the 13GB bacteria final-whitelist external
wide table. DuckDB scans the wide CSV once into a compact filtered table, then
all long/QC outputs are generated from that filtered table plus the existing
per-species QC table.
"""

from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINAL_ROOT = PROJECT_ROOT / "data" / "id_mapping" / "final_whitelist"
WIDE_CSV = FINAL_ROOT / "bacteria" / "bacteria_external_id_mapping_final_whitelist.csv"
SPECIES_QC_CSV = FINAL_ROOT / "bacteria" / "bacteria_id_mapping_species_qc.csv"
OUT_ROOT = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping_final_whitelist_online_external" / "bacteria"
DATA_ROOT = FINAL_ROOT / "online_external" / "bacteria"
DB_PATH = OUT_ROOT / "bacteria_external_long_build.duckdb"

ACC_FIELDS = [
    "division",
    "uniprot_accession",
    "target_database",
    "external_id",
    "external_id_type",
    "mapping_method",
    "mapping_source",
]
LONG_FIELDS = [
    "division",
    "species_id",
    "tax_id",
    "assembly_accession",
    "internal_gene_id",
    "internal_transcript_id",
    "internal_protein_id",
    "uniprot_accession",
    "external_database",
    "external_id",
    "external_id_type",
    "mapping_source",
    "mapping_method",
    "mapping_confidence",
    "evidence_level",
    "source_release",
]
QC_FIELDS = [
    "division",
    "species_id",
    "tax_id",
    "assembly_accession",
    "total_internal_rows",
    "rows_with_local_uniprot",
    "rows_with_local_ncbi_gene",
    "rows_with_local_ncbi_protein",
    "rows_with_local_refseq_protein",
    "rows_with_local_refseq_transcript",
    "rows_with_local_insdc_region",
    "rows_with_online_ncbi_gene",
    "rows_with_online_refseq_protein",
    "rows_with_any_external_gene_or_protein_id",
    "rows_species_standard_only",
    "long_external_rows",
    "external_mapping_grade",
]
STANDARD_FIELDS = ["division", "species_id", "tax_id", "assembly_accession", "standard_id_note"]


def sql_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace("'", "''")


def hardlink_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        if src.stat().st_size <= 100 * 1024 * 1024:
            dst.write_bytes(src.read_bytes())


def sample_csv(src: Path, dst: Path, every: int = 100, max_rows: int = 100_000) -> int:
    rows = 0
    with src.open("r", encoding="utf-8-sig", newline="") as in_fh, dst.open("w", encoding="utf-8", newline="") as out_fh:
        reader = csv.reader(in_fh)
        writer = csv.writer(out_fh)
        header = next(reader, None)
        if header:
            writer.writerow(header)
        for idx, row in enumerate(reader, start=1):
            if idx % every == 0:
                writer.writerow(row)
                rows += 1
                if rows >= max_rows:
                    break
    return rows


def write_empty_accession_map(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        csv.DictWriter(fh, fieldnames=ACC_FIELDS).writeheader()


def main() -> int:
    start = time.time()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    con = duckdb.connect(str(DB_PATH))
    con.execute("PRAGMA threads=8")
    con.execute("PRAGMA memory_limit='6GB'")
    con.execute(f"PRAGMA temp_directory='{sql_path(OUT_ROOT)}'")
    wide = sql_path(WIDE_CSV)
    qc = sql_path(SPECIES_QC_CSV)

    print("[bacteria-duckdb] scanning wide CSV into filtered external_rows", flush=True)
    con.execute(
        f"""
        CREATE TABLE external_rows AS
        SELECT
          division, species_id, tax_id, assembly_accession,
          gene_id, transcript_id, protein_id,
          uniprot_accessions, ncbi_gene_ids,
          refseq_protein_accessions, insdc_protein_accessions,
          ncbi_protein_accessions, refseq_transcript_accessions,
          insdc_sequence_region_accessions
        FROM read_csv('{wide}', header=true, all_varchar=true, ignore_errors=true, parallel=true)
        WHERE coalesce(uniprot_accessions, '') <> ''
           OR coalesce(ncbi_gene_ids, '') <> ''
           OR coalesce(refseq_protein_accessions, '') <> ''
           OR coalesce(insdc_protein_accessions, '') <> ''
           OR coalesce(ncbi_protein_accessions, '') <> ''
           OR coalesce(refseq_transcript_accessions, '') <> ''
           OR coalesce(insdc_sequence_region_accessions, '') <> ''
        """
    )
    external_rows = con.execute("SELECT count(*) FROM external_rows").fetchone()[0]
    unique_uniprot = con.execute(
        """
        SELECT count(DISTINCT accession)
        FROM external_rows, unnest(string_split(uniprot_accessions, ';')) AS t(accession)
        WHERE coalesce(uniprot_accessions, '') <> '' AND accession <> ''
        """
    ).fetchone()[0]
    print(f"[bacteria-duckdb] external_rows={external_rows:,} unique_uniprot={unique_uniprot:,}", flush=True)

    long_path = OUT_ROOT / "bacteria_external_id_mapping_long_final_whitelist.csv"
    print("[bacteria-duckdb] building validated long rows", flush=True)
    con.execute(
        """
        CREATE TABLE long_rows AS
        SELECT * FROM (
          SELECT division, species_id, tax_id, assembly_accession,
                 gene_id AS internal_gene_id, transcript_id AS internal_transcript_id, protein_id AS internal_protein_id,
                 external_id AS uniprot_accession,
                 'UniProtKB' AS external_database, external_id,
                 'protein_accession' AS external_id_type,
                 'local_feature_tables' AS mapping_source,
                 'local_uniprot_source_acc' AS mapping_method,
                 'high' AS mapping_confidence,
                 'direct_annotation_xref' AS evidence_level,
                 'EnsemblGenomes' AS source_release
          FROM external_rows, unnest(string_split(uniprot_accessions, ';')) AS t(external_id)
          WHERE coalesce(uniprot_accessions, '') <> ''
            AND regexp_full_match(external_id, '^[A-NR-Z][0-9][A-Z][A-Z0-9]{2}[0-9](?:-[0-9]+)?$|^[A-NR-Z][A-Z0-9][0-9][A-Z][A-Z0-9]{2}[0-9](?:-[0-9]+)?$')
          UNION ALL
          SELECT division, species_id, tax_id, assembly_accession, gene_id, transcript_id, protein_id,
                 '' AS uniprot_accession, 'NCBI Gene', external_id, 'gene_id',
                 'local_feature_tables', 'local_geneid', 'high', 'direct_annotation_xref', 'EnsemblGenomes'
          FROM external_rows, unnest(string_split(ncbi_gene_ids, ';')) AS t(external_id)
          WHERE coalesce(ncbi_gene_ids, '') <> ''
            AND regexp_full_match(external_id, '^[0-9]+$')
          UNION ALL
          SELECT division, species_id, tax_id, assembly_accession, gene_id, transcript_id, protein_id,
                 '' AS uniprot_accession, 'NCBI Protein', external_id, 'refseq_protein_accession',
                 'local_feature_tables', 'local_refseq_protein', 'medium', 'direct_annotation_xref', 'EnsemblGenomes'
          FROM external_rows, unnest(string_split(refseq_protein_accessions, ';')) AS t(external_id)
          WHERE coalesce(refseq_protein_accessions, '') <> ''
            AND regexp_full_match(external_id, '^(?:[NXWAYZ]P|WP|AP|YP|XP|NP|ZP)_[0-9]{5,}(?:\\.[0-9]+)?$')
          UNION ALL
          SELECT division, species_id, tax_id, assembly_accession, gene_id, transcript_id, protein_id,
                 '' AS uniprot_accession, 'NCBI Protein', external_id, 'insdc_protein_accession',
                 'local_feature_tables', 'local_insdc_protein', 'medium', 'direct_annotation_xref', 'EnsemblGenomes'
          FROM external_rows, unnest(string_split(insdc_protein_accessions, ';')) AS t(external_id)
          WHERE coalesce(insdc_protein_accessions, '') <> ''
            AND regexp_full_match(external_id, '^(?:[A-Z]{3}[0-9]{5}|[A-Z]{4,6}[0-9]{6,10})(?:\\.[0-9]+)?$')
          UNION ALL
          SELECT division, species_id, tax_id, assembly_accession, gene_id, transcript_id, protein_id,
                 '' AS uniprot_accession, 'NCBI Transcript', external_id, 'refseq_transcript_accession',
                 'local_feature_tables', 'local_refseq_transcript', 'medium', 'direct_annotation_xref', 'EnsemblGenomes'
          FROM external_rows, unnest(string_split(refseq_transcript_accessions, ';')) AS t(external_id)
          WHERE coalesce(refseq_transcript_accessions, '') <> ''
            AND regexp_full_match(external_id, '^(?:NM|XM|NR|XR)_[0-9]{5,}(?:\\.[0-9]+)?$')
          UNION ALL
          SELECT division, species_id, tax_id, assembly_accession, gene_id, transcript_id, protein_id,
                 '' AS uniprot_accession, 'INSDC/NCBI Sequence', external_id, 'sequence_region_accession',
                 'local_feature_tables', 'local_region', 'low', 'region_annotation', 'EnsemblGenomes'
          FROM external_rows, unnest(string_split(insdc_sequence_region_accessions, ';')) AS t(external_id)
          WHERE coalesce(insdc_sequence_region_accessions, '') <> ''
            AND regexp_full_match(external_id, '^(?:[A-Z]{1,2}[0-9]{5,8}|[A-Z]{4,6}[0-9]{6,10})(?:\\.[0-9]+)?$')
        )
        """
    )
    print("[bacteria-duckdb] writing complete long table", flush=True)
    con.execute(
        f"""
        COPY (
          SELECT * FROM long_rows
          ORDER BY species_id, internal_gene_id, internal_transcript_id, internal_protein_id, external_database, external_id
        ) TO '{sql_path(long_path)}' (HEADER, DELIMITER ',')
        """
    )
    long_rows = con.execute("SELECT count(*) FROM long_rows").fetchone()[0]
    print(f"[bacteria-duckdb] long_rows={long_rows:,}", flush=True)

    species_standard_path = OUT_ROOT / "bacteria_species_standard_ids.csv"
    con.execute(
        f"""
        COPY (
          SELECT 'bacteria' AS division, species_id, tax_id, assembly_accession,
                 'NCBI Taxonomy and INSDC/NCBI Assembly are species-level standards; row-level external IDs are expanded in bacteria_external_id_mapping_long_final_whitelist.csv.' AS standard_id_note
          FROM read_csv('{qc}', header=true, all_varchar=true)
          ORDER BY species_id
        ) TO '{sql_path(species_standard_path)}' (HEADER, DELIMITER ',')
        """
    )

    qc_path = OUT_ROOT / "bacteria_online_external_id_mapping_species_qc.csv"
    con.execute(
        """
        CREATE TABLE external_species AS
        SELECT species_id,
          count(DISTINCT row_key) FILTER (WHERE external_database IN ('UniProtKB', 'NCBI Gene', 'NCBI Protein')) AS rows_with_any_external_gene_or_protein_id,
          count(DISTINCT row_key) FILTER (WHERE external_database = 'UniProtKB') AS rows_with_local_uniprot,
          count(DISTINCT row_key) FILTER (WHERE external_database = 'NCBI Gene') AS rows_with_local_ncbi_gene,
          count(DISTINCT row_key) FILTER (WHERE external_database = 'NCBI Protein') AS rows_with_local_ncbi_protein,
          count(DISTINCT row_key) FILTER (WHERE external_id_type = 'refseq_protein_accession') AS rows_with_local_refseq_protein,
          count(DISTINCT row_key) FILTER (WHERE external_id_type = 'refseq_transcript_accession') AS rows_with_local_refseq_transcript,
          count(DISTINCT row_key) FILTER (WHERE external_id_type = 'sequence_region_accession') AS rows_with_local_insdc_region
        FROM (
          SELECT *,
            coalesce(internal_gene_id, '') || '|' || coalesce(internal_transcript_id, '') || '|' || coalesce(internal_protein_id, '') AS row_key
          FROM long_rows
        )
        GROUP BY species_id
        """
    )
    con.execute(
        f"""
        CREATE TABLE long_species AS
        SELECT species_id, count(*) AS long_external_rows
        FROM long_rows
        GROUP BY species_id
        """
    )
    con.execute(
        f"""
        COPY (
          SELECT
            'bacteria' AS division,
            q.species_id,
            q.tax_id,
            q.assembly_accession,
            cast(q.total_mapping_rows AS BIGINT) AS total_internal_rows,
            coalesce(e.rows_with_local_uniprot, 0) AS rows_with_local_uniprot,
            coalesce(e.rows_with_local_ncbi_gene, 0) AS rows_with_local_ncbi_gene,
            coalesce(e.rows_with_local_ncbi_protein, 0) AS rows_with_local_ncbi_protein,
            coalesce(e.rows_with_local_refseq_protein, 0) AS rows_with_local_refseq_protein,
            coalesce(e.rows_with_local_refseq_transcript, 0) AS rows_with_local_refseq_transcript,
            coalesce(e.rows_with_local_insdc_region, 0) AS rows_with_local_insdc_region,
            0 AS rows_with_online_ncbi_gene,
            0 AS rows_with_online_refseq_protein,
            coalesce(e.rows_with_any_external_gene_or_protein_id, 0) AS rows_with_any_external_gene_or_protein_id,
            cast(q.total_mapping_rows AS BIGINT) - coalesce(e.rows_with_any_external_gene_or_protein_id, 0) AS rows_species_standard_only,
            coalesce(l.long_external_rows, 0) AS long_external_rows,
            CASE
              WHEN coalesce(e.rows_with_any_external_gene_or_protein_id, 0) = 0 THEN 'D'
              WHEN coalesce(e.rows_with_any_external_gene_or_protein_id, 0)::DOUBLE / nullif(cast(q.total_mapping_rows AS BIGINT), 0) >= 0.25 THEN 'B'
              ELSE 'C'
            END AS external_mapping_grade
          FROM read_csv('{qc}', header=true, all_varchar=true) q
          LEFT JOIN external_species e ON q.species_id = e.species_id
          LEFT JOIN long_species l ON q.species_id = l.species_id
          ORDER BY q.species_id
        ) TO '{sql_path(qc_path)}' (HEADER, DELIMITER ',')
        """
    )

    accession_path = OUT_ROOT / "bacteria_uniprot_online_accession_map.csv"
    write_empty_accession_map(accession_path)

    samples: dict[str, dict[str, object]] = {}
    for path in [accession_path, long_path, qc_path, species_standard_path]:
        sample_path = path.with_name(path.stem + ".sample_1pct.csv")
        samples[sample_path.name] = {"path": str(sample_path), "rows": sample_csv(path, sample_path)}

    species_count = con.execute(f"SELECT count(*) FROM read_csv('{qc}', header=true, all_varchar=true)").fetchone()[0]
    summary = {
        "division": "bacteria",
        "generated_at_unix": int(time.time()),
        "source_external_wide_csv": str(WIDE_CSV),
        "build_engine": "DuckDB",
        "unique_uniprot_accessions": unique_uniprot,
        "online_accession_map_rows": 0,
        "species_standard_rows": species_count,
        "collect_counts": {
            "rows_scanned": 63_720_732,
            "rows_with_uniprot": unique_uniprot,
            "filtered_external_rows": external_rows,
        },
        "long_summary": {
            "species_count": species_count,
            "counts": {"rows_scanned": 63_720_732, "long_external_rows": long_rows},
            "status": "completed",
        },
        "outputs": {
            "online_accession_map": str(accession_path),
            "combined_long_mapping": str(long_path),
            "species_qc": str(qc_path),
            "species_standard_ids": str(species_standard_path),
            "samples": samples,
        },
        "notes": [
            "No UniProt accession rows were available for bacteria online enrichment when unique_uniprot_accessions is 0.",
            "The complete bacteria long table is expanded from all local NCBI/INSDC evidence in the final-whitelist external wide CSV.",
            "Strict accession validation is applied during long-table expansion to avoid short false-positive RefSeq-like fragments from internal ENSB IDs.",
        ],
        "runtime_seconds": round(time.time() - start, 3),
    }
    summary_path = OUT_ROOT / "bacteria_online_external_id_mapping_summary.json"
    summary["outputs"]["summary"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    for path in [accession_path, long_path, qc_path, species_standard_path, summary_path, *[Path(v["path"]) for v in samples.values()]]:
        hardlink_or_copy(path, DATA_ROOT / path.name)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
