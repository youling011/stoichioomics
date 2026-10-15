#!/usr/bin/env python3
"""Supplement local protist ID mappings with UniProt online cross-references."""

from __future__ import annotations

import csv
import json
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ID_MAPPING_DIR = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping"
LOCAL_WIDE = ID_MAPPING_DIR / "protist_external_id_mapping_all_species.csv"
ONLINE_LONG_OUT = ID_MAPPING_DIR / "protist_uniprot_to_ncbi_online_mapping_long.csv"
ONLINE_ACC_OUT = ID_MAPPING_DIR / "protist_uniprot_to_ncbi_online_accession_map.csv"
ONLINE_SUMMARY_OUT = ID_MAPPING_DIR / "protist_uniprot_to_ncbi_online_summary.json"

UNIPROT_RUN_URL = "https://rest.uniprot.org/idmapping/run"
UNIPROT_STATUS_URL = "https://rest.uniprot.org/idmapping/status/{job_id}"

TARGETS = {
    "GeneID": {
        "external_database": "NCBI Gene",
        "external_id_type": "gene_id",
        "mapping_method": "uniprot_idmapping_uniprotkb_to_geneid",
    },
    "RefSeq_Protein": {
        "external_database": "NCBI Protein",
        "external_id_type": "refseq_protein_accession",
        "mapping_method": "uniprot_idmapping_uniprotkb_to_refseq_protein",
    },
}

LONG_FIELDS = [
    "species_id",
    "tax_id",
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
    "uniprot_accession",
    "target_database",
    "external_id",
    "external_id_type",
    "mapping_method",
]


def clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def read_uniprot_rows() -> dict[str, list[dict[str, str]]]:
    acc_to_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    with LOCAL_WIDE.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            accessions = [item for item in clean(row.get("uniprot_accessions")).split(";") if item]
            if not accessions:
                continue
            base = {
                "species_id": clean(row.get("species_id")),
                "tax_id": clean(row.get("tax_id")),
                "internal_gene_id": clean(row.get("gene_id")),
                "internal_transcript_id": clean(row.get("transcript_id")),
                "internal_protein_id": clean(row.get("protein_id")),
                "source_release": f"EnsemblGenomes:{clean(row.get('ensembl_release'))}".rstrip(":"),
            }
            for accession in accessions:
                acc_to_rows[accession].append(base)
    return acc_to_rows


def request_json(url: str, data: dict[str, str] | None = None, timeout: int = 120) -> dict:
    encoded = None
    if data is not None:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(url, data=encoded)
    request.add_header("User-Agent", "Stoichioomics-IDMapping/1.0")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def submit_mapping_job(target: str, ids: list[str]) -> str:
    payload = {
        "from": "UniProtKB_AC-ID",
        "to": target,
        "ids": ",".join(ids),
    }
    response = request_json(UNIPROT_RUN_URL, payload)
    return response["jobId"]


def wait_for_results(job_id: str, poll_seconds: float = 3.0, max_wait_seconds: int = 900) -> dict:
    deadline = time.time() + max_wait_seconds
    url = UNIPROT_STATUS_URL.format(job_id=job_id)
    while True:
        response = request_json(url)
        if "jobStatus" not in response:
            return response
        if response["jobStatus"] in {"FINISHED", "ERROR", "FAILED"}:
            return response
        if time.time() > deadline:
            raise TimeoutError(f"UniProt job {job_id} did not finish within {max_wait_seconds}s")
        time.sleep(poll_seconds)


def run_target(target: str, accessions: list[str], batch_size: int = 5000) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    for index, batch in enumerate(chunks(accessions, batch_size), start=1):
        job_id = submit_mapping_job(target, batch)
        result = wait_for_results(job_id)
        for item in result.get("results", []):
            from_id = clean(item.get("from"))
            to_id = item.get("to")
            if isinstance(to_id, dict):
                to_id = clean(to_id.get("primaryAccession") or to_id.get("id"))
            else:
                to_id = clean(to_id)
            if from_id and to_id:
                mapping[from_id].add(to_id)
        print(f"{target}: batch {index} / {len(chunks(accessions, batch_size))} done; job={job_id}")
        time.sleep(0.5)
    return mapping


def main() -> None:
    start = time.time()
    acc_to_rows = read_uniprot_rows()
    accessions = sorted(acc_to_rows)
    all_target_maps: dict[str, dict[str, set[str]]] = {}
    counts = Counter()

    for target in TARGETS:
        target_map = run_target(target, accessions)
        all_target_maps[target] = target_map
        counts[f"{target}_mapped_accessions"] = sum(1 for values in target_map.values() if values)
        counts[f"{target}_external_ids"] = sum(len(values) for values in target_map.values())

    long_rows = 0
    with ONLINE_LONG_OUT.open("w", encoding="utf-8", newline="") as long_fh, ONLINE_ACC_OUT.open(
        "w", encoding="utf-8", newline=""
    ) as acc_fh:
        long_writer = csv.DictWriter(long_fh, fieldnames=LONG_FIELDS)
        acc_writer = csv.DictWriter(acc_fh, fieldnames=ACC_FIELDS)
        long_writer.writeheader()
        acc_writer.writeheader()

        for target, target_map in all_target_maps.items():
            meta = TARGETS[target]
            for accession in sorted(target_map):
                for external_id in sorted(target_map[accession]):
                    acc_writer.writerow(
                        {
                            "uniprot_accession": accession,
                            "target_database": meta["external_database"],
                            "external_id": external_id,
                            "external_id_type": meta["external_id_type"],
                            "mapping_method": meta["mapping_method"],
                        }
                    )
                    for base in acc_to_rows.get(accession, []):
                        long_writer.writerow(
                            {
                                **base,
                                "uniprot_accession": accession,
                                "external_database": meta["external_database"],
                                "external_id": external_id,
                                "external_id_type": meta["external_id_type"],
                                "mapping_source": "UniProt REST ID Mapping API",
                                "mapping_method": meta["mapping_method"],
                                "mapping_confidence": "high",
                                "evidence_level": "official_uniprot_cross_reference",
                            }
                        )
                        long_rows += 1

    counts["input_unique_uniprot_accessions"] = len(accessions)
    counts["input_internal_rows_with_uniprot"] = sum(len(rows) for rows in acc_to_rows.values())
    counts["long_rows"] = long_rows
    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_local_wide_mapping": str(LOCAL_WIDE),
        "counts": dict(counts),
        "outputs": {
            "online_long_mapping": str(ONLINE_LONG_OUT),
            "online_accession_map": str(ONLINE_ACC_OUT),
            "summary": str(ONLINE_SUMMARY_OUT),
        },
        "runtime_seconds": round(time.time() - start, 3),
    }
    ONLINE_SUMMARY_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
