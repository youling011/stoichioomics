from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timezone, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.config.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from backend.apps.common.reproducibility import sha256_file, utc_now_iso, write_reproducibility_manifest  # noqa: E402
from backend.apps.sequence_analysis.real_engine import feature_extractor_contract, run_sequence_analysis  # noqa: E402
from backend.apps.sequence_analysis.services import OUTPUT_FILES  # noqa: E402


CASE_ROOT = PROJECT_ROOT / "data" / "case_studies" / "model8" / "case4_upload_gold"
WORKFLOW_INPUT_ROOT = CASE_ROOT / "inputs" / "workflow_examples"
GOLD_PROTEIN_ROOT = CASE_ROOT / "inputs" / "gold" / "protein"
EXAMPLE_ROOT = PROJECT_ROOT / "data" / "examples" / "sequence_analysis_results"

REAL_JOB_IDS = {
    "ECOLI": "seq_model8_case4_ECOLI_proteome_multi_sample",
    "YEAST": "seq_model8_case4_YEAST_proteome_multi_sample",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_log(job_root: Path, event: str, payload: dict[str, Any]) -> None:
    log_path = job_root / "logs" / "job_events.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = {"ts": utc_now_iso(), "event": event, "payload": payload}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def _parse_fasta(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    header = ""
    chunks: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header:
                records.append((header, "".join(chunks)))
            header = line[1:].strip()
            chunks = []
        else:
            chunks.append(line)
    if header:
        records.append((header, "".join(chunks)))
    return records


def _write_fasta(path: Path, records: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for header, sequence in records:
            handle.write(f">{header}\n")
            for idx in range(0, len(sequence), 80):
                handle.write(sequence[idx : idx + 80] + "\n")


def _write_sample_sheet(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["file_name", "sample_id", "condition", "species_id"]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(",".join(columns) + "\n")
        for row in rows:
            handle.write(",".join(row[col] for col in columns) + "\n")


def _ensure_yeast_inputs() -> tuple[list[Path], Path, dict[str, Any]]:
    source = GOLD_PROTEIN_ROOT / "YEAST_protein_gold_1000.faa"
    records = _parse_fasta(source)
    if len(records) < 100:
        raise RuntimeError(f"YEAST source FASTA has too few records: {source}")

    ordered = sorted(records, key=lambda item: len(item[1]))
    midpoint = len(ordered) // 2
    control_records = ordered[:midpoint]
    case_records = ordered[midpoint:]

    control = WORKFLOW_INPUT_ROOT / "multi_sample_YEAST_control.faa"
    case = WORKFLOW_INPUT_ROOT / "multi_sample_YEAST_case.faa"
    sheet = WORKFLOW_INPUT_ROOT / "sample_sheet_multi_sample_YEAST.csv"
    _write_fasta(control, control_records)
    _write_fasta(case, case_records)
    _write_sample_sheet(
        sheet,
        [
            {
                "file_name": control.name,
                "sample_id": "yeast_control_low_length",
                "condition": "control",
                "species_id": "YEAST",
            },
            {
                "file_name": case.name,
                "sample_id": "yeast_case_high_length",
                "condition": "case",
                "species_id": "YEAST",
            },
        ],
    )
    note = {
        "source_fasta": str(source.relative_to(PROJECT_ROOT)),
        "derivation": "real YEAST protein gold FASTA split into low-length and high-length uploaded samples",
        "control_records": len(control_records),
        "case_records": len(case_records),
        "control_length_range": [min(len(seq) for _, seq in control_records), max(len(seq) for _, seq in control_records)],
        "case_length_range": [min(len(seq) for _, seq in case_records), max(len(seq) for _, seq in case_records)],
    }
    return [control, case], sheet, note


def _ecoli_inputs() -> tuple[list[Path], Path, dict[str, Any]]:
    files = [
        WORKFLOW_INPUT_ROOT / "multi_sample_ECOLI_control.faa",
        WORKFLOW_INPUT_ROOT / "multi_sample_ECOLI_case.faa",
    ]
    sheet = WORKFLOW_INPUT_ROOT / "sample_sheet_multi_sample_ECOLI.csv"
    missing = [path for path in [*files, sheet] if not path.exists()]
    if missing:
        raise FileNotFoundError(", ".join(str(path) for path in missing))
    note = {
        "source_fasta": "data/case_studies/model8/case4_upload_gold/inputs/workflow_examples/multi_sample_ECOLI_*.faa",
        "derivation": "real ECOLI Case 4 workflow FASTA files with independent control and case uploaded samples",
    }
    return files, sheet, note


def _input_manifest(files: list[Path], sample_sheet: Path) -> list[dict[str, Any]]:
    manifest = []
    for path in [*files, sample_sheet]:
        manifest.append(
            {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return manifest


def _write_job(species_code: str, files: list[Path], sample_sheet: Path, summary: dict[str, Any], curation_note: dict[str, Any]) -> None:
    job_id = REAL_JOB_IDS[species_code]
    job_root = EXAMPLE_ROOT / job_id
    created_at = summary.get("created_at") or datetime.now(timezone.utc).isoformat()
    job = {
        "job_id": job_id,
        "name": f"Model-8 {species_code} proteome upload multi-sample",
        "status": "SUCCEEDED",
        "analysis_type": "multi_sample",
        "omics_type": "proteome",
        "group_field": "condition",
        "reference_group": "control",
        "feature_set": "core",
        "genetic_code": 1,
        "created_at": created_at,
        "updated_at": utc_now_iso(),
        "expires_at": None,
        "source": "persistent_model8_sequence_upload_example",
        "is_example": True,
        "case_family": "model8_case4_upload_gold",
        "species_case_code": species_code,
        "standard_sequence_upload_case": True,
        "summary": summary,
        "outputs": OUTPUT_FILES,
        "inputs": {
            "files": [path.name for path in files],
            "annotation_files": [],
            "sample_sheet": sample_sheet.name,
            "manifest": {
                "files": _input_manifest(files, sample_sheet),
                "annotation_files": [],
                "sample_sheet": {
                    "path": str(sample_sheet.relative_to(PROJECT_ROOT)),
                    "name": sample_sheet.name,
                    "size_bytes": sample_sheet.stat().st_size,
                    "sha256": sha256_file(sample_sheet),
                },
            },
        },
        "privacy": {
            "raw_uploads_persisted": False,
            "derived_results_persisted_until": "public example release",
            "cleanup_policy": "persistent_curated_example",
            "workspace_isolation": "per-sequence-job example directory",
        },
        "reproducibility": {
            "manifest_path": str(job_root / "logs" / "reproducibility_manifest.json"),
            "run_log_path": str(job_root / "logs" / "job_events.log"),
        },
        "curation_note": curation_note,
    }
    _write_json(job_root / "job.json", job)


def build_species(species_code: str) -> dict[str, Any]:
    code = species_code.upper()
    if code == "ECOLI":
        files, sample_sheet, note = _ecoli_inputs()
    elif code == "YEAST":
        files, sample_sheet, note = _ensure_yeast_inputs()
    else:
        raise ValueError(f"Unsupported species for this build step: {species_code}")

    job_id = REAL_JOB_IDS[code]
    job_root = EXAMPLE_ROOT / job_id
    output_dir = job_root / "outputs"
    job_root.mkdir(parents=True, exist_ok=True)
    if (job_root / "logs" / "job_events.log").exists():
        (job_root / "logs" / "job_events.log").unlink()

    params = {
        "analysis_type": "multi_sample",
        "omics_type": "proteome",
        "group_field": "condition",
        "reference_group": "control",
        "feature_set": "core",
        "genetic_code": 1,
        "species_case_code": code,
    }
    _append_log(job_root, "job_created", {"parameters": params, "curation_note": note})
    summary = run_sequence_analysis(
        input_files=files,
        annotation_files=[],
        sample_sheet_path=sample_sheet,
        output_dir=output_dir,
        analysis_type="multi_sample",
        omics_type="proteome",
        group_field="condition",
        reference_group="control",
        feature_set="core",
        genetic_code=1,
    )
    _append_log(job_root, "feature_extraction_completed", {"summary": summary})
    _append_log(job_root, "job_succeeded", {"outputs": OUTPUT_FILES})
    _write_job(code, files, sample_sheet, summary, note)
    write_reproducibility_manifest(
        job_root / "logs" / "reproducibility_manifest.json",
        job_id=job_id,
        pipeline_type="sequence_analysis",
        parameters=params,
        inputs=_input_manifest(files, sample_sheet),
        base_dir=settings.BASE_DIR,
        extra={
            "stage": "succeeded",
            "case_family": "model8_case4_upload_gold",
            "species_case_code": code,
            "standard_sequence_upload_case": True,
            "curation_note": note,
            "outputs": OUTPUT_FILES,
            "feature_extractor_contract": feature_extractor_contract(),
        },
    )
    return {"job_id": job_id, "record_count": summary.get("record_count"), "feature_count": summary.get("feature_count")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build real Model-8 sequence upload workflow example jobs.")
    parser.add_argument("--species", nargs="+", default=["ECOLI", "YEAST"], choices=sorted(REAL_JOB_IDS))
    args = parser.parse_args()
    built = [build_species(code) for code in args.species]
    print(json.dumps({"built": built}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
