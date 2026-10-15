from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts.model8_elemental_contract import (
        ELEMENTAL_CONTRACT_ID,
        validate_model8_protein_feature_files,
    )
except ModuleNotFoundError:  # Direct execution from scripts/.
    from model8_elemental_contract import (
        ELEMENTAL_CONTRACT_ID,
        validate_model8_protein_feature_files,
    )


CASE_DIRS = {
    "case1": "case1_atlas",
    "case2": "case2_coupling",
    "case3": "case3_evidence",
    "case4": "case4_upload_gold",
    "case5": "case5_hvg_stoich",
}
FORBIDDEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:c_per_aa|s_per_aa|n_per_aa|"
    r"protein_c_per_aa|protein_s_per_aa|protein_n_per_aa)(?![A-Za-z0-9_])"
)
TEXT_SUFFIXES = {".csv", ".tsv", ".json", ".md", ".txt"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def header(path: Path, delimiter: str = ",") -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle, delimiter=delimiter), [])


def audit(model8_dir: Path) -> dict[str, Any]:
    raw = validate_model8_protein_feature_files(model8_dir)
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    if raw["status"] != "passed":
        errors.append("raw protein feature files do not satisfy the elemental contract")

    for case_id, dirname in CASE_DIRS.items():
        summary_path = model8_dir / dirname / "summary.json"
        contract = read_json(summary_path).get("elemental_contract_id") if summary_path.exists() else None
        passed = contract == ELEMENTAL_CONTRACT_ID
        checks.append({"check": f"{case_id}_contract", "status": "passed" if passed else "blocked", "observed": contract})
        if not passed:
            errors.append(f"{case_id} summary does not declare {ELEMENTAL_CONTRACT_ID}")

    expected_headers = {
        model8_dir / "case2_coupling" / "case2_coupled_entities.csv.gz": {
            "protein_c_atoms_per_aa", "protein_n_atoms_per_aa", "protein_s_atoms_per_aa"
        },
        model8_dir / "case4_upload_gold" / "expected_protein_features.csv": {
            "c_atoms", "n_atoms", "s_atoms", "c_atoms_per_aa", "n_atoms_per_aa", "s_atoms_per_aa",
            "cys_count", "ser_count", "asn_count", "met_count", "elemental_contract_id",
        },
        model8_dir / "case5_hvg_stoich" / "candidate_genes.csv": {
            "protein_n_atoms_per_aa", "protein_s_atoms_per_aa"
        },
    }
    for joined_path in (model8_dir / "case5_hvg_stoich").glob("*_joined_hvg_stoich.csv.gz"):
        expected_headers[joined_path] = {"c_atoms_per_aa", "n_atoms_per_aa", "s_atoms_per_aa"}
    for path, required in expected_headers.items():
        observed = set(header(path, "\t" if path.name.endswith(".tsv.gz") else ",")) if path.exists() else set()
        missing = sorted(required - observed)
        legacy = sorted(field for field in observed if FORBIDDEN_PATTERN.fullmatch(field))
        passed = bool(observed) and not missing and not legacy
        checks.append({
            "check": f"header:{path.name}",
            "status": "passed" if passed else "blocked",
            "missing": missing,
            "legacy": legacy,
        })
        if not passed:
            errors.append(f"invalid elemental header in {path}: missing={missing}, legacy={legacy}")

    stale_examples: list[dict[str, Any]] = []
    for dirname in CASE_DIRS.values():
        root = model8_dir / dirname
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                content = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                continue
            match = FORBIDDEN_PATTERN.search(content)
            if match:
                stale_examples.append({"path": str(path), "token": match.group(0)})
                if len(stale_examples) >= 25:
                    break
        if len(stale_examples) >= 25:
            break
    if stale_examples:
        errors.append("legacy ambiguous elemental field names remain in Case 1-5 text artifacts")

    return {
        "contract_id": ELEMENTAL_CONTRACT_ID,
        "status": "passed" if not errors else "blocked",
        "protein_rows_validated": raw.get("protein_rows_validated", 0),
        "raw_feature_validation": raw,
        "checks": checks,
        "stale_field_examples": stale_examples,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Model-8 elemental semantics across raw and Case 1-5 artifacts.")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    model8_dir = Path(args.project_root).resolve() / "data" / "case_studies" / "model8"
    result = audit(model8_dir)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "contract_id": result["contract_id"],
        "protein_rows_validated": result["protein_rows_validated"],
        "errors": result["errors"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
