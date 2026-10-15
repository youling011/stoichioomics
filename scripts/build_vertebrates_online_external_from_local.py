#!/usr/bin/env python3
"""Create vertebrates online-external compatible outputs from local evidence.

The vertebrates final-whitelist external wide table contains no UniProtKB
accessions, so there is no online UniProt ID Mapping job to submit.  This script
still emits the same online_external schema used by the other divisions.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINAL_ROOT = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping_final_whitelist"
ONLINE_ROOT = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping_final_whitelist_online_external"
GROUP = "vertebrates"
RG_EXE = shutil.which("rg") or shutil.which("rg.exe")

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

ACC_FIELDS = [
    "division",
    "uniprot_accession",
    "target_database",
    "external_id",
    "external_id_type",
    "mapping_method",
    "mapping_source",
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


def clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def external_wide_path() -> Path:
    return FINAL_ROOT / GROUP / "vertebrates_external_id_mapping_final_whitelist.csv"


def local_mapping_lines() -> list[str]:
    path = external_wide_path()
    if not path.exists():
        raise FileNotFoundError(path)
    if RG_EXE:
        result = subprocess.run(
            [RG_EXE, "--no-heading", "--color", "never", ",mapped_external_gene_or_protein,", str(path)],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode not in {0, 1}:
            raise RuntimeError(result.stderr[:500])
        return result.stdout.splitlines() if result.stdout else []
    lines: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        header = fh.readline()
        for line in fh:
            if ",mapped_external_gene_or_protein," in line:
                lines.append(line.rstrip("\r\n"))
    return lines


def write_sample(src: Path, dst: Path, pct: float = 0.01) -> int:
    keep_every = max(1, round(1 / pct))
    written = 0
    with src.open("r", encoding="utf-8-sig", newline="") as in_fh, dst.open("w", encoding="utf-8", newline="") as out_fh:
        reader = csv.reader(in_fh)
        writer = csv.writer(out_fh)
        header = next(reader, None)
        if header:
            writer.writerow(header)
        for idx, row in enumerate(reader, start=1):
            if idx % keep_every == 0:
                writer.writerow(row)
                written += 1
    return written


def grade(counts: Counter[str]) -> str:
    if counts["rows_with_any_external_gene_or_protein_id"]:
        return "B"
    return "D"


def build() -> dict[str, Any]:
    start = time.time()
    out_dir = ONLINE_ROOT / GROUP
    out_dir.mkdir(parents=True, exist_ok=True)

    qc_rows = read_csv(FINAL_ROOT / GROUP / "vertebrates_id_mapping_species_qc.csv")
    whitelist_rows = read_csv(FINAL_ROOT / GROUP / "vertebrates_species_whitelist_final_merged.csv")

    accession_map_path = out_dir / "vertebrates_uniprot_online_accession_map.csv"
    write_csv(accession_map_path, [], ACC_FIELDS)

    standard_rows = [
        {
            "division": GROUP,
            "species_id": clean(row.get("species")),
            "tax_id": clean(row.get("taxon_id")),
            "assembly_accession": clean(row.get("assembly_accession")),
            "standard_id_note": "NCBI Taxonomy and INSDC/NCBI Assembly are species-level standards; gene/protein xrefs are row-level assertions.",
        }
        for row in whitelist_rows
        if clean(row.get("species"))
    ]
    standard_path = out_dir / "vertebrates_species_standard_ids.csv"
    write_csv(standard_path, standard_rows, STANDARD_FIELDS)

    with external_wide_path().open("r", encoding="utf-8-sig", newline="") as fh:
        wide_header = next(csv.reader([fh.readline().rstrip("\r\n")]))
    local_lines = local_mapping_lines()
    long_rows: list[dict[str, str]] = []
    species_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for line in local_lines:
        values = next(csv.reader([line]))
        row = dict(zip(wide_header, values))
        species_id = clean(row.get("species_id"))
        base = {
            "division": GROUP,
            "species_id": species_id,
            "tax_id": clean(row.get("tax_id")),
            "assembly_accession": clean(row.get("assembly_accession")),
            "internal_gene_id": clean(row.get("gene_id")),
            "internal_transcript_id": clean(row.get("transcript_id")),
            "internal_protein_id": clean(row.get("protein_id")),
            "uniprot_accession": "",
            "mapping_source": "local_feature_tables",
            "mapping_confidence": clean(row.get("external_mapping_confidence")) or "medium",
            "evidence_level": "direct_annotation_xref",
            "source_release": "Ensembl",
        }
        for external_id in [item for item in clean(row.get("refseq_transcript_accessions")).split(";") if item]:
            long_rows.append(
                {
                    **base,
                    "external_database": "NCBI RefSeq Transcript",
                    "external_id": external_id,
                    "external_id_type": "refseq_transcript_accession",
                    "mapping_method": "local_refseq_transcript",
                }
            )
            species_counts[species_id]["rows_with_local_refseq_transcript"] += 1
            species_counts[species_id]["rows_with_any_external_gene_or_protein_id"] += 1
            species_counts[species_id]["long_external_rows"] += 1

    qc_out_rows: list[dict[str, Any]] = []
    total = Counter()
    for row in qc_rows:
        species_id = clean(row.get("species_id"))
        counts = species_counts[species_id]
        counts["total_internal_rows"] = int(float(clean(row.get("total_mapping_rows")) or 0))
        counts["rows_species_standard_only"] = max(
            0,
            counts["total_internal_rows"] - counts["rows_with_any_external_gene_or_protein_id"],
        )
        out = {
            "division": GROUP,
            "species_id": species_id,
            "tax_id": clean(row.get("tax_id")),
            "assembly_accession": clean(row.get("assembly_accession")),
            "external_mapping_grade": grade(counts),
        }
        for field in QC_FIELDS:
            if field not in out:
                out[field] = counts[field]
        qc_out_rows.append(out)
        total.update(counts)

    long_path = out_dir / "vertebrates_external_id_mapping_long_final_whitelist.csv"
    qc_path = out_dir / "vertebrates_online_external_id_mapping_species_qc.csv"
    write_csv(long_path, long_rows, LONG_FIELDS)
    write_csv(qc_path, qc_out_rows, QC_FIELDS)

    sample_outputs = {}
    for src, name in [
        (accession_map_path, "vertebrates_uniprot_online_accession_map.sample_1pct.csv"),
        (long_path, "vertebrates_external_id_mapping_long_final_whitelist.sample_1pct.csv"),
        (qc_path, "vertebrates_online_external_id_mapping_species_qc.sample_1pct.csv"),
        (standard_path, "vertebrates_species_standard_ids.sample_1pct.csv"),
    ]:
        sample_path = out_dir / name
        sample_outputs[name] = {"path": str(sample_path), "rows": write_sample(src, sample_path)}

    summary = {
        "division": GROUP,
        "generated_at_unix": int(time.time()),
        "source_external_wide_csv": str(external_wide_path()),
        "unique_uniprot_accessions": 0,
        "online_accessions_requested": 0,
        "online_accession_map_rows": 0,
        "species_standard_rows": len(standard_rows),
        "collect_counts": {
            "rows_scanned": sum(int(float(clean(row.get("total_mapping_rows")) or 0)) for row in qc_rows),
            "rows_with_uniprot": 0,
        },
        "long_summary": {"species_count": len(qc_out_rows), "counts": dict(total)},
        "outputs": {
            "online_accession_map": str(accession_map_path),
            "combined_long_mapping": str(long_path),
            "species_qc": str(qc_path),
            "species_standard_ids": str(standard_path),
            "samples": sample_outputs,
        },
        "runtime_seconds": round(time.time() - start, 3),
        "notes": [
            "No UniProtKB accessions were present in the vertebrates local external wide table, so no UniProt online job was submitted.",
            "The long table contains local RefSeq transcript assertions detected in the feature-derived wide table.",
        ],
    }
    summary_path = out_dir / "vertebrates_online_external_id_mapping_summary.json"
    summary["outputs"]["summary"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def update_manifest(summary: dict[str, Any]) -> None:
    manifest_path = ONLINE_ROOT / "final_whitelist_online_external_id_mapping_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "schema_version": "final_whitelist_online_external_id_mapping.v1",
            "generated_at_unix": int(time.time()),
            "source": {"online_api": "UniProt REST ID Mapping API"},
            "groups": [],
            "long_fields": LONG_FIELDS,
            "accession_fields": ACC_FIELDS,
            "qc_fields": QC_FIELDS,
            "notes": [],
        }
    groups = [item for item in manifest.get("groups", []) if item.get("division") != GROUP]
    groups.append(summary)
    manifest["groups"] = groups
    manifest["updated_at_unix"] = int(time.time())
    manifest["long_fields"] = LONG_FIELDS
    manifest["accession_fields"] = ACC_FIELDS
    manifest["qc_fields"] = QC_FIELDS
    notes = set(manifest.get("notes") or [])
    notes.add("Vertebrates/chordates online_external layer has no UniProt online submissions because the local wide table contains no UniProtKB accessions.")
    manifest["notes"] = sorted(notes)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ONLINE_ROOT.mkdir(parents=True, exist_ok=True)
    summary = build()
    update_manifest(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
