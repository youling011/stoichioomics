#!/usr/bin/env python3
"""Online external-ID enrichment for final-whitelist non-protist divisions.

The script supplements the existing final-whitelist external wide CSV files.
It does not rebuild the full gene-transcript-protein omics chain.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINAL_ROOT = PROJECT_ROOT / "data" / "id_mapping" / "final_whitelist"
OUT_ROOT = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping_final_whitelist_online_external"
DATA_OUT_ROOT = FINAL_ROOT / "online_external"
GROUPS = ("bacteria", "fungi", "metazoa", "plants")

UNIPROT_RUN_URL = "https://rest.uniprot.org/idmapping/run"
UNIPROT_STATUS_URL = "https://rest.uniprot.org/idmapping/status/{job_id}"
UNIPROT_STREAM_URL = "https://rest.uniprot.org/idmapping/stream/{job_id}?format=tsv"

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
    return "" if text.lower() in {"nan", "none", "null"} else text


def split_values(value: object) -> list[str]:
    text = clean(value)
    if not text:
        return []
    return [part.strip() for part in text.replace("|", ";").replace(",", ";").split(";") if part.strip()]


def external_csv(group: str) -> Path:
    return FINAL_ROOT / group / f"{group}_external_id_mapping_final_whitelist.csv"


def group_out_dir(group: str) -> Path:
    out = OUT_ROOT / group
    out.mkdir(parents=True, exist_ok=True)
    return out


def iter_wide_rows(group: str, *, fast_split: bool = False):
    path = external_csv(group)
    if not fast_split:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            yield from csv.DictReader(fh)
        return
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        header_line = fh.readline()
        header = header_line.rstrip("\r\n").split(",")
        for line in fh:
            values = line.rstrip("\r\n").split(",")
            if len(values) < len(header):
                values.extend([""] * (len(header) - len(values)))
            yield dict(zip(header, values))


def request_json(url: str, data: dict[str, str] | None, timeout: int) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8") if data else None
    request = urllib.request.Request(url, data=encoded)
    request.add_header("User-Agent", "Stoichioomics-IDMapping/1.0")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def chunks(values: list[str], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def batch_key(target: str, batch: list[str]) -> str:
    return f"{target}:{hashlib.sha1(chr(10).join(batch).encode('utf-8')).hexdigest()}"


def load_done(path: Path) -> set[str]:
    done = set()
    if not path.exists():
        return done
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("status") == "done" and item.get("result_mode") == "stream_tsv_v1":
                done.add(item.get("batch_key", ""))
    return done


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def collect_accessions(group: str, progress_interval: int, max_rows: int | None) -> tuple[list[str], dict[str, dict[str, str]], Counter]:
    accessions: set[str] = set()
    species: dict[str, dict[str, str]] = {}
    counts: Counter[str] = Counter()
    with external_csv(group).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            counts["rows_scanned"] += 1
            species_id = clean(row.get("species_id"))
            if species_id and species_id not in species:
                species[species_id] = {
                    "division": group,
                    "species_id": species_id,
                    "tax_id": clean(row.get("tax_id")),
                    "assembly_accession": clean(row.get("assembly_accession")),
                    "standard_id_note": "NCBI Taxonomy and INSDC/NCBI Assembly are species-level standards; gene/protein xrefs are row-level assertions.",
                }
            vals = split_values(row.get("uniprot_accessions"))
            if vals:
                counts["rows_with_uniprot"] += 1
                accessions.update(vals)
            if progress_interval and counts["rows_scanned"] % progress_interval == 0:
                print(f"[{group}] collect rows={counts['rows_scanned']:,} unique_uniprot={len(accessions):,}", flush=True)
            if max_rows and counts["rows_scanned"] >= max_rows:
                break
    return sorted(accessions), species, counts


def collect_accessions_fast(group: str, progress_interval: int, max_rows: int | None) -> tuple[list[str], dict[str, dict[str, str]], Counter]:
    accessions: set[str] = set()
    species: dict[str, dict[str, str]] = {}
    counts: Counter[str] = Counter()
    for row in iter_wide_rows(group, fast_split=True):
        counts["rows_scanned"] += 1
        species_id = clean(row.get("species_id"))
        if species_id and species_id not in species:
            species[species_id] = {
                "division": group,
                "species_id": species_id,
                "tax_id": clean(row.get("tax_id")),
                "assembly_accession": clean(row.get("assembly_accession")),
                "standard_id_note": "NCBI Taxonomy and INSDC/NCBI Assembly are species-level standards; gene/protein xrefs are row-level assertions.",
            }
        vals = split_values(row.get("uniprot_accessions"))
        if vals:
            counts["rows_with_uniprot"] += 1
            accessions.update(vals)
        if progress_interval and counts["rows_scanned"] % progress_interval == 0:
            print(f"[{group}] collect rows={counts['rows_scanned']:,} unique_uniprot={len(accessions):,}", flush=True)
        if max_rows and counts["rows_scanned"] >= max_rows:
            break
    return sorted(accessions), species, counts


def submit_job(target: str, ids: list[str], timeout: int) -> str:
    return request_json(
        UNIPROT_RUN_URL,
        {"from": "UniProtKB_AC-ID", "to": target, "ids": ",".join(ids)},
        timeout,
    )["jobId"]


def wait_job(job_id: str, timeout: int, max_wait: int) -> dict[str, Any]:
    url = UNIPROT_STATUS_URL.format(job_id=job_id)
    deadline = time.time() + max_wait
    while True:
        result = request_json(url, None, timeout)
        status = result.get("jobStatus")
        if not status or status in {"FINISHED", "ERROR", "FAILED"}:
            return result
        if time.time() > deadline:
            raise TimeoutError(f"UniProt job {job_id} did not finish within {max_wait}s")
        time.sleep(3)


def fetch_stream_results(job_id: str, timeout: int) -> list[tuple[str, str]]:
    url = UNIPROT_STREAM_URL.format(job_id=job_id)
    request = urllib.request.Request(url)
    request.add_header("User-Agent", "Stoichioomics-IDMapping/1.0")
    pairs: list[tuple[str, str]] = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        header_seen = False
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if not header_seen:
                header_seen = True
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                from_id = clean(parts[0])
                to_id = clean(parts[1])
                if from_id and to_id:
                    pairs.append((from_id, to_id))
    return pairs


def run_uniprot(group: str, target: str, accessions: list[str], out_dir: Path, args: argparse.Namespace) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    log_path = out_dir / f"{group}_{target.lower()}_uniprot_batches.jsonl"
    done = load_done(log_path)
    batch_total = (len(accessions) + args.batch_size - 1) // args.batch_size
    for idx, batch in enumerate(chunks(accessions, args.batch_size), start=1):
        key = batch_key(target, batch)
        if key in done:
            continue
        last_error = ""
        for attempt in range(1, args.retry_count + 2):
            try:
                job_id = submit_job(target, batch, args.timeout)
                result = wait_job(job_id, args.timeout, args.max_wait_seconds)
                if result.get("jobStatus") in {"ERROR", "FAILED"}:
                    raise RuntimeError(result)
                pairs = fetch_stream_results(job_id, args.timeout)
                result_count = 0
                for from_id, to_id in pairs:
                    if from_id and to_id:
                        mapping[from_id].add(to_id)
                        result_count += 1
                append_jsonl(
                    log_path,
                    {
                        "batch_key": key,
                        "target": target,
                        "batch_index": idx,
                        "batch_total": batch_total,
                        "input_count": len(batch),
                        "result_count": result_count,
                        "job_id": job_id,
                        "status": "done",
                        "result_mode": "stream_tsv_v1",
                        "completed_at_unix": int(time.time()),
                    },
                )
                print(f"[{group}] {target} batch={idx}/{batch_total} result_count={result_count}", flush=True)
                time.sleep(0.5)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = repr(exc)
                if attempt <= args.retry_count:
                    time.sleep(min(30, attempt * 5))
        else:
            append_jsonl(
                log_path,
                {
                    "batch_key": key,
                    "target": target,
                    "batch_index": idx,
                    "batch_total": batch_total,
                    "input_count": len(batch),
                    "result_count": 0,
                    "status": "failed",
                    "error": last_error,
                    "completed_at_unix": int(time.time()),
                },
            )
            print(f"[{group}] {target} batch={idx}/{batch_total} failed={last_error}", flush=True)
    return mapping


def write_accession_map(group: str, target_maps: dict[str, dict[str, set[str]]], path: Path) -> int:
    rows = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ACC_FIELDS)
        writer.writeheader()
        for target, mapping in target_maps.items():
            meta = TARGETS[target]
            for acc in sorted(mapping):
                for external_id in sorted(mapping[acc]):
                    writer.writerow(
                        {
                            "division": group,
                            "uniprot_accession": acc,
                            "target_database": meta["external_database"],
                            "external_id": external_id,
                            "external_id_type": meta["external_id_type"],
                            "mapping_method": meta["mapping_method"],
                            "mapping_source": "UniProt REST ID Mapping API",
                        }
                    )
                    rows += 1
    return rows


def load_accession_map(path: Path) -> dict[str, dict[str, set[str]]]:
    data: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    if not path.exists():
        return data
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            acc = clean(row.get("uniprot_accession"))
            db = clean(row.get("target_database"))
            ext = clean(row.get("external_id"))
            if acc and db and ext:
                data[acc][db].add(ext)
    return data


def local_entries(row: dict[str, str]) -> list[tuple[str, str, str, str, str, str]]:
    specs = [
        ("UniProtKB", "uniprot_accessions", "protein_accession", "local_uniprot_source_acc", "direct_annotation_xref", "high"),
        ("NCBI Gene", "ncbi_gene_ids", "gene_id", "local_geneid", "direct_annotation_xref", "high"),
        ("NCBI Protein", "refseq_protein_accessions", "refseq_protein_accession", "local_refseq_protein", "direct_annotation_xref", "medium"),
        ("NCBI Protein", "insdc_protein_accessions", "insdc_protein_accession", "local_insdc_protein", "direct_annotation_xref", "medium"),
        ("NCBI Transcript", "refseq_transcript_accessions", "refseq_transcript_accession", "local_refseq_transcript", "direct_annotation_xref", "medium"),
        ("INSDC/NCBI Sequence", "insdc_sequence_region_accessions", "sequence_region_accession", "local_region", "region_annotation", "low"),
    ]
    rows = []
    for db, field, id_type, method, evidence, conf in specs:
        for ext in split_values(row.get(field)):
            rows.append((db, ext, id_type, method, evidence, conf))
    return rows


def grade(counts: Counter) -> str:
    total = counts["total_internal_rows"]
    if not total:
        return "D"
    external = counts["rows_with_any_external_gene_or_protein_id"]
    online = counts["rows_with_online_ncbi_gene"] + counts["rows_with_online_refseq_protein"]
    if external / total >= 0.6 and online:
        return "A"
    if external / total >= 0.25:
        return "B"
    if external:
        return "C"
    return "D"


def write_long_and_qc(group: str, acc_map: dict[str, dict[str, set[str]]], long_path: Path, qc_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    species_counts: dict[str, Counter] = defaultdict(Counter)
    totals: Counter[str] = Counter()
    with long_path.open("w", encoding="utf-8", newline="") as out_fh:
        reader = iter_wide_rows(group, fast_split=args.fast_split)
        writer = csv.DictWriter(out_fh, fieldnames=LONG_FIELDS)
        writer.writeheader()
        for row in reader:
            totals["rows_scanned"] += 1
            species_id = clean(row.get("species_id"))
            counts = species_counts[species_id]
            counts["total_internal_rows"] += 1
            for src_field, count_field in [
                ("uniprot_accessions", "rows_with_local_uniprot"),
                ("ncbi_gene_ids", "rows_with_local_ncbi_gene"),
                ("ncbi_protein_accessions", "rows_with_local_ncbi_protein"),
                ("refseq_protein_accessions", "rows_with_local_refseq_protein"),
                ("refseq_transcript_accessions", "rows_with_local_refseq_transcript"),
                ("insdc_sequence_region_accessions", "rows_with_local_insdc_region"),
            ]:
                if row.get(src_field):
                    counts[count_field] += 1
            base = {
                "division": group,
                "species_id": species_id,
                "tax_id": clean(row.get("tax_id")),
                "assembly_accession": clean(row.get("assembly_accession")),
                "internal_gene_id": clean(row.get("gene_id")),
                "internal_transcript_id": clean(row.get("transcript_id")),
                "internal_protein_id": clean(row.get("protein_id")),
                "source_release": "EnsemblGenomes",
            }
            has_external = bool(row.get("uniprot_accessions") or row.get("ncbi_gene_ids") or row.get("ncbi_protein_accessions"))
            for db, ext, id_type, method, evidence, conf in local_entries(row):
                writer.writerow(
                    {
                        **base,
                        "uniprot_accession": ext if db == "UniProtKB" else "",
                        "external_database": db,
                        "external_id": ext,
                        "external_id_type": id_type,
                        "mapping_source": "local_feature_tables",
                        "mapping_method": method,
                        "mapping_confidence": conf,
                        "evidence_level": evidence,
                    }
                )
                counts["long_external_rows"] += 1
                totals["long_external_rows"] += 1
            for acc in split_values(row.get("uniprot_accessions")):
                for db, values in acc_map.get(acc, {}).items():
                    if db == "NCBI Gene":
                        counts["rows_with_online_ncbi_gene"] += 1
                    if db == "NCBI Protein":
                        counts["rows_with_online_refseq_protein"] += 1
                    has_external = True
                    meta = next(item for item in TARGETS.values() if item["external_database"] == db)
                    for ext in sorted(values):
                        writer.writerow(
                            {
                                **base,
                                "uniprot_accession": acc,
                                "external_database": db,
                                "external_id": ext,
                                "external_id_type": meta["external_id_type"],
                                "mapping_source": "UniProt REST ID Mapping API",
                                "mapping_method": meta["mapping_method"],
                                "mapping_confidence": "high",
                                "evidence_level": "official_uniprot_cross_reference",
                            }
                        )
                        counts["long_external_rows"] += 1
                        totals["long_external_rows"] += 1
            if has_external:
                counts["rows_with_any_external_gene_or_protein_id"] += 1
            else:
                counts["rows_species_standard_only"] += 1
            if args.progress_interval and totals["rows_scanned"] % args.progress_interval == 0:
                print(f"[{group}] long rows={totals['rows_scanned']:,} long_assertions={totals['long_external_rows']:,}", flush=True)
            if args.max_rows and totals["rows_scanned"] >= args.max_rows:
                break
    with qc_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=QC_FIELDS)
        writer.writeheader()
        for species_id in sorted(species_counts):
            counts = species_counts[species_id]
            out = {"division": group, "species_id": species_id, "external_mapping_grade": grade(counts)}
            for field in QC_FIELDS:
                out.setdefault(field, counts[field])
            writer.writerow(out)
    return {"species_count": len(species_counts), "counts": dict(totals)}


def write_standard(path: Path, species: dict[str, dict[str, str]]) -> int:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=STANDARD_FIELDS)
        writer.writeheader()
        for species_id in sorted(species):
            writer.writerow({field: species[species_id].get(field, "") for field in STANDARD_FIELDS})
    return len(species)


def sample_csv(src: Path, dst: Path, every: int = 100, max_rows: int = 100_000) -> int:
    if not src.exists():
        return 0
    count = 0
    with src.open("r", encoding="utf-8-sig", newline="") as in_fh, dst.open("w", encoding="utf-8", newline="") as out_fh:
        reader = csv.reader(in_fh)
        writer = csv.writer(out_fh)
        header = next(reader, None)
        if header:
            writer.writerow(header)
        for idx, row in enumerate(reader, start=1):
            if idx % every == 0:
                writer.writerow(row)
                count += 1
                if count >= max_rows:
                    break
    return count


def hardlink_or_copy(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        if src.stat().st_size <= 20 * 1024 * 1024:
            dst.write_bytes(src.read_bytes())


def build_group(group: str, args: argparse.Namespace) -> dict[str, Any]:
    start = time.time()
    out_dir = group_out_dir(group)
    if args.fast_split:
        accessions, species, collect_counts = collect_accessions_fast(group, args.progress_interval, args.max_rows)
    else:
        accessions, species, collect_counts = collect_accessions(group, args.progress_interval, args.max_rows)
    if args.max_accessions:
        accessions = accessions[: args.max_accessions]
    target_maps: dict[str, dict[str, set[str]]] = {}
    if not args.skip_online:
        for target in TARGETS:
            target_maps[target] = run_uniprot(group, target, accessions, out_dir, args) if accessions else {}
    acc_path = out_dir / f"{group}_uniprot_online_accession_map.csv"
    acc_rows = write_accession_map(group, target_maps, acc_path)
    acc_map = load_accession_map(acc_path)
    standard_path = out_dir / f"{group}_species_standard_ids.csv"
    standard_rows = write_standard(standard_path, species)
    long_path = out_dir / f"{group}_external_id_mapping_long_final_whitelist.csv"
    qc_path = out_dir / f"{group}_online_external_id_mapping_species_qc.csv"
    long_summary = {"species_count": 0, "counts": {}}
    if not args.skip_long:
        long_summary = write_long_and_qc(group, acc_map, long_path, qc_path, args)
    sample_paths = {}
    for path in [acc_path, long_path, qc_path, standard_path]:
        if path.exists():
            sample = path.with_name(path.stem + ".sample_1pct.csv")
            sample_paths[sample.name] = {"path": str(sample), "rows": sample_csv(path, sample)}
    summary = {
        "division": group,
        "generated_at_unix": int(time.time()),
        "source_external_wide_csv": str(external_csv(group)),
        "unique_uniprot_accessions": len(accessions),
        "online_accession_map_rows": acc_rows,
        "species_standard_rows": standard_rows,
        "collect_counts": dict(collect_counts),
        "long_summary": long_summary,
        "outputs": {
            "online_accession_map": str(acc_path),
            "combined_long_mapping": str(long_path),
            "species_qc": str(qc_path),
            "species_standard_ids": str(standard_path),
            "samples": sample_paths,
        },
        "runtime_seconds": round(time.time() - start, 3),
    }
    summary_path = out_dir / f"{group}_online_external_id_mapping_summary.json"
    summary["outputs"]["summary"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    data_group = DATA_OUT_ROOT / group
    for path in [acc_path, long_path, qc_path, standard_path, summary_path, *[Path(v["path"]) for v in sample_paths.values()]]:
        hardlink_or_copy(path, data_group / path.name)
    return summary


def write_report(manifest: dict[str, Any]) -> None:
    lines = [
        "# Final-Whitelist Online External ID Mapping Result Report",
        "",
        "## Task Status",
        "",
        "Completed for generated artifacts listed in the manifest. This enrichment layer supplements external standard IDs only and does not regenerate the full omics ID chain.",
        "",
        "| division | unique UniProt | online accession rows | long rows | species | runtime seconds |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in manifest.get("groups", []):
        long_counts = (item.get("long_summary") or {}).get("counts", {})
        lines.append(
            f"| {item['division']} | {item.get('unique_uniprot_accessions', 0):,} | "
            f"{item.get('online_accession_map_rows', 0):,} | "
            f"{long_counts.get('long_external_rows', 0):,} | "
            f"{(item.get('long_summary') or {}).get('species_count', 0):,} | "
            f"{item.get('runtime_seconds', 0):,} |"
        )
    lines.extend(
        [
            "",
            "## Limits",
            "",
            "Online cross-references come from UniProtKB accessions that already exist in the local Ensembl-derived feature evidence. Rows without UniProt accessions remain supported by local NCBI/RefSeq/INSDC evidence and species-level NCBI Taxonomy/assembly identifiers.",
        ]
    )
    (OUT_ROOT / "final_whitelist_online_external_id_mapping_result_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("groups", nargs="*", choices=GROUPS)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-wait-seconds", type=int, default=900)
    parser.add_argument("--retry-count", type=int, default=2)
    parser.add_argument("--progress-interval", type=int, default=1_000_000)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--max-accessions", type=int, default=None)
    parser.add_argument("--skip-online", action="store_true")
    parser.add_argument("--skip-long", action="store_true")
    parser.add_argument("--fast-split", action="store_true", help="Use fast comma split reader for generated wide CSV files without quoted comma fields.")
    args = parser.parse_args()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    DATA_OUT_ROOT.mkdir(parents=True, exist_ok=True)
    start = time.time()
    summaries = [build_group(group, args) for group in (args.groups or GROUPS)]
    manifest = {
        "schema_version": "final_whitelist_online_external_id_mapping.v1",
        "generated_at_unix": int(time.time()),
        "runtime_seconds": round(time.time() - start, 3),
        "source": {"online_api": "UniProt REST ID Mapping API", "targets": TARGETS, "local_external_wide_root": str(FINAL_ROOT)},
        "groups": summaries,
        "long_fields": LONG_FIELDS,
        "accession_fields": ACC_FIELDS,
        "qc_fields": QC_FIELDS,
        "notes": [
            "This layer supplements external standard IDs only; full omics ID chain expansion is not regenerated.",
            "UniProt online mappings are limited to rows with local UniProtKB accessions.",
        ],
    }
    manifest_path = OUT_ROOT / "final_whitelist_online_external_id_mapping_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(manifest)
    for path in [manifest_path, OUT_ROOT / "final_whitelist_online_external_id_mapping_result_report.md"]:
        hardlink_or_copy(path, DATA_OUT_ROOT / path.name)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
