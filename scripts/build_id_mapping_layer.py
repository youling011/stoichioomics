#!/usr/bin/env python3
"""Build a fast ID mapping lookup layer for Stoichioomics.

This implementation intentionally avoids expanding every possible alias from
the full CSV into a huge duplicate-heavy table. It builds:

1. id_mapping_chain: one compact row per internal mapping row.
2. id_alias_index: exact lookup aliases for internal IDs and external standard IDs.
3. id_mapping_summary/release JSON: manifest and QC generated from existing full outputs.
"""

from __future__ import annotations
import sys as _corefull_sys
from pathlib import Path as _CoreFullPath
_corefull_sys.path.insert(0, str(_CoreFullPath(__file__).resolve().parents[1]))
from backend.apps.stoichdb.feature_sources import io as feature_io

import csv
import hashlib
import json
import sqlite3
import time
from collections import Counter
from backend.apps.common.host_paths import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "id_mapping"
ARTIFACT_DIR = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping"

OMICS_CSV = DATA_DIR / "protist_omics_id_mapping_all_species.csv"
EXTERNAL_CSV = DATA_DIR / "protist_external_id_mapping_all_species.csv"
OMICS_INDEX_CSV = DATA_DIR / "protist_omics_id_mapping_all_species.sample_1pct.csv"
EXTERNAL_INDEX_CSV = DATA_DIR / "protist_external_id_mapping_all_species.sample_1pct.csv"
OMICS_QC_CSV = ARTIFACT_DIR / "protist_omics_id_mapping_species_qc.csv"
EXTERNAL_QC_CSV = ARTIFACT_DIR / "protist_external_id_mapping_species_qc.csv"
OMICS_SUMMARY_JSON = ARTIFACT_DIR / "protist_omics_id_mapping_summary.json"
EXTERNAL_SUMMARY_JSON = ARTIFACT_DIR / "protist_external_id_mapping_summary.json"

SQLITE_PATH = DATA_DIR / "id_mapping.sqlite"
MANIFEST_PATH = DATA_DIR / "id_mapping_manifest.json"
SCHEMA_PATH = DATA_DIR / "id_mapping_schema.json"
QC_PATH = DATA_DIR / "id_mapping_qc_summary.json"
PER_SPECIES_DIR = DATA_DIR / "per_species"
PER_SPECIES_SUMMARY_PATH = DATA_DIR / "per_species_mapping_summary.json"
CASE2_PAYLOAD_PATH = DATA_DIR / "case2_id_mapping_advanced_payload.json"

