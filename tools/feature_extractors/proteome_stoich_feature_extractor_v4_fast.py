#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proteome Stoichiometric Feature Extractor (Fast v4)

Optimizations relative to the previous version:
1. When full and core are both requested, the FASTA is read only once and the
   full feature row is computed once; the core row is sliced from the same row.
2. No pre-scan for FASTA record counts, so .gz inputs are no longer read twice
   just for progress display.
3. Progress is simplified to a lightweight whole-run display only.
4. The original chemical stoichiometry and feature definitions are kept intact.

Dependencies:
  pip install biopython
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from Bio.SeqUtils import ProtParamData
from Bio.SeqUtils.ProtParam import ProteinAnalysis


CANONICAL20 = list("ACDEFGHIKLMNPQRSTVWY")
CANONICAL20_SET = set(CANONICAL20)

RES_ATOMS: Dict[str, Dict[str, int]] = {
    "A": {"C": 3,  "H": 5,  "N": 1, "O": 1, "S": 0, "Se": 0},
    "R": {"C": 6,  "H": 12, "N": 4, "O": 1, "S": 0, "Se": 0},
    "N": {"C": 4,  "H": 6,  "N": 2, "O": 2, "S": 0, "Se": 0},
    "D": {"C": 4,  "H": 5,  "N": 1, "O": 3, "S": 0, "Se": 0},
    "C": {"C": 3,  "H": 5,  "N": 1, "O": 1, "S": 1, "Se": 0},
    "E": {"C": 5,  "H": 7,  "N": 1, "O": 3, "S": 0, "Se": 0},
    "Q": {"C": 5,  "H": 8,  "N": 2, "O": 2, "S": 0, "Se": 0},
    "G": {"C": 2,  "H": 3,  "N": 1, "O": 1, "S": 0, "Se": 0},
    "H": {"C": 6,  "H": 7,  "N": 3, "O": 1, "S": 0, "Se": 0},
    "I": {"C": 6,  "H": 11, "N": 1, "O": 1, "S": 0, "Se": 0},
    "L": {"C": 6,  "H": 11, "N": 1, "O": 1, "S": 0, "Se": 0},
    "K": {"C": 6,  "H": 12, "N": 2, "O": 1, "S": 0, "Se": 0},
    "M": {"C": 5,  "H": 9,  "N": 1, "O": 1, "S": 1, "Se": 0},
    "F": {"C": 9,  "H": 9,  "N": 1, "O": 1, "S": 0, "Se": 0},
    "P": {"C": 5,  "H": 7,  "N": 1, "O": 1, "S": 0, "Se": 0},
    "S": {"C": 3,  "H": 5,  "N": 1, "O": 2, "S": 0, "Se": 0},
    "T": {"C": 4,  "H": 7,  "N": 1, "O": 2, "S": 0, "Se": 0},
    "W": {"C": 11, "H": 10, "N": 2, "O": 1, "S": 0, "Se": 0},
    "Y": {"C": 9,  "H": 9,  "N": 1, "O": 2, "S": 0, "Se": 0},
    "V": {"C": 5,  "H": 9,  "N": 1, "O": 1, "S": 0, "Se": 0},
    "U": {"C": 3,  "H": 5,  "N": 1, "O": 1, "S": 0, "Se": 1},
    "O": {"C": 12, "H": 19, "N": 3, "O": 2, "S": 0, "Se": 0},
}

TERM_H2O = {"H": 2, "O": 1}
ATOMIC_WEIGHTS = {"C": 12.0107, "H": 1.00794, "N": 14.0067, "O": 15.9994, "S": 32.065, "Se": 78.96}


HEADER_PATTERNS = {
    "gene": re.compile(r"\bgene:([^\s]+)"),
    "transcript": re.compile(r"\btranscript:([^\s]+)"),
    "protein": re.compile(r"\bprotein:([^\s]+)"),
    "gene_symbol": re.compile(r"\bgene_symbol:([^\s]+)"),
    "description": re.compile(r"\bdescription:(.+)$"),
    "uniprot_gn": re.compile(r"\bGN=([^\s]+)"),
    "ncbi_gene": re.compile(r"\[gene=([^\]]+)\]"),
    "ncbi_locus": re.compile(r"\[locus_tag=([^\]]+)\]"),
    "ncbi_protein": re.compile(r"\[protein=([^\]]+)\]"),
    "refseq": re.compile(r"^(NP|YP|XP|WP)_\d+(\.\d+)?$"),
}

