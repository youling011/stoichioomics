#!/usr/bin/env python3
"""Build a standard external-ID overlay from local GFF3 and UniProt.

The existing ID mapping tables keep the internal gene-transcript-protein chain.
This overlay supplements each internal ID with as many UniProtKB and NCBI
standard IDs as can be recovered from official annotation attributes and,
optionally, UniProt REST ID Mapping.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "id_mapping"
FINAL_ROOT = DATA_ROOT / "final_whitelist"
FINAL_ONLINE_ROOT = FINAL_ROOT / "online_external"
OVERLAY_ROOT = DATA_ROOT / "standard_external_id_overlay"
WORK_ROOT = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "standard_external_id_overlay"
PROTIST_WORK_ID_MAPPING = PROJECT_ROOT / "workspace" / "generated_analysis_artifacts" / "id_mapping"

G_DOWNLOAD_ROOT = Path("G:/stoichioomics/全组学下载数据")
G_FINAL_ROOT = Path("G:/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj/data/id_mapping/final_whitelist")
G_DATA_ROOT = Path("G:/stoichioomics/项目平台数据/stoich_platform_postgres_open_search_v6_2_perf_fix/proj/data/id_mapping")

GROUPS = {
    "protists": {
        "download_dir": "protists",
        "species_qc": DATA_ROOT / "protist_external_id_mapping_species_qc.csv",
        "g_species_qc": G_DATA_ROOT / "protist_external_id_mapping_species_qc.csv",
        "work_species_qc": PROTIST_WORK_ID_MAPPING / "protist_external_id_mapping_species_qc.csv",
        "wide_csv": DATA_ROOT / "protist_external_id_mapping_all_species.csv",
        "g_wide_csv": G_DATA_ROOT / "protist_external_id_mapping_all_species.csv",
        "final": False,
    },
    "bacteria": {"download_dir": "bacteria", "final": True},
    "fungi": {"download_dir": "fungi", "final": True},
    "metazoa": {"download_dir": "metazoa", "final": True},
    "plants": {"download_dir": "plants", "final": True},
    "vertebrates": {"download_dir": "vertebrates", "final": True},
}

UNIPROT_RUN_URL = "https://rest.uniprot.org/idmapping/run"
UNIPROT_STATUS_URL = "https://rest.uniprot.org/idmapping/status/{job_id}"
UNIPROT_STREAM_URL = "https://rest.uniprot.org/idmapping/stream/{job_id}?format=tsv"

OVERLAY_FIELDS = [
    "division",
    "species_id",
    "internal_id",
    "internal_id_type",
    "uniprot_accessions",
    "ncbi_gene_ids",
    "refseq_protein_accessions",
    "refseq_transcript_accessions",
    "insdc_protein_accessions",
    "mapping_sources",
    "mapping_methods",
    "mapping_confidence",
    "evidence",
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

GFF_ID_KEYS = (
    "ID",
    "Parent",
    "gene_id",
    "transcript_id",
    "protein_id",
    "Derives_from",
    "Name",
    "gene",
    "locus_tag",
    "standard_name",
)

UNIPROT_ACC_RE = re.compile(r"\b(?:[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9][A-Z][A-Z0-9]{2}[0-9])(?:-\d+)?\b")
GENEID_RE = re.compile(r"(?:GeneID|NCBI_Gene|EntrezGene)[:=]?(\d+)", re.IGNORECASE)
REFSEQ_PROTEIN_RE = re.compile(r"\b(?:[NXWAYZ]P|WP|AP|YP|XP|NP|ZP)_\d+(?:\.\d+)?\b")
REFSEQ_TRANSCRIPT_RE = re.compile(r"\b(?:NM|XM|NR|XR)_\d+(?:\.\d+)?\b")
INSDC_PROTEIN_RE = re.compile(r"\b[A-Z]{3,6}\d{5,10}(?:\.\d+)?\b")
GFF_EXTERNAL_HINT_RE = re.compile(
    r"Dbxref|db_xref|UniProt|GeneID|EntrezGene|RefSeq|Gen[Bb]ank|EMBL|DDBJ|"
    r"protein_id=(?:[A-Z]{2}_\d|[A-Z]{3,6}\d{5,10})|"
    r"(?:[=,:])[A-Z]{3,6}\d{5,10}(?:\.\d+)?",
    re.IGNORECASE,
)
GFF_EXTERNAL_HINT_BYTES_RE = re.compile(
    rb"Dbxref|db_xref|UniProt|GeneID|EntrezGene|RefSeq|Gen[Bb]ank|EMBL|DDBJ|"
    rb"protein_id=(?:[A-Z]{2}_\d|[A-Z]{3,6}\d{5,10})|"
    rb"(?:[=,:])[A-Z]{3,6}\d{5,10}(?:\.\d+)?",
    re.IGNORECASE,
)


def clean(value: object) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def split_values(value: object) -> list[str]:
    text = clean(value)
    if not text:
        return []
    return [part.strip() for part in re.split(r"[;,|]", text) if part.strip()]


def join_values(values: set[str]) -> str:
    return ";".join(sorted(v for v in values if v))


def species_file_stem(species_id: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9_.-]+", "_", species_id)
    if len(candidate) <= 56:
        return candidate
    digest = hashlib.sha1(species_id.encode("utf-8")).hexdigest()[:16]
    return f"{candidate[:48]}_{digest}"


def species_overlay_path(out_dir: Path, species_id: str) -> Path:
    return out_dir / f"{species_file_stem(species_id)}.standard_id_overlay.csv"


def species_empty_marker_path(out_dir: Path, species_id: str) -> Path:
    return out_dir / f"{species_file_stem(species_id)}.no_external.json"


def parse_attrs(raw: str) -> dict[str, list[str]]:
    attrs: dict[str, list[str]] = defaultdict(list)
    for part in raw.strip().split(";"):
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
        elif " " in part:
            key, value = part.split(" ", 1)
        else:
            continue
        key = urllib.parse.unquote_plus(key.strip())
        for item in re.split(r",", urllib.parse.unquote_plus(value.strip())):
            item = item.strip()
            if item:
                attrs[key].append(item)
    return attrs


def add_external(target: dict[str, set[str]], value: str, evidence: set[str]) -> None:
    value = clean(value)
    if not value:
        return
    low = value.lower()
    if low.startswith(("uniprotkb:", "uniprot:")) or "uniprot" in low:
        for acc in UNIPROT_ACC_RE.findall(value):
            target["uniprot_accessions"].add(acc)
            evidence.add("gff3_dbxref_uniprot")
    for gene_id in GENEID_RE.findall(value):
        target["ncbi_gene_ids"].add(gene_id)
        evidence.add("gff3_dbxref_ncbi_gene")
    for acc in REFSEQ_PROTEIN_RE.findall(value):
        target["refseq_protein_accessions"].add(acc)
        target["insdc_protein_accessions"].discard(acc)
        evidence.add("gff3_dbxref_refseq_protein")
    for acc in REFSEQ_TRANSCRIPT_RE.findall(value):
        target["refseq_transcript_accessions"].add(acc)
        evidence.add("gff3_dbxref_refseq_transcript")
    if "protein_id" in low or "genbank" in low or "embl" in low or "ddbj" in low or "insdc" in low:
        for acc in INSDC_PROTEIN_RE.findall(value):
            if not REFSEQ_PROTEIN_RE.fullmatch(acc):
                target["insdc_protein_accessions"].add(acc)
                evidence.add("gff3_dbxref_insdc_protein")


def normalize_internal_id(value: str) -> str:
    value = clean(value)
    for prefix in ("gene:", "transcript:", "protein:", "cds:", "mrna:"):
        if value.lower().startswith(prefix):
            return value[len(prefix) :]
    return value


def infer_internal_type(feature_type: str, key: str, value: str) -> str:
    key_l = key.lower()
    ft = feature_type.lower()
    if "protein" in key_l or ft in {"cds", "polypeptide", "protein"}:
        return "protein"
    if "transcript" in key_l or ft in {"mrna", "transcript", "rrna", "trna"}:
        return "transcript"
    if "gene" in key_l or ft == "gene" or key_l in {"locus_tag", "standard_name"}:
        return "gene"
    return "internal_id"


def empty_xrefs() -> dict[str, set[str]]:
    return {
        "uniprot_accessions": set(),
        "ncbi_gene_ids": set(),
        "refseq_protein_accessions": set(),
        "refseq_transcript_accessions": set(),
        "insdc_protein_accessions": set(),
        "mapping_sources": set(),
        "mapping_methods": set(),
        "evidence": set(),
    }


def update_overlay(
    overlay: dict[tuple[str, str], dict[str, set[str]]],
    internal_id: str,
    internal_type: str,
    xrefs: dict[str, set[str]],
) -> None:
    internal_id = normalize_internal_id(internal_id)
    if not internal_id:
        return
    if not any(xrefs[field] for field in ("uniprot_accessions", "ncbi_gene_ids", "refseq_protein_accessions", "refseq_transcript_accessions", "insdc_protein_accessions")):
        return
    item = overlay.setdefault((internal_id, internal_type), empty_xrefs())
    for key, values in xrefs.items():
        item[key].update(values)
    item["mapping_sources"].add("local_gff3_annotation")
    item["mapping_methods"].add("gff3_attribute_dbxref_parse")


def find_gff(species_dir: Path) -> Path | None:
    if not species_dir.exists():
        return None
    files = sorted(species_dir.glob("*.gff3.gz"))
    if files:
        return files[0]
    files = sorted(species_dir.glob("*.gff.gz"))
    return files[0] if files else None


def parse_gff_species(group: str, species_id: str, gff_path: Path) -> tuple[dict[tuple[str, str], dict[str, set[str]]], Counter]:
    overlay: dict[tuple[str, str], dict[str, set[str]]] = {}
    counts: Counter[str] = Counter()
    opener = gzip.open if gff_path.suffix == ".gz" else open
    with opener(gff_path, "rb") as fh:  # type: ignore[arg-type]
        for raw in fh:
            if not raw or raw.startswith(b"#"):
                continue
            parts = raw.rstrip(b"\r\n").split(b"\t", 8)
            if len(parts) < 9:
                continue
            counts["features_scanned"] += 1
            attr_bytes = parts[8]
            if not GFF_EXTERNAL_HINT_BYTES_RE.search(attr_bytes):
                continue
            feature_type = parts[2].decode("utf-8", errors="replace")
            attr_raw = attr_bytes.decode("utf-8", errors="replace")
            attrs = parse_attrs(attr_raw)
            xrefs = empty_xrefs()
            for key, values in attrs.items():
                if key.lower() in {"dbxref", "db_xref", "xref", "ontology_term", "note", "description", "protein_id"}:
                    for value in values:
                        add_external(xrefs, value, xrefs["evidence"])
            if attrs.get("protein_id"):
                for value in attrs["protein_id"]:
                    for acc in REFSEQ_PROTEIN_RE.findall(value):
                        xrefs["refseq_protein_accessions"].add(acc)
                        xrefs["evidence"].add("gff3_protein_id_refseq")
                    for acc in INSDC_PROTEIN_RE.findall(value):
                        if not REFSEQ_PROTEIN_RE.fullmatch(acc):
                            xrefs["insdc_protein_accessions"].add(acc)
                            xrefs["evidence"].add("gff3_protein_id_insdc")
            if not any(xrefs[field] for field in ("uniprot_accessions", "ncbi_gene_ids", "refseq_protein_accessions", "refseq_transcript_accessions", "insdc_protein_accessions")):
                continue
            counts["features_with_external"] += 1
            for key in GFF_ID_KEYS:
                for raw_id in attrs.get(key, []):
                    internal_id = normalize_internal_id(raw_id)
                    if internal_id:
                        update_overlay(overlay, internal_id, infer_internal_type(feature_type, key, raw_id), xrefs)
    counts["overlay_internal_ids"] = len(overlay)
    counts["overlay_rows_with_uniprot"] = sum(1 for item in overlay.values() if item["uniprot_accessions"])
    counts["overlay_rows_with_ncbi_gene"] = sum(1 for item in overlay.values() if item["ncbi_gene_ids"])
    return overlay, counts


def final_qc_path(group: str) -> Path:
    return FINAL_ROOT / group / f"{group}_id_mapping_species_qc.csv"


def g_final_qc_path(group: str) -> Path:
    return G_FINAL_ROOT / group / f"{group}_id_mapping_species_qc.csv"


def species_rows(group: str) -> list[dict[str, str]]:
    cfg = GROUPS[group]
    path = Path(cfg.get("species_qc") or final_qc_path(group))
    if not path.exists() and cfg.get("g_species_qc"):
        path = Path(cfg["g_species_qc"])
    if not path.exists() and cfg.get("work_species_qc"):
        path = Path(cfg["work_species_qc"])
    if not path.exists() and cfg.get("final"):
        path = g_final_qc_path(group)
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            species_id = clean(row.get("species_id") or row.get("species"))
            if species_id:
                rows.append({
                    "species_id": species_id,
                    "tax_id": clean(row.get("tax_id")),
                    "assembly_accession": clean(row.get("assembly_accession")),
                })
    return rows


def write_species_overlay(group: str, species: dict[str, str], overlay: dict[tuple[str, str], dict[str, set[str]]], out_dir: Path) -> Counter:
    counts: Counter[str] = Counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = species_overlay_path(out_dir, species["species_id"])
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OVERLAY_FIELDS)
        writer.writeheader()
        for (internal_id, internal_type), item in sorted(overlay.items()):
            row = {
                "division": group,
                "species_id": species["species_id"],
                "internal_id": internal_id,
                "internal_id_type": internal_type,
                "uniprot_accessions": join_values(item["uniprot_accessions"]),
                "ncbi_gene_ids": join_values(item["ncbi_gene_ids"]),
                "refseq_protein_accessions": join_values(item["refseq_protein_accessions"]),
                "refseq_transcript_accessions": join_values(item["refseq_transcript_accessions"]),
                "insdc_protein_accessions": join_values(item["insdc_protein_accessions"]),
                "mapping_sources": join_values(item["mapping_sources"]),
                "mapping_methods": join_values(item["mapping_methods"]),
                "mapping_confidence": "high" if item["ncbi_gene_ids"] or item["uniprot_accessions"] else "medium",
                "evidence": join_values(item["evidence"]),
            }
            writer.writerow(row)
            counts["overlay_rows"] += 1
            if row["uniprot_accessions"]:
                counts["rows_with_uniprot"] += 1
            if row["ncbi_gene_ids"]:
                counts["rows_with_ncbi_gene"] += 1
            if row["refseq_protein_accessions"] or row["insdc_protein_accessions"]:
                counts["rows_with_ncbi_protein"] += 1
    if counts["overlay_rows"] == 0:
        out_path.unlink(missing_ok=True)
    else:
        counts["file_size_bytes"] = out_path.stat().st_size
    return counts


def process_species_local(group: str, species: dict[str, str]) -> dict[str, Any]:
    species_id = species["species_id"]
    out_dir = WORK_ROOT / group
    out_dir.mkdir(parents=True, exist_ok=True)
    gff_path = find_gff(G_DOWNLOAD_ROOT / GROUPS[group]["download_dir"] / species_id)
    row_counts: Counter[str] = Counter()
    existing = species_overlay_path(out_dir, species_id)
    empty_marker = species_empty_marker_path(out_dir, species_id)
    if existing.exists() and existing.stat().st_size > 0:
        with existing.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                row_counts["overlay_rows"] += 1
                if row.get("uniprot_accessions"):
                    row_counts["rows_with_uniprot"] += 1
                if row.get("ncbi_gene_ids"):
                    row_counts["rows_with_ncbi_gene"] += 1
                if row.get("refseq_protein_accessions") or row.get("insdc_protein_accessions"):
                    row_counts["rows_with_ncbi_protein"] += 1
        row_counts["file_size_bytes"] = existing.stat().st_size
        row_counts["has_gff3"] = 1 if gff_path else 0
        return {
            "division": group,
            "species_id": species_id,
            "tax_id": species.get("tax_id", ""),
            "assembly_accession": species.get("assembly_accession", ""),
            "has_gff3": row_counts["has_gff3"],
            "overlay_rows": row_counts["overlay_rows"],
            "rows_with_uniprot": row_counts["rows_with_uniprot"],
            "rows_with_ncbi_gene": row_counts["rows_with_ncbi_gene"],
            "rows_with_ncbi_protein": row_counts["rows_with_ncbi_protein"],
            "features_scanned": 0,
            "features_with_external": 0,
            "file_size_bytes": row_counts["file_size_bytes"],
            "gff3_path": str(gff_path or ""),
        }
    if empty_marker.exists():
        try:
            data = json.loads(empty_marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        return {
            "division": group,
            "species_id": species_id,
            "tax_id": species.get("tax_id", ""),
            "assembly_accession": species.get("assembly_accession", ""),
            "has_gff3": int(data.get("has_gff3") or (1 if gff_path else 0)),
            "overlay_rows": 0,
            "rows_with_uniprot": 0,
            "rows_with_ncbi_gene": 0,
            "rows_with_ncbi_protein": 0,
            "features_scanned": int(data.get("features_scanned") or 0),
            "features_with_external": int(data.get("features_with_external") or 0),
            "file_size_bytes": 0,
            "gff3_path": str(gff_path or data.get("gff3_path") or ""),
        }
    if gff_path:
        overlay, parse_counts = parse_gff_species(group, species_id, gff_path)
        row_counts.update(parse_counts)
        row_counts.update(write_species_overlay(group, species, overlay, out_dir))
        row_counts["has_gff3"] = 1
    else:
        row_counts["has_gff3"] = 0
    if row_counts["overlay_rows"] == 0:
        empty_marker.write_text(
            json.dumps(
                {
                    "division": group,
                    "species_id": species_id,
                    "has_gff3": row_counts["has_gff3"],
                    "features_scanned": row_counts["features_scanned"],
                    "features_with_external": row_counts["features_with_external"],
                    "gff3_path": str(gff_path or ""),
                    "generated_at_unix": int(time.time()),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return {
        "division": group,
        "species_id": species_id,
        "tax_id": species.get("tax_id", ""),
        "assembly_accession": species.get("assembly_accession", ""),
        "has_gff3": row_counts["has_gff3"],
        "overlay_rows": row_counts["overlay_rows"],
        "rows_with_uniprot": row_counts["rows_with_uniprot"],
        "rows_with_ncbi_gene": row_counts["rows_with_ncbi_gene"],
        "rows_with_ncbi_protein": row_counts["rows_with_ncbi_protein"],
        "features_scanned": row_counts["features_scanned"],
        "features_with_external": row_counts["features_with_external"],
        "file_size_bytes": row_counts["file_size_bytes"],
        "gff3_path": str(gff_path or ""),
    }


def hardlink_or_copy(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        with src.open("rb") as in_fh, dst.open("wb") as out_fh:
            while True:
                chunk = in_fh.read(8 * 1024 * 1024)
                if not chunk:
                    break
                out_fh.write(chunk)


def build_local_group(group: str, args: argparse.Namespace) -> dict[str, Any]:
    start = time.time()
    rows = species_rows(group)
    out_dir = WORK_ROOT / group
    index_path = out_dir / f"{group}_standard_id_overlay_index.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    totals: Counter[str] = Counter()
    if args.max_species:
        rows = rows[: args.max_species]
    if args.sort_by_size:
        rows.sort(
            key=lambda row: (
                (find_gff(G_DOWNLOAD_ROOT / GROUPS[group]["download_dir"] / row["species_id"]).stat().st_size if find_gff(G_DOWNLOAD_ROOT / GROUPS[group]["download_dir"] / row["species_id"]) else 10**18),
                row["species_id"],
            )
        )
    with index_path.open("w", encoding="utf-8", newline="") as idx_fh:
        fields = ["division", "species_id", "tax_id", "assembly_accession", "has_gff3", "overlay_rows", "rows_with_uniprot", "rows_with_ncbi_gene", "rows_with_ncbi_protein", "features_scanned", "features_with_external", "file_size_bytes", "gff3_path"]
        writer = csv.DictWriter(idx_fh, fieldnames=fields)
        writer.writeheader()
        if args.workers <= 1:
            iterator = ((number, process_species_local(group, species)) for number, species in enumerate(rows, start=1))
            for number, result in iterator:
                writer.writerow(result)
                for key, value in result.items():
                    if isinstance(value, int):
                        totals[key] += value
                if args.progress_interval and number % args.progress_interval == 0:
                    print(f"[{group}] species={number:,}/{len(rows):,} overlay_rows={totals['overlay_rows']:,}", flush=True)
        else:
            completed = 0
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                futures = [pool.submit(process_species_local, group, species) for species in rows]
                for future in as_completed(futures):
                    completed += 1
                    result = future.result()
                    writer.writerow(result)
                    for key, value in result.items():
                        if isinstance(value, int):
                            totals[key] += value
                    if args.progress_interval and completed % args.progress_interval == 0:
                        print(f"[{group}] species={completed:,}/{len(rows):,} overlay_rows={totals['overlay_rows']:,}", flush=True)
    summary = {
        "division": group,
        "generated_at_unix": int(time.time()),
        "species_requested": len(rows),
        "species_processed": sum(1 for _ in index_path.open("r", encoding="utf-8")) - 1,
        "counts": dict(totals),
        "outputs": {
            "overlay_dir": str(out_dir),
            "index_csv": str(index_path),
        },
        "runtime_seconds": round(time.time() - start, 3),
    }
    (out_dir / f"{group}_standard_id_overlay_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def request_json(url: str, data: dict[str, str] | None, timeout: int) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8") if data else None
    request = urllib.request.Request(url, data=encoded)
    request.add_header("User-Agent", "Stoichioomics-IDMapping/1.0")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_done(log_path: Path) -> set[str]:
    done: set[str] = set()
    if not log_path.exists():
        return done
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("status") == "done":
                done.add(item.get("batch_key", ""))
    return done


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def submit_mapping(from_db: str, to_db: str, ids: list[str], timeout: int) -> str:
    return request_json(UNIPROT_RUN_URL, {"from": from_db, "to": to_db, "ids": ",".join(ids)}, timeout)["jobId"]


def wait_mapping(job_id: str, timeout: int, max_wait: int) -> None:
    deadline = time.time() + max_wait
    while True:
        result = request_json(UNIPROT_STATUS_URL.format(job_id=job_id), None, timeout)
        status = result.get("jobStatus")
        if not status or status == "FINISHED":
            return
        if status in {"ERROR", "FAILED"}:
            raise RuntimeError(result)
        if time.time() > deadline:
            raise TimeoutError(f"UniProt job {job_id} did not finish within {max_wait}s")
        time.sleep(3)


def stream_pairs(job_id: str, timeout: int) -> list[tuple[str, str]]:
    request = urllib.request.Request(UNIPROT_STREAM_URL.format(job_id=job_id))
    request.add_header("User-Agent", "Stoichioomics-IDMapping/1.0")
    pairs: list[tuple[str, str]] = []
    with urllib.request.urlopen(request, timeout=timeout) as response:
        header = True
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            if header:
                header = False
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] and parts[1]:
                pairs.append((clean(parts[0]), clean(parts[1])))
    return pairs


def batch_key(from_db: str, to_db: str, values: list[str]) -> str:
    return f"{from_db}->{to_db}:{hashlib.sha1(chr(10).join(values).encode('utf-8')).hexdigest()}"


def chunks(values: list[str], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def run_uniprot_batches(group: str, from_db: str, to_db: str, values: list[str], out_dir: Path, args: argparse.Namespace) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)
    log_path = out_dir / f"{group}_{from_db}_to_{to_db}_batches.jsonl"
    done = load_done(log_path)
    values = sorted(set(v for v in values if v))
    if args.max_online_ids:
        values = values[: args.max_online_ids]
    total = (len(values) + args.batch_size - 1) // args.batch_size
    for idx, batch in enumerate(chunks(values, args.batch_size), start=1):
        key = batch_key(from_db, to_db, batch)
        if key in done:
            continue
        last_error = ""
        for attempt in range(1, args.retry_count + 2):
            try:
                job_id = submit_mapping(from_db, to_db, batch, args.timeout)
                wait_mapping(job_id, args.timeout, args.max_wait_seconds)
                pairs = stream_pairs(job_id, args.timeout)
                for from_id, to_id in pairs:
                    mapping[from_id].add(to_id)
                append_jsonl(log_path, {"batch_key": key, "status": "done", "batch_index": idx, "batch_total": total, "input_count": len(batch), "result_count": len(pairs), "job_id": job_id, "completed_at_unix": int(time.time())})
                print(f"[{group}] {from_db}->{to_db} batch={idx}/{total} results={len(pairs)}", flush=True)
                time.sleep(args.sleep_seconds)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = repr(exc)
                if attempt <= args.retry_count:
                    time.sleep(min(60, attempt * 10))
        else:
            append_jsonl(log_path, {"batch_key": key, "status": "failed", "batch_index": idx, "batch_total": total, "input_count": len(batch), "result_count": 0, "error": last_error, "completed_at_unix": int(time.time())})
            print(f"[{group}] {from_db}->{to_db} batch={idx}/{total} failed={last_error}", flush=True)
    return mapping


def collect_overlay_uniprot(group: str) -> list[str]:
    accessions: set[str] = set()
    group_dir = WORK_ROOT / group
    for path in group_dir.glob("*.standard_id_overlay.csv"):
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                accessions.update(split_values(row.get("uniprot_accessions")))
    return sorted(accessions)


def write_accession_map(group: str, gene_map: dict[str, set[str]], refseq_map: dict[str, set[str]], out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{group}_uniprot_online_accession_map.csv"
    rows = 0
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=ACC_FIELDS)
        writer.writeheader()
        for acc, values in sorted(gene_map.items()):
            for value in sorted(values):
                writer.writerow({"division": group, "uniprot_accession": acc, "target_database": "NCBI Gene", "external_id": value, "external_id_type": "gene_id", "mapping_method": "uniprot_idmapping_uniprotkb_to_geneid", "mapping_source": "UniProt REST ID Mapping API"})
                rows += 1
        for acc, values in sorted(refseq_map.items()):
            for value in sorted(values):
                writer.writerow({"division": group, "uniprot_accession": acc, "target_database": "NCBI Protein", "external_id": value, "external_id_type": "refseq_protein_accession", "mapping_method": "uniprot_idmapping_uniprotkb_to_refseq_protein", "mapping_source": "UniProt REST ID Mapping API"})
                rows += 1
    return rows


def run_online_group(group: str, args: argparse.Namespace) -> dict[str, Any]:
    start = time.time()
    out_dir = WORK_ROOT / group
    accessions = collect_overlay_uniprot(group)
    gene_map = run_uniprot_batches(group, "UniProtKB_AC-ID", "GeneID", accessions, out_dir, args) if accessions else {}
    refseq_map = run_uniprot_batches(group, "UniProtKB_AC-ID", "RefSeq_Protein", accessions, out_dir, args) if accessions else {}
    rows = write_accession_map(group, gene_map, refseq_map, out_dir)
    return {
        "division": group,
        "unique_overlay_uniprot_accessions": len(accessions),
        "online_accession_map_rows": rows,
        "runtime_seconds": round(time.time() - start, 3),
        "outputs": {"online_accession_map": str(out_dir / f"{group}_uniprot_online_accession_map.csv")},
    }


def sync_group_to_project(group: str) -> None:
    src_dir = WORK_ROOT / group
    dst_dir = OVERLAY_ROOT / group
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src in src_dir.glob("*"):
        if src.is_file():
            hardlink_or_copy(src, dst_dir / src.name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("groups", nargs="*", choices=GROUPS)
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--online-only", action="store_true")
    parser.add_argument("--max-species", type=int, default=None)
    parser.add_argument("--max-online-ids", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-wait-seconds", type=int, default=900)
    parser.add_argument("--retry-count", type=int, default=2)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    parser.add_argument("--progress-interval", type=int, default=100)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--sort-by-size", action="store_true", default=True)
    args = parser.parse_args()

    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    OVERLAY_ROOT.mkdir(parents=True, exist_ok=True)
    selected = args.groups or list(GROUPS)
    local_summaries = []
    online_summaries = []
    start = time.time()
    if not args.online_only:
        for group in selected:
            local_summaries.append(build_local_group(group, args))
            sync_group_to_project(group)
    if not args.local_only:
        for group in selected:
            online_summaries.append(run_online_group(group, args))
            sync_group_to_project(group)
    manifest = {
        "schema_version": "standard_external_id_overlay.v1",
        "generated_at_unix": int(time.time()),
        "runtime_seconds": round(time.time() - start, 3),
        "groups": selected,
        "local_gff3_summaries": local_summaries,
        "online_uniprot_summaries": online_summaries,
        "overlay_fields": OVERLAY_FIELDS,
        "accession_fields": ACC_FIELDS,
        "sources": {
            "local_gff3_root": str(G_DOWNLOAD_ROOT),
            "online_api": "UniProt REST ID Mapping API",
        },
        "notes": [
            "The overlay is keyed by species_id plus internal gene/transcript/protein/source ID.",
            "It supplements existing omics-chain wide CSV files without rewriting them.",
            "Online UniProt enrichment is resumable through per-group JSONL batch logs.",
        ],
    }
    manifest_path = WORK_ROOT / "standard_external_id_overlay_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    hardlink_or_copy(manifest_path, OVERLAY_ROOT / manifest_path.name)
    print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
