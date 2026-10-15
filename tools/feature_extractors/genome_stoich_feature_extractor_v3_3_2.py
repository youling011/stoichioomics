#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genome stoichiometric feature extractor (v3.3, cross-species hardened)

Inputs:
  - Genome FASTA (DNA, toplevel)
  - GFF3 annotation (gene / transcript / exon / CDS)

Outputs (CSV):
  One row per gene by default, indexed by (species_id, gene_id).
  For eukaryotes with multiple transcripts per gene, CDS-derived features
  (codon/AA/CDS stats) are computed from a chosen transcript (canonical if
  annotated, otherwise longest CDS). The chosen transcript metadata is recorded.

Key feature groups (per gene):
  - Locus (gene span) nucleotide composition, entropy, AT/GC skew, DNA atom counts
  - Promoter (upstream) composition + dinucleotide spectrum
  - Exon-union composition (from chosen transcript if exists; else gene span)
  - CDS sequence (from chosen transcript) codon usage (64), AA composition (20),
    GC1/2/3, plus optional translation using inferred / specified genetic code
  - Intergenic distances (oriented upstream/downstream in transcription direction)

Notes:
  - This script is designed to be portable (stdlib-only).
  - For FASTA.gz, the file is first materialized to a temporary plain FASTA,
    then indexed for random access. Set STOICH_FASTA_TMPDIR to control temp space.

Typical usage:
  python genome_stoich_feature_extractor_v3_3.py --fasta genome.fa --gff annot.gff3 \
      --species-id S1 --out S1.genome_features.csv --emit-schema schema.json

Batch usage:
  python genome_stoich_feature_extractor_v3_3.py --batch-manifest manifest.csv --out-dir out/ --feature-set core
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Iterable
from urllib.parse import unquote

# -----------------------------
# IO helpers
# -----------------------------
def smart_open(path: str, mode: str = "rt"):
    """Open plain or gz file transparently (safe for binary/text modes)."""
    if path.endswith(".gz"):
        if "b" in mode:
            return gzip.open(path, mode)
        return gzip.open(path, mode, encoding="utf-8", newline="")
    if "b" in mode:
        return open(path, mode)
    return open(path, mode, encoding="utf-8", newline="")

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

# -----------------------------
# Lightweight progress display (stdlib-only)
# -----------------------------
class ProgressBar:
    """
    Simple terminal progress bar (stderr). Designed to be low overhead and portable.

    - Updates at most every `min_interval` seconds, or every `every` items.
    - Uses carriage returns; safe for Windows terminals.
    """
    def __init__(self, total: int, desc: str = "", enabled: bool = True,
                 width: int = 28, every: int = 200, min_interval: float = 0.2):
        self.total = int(total) if total is not None else 0
        self.desc = desc
        self.enabled = enabled and self.total > 0 and sys.stderr.isatty()
        self.width = width
        self.every = max(1, int(every))
        self.min_interval = float(min_interval)
        self._last_t = 0.0
        self._last_i = 0

        if self.enabled:
            self._render(0, force=True)

    def _render(self, i: int, force: bool = False):
        if not self.enabled:
            return
        now = time.time()
        if not force:
            if i != self.total and (i - self._last_i) < self.every and (now - self._last_t) < self.min_interval:
                return
        self._last_t = now
        self._last_i = i

        frac = min(1.0, max(0.0, i / self.total))
        filled = int(round(self.width * frac))
        bar = "█" * filled + " " * (self.width - filled)
        pct = int(round(frac * 100))
        msg = f"{self.desc} [{bar}] {pct:3d}% ({i}/{self.total})"
        # pad to clear prior line
        pad = " " * max(0, 3)
        sys.stderr.write("\r" + msg + pad)
        sys.stderr.flush()

    def update(self, i: int):
        self._render(i, force=False)

    def close(self):
        if not self.enabled:
            return
        self._render(self.total, force=True)
        sys.stderr.write("\n")
        sys.stderr.flush()

# -----------------------------
# FASTA indexing / fetching
# -----------------------------
@dataclass
class FaiRecord:
    name: str
    length: int
    offset: int  # byte offset to first base
    line_bases: int
    line_bytes: int

class FastaIndexed:
    """
    Minimal FASTA random-access reader (FAI-like) for uncompressed FASTA.

    For compressed FASTA (.gz), materializes a temporary plain FASTA and indexes it
    to avoid loading large metazoan genomes fully into memory.
    For variable line lengths, caches whole contig on first access.
    """
    def __init__(self, fasta_path: str):
        self.fasta_path = fasta_path
        self._source_fasta_path = fasta_path
        self._is_gz = fasta_path.endswith(".gz")
        self._fh = None
        self._index: Dict[str, FaiRecord] = {}
        self._cache: Dict[str, str] = {}  # contig -> full seq (used when needed)
        self._tmp_plain_path: Optional[str] = None

        if self._is_gz:
            self._materialize_gz_to_temp()
        self._build_index()

    def close(self):
        if self._fh:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
        if self._tmp_plain_path:
            try:
                os.remove(self._tmp_plain_path)
                eprint(f"[FASTA] removed temporary FASTA: {self._tmp_plain_path}")
            except Exception as exc:
                eprint(f"[WARN] failed to remove temporary FASTA {self._tmp_plain_path}: {exc}")
            self._tmp_plain_path = None

    def _materialize_gz_to_temp(self):
        tmp_dir = os.environ.get("STOICH_FASTA_TMPDIR") or os.path.dirname(os.path.abspath(self.fasta_path))
        if tmp_dir:
            os.makedirs(tmp_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".stoich_fasta_", suffix=".fa", dir=tmp_dir or None)
        os.close(fd)
        eprint(f"[FASTA] gzip detected; materializing to temporary plain FASTA: {self.fasta_path} -> {tmp_path}")
        try:
            with gzip.open(self.fasta_path, "rb") as fin, open(tmp_path, "wb") as fout:
                shutil.copyfileobj(fin, fout, length=8 * 1024 * 1024)
        except Exception:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            raise
        self._tmp_plain_path = tmp_path
        self.fasta_path = tmp_path
        self._is_gz = False

    def _load_all_sequences_gz(self):
        eprint(f"[FASTA] gzip detected; loading all sequences into memory: {self.fasta_path}")
        seqs: Dict[str, List[str]] = {}
        cur = None
        with smart_open(self.fasta_path, "rt") as f:
            for line in f:
                if not line:
                    continue
                if line.startswith(">"):
                    cur = line[1:].strip().split()[0]
                    seqs[cur] = []
                else:
                    if cur is None:
                        continue
                    seqs[cur].append(line.strip())
        for k, parts in seqs.items():
            self._cache[k] = "".join(parts).upper()

    def _build_index(self):
        self._fh = smart_open(self.fasta_path, "rb")
        fh = self._fh
        fh.seek(0)

        name = None
        length = 0
        offset = 0
        line_bases = None
        line_bytes = None

        while True:
            pos = fh.tell()
            line = fh.readline()
            if not line:
                break
            if line.startswith(b">"):
                # finalize previous
                if name is not None:
                    if line_bases is None or line_bytes is None:
                        # header with no sequence
                        line_bases = 0
                        line_bytes = 0
                    self._index[name] = FaiRecord(name, length, offset, line_bases, line_bytes)
                header = line[1:].decode("utf-8", errors="ignore").strip()
                name = header.split()[0]
                length = 0
                # next line is sequence (if any)
                offset = fh.tell()
                line_bases = None
                line_bytes = None
            else:
                if name is None:
                    continue
                s = line.rstrip(b"\r\n")
                if line_bases is None:
                    line_bases = len(s)
                    line_bytes = len(line)
                else:
                    # detect variable line lengths (ignore shorter final line)
                    if len(s) > line_bases:
                        # set sentinel for variable lines
                        line_bases = -1
                        line_bytes = -1
                length += len(s)

        if name is not None:
            if line_bases is None or line_bytes is None:
                line_bases = 0
                line_bytes = 0
            self._index[name] = FaiRecord(name, length, offset, line_bases, line_bytes)

        eprint(f"[FASTA] indexed contigs: {len(self._index)}")

    def contigs(self) -> List[str]:
        return list(self._cache.keys()) if self._is_gz else list(self._index.keys())

    def length(self, contig: str) -> int:
        if contig in self._cache:
            return len(self._cache[contig])
        rec = self._index.get(contig)
        if rec is None:
            raise KeyError(f"Contig not found in FASTA: {contig}")
        return rec.length

    def _get_full_contig(self, contig: str) -> str:
        if contig in self._cache:
            return self._cache[contig]
        rec = self._index.get(contig)
        if rec is None:
            raise KeyError(f"Contig not found in FASTA: {contig}")
        # if variable line lengths, read contig sequentially
        if rec.line_bases < 0:
            eprint(f"[FASTA] variable line length detected for {contig}; caching whole contig.")
            self._fh.seek(rec.offset)
            parts = []
            while True:
                pos = self._fh.tell()
                line = self._fh.readline()
                if not line or line.startswith(b">"):
                    break
                parts.append(line.strip().decode("utf-8", errors="ignore"))
            self._cache[contig] = "".join(parts).upper()
            return self._cache[contig]
        # otherwise, we can still fetch via random access, but caching is okay
        self._cache[contig] = self.fetch(contig, 1, rec.length, oriented=False)
        return self._cache[contig]

    def fetch(self, contig: str, start_1: int, end_1: int, oriented: bool = False, strand: str = "+") -> str:
        """
        Fetch 1-based inclusive interval from contig. Returns uppercase sequence.
        If oriented=True and strand='-', returns reverse-complement.
        """
        if start_1 > end_1:
            return ""
        if contig in self._cache:
            seq = self._cache[contig][start_1-1:end_1]
            return revcomp(seq) if (oriented and strand == "-") else seq

        rec = self._index.get(contig)
        if rec is None:
            raise KeyError(f"Contig not found in FASTA: {contig}")

        # bounds
        start_1 = max(1, start_1)
        end_1 = min(rec.length, end_1)
        if start_1 > end_1:
            return ""

        if rec.line_bases < 0:
            # variable lines -> cache
            seq = self._get_full_contig(contig)[start_1-1:end_1]
            return revcomp(seq) if (oriented and strand == "-") else seq

        # random access calculation
        line_bases = rec.line_bases
        line_bytes = rec.line_bytes
        # 0-based start/end
        s0 = start_1 - 1
        e0 = end_1 - 1

        # byte offset of first requested base
        start_line = s0 // line_bases
        start_in_line = s0 % line_bases
        start_byte = rec.offset + start_line * line_bytes + start_in_line

        # read chunk spanning to end
        end_line = e0 // line_bases
        end_in_line = e0 % line_bases
        end_byte = rec.offset + end_line * line_bytes + end_in_line + 1  # exclusive
        nbytes = end_byte - start_byte

        self._fh.seek(start_byte)
        raw = self._fh.read(nbytes)
        # remove newlines
        seq = raw.replace(b"\n", b"").replace(b"\r", b"").decode("utf-8", errors="ignore").upper()
        return revcomp(seq) if (oriented and strand == "-") else seq