HYDROPHOBIC_SET = set("AILMFWVYP")
POLAR_SET = set("STNQCYG")
POS_SET = set("KRH")
NEG_SET = set("DE")
AROMATIC_SET = set("FWY")


def compute_feature_sets() -> Dict[str, List[str]]:
    id_cols = [
        "species_id",
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
    ]

    aa_pct_cols = [f"AA_{aa}_pct" for aa in CANONICAL20] + ["AA_other_pct"]

    core = id_cols + [
        "length_aa",
        "mw_da",
        "pI",
        "net_charge_pH7",
        "gravy",
        "aromaticity",
        "instability_index",
        "aliphatic_index",
        "aa_entropy_bits",
        "aa_hydrophobic_frac",
        "aa_polar_frac",
        "aa_pos_frac",
        "aa_neg_frac",
        "aa_aromatic_frac",
        "cys_count",
        "met_count",
        "sulfur_aa_frac",
        "C_atoms",
        "H_atoms",
        "N_atoms",
        "O_atoms",
        "S_atoms",
        "Se_atoms",
        "C_atoms_per_aa",
        "N_atoms_per_aa",
        "S_atoms_per_aa",
        "avg_oxidation_state_C",
        "C_N_ratio",
        "N_S_ratio",
        "O_C_ratio",
        "H_C_ratio",
    ] + aa_pct_cols

    qc_cols = [
        "length_canonical_aa",
        "noncanonical_aa",
        "X_count",
        "B_count",
        "Z_count",
        "J_count",
        "U_count",
        "O_count",
        "stop_asterisk_count",
        "seq_md5",
        "known_residues_for_atoms",
        "unknown_residues_for_atoms",
    ]

    aa_count_cols = [f"AA_{aa}_count" for aa in CANONICAL20] + ["AA_other_count"]

    full = id_cols + qc_cols + [
        "length_aa",
        "mw_da",
        "mw_atoms_da",
        "avg_residue_mass_da",
        "pI",
        "net_charge_pH7",
        "gravy",
        "aromaticity",
        "instability_index",
        "aliphatic_index",
        "ss_helix_frac",
        "ss_turn_frac",
        "ss_sheet_frac",
        "aa_entropy_bits",
        "aa_hydrophobic_frac",
        "aa_polar_frac",
        "aa_pos_frac",
        "aa_neg_frac",
        "aa_aromatic_frac",
        "cys_count",
        "met_count",
        "sulfur_aa_frac",
        "possible_disulfides",
        "disulfide_density",
        "C_atoms",
        "H_atoms",
        "N_atoms",
        "O_atoms",
        "S_atoms",
        "Se_atoms",
        "C_atoms_per_aa",
        "H_atoms_per_aa",
        "N_atoms_per_aa",
        "O_atoms_per_aa",
        "S_atoms_per_aa",
        "avg_oxidation_state_C",
        "C_N_ratio",
        "N_S_ratio",
        "O_C_ratio",
        "H_C_ratio",
        "O_N_ratio",
        "S_C_ratio",
        "N_C_ratio",
        "C_mass_frac",
        "N_mass_frac",
        "O_mass_frac",
        "S_mass_frac",
        "Se_mass_frac",
        "extinction_reduced",
        "extinction_cystines",
        "a280_1mgml_reduced",
        "a280_1mgml_cystines",
        "flex_mean",
        "flex_std",
        "flex_min",
        "flex_max",
        "hydrophilicity_hw_mean",
        "hydrophilicity_hw_std",
        "hydrophilicity_hw_min",
        "hydrophilicity_hw_max",
        "surface_access_em_mean",
        "surface_access_em_std",
        "surface_access_em_min",
        "surface_access_em_max",
    ] + aa_count_cols + aa_pct_cols + ["header_raw"]

    return {"core": core, "full": full}


FEATURE_SETS = compute_feature_sets()
CORE_COLS = FEATURE_SETS["core"]
FULL_COLS = FEATURE_SETS["full"]


