from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.model8_elemental_contract import (
        ELEMENTAL_CONTRACT_ID,
        protein_elemental_features,
        validate_model8_protein_feature_files,
    )
except ImportError:
    from model8_elemental_contract import (
        ELEMENTAL_CONTRACT_ID,
        protein_elemental_features,
        validate_model8_protein_feature_files,
    )


SEED = 20260729
SCHEMA_VERSION = "model8-a0-a3-v2-elemental"

SPECIES_ORDER = ["ECOLI", "BSUB", "ORYSA", "DROME", "YEAST", "ARATH", "DANRE", "MOUSE"]

STRAIN_AND_ROLE = {
    "ECOLI": {
        "strain_or_cultivar": "K-12 substr. MG1655",
        "case_role": "bacterial exact-strain sequence and expression baseline",
        "reference_identity_rule": "exact_reference_required",
        "go_taxon_policy": "UniProt taxonomy_id:83333 fallback for K-12 GO coverage; reference remains MG1655 taxon 511145",
    },
    "BSUB": {
        "strain_or_cultivar": "subsp. subtilis str. 168",
        "case_role": "Gram-positive bacterial exact-strain baseline",
        "reference_identity_rule": "exact_reference_required",
        "go_taxon_policy": "UniProt taxonomy_id:224308",
    },
    "ORYSA": {
        "strain_or_cultivar": "Nipponbare / Japonica reference; 93-11 expression used as cross-cultivar validation",
        "case_role": "plant discovery-validation pair",
        "reference_identity_rule": "cross_cultivar_validation_separated",
        "go_taxon_policy": "UniProt taxonomy_id:39947",
    },
    "DROME": {
        "strain_or_cultivar": "BDGP6 reference",
        "case_role": "development and aging metazoan atlas",
        "reference_identity_rule": "reference_assembly_match_required",
        "go_taxon_policy": "UniProt taxonomy_id:7227",
    },
    "YEAST": {
        "strain_or_cultivar": "S288C / R64 reference",
        "case_role": "fungal single-cell and stress baseline",
        "reference_identity_rule": "reference_assembly_match_required",
        "go_taxon_policy": "UniProt taxonomy_id:559292",
    },
    "ARATH": {
        "strain_or_cultivar": "Col-0 / TAIR10 reference",
        "case_role": "plant root single-cell baseline",
        "reference_identity_rule": "reference_assembly_match_required",
        "go_taxon_policy": "UniProt taxonomy_id:3702",
    },
    "DANRE": {
        "strain_or_cultivar": "GRCz11 reference",
        "case_role": "vertebrate embryogenesis single-cell baseline",
        "reference_identity_rule": "reference_assembly_match_required",
        "go_taxon_policy": "UniProt taxonomy_id:7955",
    },
    "MOUSE": {
        "strain_or_cultivar": "C57BL/6J / GRCm39 reference; Tabula Muris multi-tissue expression",
        "case_role": "mammalian multi-tissue HVG baseline",
        "reference_identity_rule": "reference_assembly_match_required",
        "go_taxon_policy": "UniProt taxonomy_id:10090",
    },
}


DNA_ASSET = "dna_toplevel"
TRANSCRIPT_ASSETS = ("cdna_all", "cds_all")
PROTEIN_ASSET = "pep_all"
GFF3_ASSET = "gff3"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def file_line_count(path: Path, max_lines: int | None = None) -> int:
    n = 0
    with open_text(path) as fh:
        for n, _ in enumerate(fh, 1):
            if max_lines and n >= max_lines:
                break
    return n


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict], fields: list[str]) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, delimiter="\t", fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def write_tsv_gz(path: Path, rows_iter, fields: list[str]) -> int:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, delimiter="\t", fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows_iter:
            writer.writerow(row)
            count += 1
    tmp.replace(path)
    return count