CHAIN_COLUMNS = [
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

ALIAS_COLUMNS = [
    "species_id",
    "alias_value",
    "normalized_alias",
    "alias_type",
    "target_type",
    "target_id",
    "gene_id",
    "transcript_id",
    "protein_id",
    "mapping_status",
    "mapping_confidence",
    "external_mapping_status",
    "external_mapping_confidence",
    "source_table",
]


def clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def norm(value: str) -> str:
    return clean(value).casefold()


def split_multi(value: object) -> list[str]:
    text = clean(value)
    if not text:
        return []
    values = []
    for part in text.replace("|", ";").replace(",", ";").split(";"):
        item = part.strip()
        if item:
            values.append(item)
    return values


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with feature_io.open_source(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def mapping_uid(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(clean(part) for part in parts).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict:
    if not feature_io.source_exists(path):
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def validate_header(path: Path, required: list[str]) -> None:
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as fh:
        header = next(csv.reader(fh))
    missing = [item for item in required if item not in header]
    if missing:
        raise SystemExit(f"{path} missing columns: {', '.join(missing)}")


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;
        PRAGMA cache_size = -200000;

        DROP TABLE IF EXISTS id_mapping_chain;
        DROP TABLE IF EXISTS id_alias_index;
        DROP TABLE IF EXISTS id_mapping_summary;
        DROP TABLE IF EXISTS id_mapping_release;

        CREATE TABLE id_mapping_chain (
            mapping_uid TEXT PRIMARY KEY,
            species_id TEXT,
            tax_id TEXT,
            tax_name TEXT,
            assembly_accession TEXT,
            ensembl_release TEXT,
            gene_id TEXT,
            transcript_id TEXT,
            protein_id TEXT,
            mapping_level TEXT,
            internal_mapping_status TEXT,
            internal_mapping_confidence TEXT,
            uniprot_accessions TEXT,
            uniprot_source TEXT,
            ncbi_gene_ids TEXT,
            refseq_protein_accessions TEXT,
            insdc_protein_accessions TEXT,
            ncbi_protein_accessions TEXT,
            refseq_transcript_accessions TEXT,
            insdc_sequence_region_accessions TEXT,
            source_protein_id TEXT,
            external_mapping_status TEXT,
            external_mapping_confidence TEXT,
            external_mapping_evidence TEXT
        );

        CREATE TABLE id_alias_index (
            alias_uid TEXT PRIMARY KEY,
            species_id TEXT,
            alias_value TEXT,
            normalized_alias TEXT,
            alias_type TEXT,
            target_type TEXT,
            target_id TEXT,
            gene_id TEXT,
            transcript_id TEXT,
            protein_id TEXT,
            mapping_status TEXT,
            mapping_confidence TEXT,
            external_mapping_status TEXT,
            external_mapping_confidence TEXT,
            source_table TEXT
        );

        CREATE TABLE id_mapping_summary (
            species_id TEXT PRIMARY KEY,
            total_rows INTEGER,
            complete_chain_rate REAL,
            gene_transcript_only_rate REAL,
            conflict_rate REAL,
            high_confidence_rate REAL,
            external_high_confidence_rate REAL,
            uniprot_coverage REAL,
            ncbi_or_insdc_coverage REAL,
            gene_in_genome_rate REAL,
            transcript_in_transcriptome_rate REAL,
            protein_in_proteome_rate REAL,
            ambiguous_alias_count INTEGER,
            grade TEXT,
            status_counts_json TEXT,
            confidence_counts_json TEXT,
            level_counts_json TEXT,
            external_status_counts_json TEXT
        );

        CREATE TABLE id_mapping_release (
            release_id TEXT PRIMARY KEY,
            schema_version TEXT,
            generated_at TEXT,
            omics_csv_sha256 TEXT,
            external_csv_sha256 TEXT,
            chain_rows INTEGER,
            alias_rows INTEGER,
            species_count INTEGER,
            status TEXT
        );
        """
    )


def add_alias(batch: list[tuple[str, ...]], row: dict[str, str], alias_value: str, alias_type: str, target_type: str, target_id: str, source_table: str) -> None:
    alias = clean(alias_value)
    if not alias:
        return
    uid = mapping_uid(row["species_id"], alias, alias_type, row.get("gene_id", ""), row.get("transcript_id", ""), row.get("protein_id", ""), source_table)
    batch.append(
        (
            uid,
            row["species_id"],
            alias,
            norm(alias),
            alias_type,
            target_type,
            clean(target_id),
            row.get("gene_id", ""),
            row.get("transcript_id", ""),
            row.get("protein_id", ""),
            row.get("internal_mapping_status", ""),
            row.get("internal_mapping_confidence", ""),
            row.get("external_mapping_status", ""),
            row.get("external_mapping_confidence", ""),
            source_table,
        )
    )


def insert_chain_and_external_aliases(conn: sqlite3.Connection) -> tuple[int, int, Counter]:
    chain_sql = "INSERT INTO id_mapping_chain VALUES (" + ",".join("?" for _ in range(len(CHAIN_COLUMNS) + 1)) + ")"
    alias_sql = "INSERT OR IGNORE INTO id_alias_index VALUES (" + ",".join("?" for _ in range(len(ALIAS_COLUMNS) + 1)) + ")"
    chain_batch: list[tuple[str, ...]] = []
    alias_batch: list[tuple[str, ...]] = []
    rows = 0
    alias_candidates = 0
    external_status_counts = Counter()

    with EXTERNAL_INDEX_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            row = {column: clean(raw.get(column)) for column in CHAIN_COLUMNS}
            uid = mapping_uid(row["species_id"], row["gene_id"], row["transcript_id"], row["protein_id"], "chain")
            chain_batch.append((uid, *[row[column] for column in CHAIN_COLUMNS]))
            rows += 1
            external_status_counts[row["external_mapping_status"] or "missing"] += 1

            for alias in split_multi(row["uniprot_accessions"]):
                add_alias(alias_batch, row, alias, "uniprot", "protein", row["protein_id"] or row["gene_id"], "external_id_mapping")
            for column, alias_type, target_type in [
                ("ncbi_gene_ids", "ncbi_gene", "gene"),
                ("refseq_protein_accessions", "refseq_protein", "protein"),
                ("insdc_protein_accessions", "insdc_protein", "protein"),
                ("ncbi_protein_accessions", "ncbi_protein", "protein"),
                ("refseq_transcript_accessions", "refseq_transcript", "transcript"),
                ("insdc_sequence_region_accessions", "insdc_region", "protein"),
                ("source_protein_id", "source_protein_id", "protein"),
                ("tax_id", "tax_id", "species"),
                ("assembly_accession", "assembly_accession", "species"),
            ]:
                target = row["protein_id"] if target_type == "protein" else row["transcript_id"] if target_type == "transcript" else row["gene_id"] if target_type == "gene" else row["species_id"]
                for alias in split_multi(row[column]):
                    add_alias(alias_batch, row, alias, alias_type, target_type, target, "external_id_mapping")

            if len(chain_batch) >= 50000:
                conn.executemany(chain_sql, chain_batch)
                conn.executemany(alias_sql, alias_batch)
                conn.commit()
                alias_candidates += len(alias_batch)
                chain_batch.clear()
                alias_batch.clear()

    if chain_batch:
        conn.executemany(chain_sql, chain_batch)
        conn.executemany(alias_sql, alias_batch)
        conn.commit()
        alias_candidates += len(alias_batch)
    return rows, alias_candidates, external_status_counts


def insert_internal_aliases(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        INSERT OR IGNORE INTO id_alias_index
        SELECT
            lower(hex(randomblob(16))) AS alias_uid,
            species_id,
            gene_id AS alias_value,
            lower(gene_id) AS normalized_alias,
            'gene_id' AS alias_type,
            'gene' AS target_type,
            gene_id AS target_id,
            gene_id,
            transcript_id,
            protein_id,
            internal_mapping_status,
            internal_mapping_confidence,
            external_mapping_status,
            external_mapping_confidence,
            'id_mapping_chain' AS source_table
        FROM id_mapping_chain
        WHERE gene_id != '';

        INSERT OR IGNORE INTO id_alias_index
        SELECT
            lower(hex(randomblob(16))) AS alias_uid,
            species_id,
            transcript_id AS alias_value,
            lower(transcript_id) AS normalized_alias,
            'transcript_id' AS alias_type,
            'transcript' AS target_type,
            transcript_id AS target_id,
            gene_id,
            transcript_id,
            protein_id,
            internal_mapping_status,
            internal_mapping_confidence,
            external_mapping_status,
            external_mapping_confidence,
            'id_mapping_chain' AS source_table
        FROM id_mapping_chain
        WHERE transcript_id != '';

        INSERT OR IGNORE INTO id_alias_index
        SELECT
            lower(hex(randomblob(16))) AS alias_uid,
            species_id,
            protein_id AS alias_value,
            lower(protein_id) AS normalized_alias,
            'protein_id' AS alias_type,
            'protein' AS target_type,
            protein_id AS target_id,
            gene_id,
            transcript_id,
            protein_id,
            internal_mapping_status,
            internal_mapping_confidence,
            external_mapping_status,
            external_mapping_confidence,
            'id_mapping_chain' AS source_table
        FROM id_mapping_chain
        WHERE protein_id != '';
        """
    )
    conn.commit()


def load_csv_by_species(path: Path) -> dict[str, dict[str, str]]:
    if not feature_io.source_exists(path):
        return {}
    rows = {}
    with feature_io.open_source(path, "r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            species_id = clean(row.get("species_id"))
            if species_id:
                rows[species_id] = {key: clean(value) for key, value in row.items()}
    return rows


def fnum(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_summaries(conn: sqlite3.Connection) -> tuple[list[dict], dict]:
    omics_qc = load_csv_by_species(OMICS_QC_CSV)
    external_qc = load_csv_by_species(EXTERNAL_QC_CSV)
    per_species = []
    grade_counts = Counter()
    insert_rows = []

    for species_id in sorted(set(omics_qc) | set(external_qc)):
        om = omics_qc.get(species_id, {})
        ex = external_qc.get(species_id, {})
        total = int(fnum(om.get("total_mapping_rows") or ex.get("total_internal_rows")))
        conflict = int(fnum(om.get("conflict_count")))
        high = int(fnum(om.get("high_confidence") or 0))
        complete = int(fnum(om.get("protein_mapping_rows") or 0))
        gene_tx = int(fnum(om.get("transcript_only_rows") or 0))
        external_high = int(fnum(ex.get("rows_with_any_external_gene_or_protein_id") or 0))
        uniprot = int(fnum(ex.get("rows_with_uniprot") or 0))
        ncbi_or_insdc = int(fnum(ex.get("rows_with_ncbi_protein") or 0)) + int(fnum(ex.get("rows_with_sequence_region") or 0))

        if total:
            complete_rate = complete / total
            high_rate = high / total
            conflict_rate = conflict / total
            external_high_rate = external_high / total
        else:
            complete_rate = high_rate = conflict_rate = external_high_rate = 0.0

        grade = "A" if complete_rate >= 0.85 and high_rate >= 0.80 and conflict_rate <= 0.02 and external_high_rate >= 0.50 else "B" if complete_rate >= 0.65 and high_rate >= 0.60 and conflict_rate <= 0.08 else "C" if total else "D"
        grade_counts[grade] += 1
        item = {
            "species_id": species_id,
            "tax_id": ex.get("tax_id", ""),
            "tax_name": ex.get("tax_name", ""),
            "assembly_accession": ex.get("assembly_accession", ""),
            "total_rows": total,
            "complete_chain_rate": round(complete_rate, 6),
            "gene_transcript_only_rate": round(gene_tx / total, 6) if total else 0.0,
            "conflict_rate": round(conflict_rate, 6),
            "high_confidence_rate": round(high_rate, 6),
            "external_high_confidence_rate": round(external_high_rate, 6),
            "uniprot_coverage": round(uniprot / total, 6) if total else 0.0,
            "ncbi_or_insdc_coverage": round(min(ncbi_or_insdc, total) / total, 6) if total else 0.0,
            "gene_in_genome_rate": round(fnum(om.get("protein_gene_in_genome_pct")) / 100.0, 6),
            "transcript_in_transcriptome_rate": round(fnum(om.get("protein_transcript_in_transcriptome_pct")) / 100.0, 6),
            "protein_in_proteome_rate": 1.0 if complete else 0.0,
            "ambiguous_alias_count": 0,
            "grade": grade,
            "status_counts": {
                "ok": max(total - conflict, 0),
                "conflict": conflict,
            },
            "confidence_counts": {
                "high": high,
                "medium": int(fnum(om.get("medium_confidence") or 0)),
                "low": int(fnum(om.get("low_confidence") or 0)),
            },
            "level_counts": {
                "gene_transcript_protein": complete,
                "gene_transcript": gene_tx,
                "gene_only": int(fnum(om.get("gene_only_rows") or 0)),
            },
            "external_status_counts": {
                "mapped_rows": external_high,
                "species_standard_only": int(fnum(ex.get("rows_species_standard_only") or 0)),
                "unmapped_external_gene_or_protein": int(fnum(ex.get("rows_unmapped_external_gene_or_protein_id") or 0)),
            },
        }
        per_species.append(item)
        insert_rows.append(
            (
                species_id,
                total,
                item["complete_chain_rate"],
                item["gene_transcript_only_rate"],
                item["conflict_rate"],
                item["high_confidence_rate"],
                item["external_high_confidence_rate"],
                item["uniprot_coverage"],
                item["ncbi_or_insdc_coverage"],
                item["gene_in_genome_rate"],
                item["transcript_in_transcriptome_rate"],
                item["protein_in_proteome_rate"],
                item["ambiguous_alias_count"],
                grade,
                json.dumps(item["status_counts"], ensure_ascii=False, sort_keys=True),
                json.dumps(item["confidence_counts"], ensure_ascii=False, sort_keys=True),
                json.dumps(item["level_counts"], ensure_ascii=False, sort_keys=True),
                json.dumps(item["external_status_counts"], ensure_ascii=False, sort_keys=True),
            )
        )

    conn.executemany("INSERT INTO id_mapping_summary VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", insert_rows)
    conn.commit()
    qc = {
        "schema_version": "id_mapping_layer.v2.fast",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "global": {
            "species_count": len(per_species),
            "grade_counts": dict(sorted(grade_counts.items())),
            "omics_source_summary": read_json(OMICS_SUMMARY_JSON),
            "external_source_summary": read_json(EXTERNAL_SUMMARY_JSON),
        },
        "per_species": per_species,
        "note": "Summary metrics are generated from previously validated full-species QC CSV files to avoid repeating heavy scans.",
    }
    return per_species, qc


def create_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX idx_chain_species_gene ON id_mapping_chain(species_id, gene_id);
        CREATE INDEX idx_chain_species_transcript ON id_mapping_chain(species_id, transcript_id);
        CREATE INDEX idx_chain_species_protein ON id_mapping_chain(species_id, protein_id);
        CREATE INDEX idx_chain_status_conf ON id_mapping_chain(species_id, internal_mapping_status, internal_mapping_confidence);
        CREATE INDEX idx_chain_external_status ON id_mapping_chain(species_id, external_mapping_status, external_mapping_confidence);
        CREATE INDEX idx_alias_norm ON id_alias_index(normalized_alias);
        CREATE INDEX idx_alias_species_norm ON id_alias_index(species_id, normalized_alias);
        CREATE INDEX idx_alias_type_norm ON id_alias_index(alias_type, normalized_alias);
        CREATE INDEX idx_summary_species ON id_mapping_summary(species_id);
        """
    )
    conn.commit()


def write_per_species_samples(conn: sqlite3.Connection, species_ids: list[str]) -> None:
    PER_SPECIES_DIR.mkdir(parents=True, exist_ok=True)
    for species_id in species_ids[:12]:
        out = PER_SPECIES_DIR / f"{species_id}.id_mapping_preview.csv"
        rows = conn.execute(
            "SELECT * FROM id_mapping_chain WHERE species_id = ? ORDER BY internal_mapping_confidence DESC, gene_id LIMIT 500",
            (species_id,),
        ).fetchall()
        headers = [desc[0] for desc in conn.execute("SELECT * FROM id_mapping_chain LIMIT 1").description]
        with out.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            writer.writerows(rows)


def select_case2_payload(conn: sqlite3.Connection, per_species: list[dict]) -> dict:
    ranked = []
    for row in per_species:
        score = (
            0.30 * fnum(row.get("complete_chain_rate"))
            + 0.20 * fnum(row.get("high_confidence_rate"))
            + 0.15 * (1.0 - fnum(row.get("conflict_rate")))
            + 0.15 * fnum(row.get("protein_in_proteome_rate"))
            + 0.10 * fnum(row.get("external_high_confidence_rate"))
            + 0.10
        )
        ranked.append({**row, "case2_score": round(score, 6)})
    ranked.sort(key=lambda item: (item["case2_score"], item["total_rows"], item["species_id"]), reverse=True)
    selected = ranked[0] if ranked else {}
    chain_rows = []
    conflict_rows = []
    if selected:
        for raw in conn.execute(
            """
            SELECT species_id,gene_id,transcript_id,protein_id,mapping_level,internal_mapping_status,
                   internal_mapping_confidence,uniprot_accessions,ncbi_gene_ids,ncbi_protein_accessions,
                   insdc_protein_accessions,insdc_sequence_region_accessions,external_mapping_status,
                   external_mapping_confidence,external_mapping_evidence
            FROM id_mapping_chain
            WHERE species_id = ?
            ORDER BY
              CASE internal_mapping_status WHEN 'ok' THEN 0 ELSE 1 END,
              CASE internal_mapping_confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
              CASE mapping_level WHEN 'gene_transcript_protein' THEN 0 ELSE 1 END,
              gene_id, transcript_id, protein_id
            LIMIT 250
            """,
            (selected["species_id"],),
        ):
            chain_rows.append(
                {
                    "species_id": raw[0],
                    "gene_id": raw[1],
                    "transcript_id": raw[2],
                    "protein_id": raw[3],
                    "mapping_level": raw[4],
                    "mapping_status": raw[5],
                    "mapping_confidence": raw[6],
                    "feature_presence": {
                        "genome": True,
                        "transcriptome": bool(raw[2]),
                        "proteome": bool(raw[3]),
                    },
                    "external_ids": {
                        "uniprot": split_multi(raw[7]),
                        "ncbi_gene": split_multi(raw[8]),
                        "ncbi_protein": split_multi(raw[9]),
                        "insdc_protein": split_multi(raw[10]),
                        "insdc_region": split_multi(raw[11]),
                    },
                    "external_mapping_status": raw[12],
                    "external_mapping_confidence": raw[13],
                    "external_mapping_evidence": raw[14],
                    "selection_reason": "canonical_high_confidence" if raw[5] == "ok" and raw[6] == "high" else "retained_noncanonical_or_lower_confidence",
                }
            )
        for raw in conn.execute(
            "SELECT gene_id, transcript_id, protein_id, internal_mapping_status, internal_mapping_confidence, external_mapping_evidence FROM id_mapping_chain WHERE species_id=? AND internal_mapping_status='conflict' LIMIT 100",
            (selected["species_id"],),
        ):
            conflict_rows.append(
                {
                    "gene_id": raw[0],
                    "transcript_id": raw[1],
                    "protein_id": raw[2],
                    "mapping_status": raw[3],
                    "mapping_confidence": raw[4],
                    "conflict_reason": raw[5] or "conflict row retained from internal mapping QC",
                }
            )
    payload = {
        "selected_species": selected,
        "candidate_species": ranked[:20],
        "mapping_summary": selected,
        "chain_table": chain_rows,
        "conflict_table": conflict_rows,
        "external_id_coverage": {
            "uniprot_coverage": selected.get("uniprot_coverage", 0),
            "ncbi_or_insdc_coverage": selected.get("ncbi_or_insdc_coverage", 0),
            "external_high_confidence_rate": selected.get("external_high_confidence_rate", 0),
        },
        "figures": {
            "mapping_sankey": {"available": True, "source": "chain_table"},
            "mapping_confidence_bar": {"available": True, "source": "mapping_summary"},
            "cross_omics_scatter_high_confidence": {"available": False, "reason": "Stored cross_omics points do not carry stable transcript/protein row IDs for full join in this release."},
        },
        "limitations": [
            "The chain table is based on Ensembl-derived feature IDs and local external ID evidence.",
            "Cross-points are linked at gene-level where possible; this release does not store a complete canonical cross_omics row-ID index.",
            "Conflict and low-confidence rows are retained for diagnostics but excluded from high-confidence interpretation by default.",
        ],
    }
    CASE2_PAYLOAD_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def build() -> dict:
    start = time.time()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    validate_header(EXTERNAL_INDEX_CSV, CHAIN_COLUMNS)
    if SQLITE_PATH.exists():
        SQLITE_PATH.unlink()

    conn = sqlite3.connect(SQLITE_PATH)
    create_schema(conn)
    chain_rows, alias_candidates, _external_status = insert_chain_and_external_aliases(conn)
    insert_internal_aliases(conn)
    per_species, qc = build_summaries(conn)
    create_indexes(conn)
    write_per_species_samples(conn, [row["species_id"] for row in per_species])
    case2_payload = select_case2_payload(conn, per_species)
    alias_rows = conn.execute("SELECT COUNT(*) FROM id_alias_index").fetchone()[0]

    generated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    manifest = {
        "schema_version": "id_mapping_layer.v2.fast",
        "generated_at": generated_at,
        "runtime_seconds": None,
        "data_dir": str(DATA_DIR),
        "sqlite_path": str(SQLITE_PATH),
        "runtime_index_scope": "sample_1pct",
        "runtime_index_note": "SQLite lookup index is built from 1% sample CSV for responsive API development; full all_species CSV files remain registered for download and offline import.",
        "source_files": {
            "omics_mapping": {
                "path": str(OMICS_CSV),
                "size_bytes": feature_io.source_metadata(OMICS_CSV).size,
                "sha256": sha256_file(OMICS_CSV),
            },
            "external_mapping": {
                "path": str(EXTERNAL_CSV),
                "size_bytes": feature_io.source_metadata(EXTERNAL_CSV).size,
                "sha256": sha256_file(EXTERNAL_CSV),
            },
            "omics_runtime_index": {
                "path": str(OMICS_INDEX_CSV),
                "size_bytes": feature_io.source_metadata(OMICS_INDEX_CSV).size,
                "sha256": sha256_file(OMICS_INDEX_CSV),
            },
            "external_runtime_index": {
                "path": str(EXTERNAL_INDEX_CSV),
                "size_bytes": feature_io.source_metadata(EXTERNAL_INDEX_CSV).size,
                "sha256": sha256_file(EXTERNAL_INDEX_CSV),
            },
        },
        "tables": {
            "id_mapping_chain": chain_rows,
            "id_alias_index": alias_rows,
            "id_mapping_summary": len(per_species),
        },
        "alias_candidates_before_dedup": alias_candidates,
        "species_count": len(per_species),
        "case2_selected_species": case2_payload.get("selected_species", {}).get("species_id", ""),
    }
    conn.execute(
        "INSERT INTO id_mapping_release VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "protist_id_mapping_20260702",
            manifest["schema_version"],
            generated_at,
            manifest["source_files"]["omics_mapping"]["sha256"],
            manifest["source_files"]["external_mapping"]["sha256"],
            chain_rows,
            alias_rows,
            len(per_species),
            "active",
        ),
    )
    conn.commit()
    conn.close()

    schema = {
        "schema_version": manifest["schema_version"],
        "tables": {
            "id_mapping_chain": ["mapping_uid", *CHAIN_COLUMNS],
            "id_alias_index": ["alias_uid", *ALIAS_COLUMNS],
            "id_mapping_summary": [
                "species_id",
                "complete_chain_rate",
                "conflict_rate",
                "high_confidence_rate",
                "external_high_confidence_rate",
                "uniprot_coverage",
                "ncbi_or_insdc_coverage",
                "ambiguous_alias_count",
            ],
        },
        "status_semantics": {
            "ok": "Internal gene-transcript-protein relation passed local consistency checks.",
            "conflict": "Row is retained but must be shown with warning and excluded from strict high-confidence use.",
        },
        "confidence_order": ["high", "medium", "low"],
    }
    qc["manifest"] = {key: value for key, value in manifest.items() if key != "source_files"}
    manifest["runtime_seconds"] = round(time.time() - start, 3)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    SCHEMA_PATH.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    QC_PATH.write_text(json.dumps(qc, ensure_ascii=False, indent=2), encoding="utf-8")
    PER_SPECIES_SUMMARY_PATH.write_text(json.dumps({"items": per_species}, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    print(json.dumps(build(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