# -----------------------------
# Sequence utilities
# -----------------------------
_RC = str.maketrans("ACGTNacgtn", "TGCANtgcan")

def revcomp(seq: str) -> str:
    return seq.translate(_RC)[::-1]

def safe_div(a: float, b: float) -> float:
    return float("nan") if b == 0 else a / b

def shannon_entropy_acgt(counts: Dict[str, int]) -> float:
    total = counts["A"] + counts["C"] + counts["G"] + counts["T"]
    if total <= 0:
        return float("nan")
    h = 0.0
    for base in ("A", "C", "G", "T"):
        p = counts[base] / total
        if p > 0:
            h -= p * math.log(p, 2)
    return h

def count_bases(seq: str) -> Dict[str, int]:
    seq = seq.upper()
    return {
        "A": seq.count("A"),
        "C": seq.count("C"),
        "G": seq.count("G"),
        "T": seq.count("T"),
        "N": seq.count("N")
    }

DINUCS = [a+b for a in "ACGT" for b in "ACGT"]

def dinuc_counts(seq: str) -> Tuple[Dict[str, int], int]:
    seq = seq.upper()
    counts = {k: 0 for k in DINUCS}
    total = 0
    prev = None
    for ch in seq:
        if ch not in "ACGT":
            prev = None
            continue
        if prev is not None:
            counts[prev+ch] += 1
            total += 1
        prev = ch
    return counts, total

# deoxynucleotide monophosphate atomic compositions (DNA)
DNA_ATOMS = {
    "A": {"C": 10, "H": 14, "O": 6, "N": 5, "P": 1},
    "C": {"C": 9,  "H": 14, "O": 7, "N": 3, "P": 1},
    "G": {"C": 10, "H": 14, "O": 7, "N": 5, "P": 1},
    "T": {"C": 10, "H": 15, "O": 8, "N": 2, "P": 1},
}

def dna_atom_counts(base_counts: Dict[str, int]) -> Dict[str, int]:
    out = {"C": 0, "H": 0, "O": 0, "N": 0, "P": 0}
    for b in "ACGT":
        n = base_counts[b]
        for el in out.keys():
            out[el] += n * DNA_ATOMS[b][el]
    return out

# -----------------------------
# Genetic codes (NCBI transl_table)
# Build codon->AA from INSDC/NCBI codon order
# -----------------------------
CODON_ORDER = []
for b1 in "TCAG":
    for b2 in "TCAG":
        for b3 in "TCAG":
            CODON_ORDER.append(b1+b2+b3)

# Amino acids strings (length 64) taken from INSDC genetic code tables (NCBI)
# https://www.insdc.org/submitting-standards/genetic-code-tables/  (see explanation)
AA_STR_BY_TABLE = {
    1:  "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    2:  "FFLLSSSSYY**CCWWLLLLPPPPHHQQRRRRIIMMTTTTNNKKSS**VVVVAAAADDEEGGGG",
    3:  "FFLLSSSSYY**CCWWTTTTPPPPHHQQRRRRIIMMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    4:  "FFLLSSSSYY**CCWWLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    5:  "FFLLSSSSYY**CCWWLLLLPPPPHHQQRRRRIIMMTTTTNNKKSSSSVVVVAAAADDEEGGGG",
    6:  "FFLLSSSSYYQQCC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    9:  "FFLLSSSSYY**CCWWLLLLPPPPHHQQRRRRIIIMTTTTNNNKSSSSVVVVAAAADDEEGGGG",
    10: "FFLLSSSSYY**CCCWLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    11: "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    12: "FFLLSSSSYY**CC*WLLLSPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    13: "FFLLSSSSYY**CCWWLLLLPPPPHHQQRRRRIIMMTTTTNNKKSSGGVVVVAAAADDEEGGGG",
    14: "FFLLSSSSYYY*CCWWLLLLPPPPHHQQRRRRIIIMTTTTNNNKSSSSVVVVAAAADDEEGGGG",
    15: "FFLLSSSSYY*QCC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    16: "FFLLSSSSYY*LCC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    21: "FFLLSSSSYY**CCWWLLLLPPPPHHQQRRRRIIMMTTTTNNNKSSSSVVVVAAAADDEEGGGG",
    22: "FFLLSS*SYY*LCC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    23: "FF*LSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
    24: "FFLLSSSSYY**CCWWLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSSKVVVVAAAADDEEGGGG",
    25: "FFLLSSSSYY**CCGWLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG",
}

def codon_to_aa_map(transl_table: int) -> Dict[str, str]:
    aa_str = AA_STR_BY_TABLE.get(transl_table, AA_STR_BY_TABLE[1])
    if len(aa_str) != 64:
        raise ValueError(f"Bad AA string length for transl_table={transl_table}")
    return {codon: aa_str[i] for i, codon in enumerate(CODON_ORDER)}

AA20 = list("ACDEFGHIKLMNPQRSTVWY")

# -----------------------------
# Feature-set selection: FULL vs CORE
# -----------------------------
# The CORE set is a compact, ML/Frontend-friendly subset derived deterministically from FULL.
# It is intentionally stable and cross-species oriented.

FEATURE_SET_CHOICES = ["full", "core", "both"]

# local 64-codon list in A/C/G/T order (matches FULL output column naming)
CODONS_64_CORE = [a+b+c for a in "ACGT" for b in "ACGT" for c in "ACGT"]


