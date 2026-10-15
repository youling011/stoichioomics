from __future__ import annotations

import csv
import gzip
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


ELEMENTAL_CONTRACT_ID = "model8-protein-elemental-v2"

# Polymerized amino-acid residue formulas. Terminal H2O does not alter C/N/S.
AA_RESIDUE_FORMULAS: dict[str, dict[str, int]] = {
    "A": {"C": 3, "H": 5, "N": 1, "O": 1},
    "R": {"C": 6, "H": 12, "N": 4, "O": 1},
    "N": {"C": 4, "H": 6, "N": 2, "O": 2},
    "D": {"C": 4, "H": 5, "N": 1, "O": 3},
    "C": {"C": 3, "H": 5, "N": 1, "O": 1, "S": 1},
    "E": {"C": 5, "H": 7, "N": 1, "O": 3},
    "Q": {"C": 5, "H": 8, "N": 2, "O": 2},
    "G": {"C": 2, "H": 3, "N": 1, "O": 1},
    "H": {"C": 6, "H": 7, "N": 3, "O": 1},
    "I": {"C": 6, "H": 11, "N": 1, "O": 1},
    "L": {"C": 6, "H": 11, "N": 1, "O": 1},
    "K": {"C": 6, "H": 12, "N": 2, "O": 1},
    "M": {"C": 5, "H": 9, "N": 1, "O": 1, "S": 1},
    "F": {"C": 9, "H": 9, "N": 1, "O": 1},
    "P": {"C": 5, "H": 7, "N": 1, "O": 1},
    "S": {"C": 3, "H": 5, "N": 1, "O": 2},
    "T": {"C": 4, "H": 7, "N": 1, "O": 2},
    "W": {"C": 11, "H": 10, "N": 2, "O": 1},
    "Y": {"C": 9, "H": 9, "N": 1, "O": 2},
    "V": {"C": 5, "H": 9, "N": 1, "O": 1},
}

ELEMENTAL_FIELDS = [
    "c_atoms",
    "n_atoms",
    "s_atoms",
    "c_atoms_per_aa",
    "n_atoms_per_aa",
    "s_atoms_per_aa",
]
RESIDUE_COUNT_FIELDS = ["cys_count", "ser_count", "asn_count", "met_count"]
LEGACY_AMBIGUOUS_FIELDS = {
    "c_count",
    "s_count",
    "n_count",
    "c_per_aa",
    "s_per_aa",
    "n_per_aa",
    "protein_c_per_aa",
    "protein_s_per_aa",
    "protein_n_per_aa",
}


def canonical_protein_sequence(sequence: str) -> tuple[str, int, int]:
    cleaned = re.sub(r"[^A-Z*]", "", sequence.upper())
    stop_count = cleaned.count("*")
    without_stops = cleaned.replace("*", "")
    canonical = "".join(aa for aa in without_stops if aa in AA_RESIDUE_FORMULAS)
    invalid_aa_count = len(without_stops) - len(canonical)
    return canonical, stop_count, invalid_aa_count


def protein_elemental_features(sequence: str) -> dict[str, int | float]:
    canonical, stop_count, invalid_aa_count = canonical_protein_sequence(sequence)
    counts = Counter(canonical)
    atom_totals = {atom: 0 for atom in ("C", "N", "S")}
    for aa, count in counts.items():
        formula = AA_RESIDUE_FORMULAS[aa]
        for atom in atom_totals:
            atom_totals[atom] += count * formula.get(atom, 0)
    length = len(canonical)
    divide = lambda value: value / length if length else 0.0
    return {
        "length": length,
        "cys_count": counts.get("C", 0),
        "ser_count": counts.get("S", 0),
        "asn_count": counts.get("N", 0),
        "met_count": counts.get("M", 0),
        "c_atoms": atom_totals["C"],
        "n_atoms": atom_totals["N"],
        "s_atoms": atom_totals["S"],
        "c_atoms_per_aa": divide(atom_totals["C"]),
        "n_atoms_per_aa": divide(atom_totals["N"]),
        "s_atoms_per_aa": divide(atom_totals["S"]),
        "stop_count": stop_count,
        "invalid_aa_count": invalid_aa_count,
    }


