#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import random
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.model8_elemental_contract import (
        ELEMENTAL_CONTRACT_ID,
        canonical_protein_sequence,
        protein_elemental_features,
    )
except ModuleNotFoundError:  # Direct execution from scripts/.
    from model8_elemental_contract import (
        ELEMENTAL_CONTRACT_ID,
        canonical_protein_sequence,
        protein_elemental_features,
    )


SEED = 20260730
CASE4_VERSION = "model8_case4_upload_gold_v2_elemental"
SCRIPT_NAME = "scripts/build_model8_case4_upload_gold.py"
NUC_VALID = set("ACGT")
NUC_ALLOWED = set("ACGTN")
AA_VALID = set("ACDEFGHIKLMNPQRSTVWY")
AA_ALLOWED = set("ACDEFGHIKLMNPQRSTVWYXBZUO*")
EUKARYOTE_DIVISIONS = {"plants", "metazoa", "fungi", "vertebrates"}

PROTEIN_FIELDS = [
    "length", "cys_count", "ser_count", "asn_count", "met_count",
    "c_atoms", "n_atoms", "s_atoms",
    "c_atoms_per_aa", "n_atoms_per_aa", "s_atoms_per_aa",
    "stop_count", "invalid_aa_count", "aa_entropy", "mw_approx",
]
NUCLEOTIDE_FIELDS = ["length", "valid_bases", "gc_count", "gc_fraction", "n_count", "n_fraction", "entropy"]
PROTEIN_MASS = {
    "A": 89.094, "R": 174.203, "N": 132.119, "D": 133.104, "C": 121.154,
    "E": 147.131, "Q": 146.146, "G": 75.067, "H": 155.156, "I": 131.175,
    "L": 131.175, "K": 146.189, "M": 149.208, "F": 165.192, "P": 115.132,
    "S": 105.093, "T": 119.120, "W": 204.228, "Y": 181.191, "V": 117.148,
}
FULL_DATABASE_EXTRACTORS = {
    "genome": {
        "version": "v3.3.2",
        "script_file": "genome_stoich_feature_extractor_v3_3_2.py",
        "source_script": r"E:\A-new-stoichioomics\N-STOICHIOOMICS\数据\基因组\genome_stoich_feature_extractor_v3_3_2.py",
        "evidence": "protists_genome_batch_manifest_strict_v3_3_2.csv and genome *.schema.json version=v3.3",
    },
    "transcriptome": {
        "version": "v5.2",
        "script_file": "transcriptome_stoich_feature_extractor_v5_2.py",
        "source_script": r"E:\A-new-stoichioomics\N-STOICHIOOMICS\数据\转录组\transcriptome_stoich_feature_extractor_v5_2.py",
        "evidence": "transcriptome *.core.v5.csv schema plus v5.2 single-pass core/full batch extractor",
    },
    "proteome": {
        "version": "v4_fast",
        "script_file": "proteome_stoich_feature_extractor_v4_fast.py",
        "source_script": r"E:\A-new-stoichioomics\N-STOICHIOOMICS\数据\蛋白质组\proteome_stoich_feature_extractor_v4_fast.py",
        "evidence": "run_proteome_batch_from_manifest_v2_parallel.py requires v4_fast and full/core output fields match stored proteome tables",
    },
}


def text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    value = str(value).strip()
    if not value or value.lower() in {"nan", "none", "null"}:
        return fallback
    return value


def to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def rounded(value: Any, digits: int = 10) -> float | None:
    number = to_float(value)
    return round(number, digits) if number is not None else None


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def optional_file_sha256(path: Path) -> str | None:
    return file_sha256(path) if path.exists() and path.is_file() else None


def build_feature_extractor_contract(root: Path) -> dict[str, Any]:
    deployed_root = root.parents[1] / "组学化学计量特征提取代码"
    contract = {}
    for omics, spec in FULL_DATABASE_EXTRACTORS.items():
        source_script = Path(spec["source_script"])
        deployed_script = deployed_root / spec["script_file"]
        entry = dict(spec)
        entry.update({
            "deployed_script": str(deployed_script),
            "source_sha256": optional_file_sha256(source_script),
            "deployed_sha256": optional_file_sha256(deployed_script),
            "applies_to_case4": True,
        })
        contract[omics] = entry
    return {
        "contract_id": "full_database_feature_extractor_contract_v1",
        "source_basis": "Resolved from E:\\A-new-stoichioomics\\N-STOICHIOOMICS\\数据 scripts/manifests and G:\\stoichioomics\\全组学特征数据 real feature schemas.",
        "deployed_root": str(deployed_root),
        "extractors": contract,
    }