# CORE column order (fixed)
CORE_FEATURE_COLUMNS: List[str] = [
    # identifiers & minimal metadata
    "species_id","gene_id","source_gene_id","gene_name","locus_tag","biotype",
    "seqid","start_1","end_1","strand","is_coding",
    "transcript_count","chosen_transcript_source_id","chosen_transcript_reason",
    "exon_seq_strategy","transl_table_used",
    "upstream_intergenic_bp","downstream_intergenic_bp",

    # locus summary
    "locus_length_bp","locus_length_acgt_bp","locus_n_percent","locus_gc_percent",

    # exon summary (gene-body proxy, euk-friendly)
    "exon_length_bp","exon_length_acgt_bp","exon_n_percent","exon_gc_percent",
    "exon_shannon_entropy_acgt",
    "exon_atoms_C_per_base","exon_atoms_H_per_base","exon_atoms_O_per_base","exon_atoms_N_per_base","exon_atoms_P_per_base",
    "exon_ratio_C_N","exon_ratio_C_P","exon_ratio_N_P",

    # promoter summary
    "promoter_length_bp","promoter_length_acgt_bp","promoter_n_percent","promoter_gc_percent",
    "promoter_shannon_entropy_acgt",
    "promoter_atoms_C_per_base","promoter_atoms_H_per_base","promoter_atoms_O_per_base","promoter_atoms_N_per_base","promoter_atoms_P_per_base",
    "promoter_ratio_C_N","promoter_ratio_C_P","promoter_ratio_N_P",
]

# add locus dinucleotide frequencies (16)
CORE_FEATURE_COLUMNS += [f"locus_dinuc_{d}_freq" for d in DINUCS]
CORE_FEATURE_COLUMNS += ["locus_dinuc_total_valid"]

# coding summary & flags
CORE_FEATURE_COLUMNS += [
    "coding_valid",
    "cds_length_bp","cds_gc_percent","gc1_percent","gc2_percent","gc3_percent",
    "codon_total_valid","codon_entropy_bits",
    "aa_total_20","aa_entropy_bits","aa_stop_count",
]

# 64 codon frequencies
CORE_FEATURE_COLUMNS += [f"codon_{c}_freq" for c in CODONS_64_CORE]

# 20 AA frequencies
CORE_FEATURE_COLUMNS += [f"aa_{a}_freq" for a in AA20]

# columns to zero-fill when a gene is noncoding or coding-invalid (ML-friendly)
CORE_ZERO_FILL_COLUMNS: List[str] = [
    "cds_length_bp","cds_gc_percent","gc1_percent","gc2_percent","gc3_percent",
    "codon_total_valid","codon_entropy_bits",
    "aa_total_20","aa_entropy_bits","aa_stop_count",
] + [f"codon_{c}_freq" for c in CODONS_64_CORE] + [f"aa_{a}_freq" for a in AA20]


def _to_int_safe(v) -> int:
    if v is None:
        return 0
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if math.isnan(v):
            return 0
        return int(v)
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0


def _to_float_safe(v) -> float:
    if v is None:
        return float("nan")
    if isinstance(v, float):
        return v
    if isinstance(v, int):
        return float(v)
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return float("nan")
    try:
        return float(s)
    except Exception:
        return float("nan")


def compute_coding_valid_row(row: Dict[str, object]) -> int:
    is_coding = _to_int_safe(row.get("is_coding", 0))
    ctv = _to_int_safe(row.get("codon_total_valid", 0))
    aa20 = _to_int_safe(row.get("aa_total_20", 0))
    return 1 if (is_coding == 1 and ctv > 0 and aa20 > 0) else 0


def build_core_rows(full_rows: List[Dict[str, object]], fill_noncoding: str = "zero") -> List[Dict[str, object]]:
    """
    Deterministically derive CORE rows from FULL rows.
    - fill_noncoding="zero": fill coding-layer columns with 0 for noncoding or coding-invalid rows.
    - fill_noncoding="nan": leave them blank ("") to preserve missingness.
    """
    fill_noncoding = (fill_noncoding or "zero").lower()
    out_rows: List[Dict[str, object]] = []
    for r in full_rows:
        rr: Dict[str, object] = {}
        # copy columns (or empty)
        for c in CORE_FEATURE_COLUMNS:
            if c == "coding_valid":
                continue
            rr[c] = r.get(c, "")

        cv = compute_coding_valid_row(r)
        rr["coding_valid"] = cv

        if fill_noncoding == "zero":
            # If noncoding OR coding-invalid, set coding-layer fields to 0
            is_coding = _to_int_safe(r.get("is_coding", 0))
            if is_coding == 0 or cv == 0:
                for c in CORE_ZERO_FILL_COLUMNS:
                    rr[c] = 0
                rr["coding_valid"] = 0

        out_rows.append(rr)
    return out_rows

# -----------------------------
# GFF parsing
# -----------------------------
def parse_attributes(attr_str: str) -> Dict[str, str]:
    d: Dict[str, str] = {}
    # GFF3 attributes are ; separated, key=value, values may be percent-encoded
    for part in attr_str.split(";"):
        if not part:
            continue
        if "=" not in part:
            # sometimes just a flag
            key = unquote(part.strip())
            if key:
                d[key] = ""
            continue
        k, v = part.split("=", 1)
        d[unquote(k.strip())] = unquote(v.strip())
    return d

def first_nonempty(*vals: Optional[str]) -> str:
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and v != "":
            return v
    return ""

def strip_prefix(s: str) -> str:
    """Strip common GFF3 ID prefixes.

    Ensembl/INSDC-style GFF3 frequently uses IDs like:
      - gene:XYZ
      - transcript:ABC
      - CDS:...
      - exon:...
      - RNA:...

    For cross-species robustness, we strip only well-known prefixes and leave
    other IDs untouched.
    """
    if not s:
        return ""
    # Fast path for most common prefixes
    for p in ("gene:", "transcript:", "CDS:", "exon:", "RNA:", "rna:", "mRNA:", "mrna:"):
        if s.startswith(p):
            return s[len(p):]
    # Generic fallback: if it looks like a prefixed id with one of the known
    # tokens, strip token + ':'
    if ":" in s:
        head = s.split(":", 1)[0].lower()
        if head in {"gene", "transcript", "cds", "exon", "rna", "mrna"}:
            return s.split(":", 1)[1]
    return s

@dataclass
class GeneRec:
    stable_id: str          # e.g., ENSB:xxx or YAL069W
    source_id: str          # e.g., gene:ENSB:xxx or gene:YAL069W
    seqid: str
    start: int
    end: int
    strand: str
    biotype: str
    attrs: Dict[str, str]

@dataclass
class TxRec:
    stable_id: str          # transcript_id attribute or stripped ID
    source_id: str          # ID attribute
    parent_gene_source: str
    seqid: str
    strand: str
    attrs: Dict[str, str]

@dataclass
class SegRec:
    parent_tx_source: str
    seqid: str
    start: int
    end: int
    strand: str
    phase: str
    attrs: Dict[str, str]