def write_json(path: Path, obj) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def parse_attr(attr: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in attr.strip().split(";"):
        if not item:
            continue
        if "=" in item:
            k, v = item.split("=", 1)
        elif " " in item:
            k, v = item.split(" ", 1)
        else:
            continue
        out[k] = urllib.parse.unquote(v.strip().strip('"'))
    return out


def parse_fasta(path: Path):
    header = None
    chunks: list[str] = []
    with open_text(path) as fh:
        for line in fh:
            line = line.rstrip("\n\r")
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    yield header, "".join(chunks)
                header = line[1:]
                chunks = []
            else:
                chunks.append(line.strip())
        if header is not None:
            yield header, "".join(chunks)


def fasta_id(header: str) -> str:
    return header.split()[0]


def parse_header_kv(header: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for token in header.split():
        if ":" in token:
            k, v = token.split(":", 1)
            if k and v:
                attrs[k] = v
    return attrs


def shannon_entropy(seq: str, alphabet: str) -> float:
    if not seq:
        return 0.0
    counts = Counter(c for c in seq.upper() if c in alphabet)
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((v / total) * math.log2(v / total) for v in counts.values())


AA_WEIGHTS = {
    "A": 89.09,
    "R": 174.20,
    "N": 132.12,
    "D": 133.10,
    "C": 121.15,
    "Q": 146.15,
    "E": 147.13,
    "G": 75.07,
    "H": 155.16,
    "I": 131.17,
    "L": 131.17,
    "K": 146.19,
    "M": 149.21,
    "F": 165.19,
    "P": 115.13,
    "S": 105.09,
    "T": 119.12,
    "W": 204.23,
    "Y": 181.19,
    "V": 117.15,
}


def sequence_stats(seq: str, alphabet: str = "ACGT") -> dict[str, str]:
    s = seq.upper()
    length = len(s)
    counts = Counter(s)
    valid = sum(counts.get(base, 0) for base in alphabet)
    gc = counts.get("G", 0) + counts.get("C", 0)
    n = counts.get("N", 0)
    return {
        "length": str(length),
        "valid_bases": str(valid),
        "gc_count": str(gc),
        "gc_fraction": f"{(gc / valid) if valid else 0:.6f}",
        "n_count": str(n),
        "n_fraction": f"{(n / length) if length else 0:.6f}",
        "entropy": f"{shannon_entropy(s, alphabet):.6f}",
    }


def protein_stats(seq: str) -> dict[str, str]:
    elemental = protein_elemental_features(seq)
    s = "".join(aa for aa in re.sub(r"[^A-Z]", "", seq.upper()) if aa in AA_WEIGHTS)
    length = int(elemental["length"])
    mw = sum(AA_WEIGHTS.get(aa, 0.0) for aa in s)
    if length > 1:
        mw -= 18.015 * (length - 1)
    return {
        "length": str(length),
        "cys_count": str(elemental["cys_count"]),
        "ser_count": str(elemental["ser_count"]),
        "asn_count": str(elemental["asn_count"]),
        "met_count": str(elemental["met_count"]),
        "c_atoms": str(elemental["c_atoms"]),
        "n_atoms": str(elemental["n_atoms"]),
        "s_atoms": str(elemental["s_atoms"]),
        "c_atoms_per_aa": f"{float(elemental['c_atoms_per_aa']):.6f}",
        "n_atoms_per_aa": f"{float(elemental['n_atoms_per_aa']):.6f}",
        "s_atoms_per_aa": f"{float(elemental['s_atoms_per_aa']):.6f}",
        "stop_count": str(elemental["stop_count"]),
        "invalid_aa_count": str(elemental["invalid_aa_count"]),
        "aa_entropy": f"{shannon_entropy(s, ''.join(AA_WEIGHTS)): .6f}".strip(),
        "mw_approx": f"{mw:.3f}",
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
    }


def summarize_numeric(values: list[float]) -> dict[str, str]:
    if not values:
        return {"min": "", "mean": "", "max": ""}
    return {
        "min": f"{min(values):.6f}",
        "mean": f"{sum(values) / len(values):.6f}",
        "max": f"{max(values):.6f}",
    }


def load_model8_metadata(model8_dir: Path) -> dict[str, dict[str, str]]:
    rows = read_tsv(model8_dir / "model8_reference_manifest.tsv")
    meta = {row["code"]: row for row in rows if row.get("code")}
    for code, extra in STRAIN_AND_ROLE.items():
        meta.setdefault(code, {"code": code})
        meta[code].update(extra)
    return meta


def load_statuses(model8_dir: Path) -> list[dict[str, str]]:
    status_path = model8_dir / "qc" / "model8_all_download_status.tsv"
    rows = read_tsv(status_path)
    if not rows:
        raise FileNotFoundError(f"missing combined download status: {status_path}")
    return rows


def status_by_code_asset(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    out = {}
    for row in rows:
        code = row.get("code") or row.get("species_code")
        asset = row.get("asset_type", "")
        if code and asset:
            out[(code, asset)] = row
    return out


def asset_path(asset_map: dict[tuple[str, str], dict[str, str]], code: str, asset: str) -> Path | None:
    row = asset_map.get((code, asset))
    if not row:
        return None
    p = Path(row.get("path", ""))
    return p if p.exists() else None


def git_commit(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unavailable"


def infer_assembly_from_path(path: str) -> str:
    name = Path(path).name
    parts = name.split(".")
    for part in parts:
        if re.search(r"(ASM|GRC|BDGP|TAIR|R64|IRGSP)", part, re.I):
            return part
    return ""


def a0_release_audit(project_root: Path, model8_dir: Path, meta: dict[str, dict[str, str]], statuses: list[dict[str, str]]):
    asset_map = status_by_code_asset(statuses)
    release_rows = []
    blockers = []
    all_hash_material = []
    for code in SPECIES_ORDER:
        m = meta[code]
        required = [DNA_ASSET, PROTEIN_ASSET, GFF3_ASSET]
        tx_asset = next((a for a in TRANSCRIPT_ASSETS if asset_path(asset_map, code, a)), "")
        if tx_asset:
            required.append(tx_asset)
        else:
            required.append("cdna_all_or_cds_all")
        missing = []
        sha_parts = []
        paths = {}
        for asset in required:
            if asset == "cdna_all_or_cds_all":
                missing.append(asset)
                continue
            row = asset_map.get((code, asset), {})
            p = row.get("path", "")
            paths[asset] = p
            if row.get("status") not in {"downloaded", "exists"} or not Path(p).exists():
                missing.append(asset)
            else:
                sha_parts.append(row.get("sha256", ""))
                all_hash_material.append(row.get("sha256", ""))
        qc_status = "passed" if not missing else "blocked"
        if missing:
            blockers.append(
                {
                    "code": code,
                    "step": "A0",
                    "reason_code": "missing_required_reference_asset",
                    "detail": ",".join(missing),
                    "status": "blocked",
                }
            )
        dna_path = paths.get(DNA_ASSET, "")
        gff3_path = paths.get(GFF3_ASSET, "")
        release_rows.append(
            {
                "case_code": code,
                "species_id": m.get("species_id", ""),
                "scientific_name": m.get("scientific_name", ""),
                "strain_or_cultivar": m.get("strain_or_cultivar", ""),
                "tax_id": m.get("taxon_id", ""),
                "assembly_accession": infer_assembly_from_path(dna_path),
                "annotation_accession": infer_assembly_from_path(gff3_path),
                "genome_release": m.get("ensembl_release", ""),
                "division": m.get("division", ""),
                "DNA_path": dna_path,
                "cDNA_path": paths.get(tx_asset, ""),
                "pep_path": paths.get(PROTEIN_ASSET, ""),
                "GFF3_path": gff3_path,
                "feature_bundle_path": str(model8_dir / code / "features"),
                "id_mapping_release": "model8_a1_id_mapping_v1",
                "go_release": m.get("go_taxon_policy", ""),
                "kegg_release": m.get("kegg_org", ""),
                "sha256": hashlib.sha256("|".join(sha_parts).encode("utf-8")).hexdigest(),
                "qc_status": qc_status,
                "reference_identity_rule": m.get("reference_identity_rule", ""),
                "case_role": m.get("case_role", ""),
            }
        )
    release_id = "model8_" + hashlib.sha256("|".join(sorted(all_hash_material)).encode("utf-8")).hexdigest()[:16]
    write_tsv(
        model8_dir / "a0_release_audit" / "model8_reference_manifest.freeze.tsv",
        release_rows,
        [
            "case_code",
            "species_id",
            "scientific_name",
            "strain_or_cultivar",
            "tax_id",
            "assembly_accession",
            "annotation_accession",
            "genome_release",
            "division",
            "DNA_path",
            "cDNA_path",
            "pep_path",
            "GFF3_path",
            "feature_bundle_path",
            "id_mapping_release",
            "go_release",
            "kegg_release",
            "sha256",
            "qc_status",
            "reference_identity_rule",
            "case_role",
        ],
    )
    # Keep the top-level required filename aligned with the optimized plan.
    shutil.copyfile(
        model8_dir / "a0_release_audit" / "model8_reference_manifest.freeze.tsv",
        model8_dir / "model8_reference_manifest.tsv",
    )
    coverage_rows = []
    for pipeline in sorted((project_root / "data").glob("*_real_pipeline")):
        reg = pipeline / "stage6_platform_registry"
        if not reg.exists():
            continue
        species_dirs = [p for p in reg.iterdir() if p.is_dir()]
        omics = Counter()
        cross = 0
        for sp in species_dirs:
            for layer in ["genome", "transcriptome", "proteome"]:
                if (sp / layer).exists():
                    omics[layer] += 1
            if (sp / "cross_omics.json").exists():
                cross += 1
        coverage_rows.append(
            {
                "pipeline": pipeline.name,
                "stage6_species_count": len(species_dirs),
                "genome_species": omics["genome"],
                "transcriptome_species": omics["transcriptome"],
                "proteome_species": omics["proteome"],
                "cross_omics_species": cross,
            }
        )
    write_tsv(
        model8_dir / "a0_release_audit" / "full_database_coverage_summary.tsv",
        coverage_rows,
        ["pipeline", "stage6_species_count", "genome_species", "transcriptome_species", "proteome_species", "cross_omics_species"],
    )
    write_tsv(
        model8_dir / "a0_release_audit" / "blocking_items.tsv",
        blockers,
        ["code", "step", "reason_code", "detail", "status"],
    )
    manifest = {
        "release_id": release_id,
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "project_root": str(project_root),
        "model8_dir": str(model8_dir),
        "code_commit": git_commit(project_root),
        "random_seed": SEED,
        "species_count": len(SPECIES_ORDER),
        "reference_manifest": "model8_reference_manifest.tsv",
        "status_manifest": "qc/model8_all_download_status.tsv",
        "a0_status": "passed" if not blockers else "blocked",
        "blocked_count": len(blockers),
        "policy": {
            "no_phylogeny": True,
            "fixed_species_design": True,
            "front_end_must_consume_artifacts": True,
            "forbidden_claims": [
                "八物种结果不得写成全库类群普遍规律",
                "不得因结果不显著替换物种或主终点",
                "不得把 candidate 命名为 causal/regulator/driver",
            ],
        },
        "dependencies": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }
    write_json(model8_dir / "model8_release_manifest.json", manifest)
    write_json(model8_dir / "a0_release_audit" / "model8_release_manifest.freeze.json", manifest)
    return release_id


def load_protein_index(path: Path | None) -> dict[str, dict[str, str]]:
    index = {}
    if not path:
        return index
    for header, seq in parse_fasta(path):
        pid = fasta_id(header)
        attrs = parse_header_kv(header)
        index[pid] = {
            "protein_id": pid,
            "protein_length": str(len(seq.replace("*", ""))),
            "gene_id": attrs.get("gene", ""),
            "transcript_id": attrs.get("transcript", ""),
            "header": header,
        }
    return index


def build_id_mapping_for_species(code: str, species_id: str, gff3: Path, protein_fasta: Path | None, out_dir: Path) -> dict[str, str]:
    protein_index = load_protein_index(protein_fasta)
    genes: dict[str, dict] = {}
    transcripts: dict[str, dict] = {}
    cds_by_parent: dict[str, list[dict]] = defaultdict(list)
    feature_counts = Counter()
    with open_text(gff3) as fh:
        for line in fh:
            if not line or line.startswith("#"):
                continue
            parts = line.rstrip("\n\r").split("\t")
            if len(parts) != 9:
                continue
            seqid, source, feature_type, start, end, score, strand, phase, attr_s = parts
            feature_counts[feature_type] += 1
            attrs = parse_attr(attr_s)
            fid = attrs.get("ID") or attrs.get("gene_id") or attrs.get("Name") or attrs.get("locus_tag")
            parent = attrs.get("Parent") or attrs.get("gene_id") or attrs.get("locus_tag")
            try:
                length = abs(int(end) - int(start)) + 1
            except ValueError:
                length = 0
            if feature_type.lower() == "gene" or feature_type in {"pseudogene"}:
                gid = fid or attrs.get("gene_id") or attrs.get("locus_tag")
                if gid:
                    genes[gid] = {
                        "gene_id": gid,
                        "seqid": seqid,
                        "start": start,
                        "end": end,
                        "strand": strand,
                        "gene_name": attrs.get("Name", attrs.get("gene_name", "")),
                        "biotype": attrs.get("biotype", attrs.get("gene_biotype", "")),
                    }
            elif feature_type.lower() in {"mrna", "transcript", "ncrna", "rrna", "trna"}:
                tid = fid
                gid = parent.split(",")[0] if parent else attrs.get("gene_id", "")
                if tid:
                    transcripts[tid] = {
                        "transcript_id": tid,
                        "gene_id": gid,
                        "transcript_length": str(length),
                        "biotype": attrs.get("biotype", attrs.get("transcript_biotype", "")),
                    }
            elif feature_type == "CDS":
                parents = [p for p in parent.split(",") if p] if parent else [fid] if fid else []
                protein_id = (
                    attrs.get("protein_id")
                    or attrs.get("proteinId")
                    or attrs.get("protein")
                    or attrs.get("Derives_from")
                    or attrs.get("Name")
                    or fid
                    or ""
                )
                for p in parents:
                    cds_by_parent[p].append(
                        {
                            "parent": p,
                            "cds_id": fid or "",
                            "protein_id": protein_id,
                            "length": length,
                            "phase": phase,
                            "seqid": seqid,
                            "start": start,
                            "end": end,
                            "strand": strand,
                        }
                    )
    rows = []
    conflicts = []
    # First pass: transcript-based chains.
    genes_seen = set()
    for tid, tx in transcripts.items():
        cds_list = cds_by_parent.get(tid, [])
        cds_len = sum(c["length"] for c in cds_list)
        protein_id = next((c["protein_id"] for c in cds_list if c.get("protein_id")), "")
        if not protein_id:
            for pid, rec in protein_index.items():
                if rec.get("transcript_id") == tid:
                    protein_id = pid
                    break
        gid = tx.get("gene_id", "")
        genes_seen.add(gid)
        plen = protein_index.get(protein_id, {}).get("protein_length", "")
        rows.append(
            {
                "code": code,
                "species_id": species_id,
                "mapping_type": "eukaryote_gene_transcript_cds_protein",
                "gene_id": gid,
                "transcript_id": tid,
                "cds_parent_id": tid,
                "protein_id": protein_id,
                "cds_length": str(cds_len),
                "protein_length": plen,
                "canonical_rank_key": f"{cds_len:012d}|{int(plen or 0):012d}|{tid}",
                "is_canonical": "false",
                "canonical_rule": "longest_cds_then_longest_protein_then_lexical",
                "mapping_status": "ok_high" if gid and tid and protein_id else "ok_medium",
                "reason_code": "" if gid and tid and protein_id else "incomplete_chain_fallback",
            }
        )
    # Bacterial or transcript-missing fallback: CDS parent/locus chains.
    if not rows or code in {"ECOLI", "BSUB"}:
        rows = []
        for parent, cds_list in cds_by_parent.items():
            cds_len = sum(c["length"] for c in cds_list)
            protein_id = next((c["protein_id"] for c in cds_list if c.get("protein_id")), "")
            gid = parent
            plen = protein_index.get(protein_id, {}).get("protein_length", "")
            rows.append(
                {
                    "code": code,
                    "species_id": species_id,
                    "mapping_type": "bacteria_locus_cds_protein" if code in {"ECOLI", "BSUB"} else "cds_parent_fallback",
                    "gene_id": gid,
                    "transcript_id": "",
                    "cds_parent_id": parent,
                    "protein_id": protein_id,
                    "cds_length": str(cds_len),
                    "protein_length": plen,
                    "canonical_rank_key": f"{cds_len:012d}|{int(plen or 0):012d}|{parent}",
                    "is_canonical": "true",
                    "canonical_rule": "single_locus_cds_or_longest_cds_fallback",
                    "mapping_status": "ok_high" if gid and protein_id else "ok_medium",
                    "reason_code": "" if gid and protein_id else "protein_id_missing_in_gff3",
                }
            )
    # Mark canonical rows for each gene.
    grouped = defaultdict(list)
    for i, row in enumerate(rows):
        grouped[row["gene_id"]].append((i, row))
    for gid, group in grouped.items():
        if not gid:
            for idx, row in group:
                row["mapping_status"] = "unmatched"
                row["reason_code"] = "missing_gene_id"
            continue
        best = sorted(group, key=lambda x: x[1]["canonical_rank_key"], reverse=True)[0]
        rows[best[0]]["is_canonical"] = "true"
        if len(group) > 1:
            top_key = best[1]["canonical_rank_key"]
            ties = [r for _, r in group if r["canonical_rank_key"] == top_key]
            if len(ties) > 1:
                conflicts.append(
                    {
                        "code": code,
                        "gene_id": gid,
                        "conflict_type": "canonical_tie",
                        "candidate_count": str(len(ties)),
                        "resolution": "lexical_order_after_length_tie",
                    }
                )
    fields = [
        "code",
        "species_id",
        "mapping_type",
        "gene_id",
        "transcript_id",
        "cds_parent_id",
        "protein_id",
        "cds_length",
        "protein_length",
        "canonical_rank_key",
        "is_canonical",
        "canonical_rule",
        "mapping_status",
        "reason_code",
    ]
    count = write_tsv_gz(out_dir / code / "mapping" / "id_chains.tsv.gz", rows, fields)
    write_tsv(
        out_dir / "a1_id_mapping" / f"{code}_mapping_conflicts.tsv",
        conflicts,
        ["code", "gene_id", "conflict_type", "candidate_count", "resolution"],
    )
    high = sum(1 for r in rows if r["mapping_status"] == "ok_high")
    canonical = sum(1 for r in rows if r["is_canonical"] == "true")
    return {
        "code": code,
        "species_id": species_id,
        "mapping_rows": str(count),
        "canonical_rows": str(canonical),
        "ok_high_rows": str(high),
        "ok_high_fraction": f"{(high / count) if count else 0:.6f}",
        "conflict_rows": str(len(conflicts)),
        "feature_counts": json.dumps(feature_counts, ensure_ascii=False, sort_keys=True),
        "qc_status": "passed" if count and (high / count) >= (0.85 if code in {"ECOLI", "BSUB"} else 0.70) else "warning",
    }


def a1_reference_id(model8_dir: Path, meta: dict[str, dict[str, str]], statuses: list[dict[str, str]]):
    asset_map = status_by_code_asset(statuses)
    summary = []
    for code in SPECIES_ORDER:
        m = meta[code]
        gff3 = asset_path(asset_map, code, GFF3_ASSET)
        pep = asset_path(asset_map, code, PROTEIN_ASSET)
        if not gff3:
            summary.append(
                {
                    "code": code,
                    "species_id": m.get("species_id", ""),
                    "mapping_rows": "0",
                    "canonical_rows": "0",
                    "ok_high_rows": "0",
                    "ok_high_fraction": "0",
                    "conflict_rows": "0",
                    "feature_counts": "{}",
                    "qc_status": "blocked",
                }
            )
            continue
        summary.append(build_id_mapping_for_species(code, m.get("species_id", ""), gff3, pep, model8_dir))
    write_tsv(
        model8_dir / "a1_id_mapping" / "id_mapping_summary.tsv",
        summary,
        [
            "code",
            "species_id",
            "mapping_rows",
            "canonical_rows",
            "ok_high_rows",
            "ok_high_fraction",
            "conflict_rows",
            "feature_counts",
            "qc_status",
        ],
    )


def make_feature_rows(code: str, layer: str, path: Path):
    if layer in {"genome", "transcript"}:
        for header, seq in parse_fasta(path):
            row = {
                "code": code,
                "layer": layer,
                "entity_id": fasta_id(header),
                "header": header,
            }
            row.update(sequence_stats(seq))
            yield row
    else:
        for header, seq in parse_fasta(path):
            attrs = parse_header_kv(header)
            row = {
                "code": code,
                "layer": layer,
                "entity_id": fasta_id(header),
                "gene_id": attrs.get("gene", ""),
                "transcript_id": attrs.get("transcript", ""),
                "header": header,
            }
            row.update(protein_stats(seq))
            yield row


def feature_file_audit(path: Path, fields: list[str]) -> dict[str, str]:
    seen = set()
    duplicates = 0
    lengths = []
    rows = 0
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            rows += 1
            eid = row.get("entity_id", "")
            if eid in seen:
                duplicates += 1
            seen.add(eid)
            try:
                lengths.append(float(row.get("length", "0") or 0))
            except ValueError:
                pass
    stats = summarize_numeric(lengths)
    return {
        "feature_rows": str(rows),
        "duplicate_entity_ids": str(duplicates),
        "length_min": stats["min"],
        "length_mean": stats["mean"],
        "length_max": stats["max"],
        "sha256": sha256_file(path),
        "qc_status": "passed" if rows and duplicates == 0 else "warning",
    }


def sample_gold_values(feature_path: Path, code: str, layer: str, k: int = 50):
    rng = random.Random(f"{SEED}:{code}:{layer}")
    sample = []
    with gzip.open(feature_path, "rt", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for n, row in enumerate(reader, 1):
            record = {
                "code": code,
                "layer": layer,
                "entity_id": row.get("entity_id", ""),
                "length": row.get("length", ""),
                "gc_fraction": row.get("gc_fraction", ""),
                "c_atoms_per_aa": row.get("c_atoms_per_aa", ""),
                "s_atoms_per_aa": row.get("s_atoms_per_aa", ""),
                "n_atoms_per_aa": row.get("n_atoms_per_aa", ""),
                "source_feature_file": str(feature_path),
                "seed": str(SEED),
            }
            if len(sample) < k:
                sample.append(record)
            else:
                j = rng.randrange(n)
                if j < k:
                    sample[j] = record
    return sample


def feature_table_has_contract(path: Path, fields: list[str]) -> bool:
    if not path.exists():
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            observed = set(next(csv.reader(handle, delimiter="\t"), []))
    except (OSError, EOFError, UnicodeDecodeError):
        return False
    return set(fields).issubset(observed)


def a2_feature_qc(
    model8_dir: Path,
    meta: dict[str, dict[str, str]],
    statuses: list[dict[str, str]],
    reuse_existing: bool = False,
):
    asset_map = status_by_code_asset(statuses)
    audit_rows = []
    gold_rows = []
    layer_specs = [
        ("genome", DNA_ASSET, ["code", "layer", "entity_id", "header", "length", "valid_bases", "gc_count", "gc_fraction", "n_count", "n_fraction", "entropy"]),
        ("protein", PROTEIN_ASSET, ["code", "layer", "entity_id", "gene_id", "transcript_id", "header", "length", "cys_count", "ser_count", "asn_count", "met_count", "c_atoms", "n_atoms", "s_atoms", "c_atoms_per_aa", "n_atoms_per_aa", "s_atoms_per_aa", "stop_count", "invalid_aa_count", "aa_entropy", "mw_approx", "elemental_contract_id"]),
    ]
    for code in SPECIES_ORDER:
        tx_asset = next((a for a in TRANSCRIPT_ASSETS if asset_path(asset_map, code, a)), "")
        specs = layer_specs.copy()
        if tx_asset:
            specs.insert(1, ("transcript", tx_asset, ["code", "layer", "entity_id", "header", "length", "valid_bases", "gc_count", "gc_fraction", "n_count", "n_fraction", "entropy"]))
        for layer, asset, fields in specs:
            src = asset_path(asset_map, code, asset)
            out = model8_dir / code / "features" / f"{layer}_features.tsv.gz"
            if not src:
                audit_rows.append(
                    {
                        "code": code,
                        "species_id": meta[code].get("species_id", ""),
                        "layer": layer,
                        "source_asset": asset,
                        "source_path": "",
                        "feature_path": str(out),
                        "feature_rows": "0",
                        "duplicate_entity_ids": "",
                        "length_min": "",
                        "length_mean": "",
                        "length_max": "",
                        "sha256": "",
                        "qc_status": "blocked",
                        "reason_code": "missing_source_asset",
                    }
                )
                continue
            if reuse_existing and feature_table_has_contract(out, fields):
                count = 1
            else:
                count = write_tsv_gz(out, make_feature_rows(code, layer, src), fields)
            audit = feature_file_audit(out, fields)
            audit_rows.append(
                {
                    "code": code,
                    "species_id": meta[code].get("species_id", ""),
                    "layer": layer,
                    "source_asset": asset,
                    "source_path": str(src),
                    "feature_path": str(out),
                    **audit,
                    "reason_code": "" if audit["qc_status"] == "passed" else "duplicate_or_empty_feature_table",
                }
            )
            if count:
                gold_rows.extend(sample_gold_values(out, code, layer, 50))
    write_tsv(
        model8_dir / "a2_feature_qc" / "feature_audit.tsv",
        audit_rows,
        [
            "code",
            "species_id",
            "layer",
            "source_asset",
            "source_path",
            "feature_path",
            "feature_rows",
            "duplicate_entity_ids",
            "length_min",
            "length_mean",
            "length_max",
            "sha256",
            "qc_status",
            "reason_code",
        ],
    )
    write_tsv(
        model8_dir / "a2_feature_qc" / "random_entity_gold_values.tsv",
        gold_rows,
        ["code", "layer", "entity_id", "length", "gc_fraction", "c_atoms_per_aa", "s_atoms_per_aa", "n_atoms_per_aa", "source_feature_file", "seed"],
    )


def parse_uniprot_go_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            yield row


def parse_kegg_link(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n\r").split("\t")
            if len(parts) >= 2:
                yield parts[0], parts[1]


def a3_annotation(model8_dir: Path, meta: dict[str, dict[str, str]], statuses: list[dict[str, str]]):
    asset_map = status_by_code_asset(statuses)
    coverage_rows = []
    function_rows = []
    background_rows = []
    for code in SPECIES_ORDER:
        go_path = asset_path(asset_map, code, "uniprot_taxon_go_annotations")
        if not go_path:
            go_path = model8_dir / "annotation" / "uniprot_go" / code / "uniprot_go_annotations.tsv.gz"
        uniprot_rows = 0
        go_annotated = 0
        unique_go = set()
        if go_path and go_path.exists():
            for row in parse_uniprot_go_rows(go_path):
                uniprot_rows += 1
                entry = row.get("Entry", "")
                gene_names = row.get("Gene Names", "")
                go_ids = [x.strip() for x in re.split(r"[;, ]+", row.get("Gene Ontology IDs", "")) if x.strip().startswith("GO:")]
                if go_ids:
                    go_annotated += 1
                for go_id in go_ids:
                    unique_go.add(go_id)
                    function_rows.append(
                        {
                            "code": code,
                            "species_id": meta[code].get("species_id", ""),
                            "source": "UniProt_GO",
                            "entity_id": entry,
                            "entity_namespace": "UniProtKB",
                            "gene_names": gene_names,
                            "term_type": "GO",
                            "term_id": go_id,
                            "term_label": "",
                            "evidence_or_release": meta[code].get("go_taxon_policy", ""),
                        }
                    )
        kegg_counts = {}
        kegg_assets = {
            "kegg_genes": "gene",
            "kegg_ko_links": "KO",
            "kegg_pathway_links": "pathway",
            "kegg_module_links": "module",
        }
        kegg_entities = set()
        for asset, term_type in kegg_assets.items():
            p = asset_path(asset_map, code, asset)
            count = 0
            if p and p.exists():
                if term_type == "gene":
                    with p.open("r", encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            parts = line.rstrip("\n\r").split("\t", 1)
                            if parts and parts[0]:
                                count += 1
                                kegg_entities.add(parts[0])
                                function_rows.append(
                                    {
                                        "code": code,
                                        "species_id": meta[code].get("species_id", ""),
                                        "source": "KEGG",
                                        "entity_id": parts[0],
                                        "entity_namespace": "KEGG_gene",
                                        "gene_names": "",
                                        "term_type": "KEGG_gene_description",
                                        "term_id": parts[0],
                                        "term_label": parts[1] if len(parts) > 1 else "",
                                        "evidence_or_release": meta[code].get("kegg_org", ""),
                                    }
                                )
                else:
                    for entity, term in parse_kegg_link(p):
                        count += 1
                        kegg_entities.add(entity)
                        function_rows.append(
                            {
                                "code": code,
                                "species_id": meta[code].get("species_id", ""),
                                "source": "KEGG",
                                "entity_id": entity,
                                "entity_namespace": "KEGG_gene",
                                "gene_names": "",
                                "term_type": term_type,
                                "term_id": term,
                                "term_label": "",
                                "evidence_or_release": meta[code].get("kegg_org", ""),
                            }
                        )
            kegg_counts[asset] = count
        protein_feature = model8_dir / code / "features" / "protein_features.tsv.gz"
        protein_count = 0
        if protein_feature.exists():
            with gzip.open(protein_feature, "rt", encoding="utf-8", errors="replace") as fh:
                protein_count = max(0, sum(1 for _ in fh) - 1)
        coverage_rows.append(
            {
                "code": code,
                "species_id": meta[code].get("species_id", ""),
                "uniprot_rows": str(uniprot_rows),
                "uniprot_go_annotated_rows": str(go_annotated),
                "unique_go_terms": str(len(unique_go)),
                "kegg_gene_rows": str(kegg_counts.get("kegg_genes", 0)),
                "kegg_ko_link_rows": str(kegg_counts.get("kegg_ko_links", 0)),
                "kegg_pathway_link_rows": str(kegg_counts.get("kegg_pathway_links", 0)),
                "kegg_module_link_rows": str(kegg_counts.get("kegg_module_links", 0)),
                "qc_status": "passed" if (uniprot_rows and sum(kegg_counts.values()) > 0) else "unavailable",
                "reason_code": "" if (uniprot_rows and sum(kegg_counts.values()) > 0) else "annotation_source_missing_or_empty",
            }
        )
        background_rows.append(
            {
                "code": code,
                "species_id": meta[code].get("species_id", ""),
                "background_set_id": f"model8_{code}_protein_feature_background",
                "entity_namespace": "protein_feature_entity",
                "entity_count": str(protein_count),
                "go_annotated_uniprot_rows": str(go_annotated),
                "kegg_annotated_entities": str(len(kegg_entities)),
                "rule": "Use only entities that pass the case-specific expression/feature mapping filters; this file records the full protein-feature starting universe.",
            }
        )
    write_tsv(
        model8_dir / "a3_annotation" / "annotation_coverage.tsv",
        coverage_rows,
        [
            "code",
            "species_id",
            "uniprot_rows",
            "uniprot_go_annotated_rows",
            "unique_go_terms",
            "kegg_gene_rows",
            "kegg_ko_link_rows",
            "kegg_pathway_link_rows",
            "kegg_module_link_rows",
            "qc_status",
            "reason_code",
        ],
    )
    write_tsv_gz(
        model8_dir / "a3_annotation" / "entity_function_rows.tsv.gz",
        function_rows,
        [
            "code",
            "species_id",
            "source",
            "entity_id",
            "entity_namespace",
            "gene_names",
            "term_type",
            "term_id",
            "term_label",
            "evidence_or_release",
        ],
    )
    write_tsv(
        model8_dir / "a3_annotation" / "background_sets.tsv",
        background_rows,
        [
            "code",
            "species_id",
            "background_set_id",
            "entity_namespace",
            "entity_count",
            "go_annotated_uniprot_rows",
            "kegg_annotated_entities",
            "rule",
        ],
    )


def final_gate(model8_dir: Path, release_id: str) -> None:
    checks = []
    for rel in [
        ("A0", model8_dir / "a0_release_audit" / "blocking_items.tsv"),
        ("A1", model8_dir / "a1_id_mapping" / "id_mapping_summary.tsv"),
        ("A2", model8_dir / "a2_feature_qc" / "feature_audit.tsv"),
        ("A3", model8_dir / "a3_annotation" / "annotation_coverage.tsv"),
    ]:
        checks.append({"step": rel[0], "path": str(rel[1]), "exists": rel[1].exists()})
    elemental_validation = validate_model8_protein_feature_files(model8_dir)
    write_json(model8_dir / "qc" / "elemental_semantics_validation.json", elemental_validation)
    checks.append({
        "step": "ELEMENTAL_SEMANTICS",
        "path": str(model8_dir / "qc" / "elemental_semantics_validation.json"),
        "exists": elemental_validation["status"] == "passed",
    })
    status = {
        "release_id": release_id,
        "schema_version": SCHEMA_VERSION,
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
        "completed_at": now_iso(),
        "random_seed": SEED,
        "checks": checks,
        "status": "passed" if all(c["exists"] for c in checks) else "blocked",
    }
    write_json(model8_dir / "qc" / "a0_a3_final_gate.json", status)
    if status["status"] != "passed":
        raise RuntimeError("Model-8 A0-A3 final gate blocked: elemental semantics validation failed")
    write_json(
        model8_dir / "qc" / "environment_lock.json",
        {
            "generated_at": now_iso(),
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sys.executable,
            "cwd": os.getcwd(),
            "schema_version": SCHEMA_VERSION,
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", required=True)
    ap.add_argument(
        "--resume-a2",
        action="store_true",
        help="Reuse complete feature tables whose headers already satisfy the current schema contract.",
    )
    args = ap.parse_args()
    project_root = Path(args.project_root)
    model8_dir = project_root / "data" / "case_studies" / "model8"
    meta = load_model8_metadata(model8_dir)
    statuses = load_statuses(model8_dir)
    run_log = {
        "started_at": now_iso(),
        "project_root": str(project_root),
        "model8_dir": str(model8_dir),
        "schema_version": SCHEMA_VERSION,
        "seed": SEED,
        "steps": [],
    }
    ensure_dir(model8_dir / "logs")
    t0 = time.time()
    release_id = a0_release_audit(project_root, model8_dir, meta, statuses)
    run_log["steps"].append({"step": "A0 Release Auditor", "seconds": round(time.time() - t0, 3)})
    t0 = time.time()
    a1_reference_id(model8_dir, meta, statuses)
    run_log["steps"].append({"step": "A1 Reference/ID Agent", "seconds": round(time.time() - t0, 3)})
    t0 = time.time()
    a2_feature_qc(model8_dir, meta, statuses, reuse_existing=args.resume_a2)
    run_log["steps"].append({"step": "A2 Feature/QC Agent", "seconds": round(time.time() - t0, 3)})
    t0 = time.time()
    a3_annotation(model8_dir, meta, statuses)
    run_log["steps"].append({"step": "A3 Annotation Agent", "seconds": round(time.time() - t0, 3)})
    final_gate(model8_dir, release_id)
    run_log["completed_at"] = now_iso()
    run_log["release_id"] = release_id
    write_json(model8_dir / "logs" / "a0_a3_run_log.json", run_log)
    print(json.dumps({"release_id": release_id, "status": "completed", "model8_dir": str(model8_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