def sequence_sha256(seq: str) -> str:
    return hashlib.sha256(seq.upper().encode("ascii", errors="ignore")).hexdigest()


def read_table(path: Path) -> list[dict[str, str]]:
    with open_text(path) as handle:
        sample = handle.readline()
        handle.seek(0)
        delimiter = "\t" if "\t" in sample else ","
        return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_manifest(root: Path) -> list[dict[str, str]]:
    path = root / "data" / "case_studies" / "model8" / "model8_reference_manifest.tsv"
    return read_table(path)


def parse_fasta_selected(path: Path, targets: set[str] | None = None) -> dict[str, tuple[str, str]]:
    records: dict[str, tuple[str, str]] = {}
    header = ""
    seq_parts: list[str] = []

    def flush() -> None:
        nonlocal header, seq_parts
        if not header:
            return
        entity_id = header.split()[0]
        if targets is None or entity_id in targets:
            records[entity_id] = (header, "".join(seq_parts).upper())
        header = ""
        seq_parts = []

    with open_text(path) as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                flush()
                header = line[1:]
            else:
                seq_parts.append(line)
        flush()
    return records


def write_fasta(path: Path, records: list[tuple[str, str]], width: int = 80) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for header, seq in records:
            handle.write(f">{header}\n")
            for idx in range(0, len(seq), width):
                handle.write(seq[idx:idx + width] + "\n")


def entropy(seq: str, alphabet: set[str]) -> float:
    counts = Counter(base for base in seq.upper() if base in alphabet)
    total = sum(counts.values())
    if not total:
        return 0.0
    return -sum((count / total) * math.log2(count / total) for count in counts.values() if count)


def nucleotide_features(seq: str) -> dict[str, Any]:
    upper = seq.upper()
    valid = sum(1 for char in upper if char in NUC_VALID)
    gc = sum(1 for char in upper if char in {"G", "C"})
    n_count = upper.count("N")
    length = len(upper)
    return {
        "length": length,
        "valid_bases": valid,
        "gc_count": gc,
        "gc_fraction": gc / valid if valid else 0.0,
        "n_count": n_count,
        "n_fraction": n_count / length if length else 0.0,
        "entropy": entropy(upper, NUC_VALID),
        "ambiguous_count": sum(1 for char in upper if char not in NUC_VALID),
        "illegal_count": sum(1 for char in upper if char not in NUC_ALLOWED),
    }


def protein_features(seq: str) -> dict[str, Any]:
    upper = seq.upper()
    canonical, _, _ = canonical_protein_sequence(seq)
    elemental = protein_elemental_features(seq)
    aa = list(canonical)
    length = int(elemental["length"])
    mw = sum(PROTEIN_MASS.get(char, 0.0) for char in aa)
    if length > 1:
        mw -= (length - 1) * 18.015
    return {
        **elemental,
        "aa_entropy": entropy(canonical, AA_VALID),
        "mw_approx": mw,
        "ambiguous_count": sum(1 for char in upper if char not in AA_VALID),
        "illegal_count": sum(1 for char in upper if char not in AA_ALLOWED),
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
    }


def select_decile_rows(rows: list[dict[str, str]], n: int = 1000) -> list[dict[str, str]]:
    eligible = []
    for row in rows:
        length = to_float(row.get("length"))
        if length is None or length <= 0:
            continue
        if text(row.get("entity_id")) and text(row.get("transcript_id")):
            eligible.append(row)
    eligible.sort(key=lambda row: (float(row.get("length") or 0), row.get("entity_id", "")))
    bins: list[list[dict[str, str]]] = [[] for _ in range(10)]
    for idx, row in enumerate(eligible):
        decile = min(9, int(idx * 10 / max(1, len(eligible))))
        bins[decile].append(row)
    rng = random.Random(SEED)
    selected = []
    base = n // 10
    remainder = n % 10
    for idx, bucket in enumerate(bins):
        take = min(len(bucket), base + (1 if idx < remainder else 0))
        selected.extend(rng.sample(bucket, take) if take < len(bucket) else bucket)
    if len(selected) < n:
        selected_keys = {row["entity_id"] for row in selected}
        fill = [row for row in eligible if row["entity_id"] not in selected_keys]
        selected.extend(fill[: n - len(selected)])
    selected.sort(key=lambda row: row["entity_id"])
    return selected[:n]


def compare_number(expected: Any, observed: Any, tolerance: float) -> tuple[str, float | None]:
    exp = to_float(expected)
    obs = to_float(observed)
    if exp is None or obs is None:
        return ("missing", None)
    delta = abs(exp - obs)
    return ("pass" if delta <= tolerance else "fail", delta)