def parse_gff3(gff_path: str) -> Tuple[Dict[str, GeneRec], Dict[str, TxRec], Dict[str, List[SegRec]], Dict[str, List[Tuple[int,int]]]]:
    """
    Returns:
      genes_by_source_id: gene_source_id -> GeneRec
      tx_by_source_id: transcript_source_id -> TxRec
      cds_by_tx_source: transcript_source_id -> list[SegRec]
      exons_by_tx_source: transcript_source_id -> list[(start,end)]
    Robust to record ordering.
    """
    genes: Dict[str, GeneRec] = {}
    txs: Dict[str, TxRec] = {}
    cds_pending: List[SegRec] = []
    exon_pending: List[Tuple[str, str, int, int, str, Dict[str,str]]] = []  # (Parent, seqid, start, end, strand, attrs)

    # Transcript-like feature types (cross-species): Ensembl often uses the RNA type
    # itself (tRNA, rRNA, snoRNA, ncRNA...) as the transcript feature type, with
    # an ID like "transcript:...".
    transcript_like_types = {
        "mrna", "transcript",
        "ncrna", "lncrna", "scrna", "srna",
        "trna", "rrna", "snorna", "snrna",
        "mirna", "pirna", "crna", "guide_rna", "antisense_rna",
        "ribozyme", "vault_rna", "telomerase_rna",
    }

    def is_gene_feature(ftype_l: str) -> bool:
        # Broadly treat "*_gene" and pseudogene as gene features.
        if ftype_l in ("gene", "pseudogene", "ncrna_gene"):
            return True
        if ftype_l.endswith("_gene"):
            return True
        return False

    def is_transcript_feature(ftype_l: str, attrs: Dict[str, str]) -> bool:
        # Primary: explicit transcript ID prefixes
        sid = attrs.get("ID", "")
        if sid.startswith(("transcript:", "RNA:", "rna:", "mRNA:", "mrna:")):
            return True
        # Secondary: transcript_id attribute present
        if attrs.get("transcript_id"):
            return True
        # Tertiary: RNA types used as transcript feature types (common in Ensembl/SGD)
        if ftype_l in transcript_like_types and attrs.get("Parent") and attrs.get("ID"):
            return True
        return False

    with smart_open(gff_path, "rt") as f:
        for line in f:
            if not line or line.startswith("#"):
                continue
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 9:
                continue
            seqid, source, ftype, start, end, score, strand, phase, attr_str = parts
            try:
                start_i = int(start)
                end_i = int(end)
            except ValueError:
                continue
            attrs = parse_attributes(attr_str)

            ftype_l = ftype.lower()

            if is_gene_feature(ftype_l):
                source_id = attrs.get("ID", "")
                stable_id = first_nonempty(attrs.get("gene_id"), strip_prefix(source_id), attrs.get("Name"), attrs.get("locus_tag"))
                biotype = first_nonempty(attrs.get("biotype"), attrs.get("gene_biotype"), attrs.get("gene_type"), ftype)
                if not source_id:
                    # synthesize a source id
                    source_id = f"gene:{stable_id}"
                genes[source_id] = GeneRec(
                    stable_id=stable_id,
                    source_id=source_id,
                    seqid=seqid,
                    start=start_i,
                    end=end_i,
                    strand=strand if strand in ("+","-") else ".",
                    biotype=biotype,
                    attrs=attrs
                )
                continue

            if is_transcript_feature(ftype_l, attrs):
                source_id = attrs.get("ID", "")
                parent = attrs.get("Parent", "")
                stable_id = first_nonempty(attrs.get("transcript_id"), strip_prefix(source_id), attrs.get("Name"))
                if not source_id:
                    source_id = f"transcript:{stable_id}"
                txs[source_id] = TxRec(
                    stable_id=stable_id,
                    source_id=source_id,
                    parent_gene_source=parent.split(",")[0] if parent else "",
                    seqid=seqid,
                    strand=strand if strand in ("+","-") else ".",
                    attrs=attrs
                )
                continue

            if ftype_l == "cds":
                parent = attrs.get("Parent", "")
                if parent:
                    cds_pending.append(SegRec(
                        parent_tx_source=parent.split(",")[0],
                        seqid=seqid, start=start_i, end=end_i,
                        strand=strand if strand in ("+","-") else ".",
                        phase=phase,
                        attrs=attrs
                    ))
                continue

            if ftype_l == "exon":
                parent = attrs.get("Parent", "")
                if parent:
                    exon_pending.append((parent.split(",")[0], seqid, start_i, end_i, strand if strand in ("+","-") else ".", attrs))
                continue

    # ------------------------------------------------------------------
    # Parent ID reconciliation (cross-species / cross-provider)
    #
    # Different GFF3 providers vary in what they put into Parent=...:
    #   - full source IDs (gene:..., transcript:...)
    #   - stripped stable IDs
    #   - Name/locus-tag style identifiers
    # This reconciliation maps common aliases back to the parsed source IDs.
    # ------------------------------------------------------------------
    gene_alias: Dict[str, str] = {}
    for gid, g in genes.items():
        for key in [gid, strip_prefix(gid), g.stable_id, g.attrs.get("ID", ""), g.attrs.get("gene_id", ""),
                    g.attrs.get("Name", ""), g.attrs.get("locus_tag", ""), g.attrs.get("gene", "")]:
            if key:
                gene_alias[key] = gid

    tx_alias: Dict[str, str] = {}
    for tid, t in txs.items():
        for key in [tid, strip_prefix(tid), t.stable_id, t.attrs.get("ID", ""), t.attrs.get("transcript_id", ""), t.attrs.get("Name", "")]:
            if key:
                tx_alias[key] = tid

    # Fix transcript->gene parent
    for tid, t in list(txs.items()):
        pg = t.parent_gene_source
        if pg and (pg not in genes) and (pg in gene_alias):
            txs[tid] = TxRec(
                stable_id=t.stable_id,
                source_id=t.source_id,
                parent_gene_source=gene_alias[pg],
                seqid=t.seqid,
                strand=t.strand,
                attrs=t.attrs,
            )

    # Fix CDS/exon parent transcript IDs
    for seg in cds_pending:
        p = seg.parent_tx_source
        if p and (p not in txs) and (p in tx_alias):
            seg.parent_tx_source = tx_alias[p]
    exon_pending_fixed: List[Tuple[str, str, int, int, str, Dict[str,str]]] = []
    for parent, seqid, start_i, end_i, strand, attrs in exon_pending:
        p = parent
        if p and (p not in txs) and (p in tx_alias):
            p = tx_alias[p]
        exon_pending_fixed.append((p, seqid, start_i, end_i, strand, attrs))
    exon_pending = exon_pending_fixed

    cds_by_tx: Dict[str, List[SegRec]] = {}
    for seg in cds_pending:
        cds_by_tx.setdefault(seg.parent_tx_source, []).append(seg)

    exons_by_tx: Dict[str, List[Tuple[int,int]]] = {}
    for parent, seqid, start_i, end_i, strand, attrs in exon_pending:
        exons_by_tx.setdefault(parent, []).append((start_i, end_i))

    return genes, txs, cds_by_tx, exons_by_tx


def materialize_pseudo_transcripts(genes_by_source: Dict[str, GeneRec],
                                   tx_by_source: Dict[str, TxRec],
                                   cds_by_tx: Dict[str, List[SegRec]],
                                   exons_by_tx: Dict[str, List[Tuple[int,int]]]) -> Tuple[Dict[str, TxRec], Dict[str, List[SegRec]], Dict[str, List[Tuple[int,int]]]]:
    """
    Cross-species hardening:
    Some (especially prokaryotic) annotations omit explicit mRNA/transcript features and attach CDS/exon
    directly to gene IDs via Parent=gene:xxx. This function creates pseudo transcripts so downstream
    CDS-feature computation still works.

    Returns possibly-updated (tx_by_source, cds_by_tx, exons_by_tx).
    """
    # promote CDS parents that are genes into pseudo transcripts
    def promote(parent_key: str) -> str:
        g = genes_by_source[parent_key]
        pseudo_source = f"pseudo_tx:{parent_key}"
        if pseudo_source not in tx_by_source:
            tx_by_source[pseudo_source] = TxRec(
                stable_id=g.stable_id,
                source_id=pseudo_source,
                parent_gene_source=parent_key,
                seqid=g.seqid,
                strand=g.strand if g.strand in ("+","-") else ".",
                attrs={"pseudo_transcript": "1", "derived_from_gene": parent_key},
            )
        return pseudo_source

    # CDS
    for parent_key in list(cds_by_tx.keys()):
        if parent_key in tx_by_source:
            continue
        if parent_key in genes_by_source:
            pseudo = promote(parent_key)
            cds_by_tx[pseudo] = cds_by_tx.pop(parent_key)

    # Exons
    for parent_key in list(exons_by_tx.keys()):
        if parent_key in tx_by_source:
            continue
        if parent_key in genes_by_source:
            pseudo = promote(parent_key)
            exons_by_tx[pseudo] = exons_by_tx.pop(parent_key)

    return tx_by_source, cds_by_tx, exons_by_tx


# -----------------------------
# Transcript selection / organelle code inference
# -----------------------------
def has_canonical_tag(tx: TxRec) -> bool:
    tag = tx.attrs.get("tag", "")
    if not tag:
        return False
    # tag can be comma-separated
    tags = set([t.strip() for t in tag.split(",") if t.strip()])
    return ("Ensembl_canonical" in tags) or ("canonical" in tags) or ("Canonical" in tags)

def choose_transcript_for_gene(tx_sources: List[str],
                               tx_by_source: Dict[str, TxRec],
                               cds_by_tx: Dict[str, List[SegRec]],
                               exons_by_tx: Optional[Dict[str, List[Tuple[int,int]]]] = None,
                               strategy: str = "auto") -> Tuple[str, str]:
    """
    Returns (chosen_tx_source_id, reason).
    strategy:
      - auto: canonical if available else longest CDS else first
      - canonical: require canonical else fallback longest
      - longest: pick transcript with longest CDS
      - first: first in list
    """
    if not tx_sources:
        return "", "none"
    if len(tx_sources) == 1:
        return tx_sources[0], "only"

    def cds_len(tx_source: str) -> int:
        segs = cds_by_tx.get(tx_source, [])
        if not segs:
            return 0
        # sum lengths
        return sum(abs(s.end - s.start) + 1 for s in segs)

    def exon_len(tx_source: str) -> int:
        if not exons_by_tx:
            return 0
        iv = exons_by_tx.get(tx_source, [])
        if not iv:
            return 0
        merged = merge_intervals(iv)
        return sum((e - s + 1) for s, e in merged)

    def score(tx_source: str) -> Tuple[int, int]:
        """Primary score by CDS length, secondary by exon length.

        For non-coding transcripts (CDS length == 0), exon length becomes primary
        discriminant downstream.
        """
        return (cds_len(tx_source), exon_len(tx_source))

    if strategy in ("auto", "canonical"):
        canon = [t for t in tx_sources if has_canonical_tag(tx_by_source.get(t, TxRec("",t,"","",".",{})))]
        if canon:
            # if multiple canonical, pick best by (CDS length, exon length)
            best = max(canon, key=score)
            return best, "canonical"
        if strategy == "canonical":
            # fallback
            best = max(tx_sources, key=score)
            # distinguish whether we fell back on CDS or exon
            return best, "longest_fallback"

    # Determine if any transcript is coding
    any_coding = any(cds_len(t) > 0 for t in tx_sources)

    if strategy in ("auto", "longest"):
        if any_coding:
            best = max(tx_sources, key=score)
            return best, "longest_cds"
        # no CDS for any transcript (non-coding gene); choose longest exon union
        best = max(tx_sources, key=exon_len) if exons_by_tx else tx_sources[0]
        return best, "longest_exon"
    return tx_sources[0], "first"