def validate_elemental_row(row: dict[str, Any], tolerance: float = 5e-6) -> list[str]:
    errors: list[str] = []
    try:
        length = int(float(row.get("length") or 0))
        c_atoms = int(float(row.get("c_atoms") or 0))
        n_atoms = int(float(row.get("n_atoms") or 0))
        s_atoms = int(float(row.get("s_atoms") or 0))
        cys_count = int(float(row.get("cys_count") or 0))
        met_count = int(float(row.get("met_count") or 0))
        ratios = {
            "c_atoms_per_aa": float(row.get("c_atoms_per_aa") or 0),
            "n_atoms_per_aa": float(row.get("n_atoms_per_aa") or 0),
            "s_atoms_per_aa": float(row.get("s_atoms_per_aa") or 0),
        }
    except (TypeError, ValueError) as exc:
        return [f"non-numeric elemental field: {exc}"]
    if min(length, c_atoms, n_atoms, s_atoms, cys_count, met_count) < 0:
        errors.append("negative count")
    if s_atoms != cys_count + met_count:
        errors.append("s_atoms must equal cys_count + met_count for canonical residues")
    expected = {
        "c_atoms_per_aa": c_atoms / length if length else 0.0,
        "n_atoms_per_aa": n_atoms / length if length else 0.0,
        "s_atoms_per_aa": s_atoms / length if length else 0.0,
    }
    for field, value in ratios.items():
        if not math.isfinite(value) or abs(value - expected[field]) > tolerance:
            errors.append(f"{field} inconsistent with atom total and length")
    if length:
        if not 2.0 <= ratios["c_atoms_per_aa"] <= 11.0:
            errors.append("c_atoms_per_aa outside residue-formula bounds")
        if not 1.0 <= ratios["n_atoms_per_aa"] <= 4.0:
            errors.append("n_atoms_per_aa outside residue-formula bounds")
        if not 0.0 <= ratios["s_atoms_per_aa"] <= 1.0:
            errors.append("s_atoms_per_aa outside residue-formula bounds")
    return errors


def validate_model8_protein_feature_files(model8_dir: Path) -> dict[str, Any]:
    species_order = ["ECOLI", "BSUB", "ORYSA", "DROME", "YEAST", "ARATH", "DANRE", "MOUSE"]
    required = {"length", *RESIDUE_COUNT_FIELDS, *ELEMENTAL_FIELDS}
    files: list[dict[str, Any]] = []
    error_examples: list[dict[str, Any]] = []
    total_rows = 0
    for code in species_order:
        path = model8_dir / code / "features" / "protein_features.tsv.gz"
        entry: dict[str, Any] = {"case_code": code, "path": str(path), "rows": 0, "status": "blocked"}
        if not path.exists():
            entry["errors"] = ["missing protein feature file"]
            files.append(entry)
            continue
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            header = set(reader.fieldnames or [])
            header_errors = []
            missing = sorted(required - header)
            legacy = sorted(LEGACY_AMBIGUOUS_FIELDS & header)
            if missing:
                header_errors.append(f"missing fields: {','.join(missing)}")
            if legacy:
                header_errors.append(f"legacy ambiguous fields present: {','.join(legacy)}")
            for row_number, row in enumerate(reader, start=2):
                entry["rows"] += 1
                row_errors = validate_elemental_row(row)
                if row_errors and len(error_examples) < 25:
                    error_examples.append({
                        "case_code": code,
                        "row_number": row_number,
                        "entity_id": row.get("entity_id", ""),
                        "errors": row_errors,
                    })
        total_rows += entry["rows"]
        entry["errors"] = header_errors
        entry["status"] = "passed" if not header_errors else "blocked"
        files.append(entry)
    passed = all(item["status"] == "passed" for item in files) and not error_examples and total_rows > 0
    return {
        "contract_id": ELEMENTAL_CONTRACT_ID,
        "status": "passed" if passed else "blocked",
        "protein_rows_validated": total_rows,
        "files": files,
        "row_error_examples": error_examples,
    }