class SimpleProgress:
    def __init__(self, label: str = "", every: int = 500, stream=None):
        self.label = label.strip()
        self.every = max(1, int(every))
        self.stream = stream or sys.stderr
        self.start_t = time.monotonic()
        self.last_shown = 0

    def update(self, n: int, force: bool = False) -> None:
        if (not force) and (n - self.last_shown < self.every):
            return
        self.last_shown = n
        elapsed = max(1e-12, time.monotonic() - self.start_t)
        rate = n / elapsed
        msg = f"\r{self.label}processed {n} proteins | {rate:7.1f}/s | elapsed {elapsed:8.1f}s"
        self.stream.write(msg[:220])
        self.stream.flush()

    def close(self, n: int) -> None:
        self.update(n, force=True)
        self.stream.write("\n")
        self.stream.flush()


# -----------------------------
# I/O helpers
# -----------------------------
def open_text_auto(path: str):
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path, "rt", encoding="utf-8", errors="replace")


def fasta_iter(fp) -> Iterator[Tuple[str, str]]:
    header = None
    seq_chunks: List[str] = []
    for line in fp:
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header is not None:
                yield header, "".join(seq_chunks)
            header = line
            seq_chunks = []
        else:
            seq_chunks.append(line)
    if header is not None:
        yield header, "".join(seq_chunks)