def infer_transl_table(seqid: str, default_table: int, mito_table: int, plastid_table: int,
                       mito_pattern: str, plastid_pattern: str) -> int:
    """
    Heuristic organelle detection by seqid name.
    """
    s = seqid or ""
    if mito_pattern and re.search(mito_pattern, s, flags=re.IGNORECASE):
        return mito_table
    if plastid_pattern and re.search(plastid_pattern, s, flags=re.IGNORECASE):
        return plastid_table
    return default_table

# -----------------------------
# Interval utilities (exon union)
# -----------------------------
def merge_intervals(intervals: List[Tuple[int,int]]) -> List[Tuple[int,int]]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: (x[0], x[1]))
    merged = [intervals[0]]
    for s,e in intervals[1:]:
        ps,pe = merged[-1]
        if s <= pe + 1:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s,e))
    return merged

def oriented_upstream_downstream_gaps(genes_on_contig: List[Tuple[str,int,int,str]]) -> Dict[str, Tuple[int,int,int,int]]:
    """
    genes_on_contig: list of (gene_source_id, start, end, strand), sorted by start.
    Returns gene_source_id -> (up_gap, down_gap, up_overlap, down_overlap)
    Gaps are in transcription direction: upstream means toward 5' end.
    """
    out = {}
    n = len(genes_on_contig)
    for i,(gid, s, e, strand) in enumerate(genes_on_contig):
        prev_end = genes_on_contig[i-1][2] if i>0 else None
        next_start = genes_on_contig[i+1][1] if i<n-1 else None

        left_gap = 0
        left_overlap = 0
        if prev_end is not None:
            if prev_end < s:
                left_gap = s - prev_end - 1
            else:
                left_overlap = prev_end - s + 1

        right_gap = 0
        right_overlap = 0
        if next_start is not None:
            if e < next_start:
                right_gap = next_start - e - 1
            else:
                right_overlap = e - next_start + 1

        if strand == "-":
            up_gap, down_gap = right_gap, left_gap
            up_ov, down_ov = right_overlap, left_overlap
        else:
            up_gap, down_gap = left_gap, right_gap
            up_ov, down_ov = left_overlap, right_overlap

        out[gid] = (up_gap, down_gap, up_ov, down_ov)
    return out

# -----------------------------
# Feature builders
# -----------------------------
def region_features(prefix: str, seq: str) -> Dict[str, object]:
    """
    Base composition / skews / entropy for a sequence.
    """
    bc = count_bases(seq)
    length = len(seq)
    acgt = bc["A"] + bc["C"] + bc["G"] + bc["T"]
    gc = bc["G"] + bc["C"]
    out: Dict[str, object] = {}
    out[f"{prefix}length_bp"] = length
    out[f"{prefix}length_acgt_bp"] = acgt
    out[f"{prefix}count_A"] = bc["A"]
    out[f"{prefix}count_C"] = bc["C"]
    out[f"{prefix}count_G"] = bc["G"]
    out[f"{prefix}count_T"] = bc["T"]
    out[f"{prefix}count_N"] = bc["N"]
    out[f"{prefix}gc_percent"] = safe_div(gc * 100.0, acgt) if acgt>0 else float("nan")
    out[f"{prefix}n_percent"] = safe_div(bc["N"] * 100.0, length) if length>0 else float("nan")
    out[f"{prefix}at_skew"] = safe_div((bc["A"] - bc["T"]), (bc["A"] + bc["T"])) if (bc["A"]+bc["T"])>0 else float("nan")
    out[f"{prefix}gc_skew"] = safe_div((bc["G"] - bc["C"]), (bc["G"] + bc["C"])) if (bc["G"]+bc["C"])>0 else float("nan")
    out[f"{prefix}shannon_entropy_acgt"] = shannon_entropy_acgt(bc)
    atoms = dna_atom_counts(bc)
    for el in ("C","H","O","N","P"):
        out[f"{prefix}atoms_{el}"] = atoms[el]
        out[f"{prefix}atoms_{el}_per_base"] = safe_div(atoms[el], acgt) if acgt>0 else float("nan")
    out[f"{prefix}ratio_C_N"] = safe_div(atoms["C"], atoms["N"]) if atoms["N"]>0 else float("nan")
    out[f"{prefix}ratio_C_P"] = safe_div(atoms["C"], atoms["P"]) if atoms["P"]>0 else float("nan")
    out[f"{prefix}ratio_N_P"] = safe_div(atoms["N"], atoms["P"]) if atoms["P"]>0 else float("nan")
    return out

def add_dinuc(prefix: str, seq: str, out: Dict[str, object]):
    dcounts, total = dinuc_counts(seq)
    out[f"{prefix}dinuc_total_valid"] = total
    for k in DINUCS:
        out[f"{prefix}dinuc_{k}_count"] = dcounts[k]
    for k in DINUCS:
        out[f"{prefix}dinuc_{k}_freq"] = safe_div(dcounts[k], total) if total>0 else float("nan")

CODONS_64_CORE = [a+b+c for a in "ACGT" for b in "ACGT" for c in "ACGT"]  # AAA..TTT order (lexicographic)

def codon_counts_freqs(cds_seq: str) -> Tuple[Dict[str,int], Dict[str,float], int]:
    seq = cds_seq.upper()
    counts = {c: 0 for c in CODONS_64_CORE}
    total = 0
    n = len(seq) // 3
    for i in range(n):
        codon = seq[i*3:(i+1)*3]
        if re.fullmatch(r"[ACGT]{3}", codon):
            counts[codon] += 1
            total += 1
    freqs = {c: (counts[c]/total if total>0 else float("nan")) for c in CODONS_64_CORE}
    return counts, freqs, total

def position_gc(cds_seq: str, pos: int) -> float:
    # pos: 0,1,2 for GC at codon position
    seq = cds_seq.upper()
    gc = 0
    total = 0
    for i in range(pos, len(seq) - ((len(seq)-pos) % 3), 3):
        b = seq[i]
        if b in "ACGT":
            total += 1
            if b in "GC":
                gc += 1
    return safe_div(gc*100.0, total) if total>0 else float("nan")

def entropy_from_freqs(freqs: Dict[str,float]) -> float:
    h = 0.0
    for p in freqs.values():
        if isinstance(p, float) and not math.isnan(p) and p > 0:
            h -= p * math.log(p, 2)
    return h

def aa_counts_freqs_from_codons(codon_counts: Dict[str,int], transl_table: int) -> Tuple[Dict[str,int], Dict[str,float], int, int]:
    """
    Returns (aa20_counts, aa20_freqs, stop_count, x_count)
    """
    cmap = codon_to_aa_map(transl_table)
    aa_counts = {aa: 0 for aa in AA20}
    stop = 0
    x = 0
    total_codons = sum(codon_counts.values())
    for codon, n in codon_counts.items():
        if n <= 0:
            continue
        aa = cmap.get(codon, "X")
        if aa == "*":
            stop += n
        elif aa in aa_counts:
            aa_counts[aa] += n
        else:
            x += n
    total20 = sum(aa_counts.values())
    aa_freqs = {aa: (aa_counts[aa]/total20 if total20>0 else float("nan")) for aa in AA20}
    return aa_counts, aa_freqs, stop, x

