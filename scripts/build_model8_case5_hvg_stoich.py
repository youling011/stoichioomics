#!/usr/bin/env python
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import random
import re
import shutil
import sys
import tarfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.config.settings")
try:
    import django

    django.setup()
except Exception:
    pass

from backend.analysis_engine.common import ExpressionDataset
from backend.analysis_engine.downstream.enrichment import run_enrichment_outputs
from backend.analysis_engine.phase1.hvg_core import run_hvg_baseline
from backend.analysis_engine.phase2.classify import classify_genes
from backend.analysis_engine.phase2.downstream import build_candidate_gene_table

try:
    from scripts.model8_elemental_contract import ELEMENTAL_CONTRACT_ID
except ModuleNotFoundError:  # Direct execution from scripts/.
    from model8_elemental_contract import ELEMENTAL_CONTRACT_ID


SEED = 20260730
CASE5_VERSION = "model8_case5_hvg_stoich_v3_publication_grade"
SCRIPT_NAME = "scripts/build_model8_case5_hvg_stoich.py"
CASE_CODES = ["ECOLI", "BSUB", "ORYSA", "DROME", "YEAST", "ARATH", "DANRE", "MOUSE"]
MAX_CELLS_DEFAULT = 600
BOOTSTRAPS = 12
PERMUTATIONS = 24
FEATURE_IMPORTANCE_REPEATS = 8
HVG_METHOD = "seurat_v3"
HVG_LOESS_SPAN = 0.3
HVG_TOP_FRACTION = 0.15
HVG_TOP_MIN = 50
HVG_TOP_MAX = 3000
FUNCTIONAL_GSEA_PERMUTATIONS = 1000
CASE_CODE_TO_SPECIES_ID = {
    "ECOLI": "escherichia_coli_k_12_gca_004919995",
    "BSUB": "bacillus_subtilis_subsp_subtilis_str_168_gca_000009045",
    "ORYSA": "oryza_sativa",
    "DROME": "drosophila_melanogaster",
    "YEAST": "saccharomyces_cerevisiae",
    "ARATH": "arabidopsis_thaliana",
    "DANRE": "danio_rerio",
    "MOUSE": "mus_musculus",
}
EXTERNAL_MAPPING_FILES = {
    "ORYSA_IC4R_MSU_RAP": "external_mappings/IC4R-MSU-RAP-DB-Locus-Mapping.csv.gz",
    "MOUSE_MGI_MARKER_LIST": "external_mappings/MGI_MRK_List1.rpt.gz",
    "DANRE_ZFIN_ENSEMBL_1_TO_1": "external_mappings/ZFIN_ensembl_1_to_1.txt",
    "DANRE_ZFIN_PREVIOUS_NAMES": "external_mappings/ZFIN_previous_names.txt",
}
STRICT_MAPPING_THRESHOLD_PHASE2 = 0.75
ENHANCED_BRIDGE_THRESHOLD_PHASE2 = 0.70
ENHANCED_BRIDGE_PHASE2_CODES = {"ORYSA"}

DATASETS = {
    "ECOLI": {
        "accession": "GSE260457",
        "topic": "RiboD-PETRI bacterial scRNA-seq biofilm/state profile",
        "matrix_kind": "delimited",
        "paths": ["expression/ECOLI/GSE260457/suppl/GSE260457_ECOLI_rRNA_and_mRNA_reads.txt.gz"],
        "sep": "\t",
        "id_col": "Geneid",
        "max_cells": 0,
        "complete_goal": True,
    },
    "BSUB": {
        "accession": "GSE226559",
        "topic": "54 bulk RNA-seq samples across stresses/states",
        "matrix_kind": "delimited",
        "paths": ["expression/BSUB/GSE226559/suppl/GSE226559_salmon.merged.gene_counts.tsv.gz"],
        "sep": "\t",
        "id_col": "gene_id",
        "drop_cols": ["gene_name"],
        "max_cells": 0,
        "complete_goal": True,
    },
    "ARATH": {
        "accession": "GSE123818",
        "topic": "Arabidopsis root WT single-cell discovery profile",
        "matrix_kind": "delimited",
        "paths": ["expression/ARATH/GSE123818/suppl/GSE123818_Root_single_cell_wt_datamatrix.csv.gz"],
        "sep": ",",
        "id_col": None,
        "max_cells": 500,
        "complete_goal": True,
    },
    "DROME": {
        "accession": "GSE198831",
        "topic": "Drosophila adult age/timepoint dge profile",
        "matrix_kind": "tar_delimited",
        "paths": ["expression/DROME/GSE198831/suppl/GSE198831_RAW.tar"],
        "members": [
            "GSM5957535_Drosophila_D21_COL17_dge.txt.gz",
            "GSM5957536_Drosophila_D21_COL18_dge.txt.gz",
            "GSM5957553_Drosophila_D36_COL35_dge.txt.gz",
            "GSM5957554_Drosophila_D36_COL36_dge.txt.gz",
        ],
        "sep": "\t",
        "id_col": "GENE",
        "max_cells": 450,
        "complete_goal": True,
    },
    "YEAST": {
        "accession": "GSE154515",
        "topic": "Saccharomyces heat-shock mDrop-seq processed 10x profiles",
        "matrix_kind": "tar_nested_10x",
        "paths": ["expression/YEAST/GSE154515/suppl/GSE154515_RAW.tar"],
        "members": [
            "GSM4672371_SC_15min_rep1_processed.tar.gz",
            "GSM4672373_SC_15min_rep2_processed.tar.gz",
            "GSM4672375_SC_HeatShock_rep1_processed.tar.gz",
            "GSM4672376_SC_HeatShock_rep2_processed.tar.gz",
        ],
        "max_cells": 500,
        "complete_goal": True,
    },
    "ORYSA": {
        "accession": "GSE146034",
        "topic": "Oryza root single-cell Nipponbare/93-11 10x profile",
        "matrix_kind": "tar_10x",
        "paths": ["expression/ORYSA/GSE146034/suppl/GSE146034_RAW.tar"],
        "groups": [
            {"label": "Nip", "genes": "GSM4363201_Nip_genes.tsv.gz", "matrix": "GSM4363201_Nip_matrix.mtx.gz"},
            {"label": "9311", "genes": "GSM4363200_9311_genes.tsv.gz", "matrix": "GSM4363200_9311_matrix.mtx.gz"},
        ],
        "max_cells": 450,
        "complete_goal": True,
    },
    "DANRE": {
        "accession": "GSE112294",
        "topic": "Zebrafish embryonic time-course single-cell matrices",
        "matrix_kind": "tar_delimited",
        "paths": ["expression/DANRE/GSE112294/suppl/GSE112294_RAW.tar"],
        "members": [
            "GSM3067189_04hpf.csv.gz",
            "GSM3067191_08hpf.csv.gz",
            "GSM3067195_24hpf.csv.gz",
        ],
        "sep": ",",
        "id_col": "Row",
        "max_cells": 420,
        "complete_goal": False,
    },
    "MOUSE": {
        "accession": "GSE109774",
        "topic": "Mouse tissue single-cell atlas 10x profiles",
        "matrix_kind": "tar_nested_10x",
        "paths": ["expression/MOUSE/GSE109774/suppl/GSE109774_RAW.tar"],
        "members": [
            "GSM3040892_Liver-10X_P4_2.tar.gz",
            "GSM3040893_Bladder-10X_P4_3.tar.gz",
            "GSM3040895_Kidney-10X_P4_5.tar.gz",
            "GSM3040902_Heart-10X_P7_4.tar.gz",
        ],
        "max_cells": 500,
        "complete_goal": True,
    },
}


def text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    value = str(value).strip()
    if not value or value.lower() in {"nan", "none", "null", "na", "n/a"}:
        return fallback
    return value


def clean_id(value: Any) -> str:
    value = text(value)
    value = re.sub(r"^(gene|transcript|protein|cds):", "", value, flags=re.I)
    value = value.split("|")[0].strip()
    value = re.sub(r"\.\d+$", "", value)
    return value


def norm_id(value: Any, code: str = "") -> str:
    value = clean_id(value)
    if not value:
        return ""
    value = value.strip()
    if code == "BSUB":
        m = re.match(r"^BSU_?(\d+)$", value, flags=re.I)
        if m:
            return f"BSU_{m.group(1)}".upper()
    return value.upper()


def parse_gene_symbol(header: Any) -> str:
    header = text(header)
    match = re.search(r"gene_symbol:([^ ]+)", header)
    return match.group(1) if match else ""


