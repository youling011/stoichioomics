#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Transcriptome Stoichiometric Feature Extractor (v5.1)
===================================================

Goal
----
Produce TWO tables (schemas) from transcriptome FASTA:

1) Full table (feature-set=full): the complete stoichiometric + pattern + ORF/protein feature set
   (matches your current "ultra" outputs; LZ removed).

2) Core table (feature-set=core): a concise, clean subset for frontend charts/query AND
   directly usable numeric features for ML/DL.

Design constraints
------------------
- Element rule: ONLY RNA_NMP (AMP/CMP/GMP/UMP), with T->U normalization.
- Core columns are a strict SUBSET of full columns: 1-to-1 mapping by identical column names.
- Stable CSV schema per feature-set (fixed columns; missing values written as empty string).
- Batch species support: directory + glob OR manifest (species_id,fasta_path,genetic_code).
- Genetic code configurable per species (NCBI translation table id).

Dependencies
------------
pip install biopython tqdm

Typical usage
-------------
# Full (complete) table
python transcriptome_stoich_feature_extractor_v5_1.py \
  --input ecoli.cdna.all.fa --species-id ecoli --genetic-code 11 \
  --feature-set full --orf-mode longest --out ecoli.transcriptome.full.csv

# Core (concise) table
python transcriptome_stoich_feature_extractor_v5_1.py \
  --input ecoli.cdna.all.fa --species-id ecoli --genetic-code 11 \
  --feature-set core --orf-mode longest --out ecoli.transcriptome.core.csv

# Batch with manifest
python transcriptome_stoich_feature_extractor_v5_1.py \
  --manifest manifest.tsv --out ./out_dir --feature-set both --orf-mode longest