# -----------------------------
# CDS / exon sequence assembly
# -----------------------------
def build_exon_union_seq(fasta: FastaIndexed, seqid: str, exon_intervals: List[Tuple[int,int]], strand: str, orient: bool) -> str:
    merged = merge_intervals(exon_intervals)
    if not merged:
        return ""
    parts = []
    if strand == "-" and orient:
        # fetch each interval, then reverse-complement and concatenate in reverse order (5'->3')
        for s,e in sorted(merged, key=lambda x: x[0], reverse=True):
            parts.append(fasta.fetch(seqid, s, e, oriented=True, strand="-"))
        return "".join(parts)
    else:
        for s,e in sorted(merged, key=lambda x: x[0]):
            parts.append(fasta.fetch(seqid, s, e, oriented=False))
        seq = "".join(parts)
        return revcomp(seq) if (orient and strand == "-") else seq

def build_cds_seq(fasta: FastaIndexed, cds_segs: List[SegRec], strand: str, orient: bool, respect_phase: bool) -> Tuple[str, int]:
    """
    Assemble spliced CDS sequence in transcription direction.

    IMPORTANT:
      In GFF3, CDS features may carry a "phase" (0/1/2). That phase is meant to
      describe the reading frame at the start of a CDS feature when interpreting
      features in isolation. When we assemble the *full spliced CDS* by
      concatenating CDS segments in transcript order, codons can legally cross
      segment boundaries. Therefore trimming each segment by its phase would
      REMOVE real coding bases and introduce frame shifts.

    Implementation here:
      - Concatenate oriented CDS segments in transcript order (no per-segment trimming).
      - Optionally (respect_phase=True), apply only the FIRST-segment phase as a
        global start offset (rare; usually 0 in Ensembl/SGD GFF3). This keeps the
        option meaningful without breaking spliced CDS assembly.

    Returns (seq, trimmed_bases_total_due_to_phase)
    """
    if not cds_segs:
        return "", 0

    # Transcript order
    if strand == "-" and orient:
        ordered = sorted(cds_segs, key=lambda s: (s.start, s.end), reverse=True)
    else:
        ordered = sorted(cds_segs, key=lambda s: (s.start, s.end))

    parts = [fasta.fetch(seg.seqid, seg.start, seg.end, oriented=orient, strand=strand) for seg in ordered]
    seq = "".join(parts).upper()

    trimmed_total = 0
    if respect_phase and ordered:
        ph = ordered[0].phase
        if ph in ("0", "1", "2"):
            trim = int(ph)
            if trim > 0:
                seq = seq[trim:] if len(seq) > trim else ""
                trimmed_total = trim

    return seq, trimmed_total

# -----------------------------
# Main per-species processing

# -----------------------------
def process_one_species(fasta_path: str, gff_path: str, species_id: str, promoter_len: int,
                        default_codon_table: int, mito_table: int, plastid_table: int,
                        mito_pattern: str, plastid_pattern: str,
                        transcript_strategy: str, orient_to_transcription: bool, respect_phase: bool,
                        include_exon: bool, include_cds_dna: bool, progress: bool = True, progress_every: int = 200) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """
    Returns (rows, schema_info)
    """
    fasta = FastaIndexed(fasta_path)
    genes_by_source, tx_by_source, cds_by_tx, exons_by_tx = parse_gff3(gff_path)
    tx_by_source, cds_by_tx, exons_by_tx = materialize_pseudo_transcripts(genes_by_source, tx_by_source, cds_by_tx, exons_by_tx)

    # Build gene->transcripts list
    gene_to_txs: Dict[str, List[str]] = {}
    for tx_source, tx in tx_by_source.items():
        pg = tx.parent_gene_source
        if not pg:
            continue
        gene_to_txs.setdefault(pg, []).append(tx_source)

    # Intergenic gaps per contig
    contig2genes: Dict[str, List[Tuple[str,int,int,str]]] = {}
    # Build contig -> genes index. This is an O(N) pass and can be slow on large genomes,
    # so we optionally show a lightweight progress bar. IMPORTANT: pb must be defined
    # before it is used (a previous version referenced pb before assignment).
    pb_index = ProgressBar(
        total=len(genes_by_source),
        desc=f"{species_id}: indexing",
        enabled=progress,
        every=progress_every,
    )
    _i = 0
    for gene_source, g in genes_by_source.items():
        _i += 1
        if pb_index:
            pb_index.update(_i)
        contig2genes.setdefault(g.seqid, []).append((gene_source, g.start, g.end, g.strand))
    if pb_index:
        pb_index.close()
    gaps: Dict[str, Tuple[int,int,int,int]] = {}
    for contig, glist in contig2genes.items():
        glist_sorted = sorted(glist, key=lambda x: x[1])
        gaps.update(oriented_upstream_downstream_gaps(glist_sorted))

    rows: List[Dict[str, object]] = []

    pb = ProgressBar(total=len(genes_by_source), desc=f"{species_id}: genes", enabled=progress, every=progress_every)

    # precompute codon column names
    codon_count_cols = [f"codon_{c}_count" for c in CODONS_64_CORE]
    codon_freq_cols = [f"codon_{c}_freq" for c in CODONS_64_CORE]
    aa_count_cols = [f"aa_{a}_count" for a in AA20]
    aa_freq_cols = [f"aa_{a}_freq" for a in AA20]

    _i = 0
    for gene_source, g in genes_by_source.items():
        _i += 1
        if pb:
            pb.update(_i)
        strand = g.strand if g.strand in ("+","-") else "+"
        seqid = g.seqid

        # choose transcript for CDS/exon features
        tx_list = gene_to_txs.get(gene_source, [])
        chosen_tx_source, chosen_reason = choose_transcript_for_gene(
            tx_list, tx_by_source, cds_by_tx, exons_by_tx=exons_by_tx, strategy=transcript_strategy
        )
        chosen_tx = tx_by_source.get(chosen_tx_source) if chosen_tx_source else None

        # infer transl_table for coding translation (aa features)
        transl_table_used = infer_transl_table(seqid, default_codon_table, mito_table, plastid_table, mito_pattern, plastid_pattern)

        # locus sequence (gene span)
        locus_seq = fasta.fetch(seqid, g.start, g.end, oriented=orient_to_transcription, strand=strand)

        # promoter region (upstream 5')
        if strand == "+":
            p_start = max(1, g.start - promoter_len)
            p_end = max(0, g.start - 1)
        else:
            p_start = g.end + 1
            p_end = g.end + promoter_len
        promoter_seq = fasta.fetch(seqid, p_start, p_end, oriented=orient_to_transcription, strand=strand) if p_start <= p_end else ""

        # exon union sequence (chosen transcript if available)
        exon_seq = ""
        exon_len_note = ""
        if include_exon and chosen_tx_source:
            exon_intervals = exons_by_tx.get(chosen_tx_source, [])
            if exon_intervals:
                exon_seq = build_exon_union_seq(fasta, seqid, exon_intervals, strand, orient_to_transcription)
                exon_len_note = "tx_exon_union"
        if include_exon and not exon_seq:
            exon_seq = locus_seq
            exon_len_note = "fallback_locus"

        # CDS sequence (chosen transcript)
        cds_seq = ""
        phase_trimmed = 0
        if chosen_tx_source:
            cds_segs = cds_by_tx.get(chosen_tx_source, [])
            if cds_segs:
                cds_seq, phase_trimmed = build_cds_seq(fasta, cds_segs, strand, orient_to_transcription, respect_phase)

        # prepare row
        row: Dict[str, object] = {}
        row["species_id"] = species_id
        row["gene_id"] = g.stable_id
        row["source_gene_id"] = g.source_id
        row["gene_name"] = first_nonempty(g.attrs.get("Name"), g.attrs.get("gene"), g.attrs.get("locus_tag"))
        row["locus_tag"] = g.attrs.get("locus_tag", "")
        row["biotype"] = g.biotype
        row["seqid"] = seqid
        row["start_1"] = g.start
        row["end_1"] = g.end
        row["strand"] = strand
        row["is_coding"] = 1 if cds_seq else 0
        row["transcript_count"] = len(tx_list)
        row["chosen_transcript_id"] = chosen_tx.stable_id if chosen_tx else ""
        row["chosen_transcript_source_id"] = chosen_tx.source_id if chosen_tx else ""
        row["chosen_transcript_reason"] = chosen_reason
        row["transl_table_used"] = transl_table_used
        row["respect_phase"] = 1 if respect_phase else 0
        row["phase_trimmed_bases"] = phase_trimmed
        if include_exon:
            row["exon_seq_strategy"] = exon_len_note

        up_gap, down_gap, up_ov, down_ov = gaps.get(gene_source, (0,0,0,0))
        row["upstream_intergenic_bp"] = up_gap
        row["downstream_intergenic_bp"] = down_gap
        row["upstream_overlap_bp"] = up_ov
        row["downstream_overlap_bp"] = down_ov

        # Region features
        row.update(region_features("locus_", locus_seq))
        row.update(region_features("promoter_", promoter_seq))
        add_dinuc("locus_", locus_seq, row)
        add_dinuc("promoter_", promoter_seq, row)

        if include_exon:
            row.update(region_features("exon_", exon_seq))
        if include_cds_dna:
            row.update(region_features("cds_", cds_seq))

        # CDS-derived codon/AA features
        if cds_seq:
            # ensure in-frame multiple of 3
            rem = len(cds_seq) % 3
            if rem != 0:
                cds_seq_eff = cds_seq[:-rem]
                row["cds_truncated_tail_bp"] = rem
            else:
                cds_seq_eff = cds_seq
                row["cds_truncated_tail_bp"] = 0

            row["cds_length_bp"] = len(cds_seq_eff)
            row["codon_total_theoretical"] = len(cds_seq_eff) // 3

            c_counts, c_freqs, c_total = codon_counts_freqs(cds_seq_eff)
            row["codon_total_valid"] = c_total

            for c in CODONS_64_CORE:
                row[f"codon_{c}_count"] = c_counts[c]
            for c in CODONS_64_CORE:
                row[f"codon_{c}_freq"] = c_freqs[c]

            row["gc1_percent"] = position_gc(cds_seq_eff, 0)
            row["gc2_percent"] = position_gc(cds_seq_eff, 1)
            row["gc3_percent"] = position_gc(cds_seq_eff, 2)

            row["codon_entropy_bits"] = entropy_from_freqs({k:v for k,v in c_freqs.items() if not math.isnan(v)})

            aa_counts, aa_freqs, stop_count, x_count = aa_counts_freqs_from_codons(c_counts, transl_table_used)
            row["aa_total_20"] = sum(aa_counts.values())
            row["aa_stop_count"] = stop_count
            row["aa_X_count"] = x_count

            for a in AA20:
                row[f"aa_{a}_count"] = aa_counts[a]
            for a in AA20:
                row[f"aa_{a}_freq"] = aa_freqs[a]
            row["aa_entropy_bits"] = entropy_from_freqs({k:v for k,v in aa_freqs.items() if not math.isnan(v)})
        else:
            # still include columns as empty/NaN for schema stability
            row["cds_truncated_tail_bp"] = ""
            row["cds_length_bp"] = ""
            row["codon_total_theoretical"] = ""
            row["codon_total_valid"] = ""
            row["gc1_percent"] = ""
            row["gc2_percent"] = ""
            row["gc3_percent"] = ""
            row["codon_entropy_bits"] = ""
            row["aa_total_20"] = ""
            row["aa_stop_count"] = ""
            row["aa_X_count"] = ""
            row["aa_entropy_bits"] = ""
            for c in CODONS_64_CORE:
                row[f"codon_{c}_count"] = ""
                row[f"codon_{c}_freq"] = ""
            for a in AA20:
                row[f"aa_{a}_count"] = ""
                row[f"aa_{a}_freq"] = ""

        rows.append(row)

    if pb:
        pb.close()

    fasta.close()

    # Build a simple schema description (types inferred)
    schema = {
        "version": "v3.3",
        "entity": "gene",
        "primary_key": ["species_id", "gene_id"],
        "notes": "CDS features computed from chosen transcript in multi-transcript genes.",
    }
    return rows, schema