def load_external_alias_map(root: Path, code: str) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = defaultdict(set)

    if code == "ORYSA":
        path = root / EXTERNAL_MAPPING_FILES["ORYSA_IC4R_MSU_RAP"]
        if not path.exists():
            return aliases
        with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if len(row) < 3:
                    continue
                ic4r, msu, rap = row[:3]
                rap_norm = norm_id(rap, code)
                if not rap_norm:
                    continue
                for alias in (ic4r, msu, rap):
                    alias_norm = norm_id(alias, code)
                    if alias_norm:
                        aliases[rap_norm].add(alias_norm)
        return aliases

    if code == "MOUSE":
        path = root / EXTERNAL_MAPPING_FILES["MOUSE_MGI_MARKER_LIST"]
        if not path.exists():
            return aliases
        with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                symbol = text(row.get("Marker Symbol"))
                current_symbol = text(row.get("Current Marker Symbol (if withdrawn)"))
                key_symbol = current_symbol or symbol
                key_norm = norm_id(key_symbol, code)
                if not key_norm:
                    continue
                raw_aliases = {
                    symbol,
                    current_symbol,
                    text(row.get("Marker Name")),
                    text(row.get("MGI Accession ID")),
                    text(row.get("Current MGI Accession ID (if withdrawn)")),
                }
                for synonym in text(row.get("Marker Synonyms (pipe-separated)")).split("|"):
                    raw_aliases.add(synonym)
                for alias in raw_aliases:
                    alias_norm = norm_id(alias, code)
                    if alias_norm:
                        aliases[key_norm].add(alias_norm)
        return aliases

    if code == "DANRE":
        path = root / EXTERNAL_MAPPING_FILES["DANRE_ZFIN_ENSEMBL_1_TO_1"]
        if path.exists():
            with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                reader = csv.reader(handle, delimiter="\t")
                for row in reader:
                    if len(row) < 4:
                        continue
                    zfin_id, so_term, symbol, ensembl_gene = row[:4]
                    gene_norm = norm_id(ensembl_gene, code)
                    if not gene_norm:
                        continue
                    for alias in (zfin_id, so_term, symbol, ensembl_gene):
                        alias_norm = norm_id(alias, code)
                        if alias_norm:
                            aliases[gene_norm].add(alias_norm)
                            aliases[norm_id(symbol, code)].add(alias_norm)
        previous_path = root / EXTERNAL_MAPPING_FILES["DANRE_ZFIN_PREVIOUS_NAMES"]
        if previous_path.exists():
            with previous_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                reader = csv.reader(handle, delimiter="\t")
                for row in reader:
                    if len(row) < 2:
                        continue
                    current_symbol = norm_id(row[0], code)
                    if not current_symbol:
                        continue
                    for alias in row[1:]:
                        alias_norm = norm_id(alias, code)
                        if alias_norm:
                            aliases[current_symbol].add(alias_norm)
    return aliases


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def selected_fields(line: str, indices: list[int], sep: str) -> list[str]:
    """Return selected unquoted delimited fields without splitting the full row."""
    if len(sep) != 1:
        parts = line.rstrip("\n").split(sep)
        return [parts[idx] if idx < len(parts) else "" for idx in indices]
    wanted = set(indices)
    max_idx = max(indices) if indices else -1
    found: dict[int, str] = {}
    start = 0
    col = 0
    for pos, char in enumerate(line):
        if char == sep:
            if col in wanted:
                found[col] = line[start:pos]
                if len(found) == len(wanted):
                    break
            col += 1
            if col > max_idx and len(found) == len(wanted):
                break
            start = pos + 1
    else:
        if col in wanted:
            found[col] = line[start:].rstrip("\r\n")
    return [found.get(idx, "") for idx in indices]