"""

from __future__ import annotations

import argparse
import bz2
import csv
import gzip
import json
import lzma
import math
import multiprocessing
import re
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from queue import Empty
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.Data import CodonTable
from Bio.SeqUtils.ProtParam import ProteinAnalysis

try:
    from tqdm import tqdm
except Exception:
    tqdm = None


# -----------------------------
# Constants
# -----------------------------
RNA_BASES = ("A", "C", "G", "U")

# RNA NMP formulas (AMP/CMP/GMP/UMP)
RNA_NMP_FORMULAS: Dict[str, Dict[str, int]] = {
    "A": {"C": 10, "H": 14, "N": 5, "O": 7, "P": 1},
    "C": {"C": 9,  "H": 14, "N": 3, "O": 8, "P": 1},
    "G": {"C": 10, "H": 14, "N": 5, "O": 8, "P": 1},
    "U": {"C": 9,  "H": 13, "N": 2, "O": 9, "P": 1},
}

ATOMIC_WEIGHTS = {
    "C": 12.011,
    "H": 1.008,
    "O": 15.999,
    "N": 14.007,
    "P": 30.974,
}

AA20 = "ACDEFGHIKLMNPQRSTVWY"


# -----------------------------
# Small utils
# -----------------------------
def safe_div(a: float, b: float) -> float:
    return float(a) / float(b) if b else float("nan")


def shannon_entropy(counts: Dict[str, int]) -> float:
    total = sum(counts.values())
    if total <= 0:
        return float("nan")
    ent = 0.0
    for c in counts.values():
        if c <= 0:
            continue
        p = c / total
        ent -= p * math.log(p, 2)
    return ent


def normalize_seq_to_rna(seq: str) -> str:
    return str(seq).upper().replace("T", "U")


def normalize_seq_to_dna(seq: str) -> str:
    return str(seq).upper().replace("U", "T")


def as_bool_str(x: bool) -> str:
    return "1" if x else "0"


def clean_rna(seq_rna: str) -> str:
    return "".join(ch for ch in seq_rna if ch in RNA_BASES)


# -----------------------------
# Core feature primitives
# -----------------------------
def count_bases_rna(seq_rna: str) -> Dict[str, int]:
    counts = {b: 0 for b in RNA_BASES}
    n_amb = 0
    n_other = 0
    for ch in seq_rna:
        if ch in counts:
            counts[ch] += 1
        elif ch == "N":
            n_amb += 1
        else:
            n_other += 1
    counts["N"] = n_amb
    counts["OTHER"] = n_other
    counts["LEN_TOTAL"] = sum(counts.values())
    counts["LEN_ACGU"] = sum(counts[b] for b in RNA_BASES)
    return counts


def elemental_atoms_from_counts_rna_nmp(counts: Dict[str, int]) -> Tuple[Dict[str, int], float]:
    totals = {e: 0 for e in ATOMIC_WEIGHTS.keys()}
    for base in RNA_BASES:
        n = counts.get(base, 0)
        for e, k in RNA_NMP_FORMULAS[base].items():
            totals[e] += k * n
    mw = sum(totals[e] * ATOMIC_WEIGHTS[e] for e in totals)
    return totals, mw


def dinuc_keys_rna() -> List[str]:
    return [a + b for a in RNA_BASES for b in RNA_BASES]


def dinuc_freqs_rna(seq_rna: str) -> Dict[str, float]:
    keys = dinuc_keys_rna()
    counts = {k: 0 for k in keys}
    valid = 0
    for i in range(len(seq_rna) - 1):
        a, b = seq_rna[i], seq_rna[i + 1]
        if a in RNA_BASES and b in RNA_BASES:
            counts[a + b] += 1
            valid += 1
    out = {f"dinuc_{k}_freq": safe_div(v, valid) for k, v in counts.items()}
    out["dinuc_valid_pairs"] = valid
    return out


def dinuc_bias_rna(seq_rna: str) -> Dict[str, float]:
    """
    bias0: obs_freq - p(x)p(y), where p is mono frequency over A/C/G/U.
    """
    keys = dinuc_keys_rna()
    mono = {b: 0 for b in RNA_BASES}
    for ch in seq_rna:
        if ch in mono:
            mono[ch] += 1
    mono_total = sum(mono.values())

    df = dinuc_freqs_rna(seq_rna)
    out: Dict[str, float] = {}
    for k in keys:
        a, b = k[0], k[1]
        exp = safe_div(mono[a], mono_total) * safe_div(mono[b], mono_total)
        out[f"dinuc_{k}_bias0"] = df[f"dinuc_{k}_freq"] - exp if not math.isnan(df[f"dinuc_{k}_freq"]) else float("nan")
    return out


def avg_spacing(seq: str, base: str) -> float:
    pos = [i for i, ch in enumerate(seq) if ch == base]
    if len(pos) < 2:
        return float("nan")
    diffs = [pos[i] - pos[i - 1] for i in range(1, len(pos))]
    return float(sum(diffs) / len(diffs))


def max_homopolymer_run(seq: str, base: str) -> int:
    best = 0
    cur = 0
    for ch in seq:
        if ch == base:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


# -----------------------------
# ORF / protein features
# -----------------------------
@lru_cache(maxsize=None)
def get_codon_table(table_id: int) -> CodonTable.CodonTable:
    return CodonTable.unambiguous_dna_by_id[int(table_id)]


def find_longest_orf(seq_dna: str, table_id: int, start_codons: Optional[List[str]] = None,
                     allow_no_stop: bool = True) -> Optional[Dict[str, object]]:
    s = normalize_seq_to_dna(seq_dna)
    table = get_codon_table(table_id)
    stops = set(table.stop_codons)
    starts = set(start_codons) if start_codons else set(table.start_codons)

    best = None  # (len_nt, frame, start, end, has_stop)
    n = len(s)
    for frame in (0, 1, 2):
        i = frame
        while i + 3 <= n:
            codon = s[i:i + 3]
            if codon in starts:
                j = i
                k_end = None
                while j + 3 <= n:
                    c = s[j:j + 3]
                    if c in stops and j > i:
                        k_end = j + 3
                        break
                    j += 3
                if k_end is not None:
                    cand = (k_end - i, frame, i, k_end, True)
                    if best is None or cand[0] > best[0]:
                        best = cand
                else:
                    if allow_no_stop:
                        end = n - ((n - frame) % 3)
                        if end - i >= 3:
                            cand = (end - i, frame, i, end, False)
                            if best is None or cand[0] > best[0]:
                                best = cand
                i += 3
            else:
                i += 3

    if best is None:
        return None
    length, frame, start, end, has_stop = best
    orf_dna = s[start:end]
    aa = str(Seq(orf_dna).translate(table=table_id, to_stop=True))
    return {
        "orf_len_nt": int(length),
        "orf_len_aa": int(len(aa)),
        "orf_frame": int(frame),
        "orf_start": int(start),
        "orf_end": int(end),
        "orf_has_stop": bool(has_stop),
        "orf_dna": orf_dna,
        "orf_aa": aa,
    }


def codon_keys_rna() -> List[str]:
    return [a + b + c for a in RNA_BASES for b in RNA_BASES for c in RNA_BASES]


def codon_freqs_rna_from_orf_dna(orf_dna: str) -> Tuple[Dict[str, float], Dict[str, int]]:
    keys = codon_keys_rna()
    counts = {k: 0 for k in keys}
    valid = 0
    s = normalize_seq_to_dna(orf_dna)
    s = s[:len(s) - (len(s) % 3)]
    for i in range(0, len(s), 3):
        codon_dna = s[i:i + 3]
        if len(codon_dna) == 3 and all(ch in "ACGT" for ch in codon_dna):
            codon_rna = codon_dna.replace("T", "U")
            counts[codon_rna] += 1
            valid += 1
    freqs = {f"codon_{k}_freq": safe_div(v, valid) for k, v in counts.items()}
    freqs["codon_valid_codons"] = valid
    return freqs, counts


def codon_bias0_from_orf_counts(codon_counts: Dict[str, int]) -> Dict[str, float]:
    keys = codon_keys_rna()
    total_codons = sum(codon_counts.values())
    if total_codons <= 0:
        return {f"codon_{k}_bias0": float("nan") for k in keys}

    mono = {b: 0 for b in RNA_BASES}
    for codon, ct in codon_counts.items():
        mono[codon[0]] += ct
        mono[codon[1]] += ct
        mono[codon[2]] += ct
    mono_total = sum(mono.values())  # 3 * total_codons

    out = {}
    for k in keys:
        obs = safe_div(codon_counts.get(k, 0), total_codons)
        exp = safe_div(mono[k[0]], mono_total) * safe_div(mono[k[1]], mono_total) * safe_div(mono[k[2]], mono_total)
        out[f"codon_{k}_bias0"] = obs - exp
    return out


def aa_freqs(protein_seq: str) -> Dict[str, float]:
    counts = {aa: 0 for aa in AA20}
    for ch in protein_seq:
        if ch in counts:
            counts[ch] += 1
    total = sum(counts.values())
    out: Dict[str, float] = {"aa_len": int(total)}
    for aa in AA20:
        out[f"aa_{aa}_freq"] = safe_div(counts[aa], total)
    return out


def aa_counts_and_freqs(protein_seq: str) -> Dict[str, float]:
    counts = {aa: 0 for aa in AA20}
    for ch in protein_seq:
        if ch in counts:
            counts[ch] += 1
    total = sum(counts.values())
    out: Dict[str, float] = {"aa_len": int(total)}
    for aa in AA20:
        out[f"aa_{aa}_count"] = int(counts[aa])
    for aa in AA20:
        out[f"aa_{aa}_freq"] = safe_div(counts[aa], total)
    return out



def sanitize_protein_seq(protein_seq: str) -> str:
    """
    Keep only the 20 standard amino acids for ProtParam.
    Ambiguous translated residues such as X are dropped so that
    ProteinAnalysis does not crash on real-world transcript sequences
    containing ambiguous nucleotides inside the inferred ORF.
    """
    return "".join(ch for ch in str(protein_seq).upper() if ch in AA20)


def protein_basic_props(protein_seq: str) -> Dict[str, float]:
    clean_protein_seq = sanitize_protein_seq(protein_seq)
    if not clean_protein_seq:
        return {
            "protein_mw_Da": float("nan"),
            "protein_aromaticity": float("nan"),
            "protein_instability_index": float("nan"),
            "protein_gravy": float("nan"),
            "protein_isoelectric_point": float("nan"),
        }
    try:
        pa = ProteinAnalysis(clean_protein_seq)
        return {
            "protein_mw_Da": float(pa.molecular_weight()),
            "protein_aromaticity": float(pa.aromaticity()),
            "protein_instability_index": float(pa.instability_index()),
            "protein_gravy": float(pa.gravy()),
            "protein_isoelectric_point": float(pa.isoelectric_point()),
        }
    except Exception:
        return {
            "protein_mw_Da": float("nan"),
            "protein_aromaticity": float("nan"),
            "protein_instability_index": float("nan"),
            "protein_gravy": float("nan"),
            "protein_isoelectric_point": float("nan"),
        }


# -----------------------------
# Header parsing (Ensembl-like)
# -----------------------------
def parse_ensembl_description(desc: str) -> Dict[str, object]:
    """
    Supports common Ensembl FASTA headers such as:
    >ENST... cdna:known chromosome:GRCh38:1:... gene:ENSG... transcript:ENST... gene_symbol:... gene_biotype:... transcript_biotype:...
    Also supports Ensembl Bacteria style.
    """
    d: Dict[str, object] = {}
    s = desc.strip()

    m = re.search(r"\sdescription:(.*)$", s)
    if m:
        d["description"] = m.group(1).strip()
        s = s[:m.start()].strip()

    parts = s.split()
    if not parts:
        return d

    d["seq_id"] = parts[0]
    flags: List[str] = []
    for tok in parts[1:]:
        if ":" in tok:
            k, v = tok.split(":", 1)
            d[k] = v
        else:
            flags.append(tok)
    if flags:
        d["flags"] = flags

    loc_key = None
    for k in ("primary_assembly", "chromosome", "scaffold", "contig", "supercontig"):
        if k in d:
            loc_key = k
            break
    if loc_key:
        loc = str(d[loc_key])  # ASSEMBLY:SEQ_REGION:START:END:STRAND
        fields = loc.split(":")
        if len(fields) >= 5:
            d["assembly"] = fields[0]
            d["seq_region"] = fields[1]
            try:
                d["start"] = int(fields[2])
                d["end"] = int(fields[3])
                d["strand"] = int(fields[4])
            except Exception:
                pass

    if "gene" in d:
        d["ensembl_gene_id"] = d["gene"]
    if "transcript" in d:
        d["ensembl_transcript_id"] = d["transcript"]
    else:
        d["ensembl_transcript_id"] = d.get("seq_id")

    return d


# -----------------------------
# Schemas (full vs core)
# -----------------------------
def build_full_schema(orf_mode: str) -> List[str]:
    """
    Full schema = the complete feature set (matches your current ultra exports; no LZ).
    """
    cols: List[str] = []
    cols += [
        "species_id", "omics", "element_rule",
        "transcript_id", "gene_id", "gene_symbol",
        "gene_biotype", "transcript_biotype",
        "assembly", "seq_region", "start", "end", "strand",
        "source_db", "raw_header",
    ]
    cols += [
        "length_nt_total", "length_nt_acgu",
        "n_A", "n_C", "n_G", "n_U", "n_N", "n_other",
        "frac_A", "frac_C", "frac_G", "frac_U",
        "gc_content", "at_skew", "gc_skew",
        "purine_frac", "pyrimidine_frac", "purine_pyrimidine_ratio",
        "nt_entropy",
    ]
    cols += [
        "C_atoms", "H_atoms", "O_atoms", "N_atoms", "P_atoms",
        "C_atom_frac", "H_atom_frac", "O_atom_frac", "N_atom_frac", "P_atom_frac",
        "C_N_ratio", "C_P_ratio", "N_P_ratio",
        "atoms_per_nt_C", "atoms_per_nt_H", "atoms_per_nt_O", "atoms_per_nt_N", "atoms_per_nt_P",
        "mw_rna_nmp_total_Da", "mw_rna_nmp_per_nt_Da",
    ]
    for k in dinuc_keys_rna():
        cols.append(f"dinuc_{k}_freq")
    cols.append("dinuc_valid_pairs")
    for k in dinuc_keys_rna():
        cols.append(f"dinuc_{k}_bias0")
    cols += [
        "clean_rna_len",
        "avg_spacing_A", "avg_spacing_C", "avg_spacing_G", "avg_spacing_U",
        "max_run_A", "max_run_C", "max_run_G", "max_run_U", "max_run_any",
    ]

    if orf_mode == "longest":
        cols += ["orf_len_nt", "orf_len_aa", "orf_frame", "orf_start", "orf_end", "orf_has_stop"]
        cols += ["protein_mw_Da", "protein_aromaticity", "protein_instability_index", "protein_gravy", "protein_isoelectric_point"]

        cols.append("aa_len")
        for aa in AA20:
            cols.append(f"aa_{aa}_count")
        for aa in AA20:
            cols.append(f"aa_{aa}_freq")

        cols.append("codon_valid_codons")
        for k in codon_keys_rna():
            cols.append(f"codon_{k}_freq")
        for k in codon_keys_rna():
            cols.append(f"codon_{k}_bias0")
    return cols


def build_core_schema() -> List[str]:
    """
    Core schema = concise subset (strict subset of full; identical names => 1-to-1 mapping).
    Intended for:
      - frontend: simple charts + search/filter
      - ML/DL: directly usable numeric features (you can drop id/meta columns in modeling)
    """
    cols: List[str] = []
    cols += [
        "species_id", "omics", "element_rule",
        "transcript_id", "gene_id", "gene_symbol",
        "gene_biotype", "transcript_biotype",
        "assembly", "seq_region", "start", "end", "strand",
    ]
    cols += [
        "length_nt_total", "length_nt_acgu", "n_N",
        "frac_A", "frac_C", "frac_G", "frac_U",
        "gc_content", "at_skew", "gc_skew",
        "purine_frac", "nt_entropy",
    ]
    cols += [
        "C_atoms", "N_atoms", "P_atoms",
        "C_N_ratio", "C_P_ratio", "N_P_ratio",
        "atoms_per_nt_C", "atoms_per_nt_N", "atoms_per_nt_P",
        "mw_rna_nmp_per_nt_Da",
    ]
    for k in dinuc_keys_rna():
        cols.append(f"dinuc_{k}_freq")
    cols.append("dinuc_valid_pairs")

    cols += ["clean_rna_len", "avg_spacing_A", "avg_spacing_U", "max_run_A", "max_run_any"]

    cols += [
        "orf_len_nt", "orf_len_aa", "orf_has_stop",
        "protein_mw_Da", "protein_isoelectric_point", "protein_gravy", "protein_instability_index",
        "aa_len",
    ]
    for aa in AA20:
        cols.append(f"aa_{aa}_freq")
    cols.append("codon_valid_codons")
    return cols


def build_schema(feature_set: str, orf_mode: str) -> List[str]:
    if feature_set == "full":
        return build_full_schema(orf_mode=orf_mode)
    if feature_set == "core":
        # Core contains ORF/protein/AA columns; if orf-mode=none, they will be empty.
        return build_core_schema()
    raise ValueError(f"Unsupported feature-set: {feature_set}")


# -----------------------------
# Extraction per record
# -----------------------------
def extract_features_for_record(record,
                                species_id: str,
                                feature_set: str,
                                orf_mode: str,
                                genetic_code: int,
                                start_codons: Optional[List[str]] = None) -> Dict[str, object]:
    """
    Returns a dict with ALL computed fields needed by the given feature_set.
    Missing keys will be filled during CSV write using the fixed schema.
    """
    desc = parse_ensembl_description(record.description)

    seq_rna = normalize_seq_to_rna(str(record.seq))
    counts = count_bases_rna(seq_rna)

    A, C, G, U = (counts["A"], counts["C"], counts["G"], counts["U"])
    denom_acgu = A + C + G + U

    gc = safe_div(G + C, denom_acgu)
    at_skew = safe_div(A - U, (A + U))
    gc_skew = safe_div(G - C, (G + C))
    pur = A + G
    pyr = C + U
    nt_entropy = shannon_entropy({b: counts[b] for b in RNA_BASES})

    atoms, mw = elemental_atoms_from_counts_rna_nmp(counts)
    total_atoms = sum(atoms.values())

    row: Dict[str, object] = {}

    # --- meta / id
    row["species_id"] = species_id
    row["omics"] = "TRANSCRIPTOME"
    row["element_rule"] = "RNA_NMP_v1"

    row["transcript_id"] = desc.get("ensembl_transcript_id") or record.id
    row["gene_id"] = desc.get("ensembl_gene_id") or desc.get("gene") or ""
    row["gene_symbol"] = desc.get("gene_symbol") or ""
    row["gene_biotype"] = desc.get("gene_biotype") or ""
    row["transcript_biotype"] = desc.get("transcript_biotype") or ""

    row["assembly"] = desc.get("assembly") or ""
    row["seq_region"] = desc.get("seq_region") or ""
    row["start"] = desc.get("start") if isinstance(desc.get("start"), int) else ""
    row["end"] = desc.get("end") if isinstance(desc.get("end"), int) else ""
    row["strand"] = desc.get("strand") if isinstance(desc.get("strand"), int) else ""

    if feature_set == "full":
        row["source_db"] = "Ensembl"
        row["raw_header"] = record.description

    # --- nucleotide (full needs more; core needs subset but we can compute once)
    row["length_nt_total"] = int(counts["LEN_TOTAL"])
    row["length_nt_acgu"] = int(counts["LEN_ACGU"])
    row["n_N"] = int(counts["N"])

    if feature_set == "full":
        row["n_A"] = int(A)
        row["n_C"] = int(C)
        row["n_G"] = int(G)
        row["n_U"] = int(U)
        row["n_other"] = int(counts["OTHER"])
        row["frac_A"] = safe_div(A, denom_acgu)
        row["frac_C"] = safe_div(C, denom_acgu)
        row["frac_G"] = safe_div(G, denom_acgu)
        row["frac_U"] = safe_div(U, denom_acgu)
        row["gc_content"] = gc
        row["at_skew"] = at_skew
        row["gc_skew"] = gc_skew
        row["purine_frac"] = safe_div(pur, denom_acgu)
        row["pyrimidine_frac"] = safe_div(pyr, denom_acgu)
        row["purine_pyrimidine_ratio"] = safe_div(pur, pyr)
        row["nt_entropy"] = nt_entropy
    else:
        # core subset
        row["frac_A"] = safe_div(A, denom_acgu)
        row["frac_C"] = safe_div(C, denom_acgu)
        row["frac_G"] = safe_div(G, denom_acgu)
        row["frac_U"] = safe_div(U, denom_acgu)
        row["gc_content"] = gc
        row["at_skew"] = at_skew
        row["gc_skew"] = gc_skew
        row["purine_frac"] = safe_div(pur, denom_acgu)
        row["nt_entropy"] = nt_entropy

    # --- elements (RNA_NMP)
    if feature_set == "full":
        row["C_atoms"] = int(atoms["C"])
        row["H_atoms"] = int(atoms["H"])
        row["O_atoms"] = int(atoms["O"])
        row["N_atoms"] = int(atoms["N"])
        row["P_atoms"] = int(atoms["P"])

        row["C_atom_frac"] = safe_div(atoms["C"], total_atoms)
        row["H_atom_frac"] = safe_div(atoms["H"], total_atoms)
        row["O_atom_frac"] = safe_div(atoms["O"], total_atoms)
        row["N_atom_frac"] = safe_div(atoms["N"], total_atoms)
        row["P_atom_frac"] = safe_div(atoms["P"], total_atoms)

        row["C_N_ratio"] = safe_div(atoms["C"], atoms["N"])
        row["C_P_ratio"] = safe_div(atoms["C"], atoms["P"])
        row["N_P_ratio"] = safe_div(atoms["N"], atoms["P"])

        row["atoms_per_nt_C"] = safe_div(atoms["C"], denom_acgu)
        row["atoms_per_nt_H"] = safe_div(atoms["H"], denom_acgu)
        row["atoms_per_nt_O"] = safe_div(atoms["O"], denom_acgu)
        row["atoms_per_nt_N"] = safe_div(atoms["N"], denom_acgu)
        row["atoms_per_nt_P"] = safe_div(atoms["P"], denom_acgu)

        row["mw_rna_nmp_total_Da"] = float(mw)
        row["mw_rna_nmp_per_nt_Da"] = safe_div(mw, denom_acgu)
    else:
        # core subset
        row["C_atoms"] = int(atoms["C"])
        row["N_atoms"] = int(atoms["N"])
        row["P_atoms"] = int(atoms["P"])
        row["C_N_ratio"] = safe_div(atoms["C"], atoms["N"])
        row["C_P_ratio"] = safe_div(atoms["C"], atoms["P"])
        row["N_P_ratio"] = safe_div(atoms["N"], atoms["P"])
        row["atoms_per_nt_C"] = safe_div(atoms["C"], denom_acgu)
        row["atoms_per_nt_N"] = safe_div(atoms["N"], denom_acgu)
        row["atoms_per_nt_P"] = safe_div(atoms["P"], denom_acgu)
        row["mw_rna_nmp_per_nt_Da"] = safe_div(mw, denom_acgu)

    # --- dinucleotide
    # core: only dinuc freq; full: freq + bias
    row.update(dinuc_freqs_rna(seq_rna))
    if feature_set == "full":
        row.update(dinuc_bias_rna(seq_rna))

    # --- structural (clean len, spacing, homopolymer)
    crna = clean_rna(seq_rna)
    row["clean_rna_len"] = int(len(crna))

    if feature_set == "full":
        row["avg_spacing_A"] = float(avg_spacing(crna, "A"))
        row["avg_spacing_C"] = float(avg_spacing(crna, "C"))
        row["avg_spacing_G"] = float(avg_spacing(crna, "G"))
        row["avg_spacing_U"] = float(avg_spacing(crna, "U"))

        row["max_run_A"] = int(max_homopolymer_run(crna, "A"))
        row["max_run_C"] = int(max_homopolymer_run(crna, "C"))
        row["max_run_G"] = int(max_homopolymer_run(crna, "G"))
        row["max_run_U"] = int(max_homopolymer_run(crna, "U"))
        row["max_run_any"] = int(max(row["max_run_A"], row["max_run_C"], row["max_run_G"], row["max_run_U"]))
    else:
        # core subset
        row["avg_spacing_A"] = float(avg_spacing(crna, "A"))
        row["avg_spacing_U"] = float(avg_spacing(crna, "U"))
        row["max_run_A"] = int(max_homopolymer_run(crna, "A"))
        row["max_run_any"] = int(max(row["max_run_A"],
                                     max_homopolymer_run(crna, "C"),
                                     max_homopolymer_run(crna, "G"),
                                     max_homopolymer_run(crna, "U")))

    # --- ORF / protein / AA / codon
    if orf_mode == "longest":
        orf = find_longest_orf(seq_dna=normalize_seq_to_dna(seq_rna), table_id=genetic_code,
                               start_codons=start_codons, allow_no_stop=True)
        if orf is None:
            # Fill minimal fields; remaining will be blank by schema fill
            row["orf_len_nt"] = 0
            row["orf_len_aa"] = 0
            if feature_set == "full":
                row["orf_frame"] = ""
                row["orf_start"] = ""
                row["orf_end"] = ""
            row["orf_has_stop"] = ""
            row["codon_valid_codons"] = 0
            row["aa_len"] = 0
        else:
            row["orf_len_nt"] = int(orf["orf_len_nt"])
            row["orf_len_aa"] = int(orf["orf_len_aa"])
            if feature_set == "full":
                row["orf_frame"] = int(orf["orf_frame"])
                row["orf_start"] = int(orf["orf_start"])
                row["orf_end"] = int(orf["orf_end"])
            row["orf_has_stop"] = as_bool_str(bool(orf["orf_has_stop"]))

            protein_seq = str(orf["orf_aa"])
            row.update(protein_basic_props(protein_seq))

            if feature_set == "full":
                row.update(aa_counts_and_freqs(protein_seq))
                codon_freqs, codon_counts = codon_freqs_rna_from_orf_dna(str(orf["orf_dna"]))
                row.update(codon_freqs)
                row.update(codon_bias0_from_orf_counts(codon_counts))
            else:
                # core subset: AA freqs only + aa_len + codon_valid_codons (from codon freqs helper)
                row.update(aa_freqs(protein_seq))
                codon_freqs, _ = codon_freqs_rna_from_orf_dna(str(orf["orf_dna"]))
                row["codon_valid_codons"] = codon_freqs.get("codon_valid_codons", 0)

    return row



# -----------------------------
# Batch IO + progress bar
# -----------------------------
@dataclass
class ManifestItem:
    species_id: str
    fasta_path: Path
    genetic_code: int
    record_count: Optional[int] = None


def read_manifest(path: Path) -> List[ManifestItem]:
    items: List[ManifestItem] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        except Exception:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        for row in reader:
            sp = (row.get("species_id") or "").strip()
            fp = (row.get("fasta_path") or row.get("path") or "").strip()
            gc = (row.get("genetic_code") or "").strip()
            if not sp or not fp:
                continue
            items.append(ManifestItem(
                species_id=sp,
                fasta_path=Path(fp),
                genetic_code=int(gc) if gc else 1
            ))
    if not items:
        raise ValueError(f"Manifest is empty or invalid: {path}")
    return items


def iter_fasta_files(input_path: Path, pattern: str) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    files = sorted(input_path.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No FASTA files matched pattern '{pattern}' under: {input_path}")
    return files


def infer_species_id_from_filename(fp: Path) -> str:
    return re.split(r"\.", fp.name, maxsplit=1)[0]


def open_text_auto(fp: Path):
    """
    Open plain-text FASTA or compressed FASTA transparently.
    Supported direct inputs: .fa/.fasta/... and .gz/.bz2/.xz compressed text FASTA.
    """
    name = fp.name.lower()
    if name.endswith(".gz"):
        return gzip.open(fp, "rt", encoding="utf-8", errors="ignore")
    if name.endswith(".bz2"):
        return bz2.open(fp, "rt", encoding="utf-8", errors="ignore")
    if name.endswith(".xz"):
        return lzma.open(fp, "rt", encoding="utf-8", errors="ignore")
    return open(fp, "r", encoding="utf-8", errors="ignore")


def count_fasta_records_fast(fp: Path) -> Optional[int]:
    """
    Count FASTA records by scanning header lines.
    Works for plain-text FASTA and .gz/.bz2/.xz compressed FASTA.
    """
    try:
        n = 0
        with open_text_auto(fp) as f:
            for line in f:
                if line.startswith(">"):
                    n += 1
        return n
    except Exception:
        return None


def build_row_projection(row: Dict[str, object], fieldnames: List[str]) -> Dict[str, object]:
    return {k: row.get(k, "") for k in fieldnames}


def open_csv_writer(out_csv: Path, fieldnames: List[str]):
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fh = open(out_csv, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    return fh, writer


def emit_progress(progress_queue, delta: int) -> None:
    if progress_queue is None or delta <= 0:
        return
    try:
        progress_queue.put_nowait(("records", int(delta)))
    except Exception:
        pass


def extract_one_fasta_to_targets(
    fasta_path: Path,
    species_id: str,
    orf_mode: str,
    genetic_code: int,
    start_codons: Optional[List[str]],
    targets: Dict[str, Path],
    show_progress: bool = True,
    progress_queue=None,
    progress_chunk: int = 200,
    known_total: Optional[int] = None,
) -> Dict[str, object]:
    """
    Stream one FASTA once, and write:
      - core only, or
      - full only, or
      - both core + full in the same pass.
    """
    feature_sets = list(targets.keys())
    if not feature_sets:
        raise ValueError("No output targets provided.")

    core_fields = build_schema("core", orf_mode) if "core" in targets else None
    full_fields = build_schema("full", orf_mode) if "full" in targets else None

    handles = []
    writers = {}
    try:
        if "core" in targets:
            fh, w = open_csv_writer(targets["core"], core_fields)
            handles.append(fh)
            writers["core"] = w
        if "full" in targets:
            fh, w = open_csv_writer(targets["full"], full_fields)
            handles.append(fh)
            writers["full"] = w

        total = known_total if known_total is not None else (count_fasta_records_fast(fasta_path) if (show_progress and progress_queue is None) else None)

        local_pbar = None
        processed = 0
        pending_emit = 0

        with open_text_auto(fasta_path) as handle:
            records = SeqIO.parse(handle, "fasta")
            if show_progress and progress_queue is None and tqdm is not None:
                local_pbar = tqdm(records, total=total, unit="seq", desc=species_id, ncols=110, leave=True)
                iterator = local_pbar
            else:
                iterator = records

            for record in iterator:
                if "core" in writers and "full" in writers:
                    full_row = extract_features_for_record(
                        record=record,
                        species_id=species_id,
                        feature_set="full",
                        orf_mode=orf_mode,
                        genetic_code=genetic_code,
                        start_codons=start_codons,
                    )
                    writers["full"].writerow(build_row_projection(full_row, full_fields))
                    writers["core"].writerow(build_row_projection(full_row, core_fields))
                elif "full" in writers:
                    full_row = extract_features_for_record(
                        record=record,
                        species_id=species_id,
                        feature_set="full",
                        orf_mode=orf_mode,
                        genetic_code=genetic_code,
                        start_codons=start_codons,
                    )
                    writers["full"].writerow(build_row_projection(full_row, full_fields))
                else:
                    core_row = extract_features_for_record(
                        record=record,
                        species_id=species_id,
                        feature_set="core",
                        orf_mode=orf_mode,
                        genetic_code=genetic_code,
                        start_codons=start_codons,
                    )
                    writers["core"].writerow(build_row_projection(core_row, core_fields))

                processed += 1
                pending_emit += 1
                if pending_emit >= progress_chunk:
                    emit_progress(progress_queue, pending_emit)
                    pending_emit = 0

        emit_progress(progress_queue, pending_emit)

        return {
            "species_id": species_id,
            "fasta_path": str(fasta_path),
            "processed_records": processed,
            "targets": {k: str(v) for k, v in targets.items()},
        }
    finally:
        for fh in handles:
            try:
                fh.close()
            except Exception:
                pass


def export_schema_csv(out_path: Path, feature_set: str, orf_mode: str) -> None:
    feature_sets = ["core", "full"] if feature_set == "both" else [feature_set]
    for fs in feature_sets:
        target = out_path
        if len(feature_sets) > 1:
            target = out_path.with_name(f"{out_path.stem}.{fs}{out_path.suffix or '.csv'}")
        cols = build_schema(fs, orf_mode)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["column"])
            for c in cols:
                w.writerow([c])


def resolve_feature_sets(feature_set: str) -> List[str]:
    return ["core", "full"] if feature_set == "both" else [feature_set]


def single_output_path(base_out: Path, feature_set: str) -> Path:
    if base_out.suffix.lower() in (".csv", ".tsv"):
        if feature_set in {"core", "full"}:
            return base_out.with_name(f"{base_out.stem}.{feature_set}{base_out.suffix}")
        return base_out
    return base_out / f"transcriptome.{feature_set}.v5.csv"


def batch_output_path(out_dir: Path, species_id: str, feature_set: str) -> Path:
    return out_dir / f"{species_id}.transcriptome.{feature_set}.v5.csv"


def prepare_items(args) -> List[ManifestItem]:
    if args.manifest.strip():
        items = read_manifest(Path(args.manifest))
    else:
        if not args.input.strip():
            raise SystemExit("--input is required when --manifest is not provided.")
        input_path = Path(args.input)
        fasta_files = iter_fasta_files(input_path, args.pattern)
        if len(fasta_files) == 1:
            sp = args.species_id.strip() or infer_species_id_from_filename(fasta_files[0])
            items = [ManifestItem(sp, fasta_files[0], int(args.genetic_code))]
        else:
            items = [ManifestItem(infer_species_id_from_filename(fp), fp, int(args.genetic_code)) for fp in fasta_files]
    return items


def compute_record_counts(items: List[ManifestItem]) -> Tuple[Optional[int], Dict[str, Optional[int]]]:
    total_records: Optional[int] = 0
    item_totals: Dict[str, Optional[int]] = {}
    for it in items:
        n = count_fasta_records_fast(it.fasta_path)
        item_totals[it.species_id] = n
        it.record_count = n
        if n is None:
            total_records = None
        elif total_records is not None:
            total_records += n
    return total_records, item_totals


def build_targets_for_item(
    item: ManifestItem,
    out_dir: Path,
    feature_sets: List[str],
) -> Dict[str, Path]:
    return {fs: batch_output_path(out_dir, item.species_id, fs) for fs in feature_sets}


def feature_set_label(feature_sets: List[str]) -> str:
    return "both" if set(feature_sets) == {"core", "full"} else "_".join(feature_sets)


def done_marker_path(out_dir: Path, item: ManifestItem, feature_sets: List[str]) -> Path:
    return out_dir / f"{item.species_id}.transcriptome.{feature_set_label(feature_sets)}.v5.done.json"


def csv_has_data_rows(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        seen = 0
        with open(path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
            for line in f:
                if line.strip():
                    seen += 1
                    if seen >= 2:
                        return True
        return False
    except OSError:
        return False


def targets_complete(targets: Dict[str, Path]) -> bool:
    return all(csv_has_data_rows(path) for path in targets.values())


def write_done_marker(marker: Path, item: ManifestItem, targets: Dict[str, Path], feature_sets: List[str], orf_mode: str) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "species_id": item.species_id,
        "fasta_path": str(item.fasta_path),
        "genetic_code": item.genetic_code,
        "feature_sets": list(feature_sets),
        "orf_mode": orf_mode,
        "targets": {k: str(v) for k, v in targets.items()},
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    with open(marker, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def filter_resume_items(
    items: List[ManifestItem],
    out_dir: Path,
    feature_sets: List[str],
    orf_mode: str,
    force_rerun: bool,
) -> List[ManifestItem]:
    if force_rerun:
        print("[BATCH] --force-rerun enabled; existing transcriptome outputs will be recomputed.")
        return items

    print("[BATCH] resume mode enabled; species with complete transcriptome outputs will be skipped.")
    pending: List[ManifestItem] = []
    skipped = 0
    for item in items:
        targets = build_targets_for_item(item, out_dir, feature_sets)
        marker = done_marker_path(out_dir, item, feature_sets)
        if targets_complete(targets):
            if not marker.exists():
                write_done_marker(marker, item, targets, feature_sets, orf_mode)
            print(f"[SKIP] {item.species_id}: existing transcriptome outputs complete")
            skipped += 1
            continue
        if any(path.exists() for path in targets.values()):
            missing = [str(path) for path in targets.values() if not csv_has_data_rows(path)]
            print(f"[RESUME] {item.species_id}: incomplete output set; recomputing species. Missing/incomplete: {', '.join(missing)}")
        pending.append(item)

    print(f"[BATCH] resume summary: total={len(items)}, skipped={skipped}, pending={len(pending)}")
    return pending


def process_item_worker(
    item: ManifestItem,
    out_dir_str: str,
    feature_sets: List[str],
    orf_mode: str,
    start_codons: Optional[List[str]],
    show_progress: bool,
    progress_queue,
    progress_chunk: int,
    done_marker_str: str,
) -> Dict[str, object]:
    out_dir = Path(out_dir_str)
    targets = build_targets_for_item(item, out_dir, feature_sets)
    res = extract_one_fasta_to_targets(
        fasta_path=item.fasta_path,
        species_id=item.species_id,
        orf_mode=orf_mode,
        genetic_code=item.genetic_code,
        start_codons=start_codons,
        targets=targets,
        show_progress=show_progress,
        progress_queue=progress_queue,
        progress_chunk=progress_chunk,
        known_total=item.record_count,
    )
    write_done_marker(Path(done_marker_str), item, targets, feature_sets, orf_mode)
    return res


def drain_progress_queue(progress_queue, records_pbar) -> None:
    if progress_queue is None or records_pbar is None:
        return
    while True:
        try:
            kind, value = progress_queue.get_nowait()
        except Empty:
            break
        except Exception:
            break
        if kind == "records":
            records_pbar.update(int(value))


def process_batch_parallel(
    items: List[ManifestItem],
    out_dir: Path,
    feature_sets: List[str],
    orf_mode: str,
    start_codons: Optional[List[str]],
    jobs: int,
    show_progress: bool,
    precount_records: bool,
    force_rerun: bool,
    progress_chunk: int = 200,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    items = filter_resume_items(items, out_dir, feature_sets, orf_mode, force_rerun)
    if not items:
        print("[DONE] species_ok=0, species_failed=0, skipped_all=True")
        return

    total_records = None
    progress_queue = None
    manager = None
    species_pbar = None
    records_pbar = None

    if show_progress and tqdm is not None:
        if precount_records:
            total_records, _ = compute_record_counts(items)
        manager = multiprocessing.Manager()
        progress_queue = manager.Queue()
        species_pbar = tqdm(total=len(items), desc="species", unit="sp", position=0, ncols=110, leave=True)
        records_pbar = tqdm(total=total_records, desc="records", unit="seq", position=1, ncols=110, leave=True)

    ok = 0
    failed = 0

    try:
        with ProcessPoolExecutor(max_workers=max(1, int(jobs))) as ex:
            future_map = {
                ex.submit(
                    process_item_worker,
                    it,
                    str(out_dir),
                    feature_sets,
                    orf_mode,
                    start_codons,
                    show_progress,
                    progress_queue,
                    progress_chunk,
                    str(done_marker_path(out_dir, it, feature_sets)),
                ): it
                for it in items
            }

            remaining = set(future_map.keys())
            while remaining:
                done, remaining = wait(remaining, timeout=0.2, return_when=FIRST_COMPLETED)
                drain_progress_queue(progress_queue, records_pbar)

                for fut in done:
                    it = future_map[fut]
                    if species_pbar is not None:
                        species_pbar.update(1)
                    try:
                        res = fut.result()
                        ok += 1
                        targets = ", ".join(f"{k}={v}" for k, v in res["targets"].items())
                        if tqdm is not None and show_progress:
                            tqdm.write(f"[OK] {it.species_id} -> {targets}")
                        else:
                            print(f"[OK] {it.species_id} -> {targets}")
                    except Exception as e:
                        failed += 1
                        msg = f"[FAILED] {it.species_id} -> {e}"
                        if tqdm is not None and show_progress:
                            tqdm.write(msg)
                        else:
                            print(msg)

            drain_progress_queue(progress_queue, records_pbar)
    finally:
        if species_pbar is not None:
            species_pbar.close()
        if records_pbar is not None:
            records_pbar.close()
        if manager is not None:
            manager.shutdown()

    print(f"[DONE] species_ok={ok}, species_failed={failed}")


def process_single_or_serial(
    items: List[ManifestItem],
    out_path: Path,
    feature_sets: List[str],
    orf_mode: str,
    start_codons: Optional[List[str]],
    show_progress: bool,
    precount_records: bool = False,
    force_rerun: bool = False,
) -> None:
    # Single item + single feature-set + file output => preserve original direct-file behavior
    if len(items) == 1 and len(feature_sets) == 1 and out_path.suffix.lower() in (".csv", ".tsv"):
        it = items[0]
        targets = {feature_sets[0]: out_path}
        res = extract_one_fasta_to_targets(
            fasta_path=it.fasta_path,
            species_id=it.species_id,
            orf_mode=orf_mode,
            genetic_code=it.genetic_code,
            start_codons=start_codons,
            targets=targets,
            show_progress=show_progress,
        )
        print(f"[OK] Wrote: {list(res['targets'].values())[0]}")
        return

    # Single item + both + file path => base.core.csv and base.full.csv
    if len(items) == 1 and out_path.suffix.lower() in (".csv", ".tsv"):
        it = items[0]
        targets = {fs: single_output_path(out_path, fs) for fs in feature_sets}
        res = extract_one_fasta_to_targets(
            fasta_path=it.fasta_path,
            species_id=it.species_id,
            orf_mode=orf_mode,
            genetic_code=it.genetic_code,
            start_codons=start_codons,
            targets=targets,
            show_progress=show_progress,
        )
        for fs in feature_sets:
            print(f"[OK] {it.species_id} [{fs}] -> {res['targets'][fs]}")
        return

    out_dir = out_path if out_path.suffix == "" else out_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    items = filter_resume_items(items, out_dir, feature_sets, orf_mode, force_rerun)
    if not items:
        print("[DONE] species_ok=0, species_failed=0, skipped_all=True")
        return

    total_records = None
    species_pbar = None
    records_pbar = None
    if show_progress and tqdm is not None:
        if precount_records:
            total_records, _ = compute_record_counts(items)
        species_pbar = tqdm(total=len(items), desc="species", unit="sp", position=0, ncols=110, leave=True)
        records_pbar = tqdm(total=total_records, desc="records", unit="seq", position=1, ncols=110, leave=True)

    ok = 0
    failed = 0
    try:
        for it in items:
            try:
                targets = build_targets_for_item(it, out_dir, feature_sets)
                res = extract_one_fasta_to_targets(
                    fasta_path=it.fasta_path,
                    species_id=it.species_id,
                    orf_mode=orf_mode,
                    genetic_code=it.genetic_code,
                    start_codons=start_codons,
                    targets=targets,
                    show_progress=False,
                    progress_queue=None,
                    known_total=it.record_count,
                )
                write_done_marker(done_marker_path(out_dir, it, feature_sets), it, targets, feature_sets, orf_mode)
                if records_pbar is not None and it.record_count:
                    records_pbar.update(it.record_count)
                if species_pbar is not None:
                    species_pbar.update(1)
                ok += 1
                target_text = ", ".join(f"{k}={v}" for k, v in res["targets"].items())
                if tqdm is not None and show_progress:
                    tqdm.write(f"[OK] {it.species_id} -> {target_text}")
                else:
                    print(f"[OK] {it.species_id} -> {target_text}")
            except Exception as e:
                failed += 1
                if species_pbar is not None:
                    species_pbar.update(1)
                msg = f"[FAILED] {it.species_id} -> {e}"
                if tqdm is not None and show_progress:
                    tqdm.write(msg)
                else:
                    print(msg)
    finally:
        if species_pbar is not None:
            species_pbar.close()
        if records_pbar is not None:
            records_pbar.close()

    print(f"[DONE] species_ok={ok}, species_failed={failed}")


def main():
    multiprocessing.freeze_support()

    ap = argparse.ArgumentParser(
        description="Transcriptome stoichiometric feature extractor v5.2 (single-pass core+full writing, species-level multiprocessing, complete batch progress, direct compressed FASTA support, robust ambiguous-AA handling)."
    )
    ap.add_argument("--input", default="", help="FASTA file or directory containing FASTA files. Supports plain text and .gz/.bz2/.xz compressed FASTA.")
    ap.add_argument("--pattern", default="*.fa*", help="If --input is a directory, glob pattern to match FASTA files.")
    ap.add_argument("--manifest", default="", help="Optional manifest CSV/TSV: species_id,fasta_path,genetic_code")

    ap.add_argument("--species-id", default="", help="Species ID (used when --input is a single FASTA).")
    ap.add_argument("--genetic-code", type=int, default=1, help="NCBI genetic code id (default=1).")
    ap.add_argument("--start-codons", default="", help="Comma-separated start codons override (DNA, e.g., ATG,GTG,TTG).")

    ap.add_argument("--out", required=True, help="Output CSV path OR output directory.")
    ap.add_argument("--feature-set", choices=["full", "core", "both"], default="full",
                    help="full: complete feature table; core: concise subset; both: write full and core together in one FASTA pass.")
    ap.add_argument("--orf-mode", choices=["none", "longest"], default="longest",
                    help="none: no ORF/protein computed; longest: derive longest ORF/protein features.")
    ap.add_argument("--jobs", type=int, default=1, help="Species-level parallel workers for batch mode (default=1).")
    ap.add_argument("--no-progress", action="store_true", help="Disable progress bar.")
    ap.add_argument(
        "--precount-records",
        action="store_true",
        help="Pre-scan all FASTA files to compute exact record totals for progress bars. Disabled by default for large .gz batches.",
    )
    ap.add_argument(
        "--force-rerun",
        action="store_true",
        help="In batch mode, recompute species even when expected transcriptome output files already exist.",
    )
    ap.add_argument("--schema-out", default="", help="If set, export the selected schema CSV to this path and exit. When --feature-set both, writes two schema files.")

    args = ap.parse_args()

    out_path = Path(args.out)

    start_codons = None
    if args.start_codons.strip():
        start_codons = [x.strip().upper() for x in args.start_codons.split(",") if x.strip()]

    if args.schema_out.strip():
        export_schema_csv(Path(args.schema_out), feature_set=args.feature_set, orf_mode=args.orf_mode)
        print(f"[OK] Schema exported: {args.schema_out}")
        return

    show_progress = not args.no_progress
    items = prepare_items(args)
    feature_sets = resolve_feature_sets(args.feature_set)

    # Keep direct single-file behavior unchanged; batch gets standardized outputs.
    is_direct_single_file_case = len(items) == 1 and out_path.suffix.lower() in (".csv", ".tsv")
    is_batch_like = (len(items) > 1) or (not is_direct_single_file_case and out_path.suffix == "")

    if not is_batch_like:
        process_single_or_serial(
            items=items,
            out_path=out_path,
            feature_sets=feature_sets,
            orf_mode=args.orf_mode,
            start_codons=start_codons,
            show_progress=show_progress,
            precount_records=args.precount_records,
            force_rerun=args.force_rerun,
        )
        return

    if args.jobs > 1 and len(items) > 1:
        out_dir = out_path if out_path.suffix == "" else out_path.parent
        process_batch_parallel(
            items=items,
            out_dir=out_dir,
            feature_sets=feature_sets,
            orf_mode=args.orf_mode,
            start_codons=start_codons,
            jobs=args.jobs,
            show_progress=show_progress,
            precount_records=args.precount_records,
            force_rerun=args.force_rerun,
        )
    else:
        process_single_or_serial(
            items=items,
            out_path=out_path,
            feature_sets=feature_sets,
            orf_mode=args.orf_mode,
            start_codons=start_codons,
            show_progress=show_progress,
            precount_records=args.precount_records,
            force_rerun=args.force_rerun,
        )


if __name__ == "__main__":
    main()