# -----------------------------
# CSV writing / schema emission
# -----------------------------
def write_csv(path: str, rows: List[Dict[str, object]], columns: Optional[List[str]] = None):
    if not rows:
        eprint(f"[WARN] no rows to write: {path}")
        return
    # stable column order: metadata first, then sorted, unless explicit columns are given
    meta_cols = [
        "species_id","gene_id","source_gene_id","gene_name","locus_tag","biotype",
        "seqid","start_1","end_1","strand","is_coding",
        "transcript_count","chosen_transcript_id","chosen_transcript_source_id","chosen_transcript_reason",
        "transl_table_used","respect_phase","phase_trimmed_bases","exon_seq_strategy",
        "upstream_intergenic_bp","downstream_intergenic_bp","upstream_overlap_bp","downstream_overlap_bp",
    ]
    all_cols = list(rows[0].keys())
    # ensure all rows have all cols
    colset = set(all_cols)
    for r in rows[1:]:
        colset |= set(r.keys())

    if columns is not None:
        # Explicit column order for CORE output. Keep requested order first, then append any extra columns.
        cols = list(columns) + [c for c in sorted(colset) if c not in set(columns)]
    else:
        # final columns: meta in order if exists, then rest alpha
        rest = sorted([c for c in colset if c not in meta_cols])
        cols = [c for c in meta_cols if c in colset] + rest

    # add missing keys for selected columns only
    for r in rows:
        for c in cols:
            if c not in r:
                r[c] = ""

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def emit_schema_json(path: str, rows: List[Dict[str, object]], schema_info: Dict[str, object]):
    if not rows:
        return
    # infer types from first non-empty value
    cols = sorted(rows[0].keys())
    fields = []
    for c in cols:
        t = "string"
        for r in rows:
            v = r.get(c, "")
            if v == "" or v is None:
                continue
            if isinstance(v, int):
                t = "integer"
            elif isinstance(v, float):
                t = "number"
            else:
                # try parse numeric strings
                if isinstance(v, str) and re.fullmatch(r"-?\d+", v):
                    t = "integer"
                elif isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v):
                    t = "number"
                else:
                    t = "string"
            break
        fields.append({"name": c, "type": t})
    out = {"schema": schema_info, "fields": fields}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

# -----------------------------
# CLI
# -----------------------------
def parse_args():
    ap = argparse.ArgumentParser(description="Genome stoichiometric feature extractor (v3)")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--batch-manifest", default="", help="CSV manifest with columns: species_id,fasta,gff (and optional promoter_len,codon_table,out)")
    grp.add_argument("--fasta", default="", help="Genome FASTA")
    ap.add_argument("--gff", default="", help="GFF3 annotation (required unless batch)")
    ap.add_argument("--species-id", default="", help="Species ID (required unless batch)")
    ap.add_argument("--out", default="", help="Output CSV path (required unless batch)")
    ap.add_argument("--out-dir", default="", help="Output directory for batch mode (default: ./out)")
    ap.add_argument("--promoter-len", type=int, default=100, help="Promoter upstream length (bp)")
    ap.add_argument("--codon-table", type=int, default=11, help="Default NCBI transl_table for nuclear/bacterial chromosomes")
    ap.add_argument("--mito-codon-table", type=int, default=1, help="NCBI transl_table for mitochondria")
    ap.add_argument("--plastid-codon-table", type=int, default=11, help="NCBI transl_table for plastids (often 11)")
    ap.add_argument("--mito-pattern", default=r"(mito|mt|chrm|mitochond)", help="Regex to detect mitochondrial contigs by seqid")
    ap.add_argument("--plastid-pattern", default=r"(chloro|plastid|cpdna|chrpt|chloroplast)", help="Regex to detect plastid contigs by seqid")
    ap.add_argument("--transcript-strategy", choices=["auto","canonical","longest","first"], default="auto",
                    help="How to choose transcript for CDS features in multi-transcript genes")
    ap.add_argument("--no-orient", action="store_true", help="Do NOT orient sequences to transcription direction (keep genomic orientation)")
    ap.add_argument("--respect-phase", action="store_true", help="Trim CDS segments using GFF phase to preserve reading frame")
    ap.add_argument("--include-exon", action="store_true", help="Include exon-union region features (default: off)")
    ap.add_argument("--include-cds-dna", action="store_true", help="Include CDS DNA region features (base composition/atoms) (default: off)")
    
    ap.add_argument("--feature-set", choices=FEATURE_SET_CHOICES, default="full",
                    help="Which feature table to emit: full (all fields), core (compact ML/Frontend set), or both")
    ap.add_argument("--fill-noncoding", choices=["zero","nan"], default="zero",
                    help="For CORE: how to fill coding-layer fields for noncoding / invalid-coding genes (default: zero)")
    ap.add_argument("--no-progress", action="store_true", help="Disable progress display")
    ap.add_argument("--progress-every", type=int, default=200, help="Progress update interval in genes (default: 200)")
    ap.add_argument("--emit-schema", default="", help="Write a JSON schema description (field names + inferred types)")
    ap.add_argument(
        "--force-rerun",
        action="store_true",
        help="In batch mode, recompute species even when expected output files already exist.",
    )
    return ap.parse_args()