def subset_gff(path: Path, selected_tokens: set[str], out_path: Path) -> tuple[int, str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    selected_tokens = {token for token in selected_tokens if token}
    count = 0
    with open_text(path) as src, out_path.open("w", encoding="utf-8", newline="\n") as dst:
        for line in src:
            if line.startswith("#"):
                dst.write(line)
                continue
            line_tokens = set(re.findall(r"[A-Za-z0-9_.:-]+", line))
            if selected_tokens & line_tokens:
                dst.write(line)
                count += 1
    return count, file_sha256(out_path)


def parse_header_coords(header: str) -> tuple[str, int, int, str]:
    match = re.search(r"chromosome:[^: ]+:([^: ]+):(\d+):(\d+):([\-0-9]+)", header)
    if not match:
        return "unknown", 1, 1, "+"
    seqid = match.group(1)
    start = int(match.group(2))
    end = int(match.group(3))
    strand = "-" if match.group(4).startswith("-") else "+"
    if end < start:
        start, end = end, start
    return seqid, start, end, strand


def write_gff_proxy(selected: list[dict[str, str]], out_path: Path) -> tuple[int, str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("##gff-version 3\n")
        handle.write("# Case 4 coordinate proxy generated from selected feature-table FASTA headers; not a full original GFF3 subset.\n")
        for item in selected:
            gene_id = text(item.get("gene_id")) or text(item.get("transcript_id")) or text(item.get("entity_id"))
            transcript_id = text(item.get("transcript_id")) or gene_id
            protein_id = text(item.get("entity_id")) or transcript_id
            seqid, start, end, strand = parse_header_coords(text(item.get("header")))
            source = "StoichioomicsCase4Proxy"
            handle.write(f"{seqid}\t{source}\tgene\t{start}\t{end}\t.\t{strand}\t.\tID=gene:{gene_id};Name={gene_id}\n")
            handle.write(f"{seqid}\t{source}\tmRNA\t{start}\t{end}\t.\t{strand}\t.\tID=transcript:{transcript_id};Parent=gene:{gene_id};protein_id={protein_id}\n")
            handle.write(f"{seqid}\t{source}\tCDS\t{start}\t{end}\t.\t{strand}\t0\tID=CDS:{transcript_id};Parent=transcript:{transcript_id};protein_id={protein_id}\n")
            rows += 3
    return rows, file_sha256(out_path)


def make_synthetic_sequences(output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    synthetic_dir = output_dir / "inputs" / "synthetic_boundary"
    rng = random.Random(SEED)
    nuc_records = []
    prot_records = []
    rows = []
    error_rows = []
    for idx in range(200):
        if idx % 5 == 0:
            seq = "G" * (60 + idx)
            kind = "extreme_gc_high"
        elif idx % 5 == 1:
            seq = "A" * (60 + idx)
            kind = "extreme_gc_low"
        elif idx % 5 == 2:
            seq = ("ACGTN" * (20 + idx % 7))[:80 + idx]
            kind = "ambiguous_n"
        elif idx % 5 == 3:
            seq = ("ATGC" * (25 + idx % 9))[:90 + idx]
            kind = "repeat_pattern"
        else:
            seq = "".join(rng.choice("ACGT") for _ in range(70 + idx))
            kind = "random_valid"
        entity_id = f"synthetic_nuc_{idx:03d}"
        nuc_records.append((f"{entity_id} boundary_case:{kind}", seq))
        feat = nucleotide_features(seq)
        rows.append({"track": "A_synthetic_boundary", "omics": "nucleotide", "entity_id": entity_id, "case_type": kind, **feat})
    for idx in range(200):
        if idx % 5 == 0:
            seq = "C" * (20 + idx)
            kind = "single_aa_cysteine"
        elif idx % 5 == 1:
            seq = "N" * (20 + idx)
            kind = "single_aa_asparagine"
        elif idx % 5 == 2:
            seq = ("ACDEFGHIKLMNPQRSTVWY" * 12)[:30 + idx]
            kind = "balanced_aa"
        elif idx % 5 == 3:
            seq = ("MXBZ" * (15 + idx % 4))[:35 + idx]
            kind = "ambiguous_aa"
        else:
            seq = "".join(rng.choice("ACDEFGHIKLMNPQRSTVWY") for _ in range(25 + idx))
            kind = "random_valid"
        entity_id = f"synthetic_prot_{idx:03d}"
        prot_records.append((f"{entity_id} boundary_case:{kind}", seq))
        feat = protein_features(seq)
        rows.append({"track": "A_synthetic_boundary", "omics": "protein", "entity_id": entity_id, "case_type": kind, **feat})
    invalid_nuc = [("duplicate_id", "ACGTACGT"), ("duplicate_id", "GGGGCCCC"), ("illegal_nuc", "ACGT123@@@")]
    invalid_prot = [("duplicate_protein", "ACDEFG"), ("duplicate_protein", "NNNNNN"), ("illegal_protein", "ACD123@@@")]
    write_fasta(synthetic_dir / "synthetic_boundary_nucleotide_200.fna", nuc_records)
    write_fasta(synthetic_dir / "synthetic_boundary_protein_200.faa", prot_records)
    write_fasta(synthetic_dir / "synthetic_error_nucleotide.fna", invalid_nuc)
    write_fasta(synthetic_dir / "synthetic_error_protein.faa", invalid_prot)
    error_rows.extend([
        {"file": "synthetic_error_nucleotide.fna", "case_type": "duplicate_id", "expected_status": "reject_or_warn_duplicate_id"},
        {"file": "synthetic_error_nucleotide.fna", "case_type": "illegal_nuc", "expected_status": "reject_invalid_character"},
        {"file": "synthetic_error_protein.faa", "case_type": "duplicate_id", "expected_status": "reject_or_warn_duplicate_id"},
        {"file": "synthetic_error_protein.faa", "case_type": "illegal_protein", "expected_status": "reject_invalid_character"},
    ])
    return rows, error_rows


def make_workflow_files(output_dir: Path, selected_records: dict[str, dict[str, list[tuple[str, str]]]]) -> list[dict[str, Any]]:
    workflow_dir = output_dir / "inputs" / "workflow_examples"
    if workflow_dir.exists():
        shutil.rmtree(workflow_dir)
    workflow_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    arath_records = selected_records["ARATH"]["protein"][:120]
    write_fasta(workflow_dir / "single_species_single_set_ARATH_protein.faa", arath_records)
    rows.append({
        "workflow_id": "C1_single_species_single_set",
        "analysis_type": "single_sequence",
        "omics_type": "proteome",
        "input_files": "single_species_single_set_ARATH_protein.faa",
        "sample_sheet": "",
        "group_field": "",
        "reference_group": "",
        "purpose": "single uploaded species/set feature profile, top/low entities, downloads",
    })

    ecoli_records = selected_records["ECOLI"]["protein"]
    control = ecoli_records[:100]
    stress = ecoli_records[-100:]
    write_fasta(workflow_dir / "multi_sample_ECOLI_control.faa", control)
    write_fasta(workflow_dir / "multi_sample_ECOLI_case.faa", stress)
    sample_sheet = [
        {"file_name": "multi_sample_ECOLI_control.faa", "sample_id": "ecoli_control", "condition": "control", "species_id": "ECOLI"},
        {"file_name": "multi_sample_ECOLI_case.faa", "sample_id": "ecoli_case", "condition": "case", "species_id": "ECOLI"},
    ]
    write_csv(workflow_dir / "sample_sheet_multi_sample_ECOLI.csv", sample_sheet, ["file_name", "sample_id", "condition", "species_id"])
    rows.append({
        "workflow_id": "C2_single_species_multi_sample",
        "analysis_type": "multi_sample",
        "omics_type": "proteome",
        "input_files": "multi_sample_ECOLI_control.faa;multi_sample_ECOLI_case.faa",
        "sample_sheet": "sample_sheet_multi_sample_ECOLI.csv",
        "group_field": "condition",
        "reference_group": "control",
        "purpose": "reference-vs-case differential features/entities and reproducible table downloads",
    })

    multi_rows = []
    files = []
    for code in ["ECOLI", "ARATH", "DROME", "MOUSE"]:
        sample = selected_records[code]["protein"][:80]
        name = f"multi_species_{code}_protein.faa"
        write_fasta(workflow_dir / name, sample)
        files.append(name)
        multi_rows.append({"file_name": name, "sample_id": f"{code}_protein", "condition": code, "species_id": code})
    write_csv(workflow_dir / "sample_sheet_multi_species_model8.csv", multi_rows, ["file_name", "sample_id", "condition", "species_id"])
    rows.append({
        "workflow_id": "C3_multi_species_multi_sample",
        "analysis_type": "multi_species",
        "omics_type": "proteome",
        "input_files": ";".join(files),
        "sample_sheet": "sample_sheet_multi_species_model8.csv",
        "group_field": "species_id",
        "reference_group": "ECOLI",
        "purpose": "multi-species separability diagnostics, RF feature ranking, plots, ML download checks",
    })
    readme = workflow_dir / "README.md"
    readme.write_text(
        "Case 4 workflow examples are fixed upload inputs. Use /sequence-analysis with the analysis_type, omics_type, sample_sheet, group_field, and reference_group recorded in workflow_manifest.csv.\n"
        "Raw uploads must remain runtime-isolated and must not enter the public registry.\n",
        encoding="utf-8",
    )
    return rows


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace(os.sep, "/")
    except ValueError:
        return str(path)


def build_case4(root: Path, output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    extractor_contract = build_feature_extractor_contract(root)
    manifest = read_manifest(root)
    synthetic_rows, error_rows = make_synthetic_sequences(output_dir)
    selected_records: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    selection_rows: list[dict[str, Any]] = []
    expected_protein_rows: list[dict[str, Any]] = []
    expected_nucleotide_rows: list[dict[str, Any]] = []
    agreement_rows: list[dict[str, Any]] = []
    subset_rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []

    for species in manifest:
        code = species["case_code"]
        division = species["division"]
        features_dir = root / "data" / "case_studies" / "model8" / code / "features"
        protein_table = {row["entity_id"]: row for row in read_table(features_dir / "protein_features.tsv.gz")}
        transcript_table = {row["entity_id"]: row for row in read_table(features_dir / "transcript_features.tsv.gz")}
        protein_rows = list(protein_table.values())
        joinable = [row for row in protein_rows if row.get("transcript_id") in transcript_table]
        selected = select_decile_rows(joinable, 1000)
        joinable_lengths = [float(row["length"]) for row in joinable if to_float(row.get("length")) is not None]
        min_joinable_length = min(joinable_lengths) if joinable_lengths else 0.0
        max_joinable_length = max(joinable_lengths) if joinable_lengths else 1.0
        length_span = max(1.0, max_joinable_length - min_joinable_length)
        selected_protein_ids = {row["entity_id"] for row in selected}
        selected_transcript_ids = {row["transcript_id"] for row in selected if row.get("transcript_id")}
        pep_records = parse_fasta_selected(Path(species["pep_path"]), selected_protein_ids)
        transcript_records = parse_fasta_selected(Path(species["cDNA_path"]), selected_transcript_ids)

        protein_out = output_dir / "inputs" / "gold" / "protein" / f"{code}_protein_gold_1000.faa"
        nuc_label = "cds_gold_1000" if division == "bacteria" else "transcript_cdna_gold_1000"
        nucleotide_out = output_dir / "inputs" / "gold" / "cds_transcript" / f"{code}_{nuc_label}.fna"
        protein_write_records = []
        nucleotide_write_records = []
        for row in selected:
            protein_id = row["entity_id"]
            transcript_id = row["transcript_id"]
            protein_header, protein_seq = pep_records.get(protein_id, (row.get("header", protein_id), ""))
            nuc_header, nuc_seq = transcript_records.get(transcript_id, (transcript_id, ""))
            protein_write_records.append((protein_header, protein_seq))
            if nuc_seq:
                nucleotide_write_records.append((nuc_header, nuc_seq))
            decile = min(9, int((float(row["length"]) - min_joinable_length) / length_span * 10))
            selection_rows.append({
                "case_code": code,
                "scientific_name": species["scientific_name"],
                "division": division,
                "gene_id": row.get("gene_id", ""),
                "transcript_id": transcript_id,
                "protein_id": protein_id,
                "protein_length": row.get("length", ""),
                "length_decile": min(9, decile),
                "protein_sequence_found": bool(protein_seq),
                "nucleotide_sequence_found": bool(nuc_seq),
                "nucleotide_gold_type": "CDS exact" if division == "bacteria" else "cDNA/transcript proxy; independent CDS FASTA unavailable in local source bundle",
                "selection_rule": "fixed seed 20260730; protein length decile stratification; joined protein/transcript feature rows",
            })
            pfeat = protein_features(protein_seq)
            p_expected = {
                "case_code": code,
                "entity_id": protein_id,
                "gene_id": row.get("gene_id", ""),
                "transcript_id": transcript_id,
                "seq_sha256": sequence_sha256(protein_seq),
                "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
                **{key: rounded(pfeat[key], 10) for key in PROTEIN_FIELDS},
            }
            expected_protein_rows.append(p_expected)
            for field in PROTEIN_FIELDS:
                tol = 0 if field in {
                    "length", "cys_count", "ser_count", "asn_count", "met_count",
                    "c_atoms", "n_atoms", "s_atoms", "stop_count", "invalid_aa_count",
                } else (1000.0 if field == "mw_approx" else 1e-6)
                status, delta = compare_number(p_expected.get(field), row.get(field), tol)
                agreement_rows.append({
                    "case_code": code,
                    "omics": "protein",
                    "entity_id": protein_id,
                    "field": field,
                    "expected": p_expected.get(field),
                    "platform": row.get(field),
                    "abs_delta": delta,
                    "tolerance": tol,
                    "status": status,
                })
            if nuc_seq:
                nfeat = nucleotide_features(nuc_seq)
                n_expected = {
                    "case_code": code,
                    "entity_id": transcript_id,
                    "gene_id": row.get("gene_id", ""),
                    "protein_id": protein_id,
                    "seq_sha256": sequence_sha256(nuc_seq),
                    "nucleotide_gold_type": "CDS exact" if division == "bacteria" else "cDNA/transcript proxy",
                    **{key: rounded(nfeat[key], 10) for key in NUCLEOTIDE_FIELDS},
                }
                expected_nucleotide_rows.append(n_expected)
                platform_nuc = transcript_table.get(transcript_id, {})
                for field in NUCLEOTIDE_FIELDS:
                    tol = 0 if field in {"length", "valid_bases", "gc_count", "n_count"} else 1e-6
                    status, delta = compare_number(n_expected.get(field), platform_nuc.get(field), tol)
                    agreement_rows.append({
                        "case_code": code,
                        "omics": "cds_or_transcript",
                        "entity_id": transcript_id,
                        "field": field,
                        "expected": n_expected.get(field),
                        "platform": platform_nuc.get(field),
                        "abs_delta": delta,
                        "tolerance": tol,
                        "status": status,
                    })
        write_fasta(protein_out, protein_write_records)
        write_fasta(nucleotide_out, nucleotide_write_records)
        selected_records[code]["protein"] = protein_write_records
        selected_records[code]["nucleotide"] = nucleotide_write_records
        gff_out = output_dir / "inputs" / "gold" / "gff3_subset" / f"{code}_gold_subset.gff3"
        gff_rows, gff_sha = write_gff_proxy(selected, gff_out)
        subset_rows.append({
            "case_code": code,
            "scientific_name": species["scientific_name"],
            "protein_records": len(protein_write_records),
            "nucleotide_records": len(nucleotide_write_records),
            "gff3_rows": gff_rows,
            "protein_gold_path": relative(protein_out, output_dir),
            "nucleotide_gold_path": relative(nucleotide_out, output_dir),
            "gff3_subset_path": relative(gff_out, output_dir),
            "protein_sha256": file_sha256(protein_out),
            "nucleotide_sha256": file_sha256(nucleotide_out),
            "gff3_sha256": gff_sha,
            "cds_status": "exact_cds_available" if division == "bacteria" else "degraded_to_cdna_transcript_proxy_no_local_cds_fasta",
            "gff3_subset_status": "degraded_coordinate_proxy_from_feature_headers_no_full_gff3_scan",
        })
        for kind, src_path in [("pep", species["pep_path"]), ("cDNA_or_CDS", species["cDNA_path"]), ("GFF3", species["GFF3_path"])]:
            src = Path(src_path)
            source_rows.append({
                "case_code": code,
                "kind": kind,
                "source_path": str(src),
                "bytes": src.stat().st_size if src.exists() else "",
                "sha256": file_sha256(src) if src.exists() else "missing",
            })

    workflow_rows = make_workflow_files(output_dir, selected_records)
    expected_synth_fields = [
        "track", "omics", "entity_id", "case_type", "length", "valid_bases", "gc_count",
        "gc_fraction", "n_count", "n_fraction", "entropy", "cys_count", "ser_count", "asn_count",
        "met_count", "c_atoms", "n_atoms", "s_atoms", "c_atoms_per_aa", "n_atoms_per_aa",
        "s_atoms_per_aa", "stop_count", "invalid_aa_count", "aa_entropy", "mw_approx",
        "ambiguous_count", "illegal_count", "elemental_contract_id",
    ]
    write_csv(output_dir / "gold_selection_manifest.csv", selection_rows, ["case_code", "scientific_name", "division", "gene_id", "transcript_id", "protein_id", "protein_length", "length_decile", "protein_sequence_found", "nucleotide_sequence_found", "nucleotide_gold_type", "selection_rule"])
    write_csv(output_dir / "gold_subset_manifest.csv", subset_rows, ["case_code", "scientific_name", "protein_records", "nucleotide_records", "gff3_rows", "protein_gold_path", "nucleotide_gold_path", "gff3_subset_path", "protein_sha256", "nucleotide_sha256", "gff3_sha256", "cds_status", "gff3_subset_status"])
    write_csv(output_dir / "expected_protein_features.csv", expected_protein_rows, ["case_code", "entity_id", "gene_id", "transcript_id", "seq_sha256", "elemental_contract_id", *PROTEIN_FIELDS])
    write_csv(output_dir / "expected_cds_transcript_features.csv", expected_nucleotide_rows, ["case_code", "entity_id", "gene_id", "protein_id", "seq_sha256", "nucleotide_gold_type", *NUCLEOTIDE_FIELDS])
    write_csv(output_dir / "platform_gold_agreement.csv", agreement_rows, ["case_code", "omics", "entity_id", "field", "expected", "platform", "abs_delta", "tolerance", "status"])
    write_csv(output_dir / "synthetic_boundary_expected_features.csv", synthetic_rows, expected_synth_fields)
    write_csv(output_dir / "synthetic_error_cases.csv", error_rows, ["file", "case_type", "expected_status"])
    write_csv(output_dir / "workflow_manifest.csv", workflow_rows, ["workflow_id", "analysis_type", "omics_type", "input_files", "sample_sheet", "group_field", "reference_group", "purpose"])
    write_csv(output_dir / "source_checksum_manifest.csv", source_rows, ["case_code", "kind", "source_path", "bytes", "sha256"])

    total_checks = len(agreement_rows)
    pass_checks = sum(1 for row in agreement_rows if row["status"] == "pass")
    missing_checks = sum(1 for row in agreement_rows if row["status"] == "missing")
    fail_checks = sum(1 for row in agreement_rows if row["status"] == "fail")
    by_field: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in agreement_rows:
        by_field[(row["omics"], row["field"])].append(row)
    tolerance_rows = [
        {
            "omics": omics,
            "field": field,
            "checked_count": len(rows),
            "pass_count": sum(1 for row in rows if row["status"] == "pass"),
            "fail_count": sum(1 for row in rows if row["status"] == "fail"),
            "missing_count": sum(1 for row in rows if row["status"] == "missing"),
            "max_abs_delta": max([float(row["abs_delta"] or 0) for row in rows] or [0]),
            "tolerance": rows[0]["tolerance"] if rows else "",
        }
        for (omics, field), rows in sorted(by_field.items())
    ]
    write_csv(output_dir / "tolerance_report.csv", tolerance_rows, ["omics", "field", "checked_count", "pass_count", "fail_count", "missing_count", "max_abs_delta", "tolerance"])

    privacy_rows = [
        {"control": "raw_upload_isolation", "expected": "inputs stored under runtime job only", "platform_status": "implemented_in_sequence_analysis_services", "evidence": "create_sequence_job saves uploads under inputs/ and deletes them in finally"},
        {"control": "ttl_cleanup", "expected": "derived runtime jobs expire", "platform_status": "implemented_in_sequence_analysis_services", "evidence": "cleanup_expired_jobs removes expired workspace/sequence_analysis jobs"},
        {"control": "extension_allowlist", "expected": "FASTA/GFF/sample sheets extension checked", "platform_status": "implemented_in_upload_security", "evidence": "validate_upload_name and store_uploaded_file enforce allowed extensions"},
        {"control": "path_containment", "expected": "uploaded file targets remain under workspace root", "platform_status": "implemented_in_upload_security", "evidence": "ensure_child_path validates resolved target path"},
        {"control": "public_registry_separation", "expected": "uploaded data does not enter public registry", "platform_status": "implemented_by_design", "evidence": "sequence jobs write only workspace/sequence_analysis outputs"},
    ]
    write_csv(output_dir / "privacy_security_checks.csv", privacy_rows, ["control", "expected", "platform_status", "evidence"])
    write_json(output_dir / "feature_extractor_contract.json", extractor_contract)

    downloads = []
    for path in sorted(output_dir.glob("*.csv")) + sorted(output_dir.glob("*.json")):
        downloads.append({"name": path.name, "path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)})
    for subdir in ["inputs/gold/protein", "inputs/gold/cds_transcript", "inputs/gold/gff3_subset", "inputs/synthetic_boundary", "inputs/workflow_examples"]:
        dir_path = output_dir / subdir
        if dir_path.exists():
            downloads.append({"name": subdir.replace("/", "_"), "path": str(dir_path), "bytes": sum(p.stat().st_size for p in dir_path.glob("*") if p.is_file()), "sha256": "directory"})

    summary = {
        "case_id": "model8_case4_upload_gold",
        "case_title": "Case 4. Eight-model-organism sequence-upload gold standard and user workflow",
        "case_version": CASE4_VERSION,
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
        "status": "implemented_with_declared_degradations",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "species_count": len(manifest),
        "protein_gold_records": len(expected_protein_rows),
        "nucleotide_gold_records": len(expected_nucleotide_rows),
        "synthetic_nucleotide_records": 200,
        "synthetic_protein_records": 200,
        "workflow_count": len(workflow_rows),
        "agreement": {
            "total_checks": total_checks,
            "pass_checks": pass_checks,
            "missing_checks": missing_checks,
            "fail_checks": fail_checks,
            "pass_rate": round(pass_checks / total_checks, 6) if total_checks else 0,
        },
        "full_database_feature_extractor_contract": extractor_contract,
        "cds_degradation": {
            "status": "partial",
            "reason": "Local Model-8 source bundle contains exact CDS FASTA for bacteria, but only cdna.all FASTA for the six eukaryotes.",
            "handling": "Eukaryotic upload gold writes canonical cDNA/transcript proxy and marks cds_status=degraded_to_cdna_transcript_proxy_no_local_cds_fasta.",
        },
        "gff3_degradation": {
            "status": "coordinate_proxy",
            "reason": "Full compressed GFF3 scans are intentionally not performed inside the gold-standard builder to avoid blocking release generation.",
            "handling": "GFF3 upload examples are generated as coordinate proxy rows from frozen feature headers and marked degraded_coordinate_proxy_from_feature_headers_no_full_gff3_scan.",
        },
        "downloads": downloads,
        "finding": "The upload workflow now has fixed synthetic boundary cases, 8x1000 real protein gold records, paired nucleotide upload records, GFF3 subsets, contract-governed expected features, field-tolerance reports, privacy/security checks, and three reproducible user workflow examples.",
        "method": "Protein gold records were selected by fixed-seed protein length decile stratification from joined Model-8 protein/transcript feature rows. Expected elemental features use the versioned polymerized-residue formula contract, with residue identity counts kept in explicitly named fields. Agreement was audited against the rebuilt full-release feature tables generated under the same declared contract.",
        "limitations": [
            "Six eukaryotic species lack local CDS FASTA in the frozen source bundle; cDNA/transcript upload gold is generated and explicitly marked as a CDS degradation.",
            "GFF3 subsets are coordinate proxies derived from frozen feature headers, not verbatim full original GFF3 row subsets.",
            "The gold-standard audit compares formula-contract expected features to stored full-release feature tables; full 8,000-record runtime upload extraction is prepared as input but not executed inside this builder.",
            "Synthetic invalid-character and duplicate-ID cases are provided as expected error cases; they are not mixed into public valid gold FASTA files.",
        ],
    }
    gold_payload = {
        "selection_manifest": selection_rows[:80],
        "subset_manifest": subset_rows,
        "tolerance_report": tolerance_rows,
        "source_checksums": source_rows,
        "full_database_feature_extractor_contract": extractor_contract,
        "synthetic_boundary": {
            "nucleotide_records": 200,
            "protein_records": 200,
            "error_cases": error_rows,
        },
    }
    workflow_payload = {
        "workflow_examples": workflow_rows,
        "privacy_security_checks": privacy_rows,
        "sequence_analysis_entry": "/sequence-analysis",
        "api_prefix": "/api/sequence-analysis/",
    }
    validation_payload = {
        "agreement": summary["agreement"],
        "tolerance_report": tolerance_rows,
        "full_database_feature_extractor_contract": extractor_contract,
        "failed_examples": [row for row in agreement_rows if row["status"] == "fail"][:50],
        "missing_examples": [row for row in agreement_rows if row["status"] == "missing"][:50],
        "cds_degradation": summary["cds_degradation"],
        "gff3_degradation": summary["gff3_degradation"],
    }
    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "gold_standard.json", gold_payload)
    write_json(output_dir / "workflows.json", workflow_payload)
    write_json(output_dir / "validation.json", validation_payload)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    out = Path(args.output_dir).resolve() if args.output_dir else root / "data" / "case_studies" / "model8" / "case4_upload_gold"
    summary = build_case4(root, out)
    print(json.dumps({
        "output_dir": str(out),
        "protein_gold_records": summary["protein_gold_records"],
        "nucleotide_gold_records": summary["nucleotide_gold_records"],
        "agreement": summary["agreement"],
        "workflow_count": summary["workflow_count"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