def md5_str(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


# -----------------------------
# Header parsing (IDs)
# -----------------------------
def parse_header(header: str) -> Dict[str, Optional[str]]:
    h = header[1:].strip()
    first = h.split()[0] if h else ""

    out: Dict[str, Optional[str]] = {
        "header_raw": h,
        "protein_id": first or None,
        "gene_id": None,
        "gene_symbol": None,
        "transcript_id": None,
        "source_db": None,
        "source_protein_id": first or None,
        "ensembl_gene_id": None,
        "ensembl_transcript_id": None,
        "ensembl_protein_id": None,
        "description": None,
    }

    m = HEADER_PATTERNS["gene"].search(h)
    if m:
        out["ensembl_gene_id"] = m.group(1)
    m = HEADER_PATTERNS["transcript"].search(h)
    if m:
        out["ensembl_transcript_id"] = m.group(1)
        out["transcript_id"] = out["ensembl_transcript_id"]
    m = HEADER_PATTERNS["protein"].search(h)
    if m:
        out["ensembl_protein_id"] = m.group(1)
    m = HEADER_PATTERNS["gene_symbol"].search(h)
    if m:
        out["gene_symbol"] = m.group(1)
    m = HEADER_PATTERNS["description"].search(h)
    if m:
        out["description"] = m.group(1).strip()

    if first and "|" in first and (first.startswith("sp|") or first.startswith("tr|") or first.count("|") >= 2):
        parts = first.split("|")
        if len(parts) >= 3:
            out["source_db"] = "uniprot"
            out["source_protein_id"] = parts[1]
            out["protein_id"] = parts[1]
        m = HEADER_PATTERNS["uniprot_gn"].search(h)
        if m:
            out["gene_symbol"] = out["gene_symbol"] or m.group(1)
        if out["description"] is None:
            rest = h.split(None, 1)[1] if len(h.split(None, 1)) == 2 else ""
            out["description"] = rest.strip() or None

    if out["source_db"] is None and first and HEADER_PATTERNS["refseq"].match(first):
        out["source_db"] = "refseq"
        out["source_protein_id"] = first

    m = HEADER_PATTERNS["ncbi_gene"].search(h)
    if m:
        out["gene_symbol"] = out["gene_symbol"] or m.group(1)
    m = HEADER_PATTERNS["ncbi_locus"].search(h)
    if m and not out["gene_symbol"]:
        out["gene_symbol"] = m.group(1)
    m = HEADER_PATTERNS["ncbi_protein"].search(h)
    if m and out["description"] is None:
        out["description"] = m.group(1)

    if first and first.startswith("ENS"):
        out["source_db"] = out["source_db"] or "ensembl"
        out["ensembl_protein_id"] = out["ensembl_protein_id"] or first

    if out["ensembl_gene_id"] or out["ensembl_transcript_id"] or out["ensembl_protein_id"]:
        out["source_db"] = out["source_db"] or "ensembl"

    if out["source_db"] == "ensembl" and not out["ensembl_protein_id"]:
        out["ensembl_protein_id"] = out["protein_id"]

    out["gene_id"] = out["gene_symbol"] or out["ensembl_gene_id"] or out["protein_id"]
    return out


# -----------------------------
# Feature computation
# -----------------------------
def safe_ratio(a: float, b: float) -> float:
    if b == 0:
        return float("nan")
    return a / b


def shannon_entropy(counts: Dict[str, int], total: int) -> float:
    if total <= 0:
        return float("nan")
    ent = 0.0
    for c in counts.values():
        if c <= 0:
            continue
        p = c / total
        ent -= p * math.log(p, 2)
    return ent


def profile_stats(xs: List[float]) -> Dict[str, float]:
    if not xs:
        return {"mean": float("nan"), "std": float("nan"), "min": float("nan"), "max": float("nan")}
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / len(xs)
    return {"mean": m, "std": math.sqrt(v), "min": min(xs), "max": max(xs)}


def element_counts_from_seq(seq: str) -> Dict[str, int]:
    cnt = Counter(seq)
    atoms = {k: 0 for k in ["C", "H", "N", "O", "S", "Se"]}
    known_res = 0
    for aa, n in cnt.items():
        if aa in RES_ATOMS:
            known_res += n
            comp = RES_ATOMS[aa]
            for el in atoms.keys():
                atoms[el] += comp[el] * n

    if known_res > 0:
        atoms["H"] += TERM_H2O["H"]
        atoms["O"] += TERM_H2O["O"]

    atoms["known_residues_for_atoms"] = known_res
    atoms["unknown_residues_for_atoms"] = len(seq) - known_res
    return atoms


def avg_oxidation_state_carbon(atoms: Dict[str, int]) -> float:
    C = atoms.get("C", 0)
    if C <= 0:
        return float("nan")
    H = atoms.get("H", 0)
    N = atoms.get("N", 0)
    O = atoms.get("O", 0)
    S = atoms.get("S", 0)
    Se = atoms.get("Se", 0)
    return (-H + 3 * N + 2 * O + 2 * S + 2 * Se) / C


def molecular_weight_from_atoms(atoms: Dict[str, int]) -> float:
    return sum(atoms.get(el, 0) * ATOMIC_WEIGHTS[el] for el in ["C", "H", "N", "O", "S", "Se"])


def aliphatic_index_from_counts(aa_counts: Dict[str, int], length: int) -> float:
    if length <= 0:
        return float("nan")
    a = aa_counts.get("A", 0) / length * 100.0
    v = aa_counts.get("V", 0) / length * 100.0
    i = aa_counts.get("I", 0) / length * 100.0
    l = aa_counts.get("L", 0) / length * 100.0
    return a + 2.9 * v + 3.9 * (i + l)


def compute_features(seq_raw: str, feature_mode: str = "full") -> Dict[str, object]:
    seq0 = re.sub(r"\s+", "", seq_raw).upper()
    stop_cnt = seq0.count("*")
    seq = seq0.replace("*", "")

    aa_counts = Counter(seq)
    length_all = len(seq)

    x_count = aa_counts.get("X", 0)
    b_count = aa_counts.get("B", 0)
    z_count = aa_counts.get("Z", 0)
    j_count = aa_counts.get("J", 0)
    u_count = aa_counts.get("U", 0)
    o_count = aa_counts.get("O", 0)

    length_canonical = sum(aa_counts.get(aa, 0) for aa in CANONICAL20_SET)
    noncanonical = length_all - length_canonical
    seq_canon = "".join([aa for aa in seq if aa in CANONICAL20_SET])

    atoms = element_counts_from_seq(seq)
    zc = avg_oxidation_state_carbon(atoms)
    mw_atoms = molecular_weight_from_atoms(atoms) if atoms["known_residues_for_atoms"] > 0 else float("nan")

    full_mode = feature_mode == "full"

    if len(seq_canon) > 0:
        pa = ProteinAnalysis(seq_canon)
        mw = float(pa.molecular_weight())
        gravy = float(pa.gravy())
        aromaticity = float(pa.aromaticity())
        pI = float(pa.isoelectric_point())
        instab = float(pa.instability_index())
        charge7 = float(pa.charge_at_pH(7.0))

        if full_mode:
            helix, turn, sheet = [float(x) for x in pa.secondary_structure_fraction()]
            ext_red, ext_cys = pa.molar_extinction_coefficient()
            ext_red = float(ext_red)
            ext_cys = float(ext_cys)
            flex_prof = [float(x) for x in pa.flexibility()]
            hw_prof = [float(x) for x in pa.protein_scale(ProtParamData.hw, window=7, edge=1.0)]
            em_prof = [float(x) for x in pa.protein_scale(ProtParamData.em, window=6, edge=1.0)]
        else:
            helix = turn = sheet = float("nan")
            ext_red = ext_cys = float("nan")
            flex_prof = []
            hw_prof = []
            em_prof = []
    else:
        mw = gravy = aromaticity = pI = instab = charge7 = float("nan")
        helix = turn = sheet = float("nan")
        ext_red = ext_cys = float("nan")
        flex_prof = []
        hw_prof = []
        em_prof = []

    aa_counts_20 = {aa: aa_counts.get(aa, 0) for aa in CANONICAL20}
    ent = shannon_entropy(aa_counts_20, length_canonical)
    alip = aliphatic_index_from_counts(aa_counts, length_all)

    def frac(s: set) -> float:
        return (sum(aa_counts.get(a, 0) for a in s) / length_all) if length_all else float("nan")

    cys = int(aa_counts.get("C", 0))
    met = int(aa_counts.get("M", 0))
    sulfur_frac = (cys + met + int(aa_counts.get("U", 0))) / length_all if length_all else float("nan")

    C = atoms.get("C", 0)
    H = atoms.get("H", 0)
    N = atoms.get("N", 0)
    O = atoms.get("O", 0)
    S = atoms.get("S", 0)
    Se = atoms.get("Se", 0)

    C_N = safe_ratio(C, N)
    N_S = safe_ratio(N, S)
    O_C = safe_ratio(O, C)
    H_C = safe_ratio(H, C)
    O_N = safe_ratio(O, N)
    S_C = safe_ratio(S, C)
    N_C = safe_ratio(N, C)

    C_per = safe_ratio(C, length_all)
    H_per = safe_ratio(H, length_all)
    N_per = safe_ratio(N, length_all)
    O_per = safe_ratio(O, length_all)
    S_per = safe_ratio(S, length_all)

    if isinstance(mw_atoms, float) and not math.isnan(mw_atoms) and mw_atoms > 0:
        C_mf = (C * ATOMIC_WEIGHTS["C"]) / mw_atoms
        N_mf = (N * ATOMIC_WEIGHTS["N"]) / mw_atoms
        O_mf = (O * ATOMIC_WEIGHTS["O"]) / mw_atoms
        S_mf = (S * ATOMIC_WEIGHTS["S"]) / mw_atoms
        Se_mf = (Se * ATOMIC_WEIGHTS["Se"]) / mw_atoms
    else:
        C_mf = N_mf = O_mf = S_mf = Se_mf = float("nan")

    avg_res_mass = (mw / length_all) if (length_all and isinstance(mw, float) and not math.isnan(mw)) else float("nan")
    possible_disulfides = cys // 2
    disulfide_density = possible_disulfides / length_all if length_all else float("nan")

    if full_mode:
        flex_s = profile_stats(flex_prof)
        hw_s = profile_stats(hw_prof)
        em_s = profile_stats(em_prof)
        if isinstance(mw, float) and not math.isnan(mw) and mw > 0:
            a280_red = ext_red / mw if not math.isnan(ext_red) else float("nan")
            a280_cys = ext_cys / mw if not math.isnan(ext_cys) else float("nan")
        else:
            a280_red = a280_cys = float("nan")
    else:
        flex_s = {"mean": float("nan"), "std": float("nan"), "min": float("nan"), "max": float("nan")}
        hw_s = {"mean": float("nan"), "std": float("nan"), "min": float("nan"), "max": float("nan")}
        em_s = {"mean": float("nan"), "std": float("nan"), "min": float("nan"), "max": float("nan")}
        a280_red = a280_cys = float("nan")

    aa_other_count = int(sum(v for k, v in aa_counts.items() if k not in CANONICAL20_SET))

    feats: Dict[str, object] = {
        "length_aa": int(length_all),
        "length_canonical_aa": int(length_canonical),
        "noncanonical_aa": int(noncanonical),
        "X_count": int(x_count),
        "B_count": int(b_count),
        "Z_count": int(z_count),
        "J_count": int(j_count),
        "U_count": int(u_count),
        "O_count": int(o_count),
        "stop_asterisk_count": int(stop_cnt),
        "seq_md5": md5_str(seq) if length_all else "",
        "mw_da": mw,
        "mw_atoms_da": mw_atoms,
        "avg_residue_mass_da": avg_res_mass,
        "pI": pI,
        "net_charge_pH7": charge7,
        "gravy": gravy,
        "aromaticity": aromaticity,
        "instability_index": instab,
        "aliphatic_index": alip,
        "ss_helix_frac": helix,
        "ss_turn_frac": turn,
        "ss_sheet_frac": sheet,
        "aa_entropy_bits": ent,
        "aa_hydrophobic_frac": frac(HYDROPHOBIC_SET),
        "aa_polar_frac": frac(POLAR_SET),
        "aa_pos_frac": frac(POS_SET),
        "aa_neg_frac": frac(NEG_SET),
        "aa_aromatic_frac": frac(AROMATIC_SET),
        "cys_count": int(cys),
        "met_count": int(met),
        "sulfur_aa_frac": sulfur_frac,
        "possible_disulfides": int(possible_disulfides),
        "disulfide_density": disulfide_density,
        "C_atoms": int(C),
        "H_atoms": int(H),
        "N_atoms": int(N),
        "O_atoms": int(O),
        "S_atoms": int(S),
        "Se_atoms": int(Se),
        "known_residues_for_atoms": int(atoms["known_residues_for_atoms"]),
        "unknown_residues_for_atoms": int(atoms["unknown_residues_for_atoms"]),
        "C_atoms_per_aa": C_per,
        "H_atoms_per_aa": H_per,
        "N_atoms_per_aa": N_per,
        "O_atoms_per_aa": O_per,
        "S_atoms_per_aa": S_per,
        "avg_oxidation_state_C": zc,
        "C_N_ratio": C_N,
        "N_S_ratio": N_S,
        "O_C_ratio": O_C,
        "H_C_ratio": H_C,
        "O_N_ratio": O_N,
        "S_C_ratio": S_C,
        "N_C_ratio": N_C,
        "C_mass_frac": C_mf,
        "N_mass_frac": N_mf,
        "O_mass_frac": O_mf,
        "S_mass_frac": S_mf,
        "Se_mass_frac": Se_mf,
        "extinction_reduced": ext_red,
        "extinction_cystines": ext_cys,
        "a280_1mgml_reduced": a280_red,
        "a280_1mgml_cystines": a280_cys,
        "flex_mean": flex_s["mean"],
        "flex_std": flex_s["std"],
        "flex_min": flex_s["min"],
        "flex_max": flex_s["max"],
        "hydrophilicity_hw_mean": hw_s["mean"],
        "hydrophilicity_hw_std": hw_s["std"],
        "hydrophilicity_hw_min": hw_s["min"],
        "hydrophilicity_hw_max": hw_s["max"],
        "surface_access_em_mean": em_s["mean"],
        "surface_access_em_std": em_s["std"],
        "surface_access_em_min": em_s["min"],
        "surface_access_em_max": em_s["max"],
    }

    for aa in CANONICAL20:
        c = int(aa_counts.get(aa, 0))
        if full_mode:
            feats[f"AA_{aa}_count"] = c
        feats[f"AA_{aa}_pct"] = (c / length_all * 100.0) if length_all else float("nan")

    if full_mode:
        feats["AA_other_count"] = int(aa_other_count)
    feats["AA_other_pct"] = (aa_other_count / length_all * 100.0) if length_all else float("nan")
    return feats


# -----------------------------
# Batch helpers + writer
# -----------------------------
def infer_species_id_from_filename(path: Path, pattern: str) -> str:
    name = path.name
    m = re.search(pattern, name)
    if m and m.group(1):
        return m.group(1)
    return path.stem


def list_fasta_files(batch_dir: str) -> List[Path]:
    paths: List[Path] = []
    for p in Path(batch_dir).rglob("*"):
        if p.is_file():
            name = p.name.lower()
            if name.endswith((
                ".fa", ".faa", ".fasta", ".pep", ".protein", ".proteome",
                ".fa.gz", ".faa.gz", ".fasta.gz"
            )):
                paths.append(p)
    return sorted(paths)


def project_row(row: Dict[str, object], cols: List[str]) -> Dict[str, object]:
    return {k: row.get(k, "") for k in cols}


def write_features_for_fasta(
    fasta_path: str,
    species_id: str,
    out_csv: str = "",
    feature_set: str = "full",
    append: bool = False,
    progress: bool = True,
    progress_every: int = 500,
    out_full_csv: str = "",
    out_core_csv: str = "",
) -> Dict[str, object]:
    """
    Compatible wrapper.
    - If feature_set is 'full' or 'core', writes one table to out_csv (legacy behavior).
    - If feature_set is 'both', writes out_full_csv and/or out_core_csv in one pass.
    """
    feature_set = str(feature_set).lower()
    if feature_set not in {"core", "full", "both"}:
        raise ValueError("feature_set must be one of: core, full, both")

    emit_full = feature_set in {"full", "both"}
    emit_core = feature_set in {"core", "both"}

    if feature_set == "full" and not out_csv:
        raise ValueError("out_csv is required for feature_set='full'")
    if feature_set == "core" and not out_csv:
        raise ValueError("out_csv is required for feature_set='core'")
    if feature_set == "both" and not (out_full_csv or out_core_csv):
        raise ValueError("for feature_set='both', provide out_full_csv and/or out_core_csv")

    if feature_set == "full":
        out_full_csv = out_csv
    elif feature_set == "core":
        out_core_csv = out_csv

    if out_full_csv:
        os.makedirs(str(Path(out_full_csv).parent), exist_ok=True)
    if out_core_csv:
        os.makedirs(str(Path(out_core_csv).parent), exist_ok=True)

    mode = "a" if append else "w"
    pb = SimpleProgress(label=f"{species_id} ", every=progress_every, stream=sys.stderr) if progress else None

    n = 0
    length_list: List[int] = []

    fout_full = open(out_full_csv, mode, newline="", encoding="utf-8") if out_full_csv else None
    fout_core = open(out_core_csv, mode, newline="", encoding="utf-8") if out_core_csv else None

    try:
        writer_full = csv.DictWriter(fout_full, fieldnames=FULL_COLS, extrasaction="ignore") if fout_full else None
        writer_core = csv.DictWriter(fout_core, fieldnames=CORE_COLS, extrasaction="ignore") if fout_core else None

        if writer_full and not append:
            writer_full.writeheader()
        if writer_core and not append:
            writer_core.writeheader()

        compute_mode = "full" if emit_full else "core"

        with open_text_auto(fasta_path) as fp:
            for header, seq in fasta_iter(fp):
                meta = parse_header(header)
                if not meta.get("gene_id"):
                    meta["gene_id"] = meta.get("protein_id")

                feats = compute_features(seq, feature_mode=compute_mode)
                row: Dict[str, object] = {"species_id": species_id}
                row.update(meta)
                row.update(feats)

                if writer_full:
                    writer_full.writerow(project_row(row, FULL_COLS))
                if writer_core:
                    writer_core.writerow(project_row(row, CORE_COLS))

                n += 1
                length_list.append(int(feats["length_aa"]))
                if pb:
                    pb.update(n)
    finally:
        if fout_full:
            fout_full.close()
        if fout_core:
            fout_core.close()
        if pb:
            pb.close(n)

    summary = {
        "species_id": species_id,
        "fasta_path": fasta_path,
        "n_proteins": n,
        "length_mean": (sum(length_list) / len(length_list)) if length_list else float("nan"),
        "length_min": int(min(length_list)) if length_list else None,
        "length_max": int(max(length_list)) if length_list else None,
        "emitted": {
            "full": str(out_full_csv) if out_full_csv else None,
            "core": str(out_core_csv) if out_core_csv else None,
        },
    }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Proteome stoichiometric feature extraction (fast; single or batch).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--fasta", type=str, default="", help="Protein FASTA path (aa), optional .gz.")
    ap.add_argument("--species-id", type=str, default="", help="Species identifier for single run.")

    # Legacy single-output arguments
    ap.add_argument("--out", type=str, default="", help="Legacy single output CSV path.")
    ap.add_argument("--feature-set", type=str, choices=["core", "full", "both"], default="full", help="Output column set.")

    # New dual-output arguments
    ap.add_argument("--emit", nargs="+", choices=["full", "core"], default=None, help="Emit one or both tables in one pass.")
    ap.add_argument("--out-full", type=str, default="", help="Full-table CSV output path.")
    ap.add_argument("--out-core", type=str, default="", help="Core-table CSV output path.")
    ap.add_argument("--summary-json", type=str, default="", help="Write per-species summary JSON to this path.")

    ap.add_argument("--no-progress", action="store_true", help="Disable progress display.")
    ap.add_argument("--progress-every", type=int, default=500, help="Refresh cadence in processed proteins.")

    # Batch mode kept for compatibility; still serial here.
    ap.add_argument("--batch-dir", type=str, default="", help="Directory containing multiple FASTA files (multi-species).")
    ap.add_argument("--out-dir", type=str, default="", help="Output directory for batch mode.")
    ap.add_argument("--combine", action="store_true", help="In batch mode, append all species into one CSV (legacy single-output mode only).")
    ap.add_argument(
        "--species-regex",
        type=str,
        default=r"^(.+?)\.(pep|protein|proteome|faa|fa|fasta)\b",
        help="Regex with 1 capturing group to infer species_id from filename.",
    )

    args = ap.parse_args()
    progress_enabled = not args.no_progress
    summaries: List[Dict[str, object]] = []

    # Decide emit mode
    emit = args.emit if args.emit else [args.feature_set] if args.feature_set != "both" else ["full", "core"]
    emit = list(dict.fromkeys(emit))
    emit_full = "full" in emit
    emit_core = "core" in emit

    if args.batch_dir:
        fasta_files = list_fasta_files(args.batch_dir)
        if not fasta_files:
            raise SystemExit(f"No FASTA files found under: {args.batch_dir}")

        if args.combine and len(emit) != 1:
            raise SystemExit("--combine is only supported for emitting exactly one table type.")

        if args.combine:
            first = True
            for fp in fasta_files:
                sid = infer_species_id_from_filename(fp, args.species_regex)
                summary = write_features_for_fasta(
                    fasta_path=str(fp),
                    species_id=sid,
                    out_csv=args.out,
                    feature_set=emit[0],
                    append=not first,
                    progress=progress_enabled,
                    progress_every=args.progress_every,
                )
                summaries.append(summary)
                first = False
        else:
            out_dir = args.out_dir or str(Path(args.out).parent or ".")
            os.makedirs(out_dir, exist_ok=True)
            for fp in fasta_files:
                sid = infer_species_id_from_filename(fp, args.species_regex)
                out_full = str(Path(out_dir) / f"{sid}.proteome_features.full.csv") if emit_full else ""
                out_core = str(Path(out_dir) / f"{sid}.proteome_features.core.csv") if emit_core else ""
                feature_mode = "both" if (emit_full and emit_core) else emit[0]
                summary = write_features_for_fasta(
                    fasta_path=str(fp),
                    species_id=sid,
                    feature_set=feature_mode,
                    out_full_csv=out_full,
                    out_core_csv=out_core,
                    append=False,
                    progress=progress_enabled,
                    progress_every=args.progress_every,
                )
                summaries.append(summary)

        if args.summary_json:
            os.makedirs(str(Path(args.summary_json).parent), exist_ok=True)
            with open(args.summary_json, "w", encoding="utf-8") as f:
                json.dump({"summaries": summaries}, f, ensure_ascii=False, indent=2)
        return

    if not args.fasta:
        raise SystemExit("Provide --fasta for single mode, or --batch-dir for batch mode.")

    fasta_path = args.fasta
    species_id = args.species_id or infer_species_id_from_filename(Path(fasta_path), args.species_regex)

    if emit_full and emit_core:
        if not args.out_full or not args.out_core:
            raise SystemExit("When emitting both full and core, provide both --out-full and --out-core.")
        summary = write_features_for_fasta(
            fasta_path=fasta_path,
            species_id=species_id,
            feature_set="both",
            out_full_csv=args.out_full,
            out_core_csv=args.out_core,
            append=False,
            progress=progress_enabled,
            progress_every=args.progress_every,
        )
    else:
        single_mode = emit[0]
        target_out = args.out_full if single_mode == "full" else args.out_core
        if not target_out:
            target_out = args.out
        if not target_out:
            raise SystemExit("Provide an output path via --out, or --out-full/--out-core.")
        summary = write_features_for_fasta(
            fasta_path=fasta_path,
            species_id=species_id,
            out_csv=target_out,
            feature_set=single_mode,
            append=False,
            progress=progress_enabled,
            progress_every=args.progress_every,
        )

    if args.summary_json:
        os.makedirs(str(Path(args.summary_json).parent), exist_ok=True)
        with open(args.summary_json, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