def read_delimited_matrix(path: Path, sep: str, id_col: str | None, max_cells: int = 0, drop_cols: list[str] | None = None) -> tuple[list[str], np.ndarray, dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        header = handle.readline().rstrip("\n").split(sep)
    first_index = header.index(id_col) if id_col in header else 0
    first_col = id_col or header[first_index] or "__gene_id"
    drop = set(drop_cols or [])
    sample_indices = [idx for idx, col in enumerate(header) if idx != first_index and col not in drop]
    sample_cols = [header[idx] for idx in sample_indices]
    if max_cells and len(sample_cols) > max_cells:
        rng = random.Random(SEED + len(sample_cols))
        sample_cols = sorted(rng.sample(sample_cols, max_cells))
        sample_indices = [header.index(col) for col in sample_cols]
    genes: list[str] = []
    rows: list[list[float]] = []
    selected_indices = [first_index, *sample_indices]
    with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        next(handle, None)
        for line in handle:
            if not line:
                continue
            fields = selected_fields(line, selected_indices, sep)
            if not fields:
                continue
            genes.append(fields[0])
            values = []
            for value in fields[1:]:
                try:
                    values.append(float(value) if value else 0.0)
                except ValueError:
                    values.append(0.0)
            rows.append(values)
    loaded_sample_cols = sample_cols
    mat = np.asarray(rows, dtype=np.float32)
    meta = {"genes": len(genes), "cells_or_samples": len(loaded_sample_cols), "source": str(path), "subsampled": bool(max_cells and len(header) - 1 > len(loaded_sample_cols))}
    return genes, mat, meta


def read_csv_gz_from_tar(tar: tarfile.TarFile, member_name: str, sep: str, id_col: str, max_cells: int) -> tuple[list[str], np.ndarray, dict[str, Any]]:
    member = tar.getmember(member_name)
    raw = tar.extractfile(member)
    if raw is None:
        raise FileNotFoundError(member_name)
    with gzip.GzipFile(fileobj=raw) as gz:
        header = gz.readline().decode("utf-8", errors="replace").rstrip("\n").split(sep)
    sample_cols = [col for col in header if col != id_col]
    if max_cells and len(sample_cols) > max_cells:
        rng = random.Random(SEED + len(member_name))
        sample_cols = sorted(rng.sample(sample_cols, max_cells))
    usecols = [id_col, *sample_cols]
    raw = tar.extractfile(member)
    assert raw is not None
    with gzip.GzipFile(fileobj=raw) as gz:
        df = pd.read_csv(gz, sep=sep, usecols=usecols)
    genes = df[id_col].astype(str).tolist()
    mat = df[sample_cols].apply(pd.to_numeric, errors="coerce").fillna(0).to_numpy(dtype=np.float32)
    meta = {"member": member_name, "genes": len(genes), "cells_or_samples": len(sample_cols), "subsampled": bool(max_cells and len(header) - 1 > len(sample_cols))}
    return genes, mat, meta


def combine_gene_matrices(parts: list[tuple[list[str], np.ndarray, dict[str, Any]]]) -> tuple[list[str], np.ndarray, list[dict[str, Any]]]:
    if not parts:
        return [], np.zeros((0, 0), dtype=np.float32), []
    gene_sets = [set(genes) for genes, _mat, _meta in parts]
    common = sorted(set.intersection(*gene_sets))
    if not common:
        common = sorted(set.union(*gene_sets))
    arrays = []
    common_index = {gene: i for i, gene in enumerate(common)}
    for genes, mat, _meta in parts:
        idx = {gene: i for i, gene in enumerate(genes)}
        arr = np.zeros((len(common), mat.shape[1]), dtype=np.float32)
        take = [g for g in common if g in idx]
        if take:
            arr[[common_index[g] for g in take], :] = mat[[idx[g] for g in take], :]
        arrays.append(arr)
    return common, np.concatenate(arrays, axis=1), [meta for _genes, _mat, meta in parts]


def read_tar_delimited(root: Path, dataset: dict[str, Any]) -> tuple[list[str], np.ndarray, list[dict[str, Any]]]:
    tar_path = root / dataset["paths"][0]
    parts = []
    with tarfile.open(tar_path) as tar:
        for member in dataset["members"]:
            parts.append(read_csv_gz_from_tar(tar, member, dataset["sep"], dataset["id_col"], int(dataset.get("max_cells") or 0)))
    return combine_gene_matrices(parts)


def read_10x_group_from_tar(tar: tarfile.TarFile, genes_member: str, matrix_member: str, max_cells: int) -> tuple[list[str], Any, dict[str, Any]]:
    from scipy.io import mmread

    genes_raw = tar.extractfile(tar.getmember(genes_member))
    matrix_raw = tar.extractfile(tar.getmember(matrix_member))
    if genes_raw is None or matrix_raw is None:
        raise FileNotFoundError(f"{genes_member} / {matrix_member}")
    with gzip.GzipFile(fileobj=genes_raw) as gz:
        genes = [line.decode("utf-8", errors="replace").rstrip("\n").split("\t")[0] for line in gz if line.strip()]
    with gzip.GzipFile(fileobj=matrix_raw) as gz:
        mat = mmread(gz).tocsr()
    if mat.shape[0] != len(genes) and mat.shape[1] == len(genes):
        mat = mat.T.tocsr()
    cells = mat.shape[1]
    if max_cells and cells > max_cells:
        rng = np.random.default_rng(SEED + cells + len(genes))
        cols = np.sort(rng.choice(cells, size=max_cells, replace=False))
        mat = mat[:, cols].tocsr()
    meta = {"genes": len(genes), "cells_or_samples": mat.shape[1], "subsampled": bool(max_cells and cells > max_cells), "matrix_member": matrix_member}
    return genes, mat, meta


def read_tar_10x(root: Path, dataset: dict[str, Any]) -> tuple[list[str], np.ndarray, list[dict[str, Any]]]:
    tar_path = root / dataset["paths"][0]
    parts = []
    with tarfile.open(tar_path) as tar:
        for group in dataset["groups"]:
            genes, mat, meta = read_10x_group_from_tar(tar, group["genes"], group["matrix"], int(dataset.get("max_cells") or 0))
            meta["label"] = group.get("label", "")
            parts.append((genes, mat.toarray().astype(np.float32), meta))
    return combine_gene_matrices(parts)


def read_nested_10x(root: Path, dataset: dict[str, Any]) -> tuple[list[str], np.ndarray, list[dict[str, Any]]]:
    from scipy.io import mmread

    outer_path = root / dataset["paths"][0]
    parts = []
    with tarfile.open(outer_path) as outer:
        for member_name in dataset["members"]:
            member = outer.getmember(member_name)
            raw = outer.extractfile(member)
            if raw is None:
                continue
            data = raw.read()
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as inner:
                names = {Path(m.name).name: m.name for m in inner.getmembers() if m.isfile()}
                genes_member = names.get("genes.tsv") or names.get("features.tsv")
                matrix_member = names.get("matrix.mtx")
                if not genes_member or not matrix_member:
                    continue
                genes_raw = inner.extractfile(inner.getmember(genes_member))
                matrix_raw = inner.extractfile(inner.getmember(matrix_member))
                assert genes_raw is not None and matrix_raw is not None
                genes = [line.decode("utf-8", errors="replace").rstrip("\n").split("\t")[0] for line in genes_raw if line.strip()]
                mat = mmread(matrix_raw).tocsr()
                if mat.shape[0] != len(genes) and mat.shape[1] == len(genes):
                    mat = mat.T.tocsr()
                cells = mat.shape[1]
                max_cells = int(dataset.get("max_cells") or 0)
                if max_cells and cells > max_cells:
                    rng = np.random.default_rng(SEED + cells + len(member_name))
                    cols = np.sort(rng.choice(cells, size=max_cells, replace=False))
                    mat = mat[:, cols].tocsr()
                parts.append((genes, mat.toarray().astype(np.float32), {"member": member_name, "genes": len(genes), "cells_or_samples": mat.shape[1], "subsampled": bool(max_cells and cells > max_cells)}))
    return combine_gene_matrices(parts)


def load_expression_matrix(root: Path, code: str, dataset: dict[str, Any]) -> tuple[list[str], np.ndarray, list[dict[str, Any]]]:
    kind = dataset["matrix_kind"]
    if kind == "delimited":
        parts = []
        for rel in dataset["paths"]:
            parts.append(read_delimited_matrix(root / rel, dataset["sep"], dataset.get("id_col"), int(dataset.get("max_cells") or 0), dataset.get("drop_cols")))
        return combine_gene_matrices(parts)
    if kind == "tar_delimited":
        return read_tar_delimited(root, dataset)
    if kind == "tar_10x":
        return read_tar_10x(root, dataset)
    if kind == "tar_nested_10x":
        return read_nested_10x(root, dataset)
    raise ValueError(kind)


def hvg_phase1(code: str, genes: list[str], mat: np.ndarray) -> pd.DataFrame:
    if mat.size == 0:
        return pd.DataFrame()
    matrix = np.nan_to_num(mat.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    n = len(genes)
    top_n = min(HVG_TOP_MAX, max(HVG_TOP_MIN, int(n * HVG_TOP_FRACTION)))
    dataset = ExpressionDataset(
        matrix=sparse.csr_matrix(matrix.T),
        gene_ids=[str(g) for g in genes],
        gene_names=[str(g) for g in genes],
        cell_ids=[f"{code}_sample_{i + 1}" for i in range(matrix.shape[1])],
        obs=pd.DataFrame({"cell_id": [f"{code}_sample_{i + 1}" for i in range(matrix.shape[1])]}),
        uns={"case_code": code, "case5_hvg_method": HVG_METHOD},
    )
    baseline, hvg_summary = run_hvg_baseline(
        dataset,
        method=HVG_METHOD,
        n_top_genes=top_n,
        loess_span=HVG_LOESS_SPAN,
    )
    baseline = baseline.rename(columns={
        "gene_id": "expression_gene_id",
        "mean_expr": "mean_expression",
        "dropout_rate": "dropout_fraction",
    })
    baseline["case_code"] = code
    baseline["fano"] = pd.to_numeric(baseline["variance"], errors="coerce") / (pd.to_numeric(baseline["mean_expression"], errors="coerce") + 1e-6)
    baseline["residual_variance"] = baseline["normalized_dispersion"]
    baseline["residual_dropout"] = baseline["dropout_fraction"]
    baseline["rank_residual_variance"] = baseline["hvg_rank"]
    baseline["rank_fano"] = pd.to_numeric(baseline["fano"], errors="coerce").rank(ascending=False, method="average")
    baseline["rank_dropout"] = pd.to_numeric(baseline["dropout_fraction"], errors="coerce").rank(ascending=True, method="average")
    baseline["method_support_count"] = baseline["is_hvg"].fillna(False).astype(bool).astype(int)
    baseline["hvg_consensus"] = baseline["is_hvg"].fillna(False).astype(bool)

    rng = np.random.default_rng(SEED + len(code) + mat.shape[1])
    stability = np.zeros(n, dtype=np.float32)
    if mat.shape[1] >= 6 and n >= 30:
        for _ in range(BOOTSTRAPS):
            cols = rng.choice(matrix.shape[1], size=max(3, int(matrix.shape[1] * 0.7)), replace=True)
            sub_dataset = ExpressionDataset(
                matrix=sparse.csr_matrix(matrix[:, cols].T),
                gene_ids=[str(g) for g in genes],
                gene_names=[str(g) for g in genes],
                cell_ids=[f"{code}_bootstrap_{i + 1}" for i in range(len(cols))],
                obs=pd.DataFrame({"cell_id": [f"{code}_bootstrap_{i + 1}" for i in range(len(cols))]}),
                uns={"case_code": code, "bootstrap": True},
            )
            sub_baseline, _ = run_hvg_baseline(sub_dataset, method=HVG_METHOD, n_top_genes=top_n, loess_span=HVG_LOESS_SPAN)
            stability += sub_baseline["is_hvg"].fillna(False).astype(bool).to_numpy(dtype=np.float32)
        stability /= BOOTSTRAPS
    else:
        stability[baseline["hvg_consensus"].to_numpy(dtype=bool)] = 1.0
    baseline["bootstrap_stability"] = stability
    baseline["phase1_method"] = HVG_METHOD
    baseline["phase1_method_family"] = hvg_summary.get("method_family")
    baseline["phase1_score_semantics"] = hvg_summary.get("hvg_score_semantics")
    baseline["phase1_standard_reference"] = hvg_summary.get("standard_reference")
    keep = [
        "case_code",
        "expression_gene_id",
        "gene_name",
        "mean_expression",
        "mean_nonzero_expr",
        "variance",
        "fano",
        "dropout_fraction",
        "n_cells_detected",
        "pct_cells_detected",
        "raw_dispersion",
        "normalized_dispersion",
        "variances_norm",
        "vst_log10_variance_fit",
        "regularized_sd",
        "residual_variance",
        "residual_dropout",
        "rank_residual_variance",
        "rank_fano",
        "rank_dropout",
        "method_support_count",
        "is_hvg",
        "hvg_consensus",
        "hvg_rank",
        "bootstrap_stability",
        "hvg_score",
        "hvg_method",
        "hvg_score_semantics",
        "phase1_method",
        "phase1_method_family",
        "phase1_score_semantics",
        "phase1_standard_reference",
    ]
    return baseline[[c for c in keep if c in baseline.columns]].sort_values(["hvg_rank", "bootstrap_stability"], ascending=[True, False]).reset_index(drop=True)


def method_concordance(code: str, phase1: pd.DataFrame) -> list[dict[str, Any]]:
    if phase1.empty:
        return []
    top_n = min(500, max(50, int(len(phase1) * 0.15)))
    methods = {
        "residual_variance": set(phase1.nsmallest(top_n, "rank_residual_variance")["expression_gene_id"]),
        "fano": set(phase1.nsmallest(top_n, "rank_fano")["expression_gene_id"]),
        "dropout_residual": set(phase1.nsmallest(top_n, "rank_dropout")["expression_gene_id"]),
        "consensus": set(phase1[phase1["hvg_consensus"]]["expression_gene_id"]),
    }
    rows = []
    for a, aset in methods.items():
        for b, bset in methods.items():
            if a >= b:
                continue
            union = aset | bset
            rows.append({
                "case_code": code,
                "method_a": a,
                "method_b": b,
                "top_n": top_n,
                "intersection": len(aset & bset),
                "union": len(union),
                "jaccard": round(len(aset & bset) / len(union), 6) if union else 0,
            })
    return rows


def load_gene_features(root: Path, code: str) -> pd.DataFrame:
    feature_dir = root / code / "features"
    mapping_dir = root / code / "mapping"
    prot = pd.read_csv(feature_dir / "protein_features.tsv.gz", sep="\t")
    trans = pd.read_csv(feature_dir / "transcript_features.tsv.gz", sep="\t")
    mapping = pd.read_csv(mapping_dir / "id_chains.tsv.gz", sep="\t")

    mapping["gene_norm"] = mapping["gene_id"].map(lambda v: norm_id(v, code))
    mapping["transcript_norm"] = mapping["transcript_id"].map(lambda v: norm_id(v, code))
    mapping["protein_norm"] = mapping["protein_id"].map(lambda v: norm_id(v, code))
    mapping = mapping[mapping["gene_norm"].astype(bool)].drop_duplicates("gene_norm")

    prot["gene_norm"] = prot["gene_id"].map(lambda v: norm_id(v, code))
    prot["transcript_norm"] = prot["transcript_id"].map(lambda v: norm_id(v, code))
    prot["protein_norm"] = prot["entity_id"].map(lambda v: norm_id(v, code))
    prot["gene_symbol"] = prot["header"].map(parse_gene_symbol)
    prot["symbol_norm"] = prot["gene_symbol"].map(lambda v: norm_id(v, code))

    trans["transcript_norm"] = trans["entity_id"].map(lambda v: norm_id(v, code))
    trans["transcript_gene_symbol"] = trans["header"].map(parse_gene_symbol)
    trans["transcript_symbol_norm"] = trans["transcript_gene_symbol"].map(lambda v: norm_id(v, code))
    external_aliases = load_external_alias_map(root, code)
    if code in {"ECOLI", "BSUB"}:
        bacteria_base = prot[["gene_norm", "gene_id", "transcript_id", "entity_id", "gene_symbol", "symbol_norm", "protein_norm", "length", "c_atoms_per_aa", "s_atoms_per_aa", "n_atoms_per_aa", "aa_entropy", "mw_approx"]].copy()
        bacteria_base = bacteria_base.rename(columns={"entity_id": "protein_id"})
        bacteria_base["transcript_norm"] = bacteria_base["transcript_id"].map(lambda v: norm_id(v, code))
        trans_gene = bacteria_base[["gene_norm", "transcript_norm"]].merge(trans, on="transcript_norm", how="left")
        length_col = "length_y" if "length_y" in trans_gene.columns else "length"
        trans_gene = trans_gene[["gene_norm", length_col, "gc_fraction", "n_fraction", "entropy"]].drop_duplicates("gene_norm").rename(columns={
            length_col: "transcript_length",
            "gc_fraction": "transcript_gc_fraction",
            "n_fraction": "transcript_n_fraction",
            "entropy": "transcript_entropy",
        })
        feat = bacteria_base.drop_duplicates("gene_norm").merge(trans_gene, on="gene_norm", how="left")
        feat["mapping_status"] = "ok_high_from_protein_feature_locus"
    else:
        prot_by_protein = mapping[["gene_norm", "protein_norm", "transcript_norm"]].merge(prot, on="protein_norm", how="left", suffixes=("", "_feature"))
        missing_prot = prot_by_protein["length"].isna()
        if missing_prot.any():
            fallback_keys = prot_by_protein.loc[missing_prot, ["gene_norm", "transcript_norm"]]
            prot_by_transcript = fallback_keys.merge(prot, on="transcript_norm", how="left", suffixes=("", "_feature")).drop_duplicates("gene_norm").set_index("gene_norm")
            for col in ["gene_symbol", "symbol_norm", "length", "c_atoms_per_aa", "s_atoms_per_aa", "n_atoms_per_aa", "aa_entropy", "mw_approx"]:
                if col in prot_by_transcript:
                    prot_by_protein.loc[missing_prot, col] = prot_by_protein.loc[missing_prot, "gene_norm"].map(prot_by_transcript[col])
        prot_cols = ["gene_norm", "protein_norm", "gene_symbol", "symbol_norm", "length", "c_atoms_per_aa", "s_atoms_per_aa", "n_atoms_per_aa", "aa_entropy", "mw_approx"]
        prot_gene = prot_by_protein[[c for c in prot_cols if c in prot_by_protein.columns]].drop_duplicates("gene_norm")
        trans_join = mapping[["gene_norm", "transcript_norm"]].merge(trans, on="transcript_norm", how="left")
        trans_cols = ["gene_norm", "length", "gc_fraction", "n_fraction", "entropy", "transcript_gene_symbol", "transcript_symbol_norm"]
        trans_gene = trans_join[trans_cols].drop_duplicates("gene_norm").rename(columns={
            "length": "transcript_length",
            "gc_fraction": "transcript_gc_fraction",
            "n_fraction": "transcript_n_fraction",
            "entropy": "transcript_entropy",
        })
        feat = mapping[["gene_norm", "gene_id", "transcript_id", "protein_id", "mapping_status"]].merge(prot_gene, on="gene_norm", how="left").merge(trans_gene, on="gene_norm", how="left")
        if "gene_symbol" in feat.columns and "transcript_gene_symbol" in feat.columns:
            feat["gene_symbol"] = feat["gene_symbol"].fillna(feat["transcript_gene_symbol"])
        if "symbol_norm" in feat.columns and "transcript_symbol_norm" in feat.columns:
            feat["symbol_norm"] = feat["symbol_norm"].fillna(feat["transcript_symbol_norm"])
    alias_rows = []
    for _, row in feat.iterrows():
        aliases = {
            row["gene_norm"],
            norm_id(row.get("gene_id"), code),
            norm_id(row.get("protein_id"), code),
            norm_id(row.get("transcript_id"), code),
            norm_id(row.get("gene_symbol"), code),
            norm_id(row.get("symbol_norm"), code),
            norm_id(row.get("transcript_gene_symbol"), code),
            norm_id(row.get("transcript_symbol_norm"), code),
        }
        for alias_key in list(aliases):
            aliases.update(external_aliases.get(alias_key, set()))
        for alias in aliases:
            if alias:
                for part in str(alias).split("|"):
                    if part:
                        rec = row.to_dict()
                        rec["expr_norm"] = part
                        alias_rows.append(rec)
    return pd.DataFrame(alias_rows).drop_duplicates("expr_norm")


def join_hvg_features(code: str, phase1: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    if phase1.empty or features.empty:
        return pd.DataFrame()
    phase1 = phase1.copy()
    phase1["expr_norm"] = phase1["expression_gene_id"].map(lambda v: norm_id(v, code))
    exploded = []
    for _, row in phase1.iterrows():
        for alias in str(row["expr_norm"]).split("|"):
            rec = row.to_dict()
            rec["expr_norm"] = alias
            exploded.append(rec)
    joined = pd.DataFrame(exploded).merge(features, on="expr_norm", how="left")
    joined = joined.drop_duplicates("expression_gene_id")
    return joined


def run_models(code: str, joined: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], pd.DataFrame]:
    from scipy import stats
    from sklearn.linear_model import Ridge
    from sklearn.metrics import r2_score
    from sklearn.model_selection import KFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if joined.empty:
        return [], [], [], joined
    numeric_sets = {
        "B0_expression": ["mean_expression", "dropout_fraction"],
        "B1_transcript": ["mean_expression", "dropout_fraction", "transcript_length", "transcript_gc_fraction", "transcript_n_fraction", "transcript_entropy"],
        "B2_protein": ["mean_expression", "dropout_fraction", "length", "c_atoms_per_aa", "s_atoms_per_aa", "n_atoms_per_aa", "aa_entropy", "mw_approx"],
        "B3_combined": ["mean_expression", "dropout_fraction", "transcript_length", "transcript_gc_fraction", "transcript_n_fraction", "transcript_entropy", "length", "c_atoms_per_aa", "s_atoms_per_aa", "n_atoms_per_aa", "aa_entropy", "mw_approx"],
    }
    y = pd.to_numeric(joined["hvg_score"], errors="coerce")
    model_rows = []
    pred_rows = []
    perm_rows = []
    best_pred = np.full(len(joined), np.nan)
    for model_id, cols in numeric_sets.items():
        cols = [c for c in cols if c in joined.columns]
        data = joined[cols].apply(pd.to_numeric, errors="coerce")
        valid = y.notna() & data.notna().all(axis=1)
        n = int(valid.sum())
        if n < 80 or len(cols) < 2:
            model_rows.append({"case_code": code, "model_id": model_id, "status": "blocked", "n_genes": n, "feature_count": len(cols), "cv_r2": "", "spearman_r": "", "permutation_p_value": "", "permutation_repeats": 0, "minimum_resolvable_p_value": "", "reason": "insufficient mapped complete rows"})
            continue
        X = data.loc[valid].to_numpy(dtype=np.float32)
        target = y.loc[valid].to_numpy(dtype=np.float32)
        k = min(5, max(3, n // 80))
        cv = KFold(n_splits=k, shuffle=True, random_state=SEED)
        model = make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        pred = cross_val_predict(model, X, target, cv=cv)
        r2 = r2_score(target, pred)
        spearman = stats.spearmanr(target, pred).statistic
        rng = np.random.default_rng(SEED + n + len(model_id))
        null = []
        for _ in range(PERMUTATIONS):
            yp = rng.permutation(target)
            pp = cross_val_predict(model, X, yp, cv=cv)
            null.append(r2_score(yp, pp))
        pval = (sum(v >= r2 for v in null) + 1) / (len(null) + 1)
        model_rows.append({
            "case_code": code,
            "model_id": model_id,
            "status": "complete",
            "n_genes": n,
            "feature_count": len(cols),
            "cv_r2": round(float(r2), 6),
            "spearman_r": round(float(spearman), 6) if math.isfinite(float(spearman)) else "",
            "permutation_p_value": round(float(pval), 6),
            "permutation_repeats": PERMUTATIONS,
            "minimum_resolvable_p_value": round(float(1.0 / (PERMUTATIONS + 1.0)), 6),
            "reason": "",
        })
        for idx, obs, pr in zip(joined.index[valid], target, pred):
            if model_id == "B3_combined":
                best_pred[idx] = pr
            if len(pred_rows) < 2500:
                pred_rows.append({"case_code": code, "model_id": model_id, "expression_gene_id": joined.loc[idx, "expression_gene_id"], "observed_hvg_score": round(float(obs), 6), "predicted_hvg_score": round(float(pr), 6), "residual": round(float(obs - pr), 6)})
        perm_rows.extend({"case_code": code, "model_id": model_id, "permutation_index": i, "null_cv_r2": round(float(v), 6), "observed_cv_r2": round(float(r2), 6)} for i, v in enumerate(null[:PERMUTATIONS]))

    joined = joined.copy()
    joined["b3_predicted_hvg_score"] = best_pred
    joined["b3_residual"] = pd.to_numeric(joined["hvg_score"], errors="coerce") - joined["b3_predicted_hvg_score"]
    joined["m3_predicted_hvg_score"] = joined["b3_predicted_hvg_score"]
    joined["m3_residual"] = joined["b3_residual"]
    return model_rows, pred_rows, perm_rows, joined


def annotation_alias_for_case(code: str, row: pd.Series) -> str:
    if code == "BSUB":
        for value in [row.get("expression_gene_id"), row.get("gene_id")]:
            clean = norm_id(value, code).replace("_", "")
            if clean.startswith("BSU"):
                return clean
    if code == "DROME":
        for value in [row.get("expression_gene_id"), row.get("gene_symbol"), row.get("gene_id")]:
            clean = clean_id(value)
            if clean.startswith("Dmel_CG"):
                return clean
            if clean.startswith("CG") and clean[2:].isdigit():
                return f"Dmel_{clean}"
    return ""


def apply_standard_stoich_classification(code: str, joined: pd.DataFrame) -> pd.DataFrame:
    if joined.empty:
        return joined
    work = joined.copy()
    observed = pd.to_numeric(work.get("hvg_score"), errors="coerce").fillna(0.0)
    expected_source = work.get("b3_predicted_hvg_score")
    if expected_source is None:
        expected_source = work.get("m3_predicted_hvg_score")
    expected = pd.to_numeric(expected_source, errors="coerce")
    if not isinstance(expected, pd.Series):
        expected = pd.Series(np.nan, index=work.index)
    if expected.isna().all():
        expected = pd.Series(0.0, index=work.index)
    residual = observed - expected.fillna(0.0)
    cost_cols = [c for c in ["c_atoms_per_aa", "n_atoms_per_aa", "s_atoms_per_aa", "transcript_gc_fraction", "transcript_entropy", "aa_entropy", "mw_approx"] if c in work.columns]
    if cost_cols:
        cost_block = work[cost_cols].apply(pd.to_numeric, errors="coerce")
        cost_index = cost_block.apply(lambda col: (col - col.median()) / (col.std(ddof=0) or 1.0)).abs().mean(axis=1).fillna(0.0)
    else:
        cost_index = pd.Series(0.0, index=work.index)
    work["gene_id"] = work.get("gene_id", work.get("expression_gene_id", "")).fillna(work.get("expression_gene_id", ""))
    work["gene_name"] = work.get("gene_symbol", work.get("gene_name", work.get("expression_gene_id", ""))).fillna(work.get("expression_gene_id", ""))
    work["source_protein_id"] = work.apply(lambda row: annotation_alias_for_case(code, row), axis=1)
    work["is_hvg"] = work.get("is_hvg", work.get("hvg_consensus", False)).fillna(False).astype(bool)
    work["mean_expr"] = pd.to_numeric(work.get("mean_expression"), errors="coerce")
    work["dropout_rate"] = pd.to_numeric(work.get("dropout_fraction"), errors="coerce")
    work["observed_hvg_signal"] = observed
    work["stoich_expected_var"] = expected.fillna(0.0)
    work["stoich_excess_var"] = residual
    denom = observed.abs() + 1e-9
    explained = (1.0 - residual.abs() / denom).clip(lower=0.0, upper=1.0)
    work["stoich_explained_fraction"] = explained
    work["stoich_fit_closeness"] = explained
    work["cost_index"] = cost_index
    feature_candidates = [c for c in ["transcript_gc_fraction", "transcript_n_fraction", "transcript_entropy", "length", "c_atoms_per_aa", "n_atoms_per_aa", "s_atoms_per_aa", "aa_entropy", "mw_approx"] if c in work.columns]
    associated_feature = ""
    if feature_candidates:
        corr_rows = []
        for feature in feature_candidates:
            values = pd.to_numeric(work[feature], errors="coerce")
            if values.notna().sum() >= 30:
                corr = values.corr(observed, method="spearman")
                if pd.notna(corr):
                    corr_rows.append((abs(float(corr)), feature))
        associated_feature = sorted(corr_rows, reverse=True)[0][1] if corr_rows else feature_candidates[0]
    work["stoich_associated_feature"] = associated_feature
    classified, _, _ = classify_genes(work, hvg_flag_col="is_hvg")
    candidate_table = build_candidate_gene_table(classified, top_n=max(300, min(1000, classified.shape[0])))
    priority = candidate_table.set_index("gene_id")["priority_score"].to_dict() if not candidate_table.empty and "gene_id" in candidate_table else {}
    classified["priority_score"] = classified["gene_id"].map(priority).fillna(0.0)
    return classified


def feature_importance_rows(code: str, joined: pd.DataFrame) -> list[dict[str, Any]]:
    from scipy import stats
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.inspection import permutation_importance
    from sklearn.model_selection import KFold

    cols = ["mean_expression", "dropout_fraction", "transcript_length", "transcript_gc_fraction", "transcript_n_fraction", "transcript_entropy", "length", "c_atoms_per_aa", "s_atoms_per_aa", "n_atoms_per_aa", "aa_entropy", "mw_approx"]
    cols = [c for c in cols if c in joined.columns]
    data = joined[cols].apply(pd.to_numeric, errors="coerce")
    y = pd.to_numeric(joined["hvg_score"], errors="coerce")
    valid = y.notna() & data.notna().all(axis=1)
    if int(valid.sum()) < 100:
        return []
    X = data.loc[valid].to_numpy(dtype=np.float32)
    target = y.loc[valid].to_numpy(dtype=np.float32)
    k = min(5, max(3, int(valid.sum()) // 200))
    cv = KFold(n_splits=k, shuffle=True, random_state=SEED)
    importances = []
    for fold, (train_idx, test_idx) in enumerate(cv.split(X), start=1):
        model = RandomForestRegressor(n_estimators=240, random_state=SEED + fold, min_samples_leaf=4, n_jobs=-1)
        model.fit(X[train_idx], target[train_idx])
        perm = permutation_importance(
            model,
            X[test_idx],
            target[test_idx],
            n_repeats=FEATURE_IMPORTANCE_REPEATS,
            random_state=SEED + fold,
            n_jobs=-1,
        )
        importances.append(perm.importances_mean)
    imp_matrix = np.vstack(importances)
    imp_mean = np.nanmean(imp_matrix, axis=0)
    imp_std = np.nanstd(imp_matrix, axis=0, ddof=1) if imp_matrix.shape[0] > 1 else np.zeros(len(cols), dtype=float)
    rows = []
    for feature, imp, std in sorted(zip(cols, imp_mean, imp_std), key=lambda x: x[1], reverse=True):
        values = pd.to_numeric(joined.loc[valid, feature], errors="coerce")
        corr = stats.spearmanr(values, target, nan_policy="omit").statistic
        rows.append({
            "case_code": code,
            "feature": feature,
            "permutation_importance": round(float(imp), 6),
            "importance_std": round(float(std), 6),
            "cv_folds": k,
            "importance_repeats_per_fold": FEATURE_IMPORTANCE_REPEATS,
            "importance_status": "cross_validated_test_fold_permutation",
            "spearman_with_hvg_score": round(float(corr), 6) if math.isfinite(float(corr)) else "",
        })
    return rows


def candidate_and_controls(code: str, joined: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if joined.empty:
        return [], []
    complete = joined.copy()
    complete["mapped_gene_id"] = complete.get("gene_id", "")
    complete["protein_length"] = pd.to_numeric(complete.get("length"), errors="coerce")
    if "priority_score" not in complete.columns:
        complete["priority_score"] = 0.0
    if "b3_residual" not in complete.columns:
        complete["b3_residual"] = complete.get("m3_residual", np.nan)
    candidates = complete.sort_values(["priority_score", "hvg_consensus", "bootstrap_stability", "hvg_score", "b3_residual"], ascending=False).head(120)
    cand_rows = []
    for rank, (_, row) in enumerate(candidates.iterrows(), start=1):
        cand_rows.append({
            "case_code": code,
            "rank": rank,
            "expression_gene_id": row.get("expression_gene_id"),
            "platform_gene_id": row.get("gene_id"),
            "protein_id": row.get("protein_id"),
            "gene_symbol": row.get("gene_symbol"),
            "hvg_score": round(float(row.get("hvg_score", 0)), 6),
            "normalized_dispersion": "" if pd.isna(row.get("normalized_dispersion")) else round(float(row.get("normalized_dispersion")), 6),
            "hvg_rank": "" if pd.isna(row.get("hvg_rank")) else int(row.get("hvg_rank")),
            "is_hvg": bool(row.get("is_hvg", row.get("hvg_consensus", False))),
            "bootstrap_stability": round(float(row.get("bootstrap_stability", 0)), 6),
            "stoich_class": row.get("stoich_class", ""),
            "priority_score": round(float(row.get("priority_score", 0)), 6),
            "stoich_expected_var": "" if pd.isna(row.get("stoich_expected_var")) else round(float(row.get("stoich_expected_var")), 6),
            "stoich_excess_var": "" if pd.isna(row.get("stoich_excess_var")) else round(float(row.get("stoich_excess_var")), 6),
            "stoich_explained_fraction": "" if pd.isna(row.get("stoich_explained_fraction")) else round(float(row.get("stoich_explained_fraction")), 6),
            "b3_residual": "" if pd.isna(row.get("b3_residual")) else round(float(row.get("b3_residual")), 6),
            "m3_residual": "" if pd.isna(row.get("m3_residual")) else round(float(row.get("m3_residual")), 6),
            "protein_n_atoms_per_aa": "" if pd.isna(row.get("n_atoms_per_aa")) else round(float(row.get("n_atoms_per_aa")), 6),
            "protein_s_atoms_per_aa": "" if pd.isna(row.get("s_atoms_per_aa")) else round(float(row.get("s_atoms_per_aa")), 6),
            "transcript_gc_fraction": "" if pd.isna(row.get("transcript_gc_fraction")) else round(float(row.get("transcript_gc_fraction")), 6),
        })
    controls = complete[~complete["hvg_consensus"].fillna(False)].copy()
    ctrl_rows = []
    if not controls.empty:
        controls["mean_rank_value"] = pd.to_numeric(controls["mean_expression"], errors="coerce")
        controls["protein_length"] = pd.to_numeric(controls["protein_length"], errors="coerce")
        for _, row in candidates.head(32).iterrows():
            target_mean = float(row.get("mean_expression", 0) or 0)
            target_len = float(row.get("protein_length", 0) or 0)
            tmp = controls.copy()
            tmp["dist"] = (np.log1p(tmp["mean_rank_value"]) - math.log1p(target_mean)) ** 2
            if math.isfinite(target_len) and target_len > 0:
                tmp["dist"] += ((tmp["protein_length"].fillna(target_len) - target_len) / max(1, target_len)) ** 2
            best = tmp.sort_values("dist").head(1)
            if not best.empty:
                b = best.iloc[0]
                ctrl_rows.append({"case_code": code, "target_expression_gene_id": row.get("expression_gene_id"), "control_expression_gene_id": b.get("expression_gene_id"), "target_hvg_score": round(float(row.get("hvg_score", 0)), 6), "control_hvg_score": round(float(b.get("hvg_score", 0)), 6), "matching_distance": round(float(b.get("dist", 0)), 6)})
    return cand_rows, ctrl_rows


def functional_enrichment_bundle(code: str, joined: pd.DataFrame, output_dir: Path) -> dict[str, Any]:
    species_id = CASE_CODE_TO_SPECIES_ID.get(code, "")
    per_case_dir = output_dir / "functional_enrichment_by_species" / code
    config = {
        "species_id": species_id,
        "functional_enrichment_top_n": 500,
        "functional_enrichment_min_overlap": 2,
        "functional_enrichment_min_term_size": 3,
        "functional_enrichment_max_term_size": 500,
        "functional_enrichment_fdr": 0.05,
        "functional_enrichment_report_terms": 300,
        "functional_enrichment_plot_terms": 40,
        "functional_gsea_permutations": FUNCTIONAL_GSEA_PERMUTATIONS,
        "random_state": SEED,
    }
    required = {"gene_id", "hvg_score", "is_hvg", "hvg_rank", "stoich_class"}
    if joined.empty or not required.issubset(set(joined.columns)):
        return {"ora": [], "gsea": [], "top": [], "summary": {"case_code": code, "species_id": species_id, "status": "skipped", "reason_code": "missing_classified_hvg_fields"}}
    run_enrichment_outputs(joined, per_case_dir, config=config)
    ora = pd.read_csv(per_case_dir / "enrichment_ora.csv") if (per_case_dir / "enrichment_ora.csv").exists() else pd.DataFrame()
    gsea = pd.read_csv(per_case_dir / "gsea_prerank_results.csv") if (per_case_dir / "gsea_prerank_results.csv").exists() else pd.DataFrame()
    top = pd.read_csv(per_case_dir / "functional_enrichment_top_terms.csv") if (per_case_dir / "functional_enrichment_top_terms.csv").exists() else pd.DataFrame()
    summary_path = per_case_dir / "functional_enrichment_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}

    def add_case(df: pd.DataFrame) -> list[dict[str, Any]]:
        if df.empty:
            return []
        out = df.copy()
        out.insert(0, "case_code", code)
        out.insert(1, "annotation_species_id", species_id)
        return out.replace([np.inf, -np.inf], np.nan).where(pd.notnull(out), "").to_dict("records")

    summary = {"case_code": code, "annotation_species_id": species_id, **summary}
    return {
        "ora": add_case(ora),
        "gsea": add_case(gsea),
        "top": add_case(top),
        "summary": summary,
    }


def ingest_sources(root: Path) -> list[dict[str, Any]]:
    rows = []
    for code, ds in DATASETS.items():
        size = 0
        sha_basis = []
        for rel in ds["paths"]:
            path = root / rel
            if path.exists():
                size += path.stat().st_size
                sha_basis.append(file_sha256(path)[:16])
        rows.append({"case_code": code, "accession": ds["accession"], "topic": ds["topic"], "matrix_kind": ds["matrix_kind"], "source_count": len(ds["paths"]), "bytes": size, "sha256_prefix": ";".join(sha_basis), "ingest_status": "available" if size else "missing"})
    return rows


def build_case5(root: Path, output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    contract_path = root / "data" / "case_studies" / "model8" / "feature_extractor_contract.json"
    extractor_contract = json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.exists() else {}
    model8_root = root / "data" / "case_studies" / "model8"

    ingest = ingest_sources(model8_root)
    phase1_rows: list[dict[str, Any]] = []
    method_rows: list[dict[str, Any]] = []
    model_rows: list[dict[str, Any]] = []
    pred_rows: list[dict[str, Any]] = []
    perm_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    enrich_rows: list[dict[str, Any]] = []
    gsea_rows: list[dict[str, Any]] = []
    enrichment_top_rows: list[dict[str, Any]] = []
    enrichment_summary_rows: list[dict[str, Any]] = []
    importance_rows: list[dict[str, Any]] = []
    species_status = []

    for code in CASE_CODES:
        ds = DATASETS[code]
        try:
            print(f"[CASE5] {code}: loading expression matrix", flush=True)
            genes, mat, source_meta = load_expression_matrix(model8_root, code, ds)
            print(f"[CASE5] {code}: matrix genes={len(genes)} cells_or_samples={mat.shape[1] if mat.size else 0}", flush=True)
            phase1 = hvg_phase1(code, genes, mat)
            print(f"[CASE5] {code}: phase1 genes={len(phase1)}", flush=True)
            features = load_gene_features(model8_root, code)
            joined = join_hvg_features(code, phase1, features)
            mapped = int(joined["gene_id"].notna().sum()) if not joined.empty and "gene_id" in joined.columns else 0
            mapping_rate = mapped / max(1, len(joined))
            phase1["mapping_available"] = phase1["expression_gene_id"].isin(set(joined.loc[joined.get("gene_id", pd.Series(dtype=object)).notna(), "expression_gene_id"])) if not joined.empty else False
            joined.to_csv(output_dir / f"{code}_joined_hvg_stoich.csv.gz", index=False, compression="gzip")
            strict_phase2 = mapping_rate >= STRICT_MAPPING_THRESHOLD_PHASE2 and len(joined) >= 200
            enhanced_bridge_phase2 = (
                not strict_phase2
                and code in ENHANCED_BRIDGE_PHASE2_CODES
                and mapping_rate >= ENHANCED_BRIDGE_THRESHOLD_PHASE2
                and mapped >= 15000
                and len(joined) >= 200
            )
            complete_phase2 = strict_phase2 or enhanced_bridge_phase2
            phase2_mode = "strict_0.75" if strict_phase2 else ("enhanced_external_alias_boundary_0.70" if enhanced_bridge_phase2 else "blocked_mapping_boundary")
            m_rows: list[dict[str, Any]] = []
            p_rows: list[dict[str, Any]] = []
            per_rows: list[dict[str, Any]] = []
            if complete_phase2:
                print(f"[CASE5] {code}: phase2 {phase2_mode} path mapped={mapped} rate={mapping_rate:.3f}", flush=True)
                m_rows, p_rows, per_rows, joined2 = run_models(code, joined)
                joined2 = apply_standard_stoich_classification(code, joined2)
                cand, ctrl = candidate_and_controls(code, joined2)
                candidate_rows.extend(cand)
                control_rows.extend(ctrl)
                enrichment = functional_enrichment_bundle(code, joined2, output_dir)
                enrich_rows.extend(enrichment["ora"])
                gsea_rows.extend(enrichment["gsea"])
                enrichment_top_rows.extend(enrichment["top"])
                enrichment_summary_rows.append(enrichment["summary"])
                importance_rows.extend(feature_importance_rows(code, joined2))
                joined2.to_csv(output_dir / f"{code}_joined_hvg_stoich.csv.gz", index=False, compression="gzip")
            else:
                print(f"[CASE5] {code}: phase2 blocked mapped={mapped} rate={mapping_rate:.3f}", flush=True)
                m_rows = [{"case_code": code, "model_id": "B0-B3", "status": "blocked", "n_genes": mapped, "feature_count": "", "cv_r2": "", "spearman_r": "", "permutation_p_value": "", "permutation_repeats": 0, "minimum_resolvable_p_value": "", "reason": f"mapping_rate={mapping_rate:.3f} below strict {STRICT_MAPPING_THRESHOLD_PHASE2:.2f}/enhanced {ENHANCED_BRIDGE_THRESHOLD_PHASE2:.2f} policy or insufficient joined rows"}]
                enrichment_summary_rows.append({"case_code": code, "annotation_species_id": CASE_CODE_TO_SPECIES_ID.get(code, ""), "status": "skipped", "reason_code": "phase2_blocked_mapping_boundary"})
            model_rows.extend(m_rows)
            pred_rows.extend(p_rows)
            perm_rows.extend(per_rows)
            phase1_rows.extend(phase1.head(2000).to_dict("records"))
            method_rows.extend(method_concordance(code, phase1))
            species_status.append({
                "case_code": code,
                "accession": ds["accession"],
                "ingest_status": "complete",
                "phase1_status": "complete" if len(phase1) else "blocked",
                "phase2_status": "complete" if complete_phase2 else "blocked_mapping_boundary",
                "phase2_mode": phase2_mode,
                "genes_profiled": len(phase1),
                "cells_or_samples": int(mat.shape[1]) if mat.size else 0,
                "mapped_genes": mapped,
                "mapping_rate": round(mapping_rate, 6),
                "hvg_consensus_count": int(phase1["hvg_consensus"].sum()) if not phase1.empty else 0,
                "source_units": len(source_meta),
                "subsample_policy": "; ".join(sorted({str(m.get("subsampled")) for m in source_meta})),
                "notes": "" if strict_phase2 else ("Phase 2 completed under enhanced official-alias boundary policy; strict 0.75 mapping threshold not reached, unmapped IDs retained as boundary." if enhanced_bridge_phase2 else "Phase 1 retained; Phase 2 blocked/degraded by declared mapping threshold."),
            })
        except Exception as exc:
            print(f"[CASE5] {code}: failed {exc}", flush=True)
            species_status.append({"case_code": code, "accession": ds["accession"], "ingest_status": "failed", "phase1_status": "blocked", "phase2_status": "blocked", "phase2_mode": "failed", "genes_profiled": 0, "cells_or_samples": 0, "mapped_genes": 0, "mapping_rate": 0, "hvg_consensus_count": 0, "source_units": 0, "subsample_policy": "", "notes": str(exc)[:240]})

    write_csv(output_dir / "ingest_status.csv", species_status, ["case_code", "accession", "ingest_status", "phase1_status", "phase2_status", "phase2_mode", "genes_profiled", "cells_or_samples", "mapped_genes", "mapping_rate", "hvg_consensus_count", "source_units", "subsample_policy", "notes"])
    write_csv(output_dir / "expression_source_manifest.csv", ingest, ["case_code", "accession", "topic", "matrix_kind", "source_count", "bytes", "sha256_prefix", "ingest_status"])
    pd.DataFrame(phase1_rows).to_csv(output_dir / "hvg_consensus.csv", index=False)
    write_csv(output_dir / "method_concordance.csv", method_rows, ["case_code", "method_a", "method_b", "top_n", "intersection", "union", "jaccard"])
    write_csv(output_dir / "model_comparison.csv", model_rows, ["case_code", "model_id", "status", "n_genes", "feature_count", "cv_r2", "spearman_r", "permutation_p_value", "permutation_repeats", "minimum_resolvable_p_value", "reason"])
    write_csv(output_dir / "cv_predictions.csv", pred_rows, ["case_code", "model_id", "expression_gene_id", "observed_hvg_score", "predicted_hvg_score", "residual"])
    write_csv(output_dir / "permutation_results.csv", perm_rows, ["case_code", "model_id", "permutation_index", "null_cv_r2", "observed_cv_r2"])
    write_csv(output_dir / "candidate_genes.csv", candidate_rows, ["case_code", "rank", "expression_gene_id", "platform_gene_id", "protein_id", "gene_symbol", "hvg_score", "normalized_dispersion", "hvg_rank", "is_hvg", "bootstrap_stability", "stoich_class", "priority_score", "stoich_expected_var", "stoich_excess_var", "stoich_explained_fraction", "b3_residual", "m3_residual", "protein_n_atoms_per_aa", "protein_s_atoms_per_aa", "transcript_gc_fraction"])
    write_csv(output_dir / "matched_controls.csv", control_rows, ["case_code", "target_expression_gene_id", "control_expression_gene_id", "target_hvg_score", "control_hvg_score", "matching_distance"])
    enrichment_fields = ["case_code", "annotation_species_id", "query_label", "source", "term_id", "term_name", "namespace_or_type", "candidate_hits", "background_hits", "candidate_n", "background_n", "p_value", "fdr_bh", "fold_enrichment", "overlap_genes", "status", "method", "reason_code", "reason_message"]
    gsea_fields = ["case_code", "annotation_species_id", "source", "term_id", "term_name", "namespace_or_type", "term_gene_count", "ranked_gene_count", "es", "nes", "p_value", "fdr_bh", "fwer_p_value", "tag_fraction", "gene_fraction", "lead_genes", "status", "method", "permutation_num", "reason_code", "reason_message"]
    write_csv(output_dir / "enrichment_results.csv", enrichment_top_rows, enrichment_fields)
    write_csv(output_dir / "functional_enrichment_ora.csv", enrich_rows, enrichment_fields)
    write_csv(output_dir / "functional_enrichment_top_terms.csv", enrichment_top_rows, enrichment_fields)
    write_csv(output_dir / "functional_enrichment_gsea.csv", gsea_rows, gsea_fields)
    write_json(output_dir / "functional_enrichment_summary.json", enrichment_summary_rows)
    write_csv(output_dir / "feature_summary.csv", importance_rows, ["case_code", "feature", "permutation_importance", "importance_std", "cv_folds", "importance_repeats_per_fold", "importance_status", "spearman_with_hvg_score"])

    complete_phase2 = [row for row in species_status if row["phase2_status"] == "complete"]
    phase1_complete = [row for row in species_status if row["phase1_status"] == "complete"]
    downloads = []
    for path in sorted(output_dir.glob("*.csv")) + sorted(output_dir.glob("*.json")) + sorted(output_dir.glob("*.csv.gz")):
        downloads.append({"name": path.name, "path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)})

    phase1_payload = {
        "hvg_consensus_top": phase1_rows[:120],
        "method_concordance": method_rows,
        "species_status": species_status,
    }
    phase2_payload = {
        "model_comparison": model_rows,
        "feature_summary": importance_rows[:120],
        "permutation_count": len(perm_rows),
        "permutation_repeats": PERMUTATIONS,
        "minimum_resolvable_p_value": round(float(1.0 / (PERMUTATIONS + 1.0)), 6),
        "feature_importance_repeats_per_fold": FEATURE_IMPORTANCE_REPEATS,
        "hvg_method": HVG_METHOD,
        "hvg_score_semantics": "seurat_v3_variance_normalized",
        "hvg_loess_span": HVG_LOESS_SPAN,
        "functional_gsea_permutations": FUNCTIONAL_GSEA_PERMUTATIONS,
        "cv_prediction_preview": pred_rows[:120],
    }
    downstream_payload = {
        "candidate_genes": candidate_rows[:160],
        "matched_controls": control_rows[:120],
        "enrichment_results": enrichment_top_rows[:120],
        "functional_enrichment_ora": enrich_rows[:120],
        "functional_enrichment_gsea": gsea_rows[:120],
        "functional_enrichment_summary": enrichment_summary_rows,
    }
    write_json(output_dir / "phase1.json", phase1_payload)
    write_json(output_dir / "phase2.json", phase2_payload)
    write_json(output_dir / "downstream.json", downstream_payload)
    downloads = []
    for path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
        downloads.append({"name": str(path.relative_to(output_dir)), "path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)})
    summary = {
        "case_id": "model8_case5_hvg_stoich",
        "case_title": "Case 5. Eight-model-organism HVG-Stoich flagship system",
        "case_version": CASE5_VERSION,
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
        "status": "implemented_with_enhanced_official_alias_boundaries",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_question": "Do expression-derived highly variable genes show reproducible incremental association with versioned sequence stoichiometric features across model organisms?",
        "finding": f"{len(phase1_complete)} of 8 model-organism expression datasets completed HVG Phase 1; {len(complete_phase2)} completed mapped B0-B3 Case 5 Phase 2 block models with cross-validation and permutations. Strict 0.75 mapping remains the primary threshold; ORYSA may enter a documented enhanced official-alias boundary path at >=0.70 with >=15000 mapped genes, while MOUSE is evaluated only by the strict threshold and datasets below boundary are retained as explicit ingest/Phase-1 evidence.",
        "method": "Expression matrices were ingested from frozen GEO-derived local bundles, profiled with the project-standard Seurat v3/Scanpy normalized-variance HVG method, joined to versioned Model-8 transcript/protein stoichiometric feature bundles, classified with the current HVG-Stoich stoich_class logic, modeled with B0 expression baseline versus B1 transcript, B2 protein, and B3 combined stoichiometric blocks using K-fold CV plus target-permutation refits, and annotated with local PostgreSQL GO/KEGG standard records using ORA and prerank GSEA.",
        "acceptance": {
            "all_8_ingest_status": len(species_status) == 8,
            "phase1_complete_count": len(phase1_complete),
            "phase2_complete_count": len(complete_phase2),
            "meets_plan_minimum": len(phase1_complete) == 8 and len(complete_phase2) >= 4,
            "mapping_threshold_phase2": STRICT_MAPPING_THRESHOLD_PHASE2,
            "enhanced_bridge_threshold_phase2": ENHANCED_BRIDGE_THRESHOLD_PHASE2,
            "enhanced_bridge_phase2_codes": sorted(ENHANCED_BRIDGE_PHASE2_CODES),
            "bootstrap_repeats": BOOTSTRAPS,
            "target_permutation_repeats": PERMUTATIONS,
            "minimum_resolvable_p_value": round(float(1.0 / (PERMUTATIONS + 1.0)), 6),
            "hvg_method": HVG_METHOD,
            "hvg_score_semantics": "seurat_v3_variance_normalized",
            "functional_annotation_source": "PostgreSQL stoichdb GOAnnotation and KEGGAnnotationLink/KEGGGeneAnnotation standard records",
            "functional_gsea_permutations": FUNCTIONAL_GSEA_PERMUTATIONS,
        },
        "species_status": species_status,
        "full_database_feature_extractor_contract": extractor_contract,
        "downloads": downloads,
        "limitations": [
            "HVG-Stoich associations are descriptive and incremental; they do not prove causal regulation.",
            "Heavy single-cell sources are release-profiled with deterministic cell subsampling when needed; source manifests and subsampling status are recorded.",
            "Datasets with mapping below the declared threshold are blocked from Phase 2 rather than being forced into unsupported model claims.",
            "Functional enrichment uses available local PostgreSQL GO/KEGG standard annotations. Species without a local standard annotation universe are reported as skipped rather than predicted.",
        ],
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    out = Path(args.output_dir).resolve() if args.output_dir else root / "data" / "case_studies" / "model8" / "case5_hvg_stoich"
    summary = build_case5(root, out)
    print(json.dumps({
        "output_dir": str(out),
        "phase1_complete_count": summary["acceptance"]["phase1_complete_count"],
        "phase2_complete_count": summary["acceptance"]["phase2_complete_count"],
        "meets_plan_minimum": summary["acceptance"]["meets_plan_minimum"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