def run_single(args):
    if not args.gff or not args.species_id or not args.out:
        raise SystemExit("For single mode, you must provide --gff --species-id --out")
    # feature-set preflight (may auto-enable exon features)
    feature_set_pre = (args.feature_set or "full").lower()
    if feature_set_pre not in FEATURE_SET_CHOICES:
        feature_set_pre = "full"
    if feature_set_pre in ("core","both") and (not args.include_exon):
        eprint("[INFO] --feature-set core/both implies exon features; enabling --include-exon automatically.")
        args.include_exon = True

    rows, schema_info = process_one_species(
        fasta_path=args.fasta,
        gff_path=args.gff,
        species_id=args.species_id,
        promoter_len=args.promoter_len,
        default_codon_table=args.codon_table,
        mito_table=args.mito_codon_table,
        plastid_table=args.plastid_codon_table,
        mito_pattern=args.mito_pattern,
        plastid_pattern=args.plastid_pattern,
        transcript_strategy=args.transcript_strategy,
        orient_to_transcription=(not args.no_orient),
        respect_phase=args.respect_phase,
        include_exon=args.include_exon,
        include_cds_dna=args.include_cds_dna,
        progress=(not args.no_progress),
        progress_every=args.progress_every,
    )
    feature_set = (args.feature_set or "full").lower()
    if feature_set not in FEATURE_SET_CHOICES:
        feature_set = "full"

    # CORE needs exon_ features; enable automatically if not requested
    if feature_set in ("core","both") and (not args.include_exon):
        eprint("[INFO] --feature-set core/both implies exon features; enabling --include-exon automatically.")
        args.include_exon = True

    if feature_set == "core":
        core_rows = build_core_rows(rows, fill_noncoding=args.fill_noncoding)
        write_csv(args.out, core_rows, columns=CORE_FEATURE_COLUMNS)
        if args.emit_schema:
            emit_schema_json(args.emit_schema, core_rows, {"feature_set": "core", **schema_info})
        eprint(f"[OK] wrote CORE {len(core_rows)} rows -> {args.out}")
    elif feature_set == "both":
        # write FULL to --out, and CORE next to it
        write_csv(args.out, rows)
        out_core = os.path.splitext(args.out)[0] + ".core.csv"
        core_rows = build_core_rows(rows, fill_noncoding=args.fill_noncoding)
        write_csv(out_core, core_rows, columns=CORE_FEATURE_COLUMNS)
        if args.emit_schema:
            base = os.path.splitext(args.emit_schema)[0]
            emit_schema_json(base + ".full.schema.json", rows, {"feature_set": "full", **schema_info})
            emit_schema_json(base + ".core.schema.json", core_rows, {"feature_set": "core", **schema_info})
        eprint(f"[OK] wrote FULL {len(rows)} rows -> {args.out}")
        eprint(f"[OK] wrote CORE {len(core_rows)} rows -> {out_core}")
    else:
        write_csv(args.out, rows)
        if args.emit_schema:
            emit_schema_json(args.emit_schema, rows, {"feature_set": "full", **schema_info})
        eprint(f"[OK] wrote FULL {len(rows)} rows -> {args.out}")

def file_nonempty(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False

def expected_batch_outputs(out: str, feature_set: str, emit_schema: str) -> List[str]:
    outputs = [out]
    if feature_set == "both":
        out_core = os.path.splitext(out)[0] + ".core.csv"
        outputs.append(out_core)
        if emit_schema:
            outputs.append(os.path.splitext(out)[0] + ".full.schema.json")
            outputs.append(os.path.splitext(out_core)[0] + ".schema.json")
    elif feature_set == "core":
        if emit_schema:
            outputs.append(os.path.splitext(out)[0] + ".schema.json")
    else:
        if emit_schema:
            outputs.append(os.path.splitext(out)[0] + ".schema.json")
    return outputs

def missing_batch_outputs(out: str, feature_set: str, emit_schema: str) -> List[str]:
    return [path for path in expected_batch_outputs(out, feature_set, emit_schema) if not file_nonempty(path)]

def run_batch(args):
    out_dir = args.out_dir or "./out"
    os.makedirs(out_dir, exist_ok=True)
    if args.force_rerun:
        eprint("[BATCH] --force-rerun enabled; existing outputs will be recomputed.")
    else:
        eprint("[BATCH] resume mode enabled; species with complete existing outputs will be skipped.")
    with open(args.batch_manifest, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"species_id","fasta","gff"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise SystemExit(f"Manifest must have columns: {sorted(required)} (optional: promoter_len,codon_table,out)")
        for row in reader:
            sid = row["species_id"].strip()
            fasta = row["fasta"].strip()
            gff = row["gff"].strip()
            if not sid or not fasta or not gff:
                continue
            promoter_len = int(row.get("promoter_len", args.promoter_len) or args.promoter_len)
            codon_table = int(row.get("codon_table", args.codon_table) or args.codon_table)
            mito_table = int(row.get("mito_codon_table", args.mito_codon_table) or args.mito_codon_table)
            plastid_table = int(row.get("plastid_codon_table", args.plastid_codon_table) or args.plastid_codon_table)

            feature_set = (row.get("feature_set", args.feature_set) or args.feature_set).strip().lower()
            if feature_set not in FEATURE_SET_CHOICES:
                feature_set = "full"
            fill_noncoding = (row.get("fill_noncoding", args.fill_noncoding) or args.fill_noncoding).strip().lower()
            if fill_noncoding not in ("zero","nan"):
                fill_noncoding = "zero"

            out = row.get("out", "").strip()
            if not out:
                if feature_set == "core":
                    out = os.path.join(out_dir, f"{sid}.genome_features_core.csv")
                else:
                    out = os.path.join(out_dir, f"{sid}.genome_features.csv")
            if not args.force_rerun:
                missing_outputs = missing_batch_outputs(out, feature_set, args.emit_schema)
                if not missing_outputs:
                    eprint(f"[SKIP] {sid}: existing outputs complete")
                    continue
                existing_outputs = [
                    path for path in expected_batch_outputs(out, feature_set, args.emit_schema)
                    if file_nonempty(path)
                ]
                if existing_outputs:
                    eprint(f"[RESUME] {sid}: incomplete output set; recomputing species. Missing: {', '.join(missing_outputs)}")
            rows, schema_info = process_one_species(
                fasta_path=fasta, gff_path=gff, species_id=sid, promoter_len=promoter_len,
                default_codon_table=codon_table, mito_table=mito_table, plastid_table=plastid_table,
                mito_pattern=args.mito_pattern, plastid_pattern=args.plastid_pattern,
                transcript_strategy=args.transcript_strategy,
                orient_to_transcription=(not args.no_orient),
                respect_phase=args.respect_phase,
                include_exon=(args.include_exon or feature_set in ("core","both")),
                include_cds_dna=args.include_cds_dna,
                progress=(not args.no_progress),
                progress_every=args.progress_every,
            )
            if feature_set == "core":
                core_rows = build_core_rows(rows, fill_noncoding=fill_noncoding)
                write_csv(out, core_rows, columns=CORE_FEATURE_COLUMNS)
                if args.emit_schema:
                    schema_path = os.path.splitext(out)[0] + ".schema.json"
                    emit_schema_json(schema_path, core_rows, {"feature_set": "core", **schema_info})
                eprint(f"[OK] {sid}: CORE {len(core_rows)} rows -> {out}")
            elif feature_set == "both":
                write_csv(out, rows)
                out_core = os.path.splitext(out)[0] + ".core.csv"
                core_rows = build_core_rows(rows, fill_noncoding=fill_noncoding)
                write_csv(out_core, core_rows, columns=CORE_FEATURE_COLUMNS)
                if args.emit_schema:
                    emit_schema_json(os.path.splitext(out)[0] + ".full.schema.json", rows, {"feature_set": "full", **schema_info})
                    emit_schema_json(os.path.splitext(out_core)[0] + ".schema.json", core_rows, {"feature_set": "core", **schema_info})
                eprint(f"[OK] {sid}: FULL {len(rows)} rows -> {out}")
                eprint(f"[OK] {sid}: CORE {len(core_rows)} rows -> {out_core}")
            else:
                write_csv(out, rows)
                if args.emit_schema:
                    schema_path = os.path.splitext(out)[0] + ".schema.json"
                    emit_schema_json(schema_path, rows, {"feature_set": "full", **schema_info})
                eprint(f"[OK] {sid}: FULL {len(rows)} rows -> {out}")

def main():
    args = parse_args()
    if args.batch_manifest:
        run_batch(args)
    else:
        run_single(args)

if __name__ == "__main__":
    main()
