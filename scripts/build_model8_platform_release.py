from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.model8_elemental_contract import ELEMENTAL_CONTRACT_ID
    from scripts.validate_model8_elemental_semantics import audit as validate_elemental_semantics
except ModuleNotFoundError:  # Direct execution from scripts/.
    from model8_elemental_contract import ELEMENTAL_CONTRACT_ID
    from validate_model8_elemental_semantics import audit as validate_elemental_semantics


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL8_DIR = PROJECT_ROOT / "data" / "case_studies" / "model8"
OUTPUT_DIR = MODEL8_DIR / "platform_release"
CASE_DIRS = {
    "case1": MODEL8_DIR / "case1_atlas",
    "case2": MODEL8_DIR / "case2_coupling",
    "case3": MODEL8_DIR / "case3_evidence",
    "case4": MODEL8_DIR / "case4_upload_gold",
    "case5": MODEL8_DIR / "case5_hvg_stoich",
}
CASE_TITLES = {
    "case1": "Eight-model-organism cross-domain stoichiometric fingerprint atlas",
    "case2": "DNA/CDS-RNA-Protein cross-omics coupling",
    "case3": "Extreme candidate entity evidence chain",
    "case4": "Sequence upload gold standard and user workflow",
    "case5": "HVG-Stoich flagship system",
}
STATUS_VALUES = {"generated", "skipped", "blocked", "unavailable"}
MODEL8_SPECIES_ORDER = ["ECOLI", "BSUB", "ORYSA", "DROME", "YEAST", "ARATH", "DANRE", "MOUSE"]
MODEL8_SPECIES_ICONS = {
    "ECOLI": "bacteria",
    "BSUB": "bacteria",
    "ORYSA": "rice",
    "DROME": "fly",
    "YEAST": "yeast",
    "ARATH": "plant",
    "DANRE": "fish",
    "MOUSE": "mouse",
}


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def detect_kind(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".json"):
        return "payload"
    if name.endswith(".csv") or name.endswith(".tsv") or name.endswith(".csv.gz"):
        return "table"
    if name.endswith(".zip"):
        return "bundle"
    return "artifact"


def format_for_path(path: Path) -> str:
    if path.name.endswith(".csv.gz"):
        return "csv.gz"
    if path.suffix:
        return path.suffix.lstrip(".").lower()
    return mimetypes.guess_type(path.name)[0] or "file"


def case_version(summary: dict[str, Any], case_id: str) -> str:
    return str(summary.get("case_version") or summary.get("version") or f"model8_{case_id}_release")


def generated_at(summary: dict[str, Any]) -> str:
    return str(summary.get("generated_at_utc") or summary.get("generated_at") or "")


def normalized_status(status: Any) -> str:
    value = str(status or "generated").lower()
    if value in STATUS_VALUES:
        return value
    if "blocked" in value:
        return "blocked"
    if "skip" in value:
        return "skipped"
    if "missing" in value or "unavailable" in value:
        return "unavailable"
    return "generated"


def artifact_rows_for_case(case_id: str, release_id: str) -> list[dict[str, Any]]:
    case_dir = CASE_DIRS[case_id]
    summary = read_json(case_dir / "summary.json", {})
    rows: list[dict[str, Any]] = []
    if not case_dir.exists():
        return [{
            "artifact_id": f"model8:{case_id}:unavailable",
            "model8": True,
            "case_id": case_id,
            "case_version": f"model8_{case_id}_release",
            "species_id": "",
            "expression_accession": "",
            "artifact_kind": "missing_case_directory",
            "path": str(case_dir.relative_to(PROJECT_ROOT)),
            "format": "directory",
            "sha256": "",
            "bytes": 0,
            "method_version": "",
            "status": "unavailable",
            "generated_at": "",
            "release_id": release_id,
            "download_url": "",
        }]
    for path in sorted(case_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        artifact_kind = detect_kind(path)
        rows.append({
            "artifact_id": f"model8:{case_id}:{path.relative_to(case_dir).as_posix()}",
            "model8": True,
            "case_id": case_id,
            "case_version": case_version(summary, case_id),
            "species_id": "",
            "expression_accession": "",
            "artifact_kind": artifact_kind,
            "path": rel,
            "format": format_for_path(path),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "method_version": str(summary.get("method_version") or summary.get("case_version") or ""),
            "status": normalized_status(summary.get("status")),
            "generated_at": generated_at(summary),
            "release_id": release_id,
            "download_url": f"/api/stoichdb/case-studies/model8/download/{case_id}/{path.relative_to(case_dir).as_posix()}",
        })
    return rows


def read_figure_mapping(case_id: str, release_id: str, artifact_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    case_dir = CASE_DIRS[case_id]
    mapping_files = sorted(case_dir.glob("*figure_mapping*.csv"))
    rows: list[dict[str, Any]] = []
    for mapping_file in mapping_files:
        with mapping_file.open("r", encoding="utf-8-sig", newline="") as handle:
            for raw in csv.DictReader(handle):
                source_name = raw.get("source_file") or raw.get("source") or ""
                checksum = raw.get("checksum") or raw.get("sha256") or ""
                if source_name and not checksum:
                    candidates = [row for row in artifact_rows if row["case_id"] == case_id and row["path"].endswith(source_name)]
                    if candidates:
                        checksum = candidates[0]["sha256"]
                rows.append({
                    "figure_id": raw.get("figure_id") or raw.get("figure") or f"{case_id}_figure",
                    "panel": raw.get("panel") or "",
                    "case_id": raw.get("case_id") or case_id,
                    "species_or_dataset": raw.get("species/dataset") or raw.get("species_or_dataset") or raw.get("dataset") or "",
                    "source_file": source_name or mapping_file.name,
                    "filter_or_query": raw.get("filter/query") or raw.get("filter_or_query") or raw.get("query") or "",
                    "script": raw.get("script") or f"scripts/build_model8_{case_id}.py",
                    "checksum": checksum or sha256_file(mapping_file),
                    "release_id": raw.get("release_id") or release_id,
                })
    if rows:
        return rows

    fallback_sources = {
        "case4": [
            ("FigUploadGold", "A", "case4", "gold_standard.json", "all gold records", "scripts/build_model8_case4_upload_gold.py"),
            ("FigUploadGold", "B", "case4", "validation.json", "tolerance report and workflow validation", "scripts/build_model8_case4_upload_gold.py"),
            ("FigUploadWorkflow", "A", "case4", "workflows.json", "workflow examples and privacy checks", "scripts/build_model8_case4_upload_gold.py"),
        ],
        "case5": [
            ("FigHVG", "A", "case5", "ingest_status.csv", "all species status", "scripts/build_model8_case5_hvg_stoich.py"),
            ("FigHVG", "B", "case5", "hvg_consensus.csv", "top HVG consensus records", "scripts/build_model8_case5_hvg_stoich.py"),
            ("FigHVG", "C", "case5", "model_comparison.csv", "B0-B3 completed/blocked block models", "scripts/build_model8_case5_hvg_stoich.py"),
            ("FigHVG", "D", "case5", "candidate_genes.csv", "candidate genes after strict/enhanced Phase 2", "scripts/build_model8_case5_hvg_stoich.py"),
        ],
    }
    for figure_id, panel, dataset, source_file, filter_query, script in fallback_sources.get(case_id, []):
        candidates = [row for row in artifact_rows if row["case_id"] == case_id and row["path"].endswith(source_file)]
        checksum = candidates[0]["sha256"] if candidates else ""
        rows.append({
            "figure_id": figure_id,
            "panel": panel,
            "case_id": case_id,
            "species_or_dataset": dataset,
            "source_file": source_file,
            "filter_or_query": filter_query,
            "script": script,
            "checksum": checksum,
            "release_id": release_id,
        })
    return rows


def claims_for_case(case_id: str, release_id: str) -> list[dict[str, Any]]:
    summary = read_json(CASE_DIRS[case_id] / "summary.json", {})
    acceptance = summary.get("acceptance") if isinstance(summary.get("acceptance"), dict) else {}
    limitations = summary.get("limitations") if isinstance(summary.get("limitations"), list) else []
    allowed = [
        summary.get("finding") or "",
        f"{CASE_TITLES[case_id]} is traceable to frozen Model-8 artifacts under release {release_id}.",
    ]
    forbidden = [
        "Do not generalize the fixed eight-model-organism results to all platform species or all clades.",
        "Do not describe candidates as causal drivers/regulators; use stoich_associated, stoich_predictive_feature, or candidate_priority.",
        "Do not replace blocked/unavailable datasets with zero-valued plots.",
    ]
    if case_id == "case5":
        allowed.append(
            f"HVG Phase 1 complete count={acceptance.get('phase1_complete_count')}; Phase 2 complete count={acceptance.get('phase2_complete_count')}; strict mapping threshold={acceptance.get('mapping_threshold_phase2')}."
        )
        forbidden.append("Functional terms are context only and cannot prove that sequence features caused expression variability.")
    return [{
        "case_id": case_id,
        "release_id": release_id,
        "result_status": normalized_status(summary.get("status")),
        "research_question": summary.get("research_question") or "",
        "data_scope": "fixed eight-model-organism artifacts plus full database coverage context",
        "allowed_claims": [item for item in allowed if item],
        "forbidden_claims": forbidden,
        "limitations": limitations,
    }]


def make_zip(bundle_path: Path, artifact_rows: list[dict[str, Any]]) -> dict[str, Any]:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in artifact_rows:
            source = PROJECT_ROOT / row["path"]
            if source.exists() and source.is_file():
                zf.write(source, arcname=row["path"])
        for extra in [
            OUTPUT_DIR / "case_artifact_registry.csv",
            OUTPUT_DIR / "figure_mapping.csv",
            OUTPUT_DIR / "claims.json",
            OUTPUT_DIR / "elemental_semantics_validation.json",
            OUTPUT_DIR / "model8_platform_release_manifest.json",
        ]:
            if extra.exists():
                zf.write(extra, arcname=extra.relative_to(PROJECT_ROOT).as_posix())
    return {
        "name": bundle_path.name,
        "path": bundle_path.relative_to(PROJECT_ROOT).as_posix(),
        "bytes": bundle_path.stat().st_size,
        "sha256": sha256_file(bundle_path),
        "download_url": "/api/stoichdb/case-studies/model8/download-bundle/",
    }


def build_platform_release() -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    elemental_validation = validate_elemental_semantics(MODEL8_DIR)
    write_json(OUTPUT_DIR / "elemental_semantics_validation.json", elemental_validation)
    if elemental_validation["status"] != "passed":
        raise RuntimeError("Model-8 platform release blocked by elemental semantics validation")
    release_manifest = read_json(MODEL8_DIR / "model8_release_manifest.json", {})
    base_release_id = str(release_manifest.get("release_id") or "model8_release")
    release_id = f"{base_release_id}_case1_5_platform"
    generated = datetime.now(timezone.utc).isoformat()

    artifact_rows: list[dict[str, Any]] = []
    for case_id in CASE_DIRS:
        artifact_rows.extend(artifact_rows_for_case(case_id, release_id))

    figure_rows: list[dict[str, Any]] = []
    for case_id in CASE_DIRS:
        figure_rows.extend(read_figure_mapping(case_id, release_id, artifact_rows))

    claims = []
    for case_id in CASE_DIRS:
        claims.extend(claims_for_case(case_id, release_id))

    artifact_fields = [
        "artifact_id",
        "model8",
        "case_id",
        "case_version",
        "species_id",
        "expression_accession",
        "artifact_kind",
        "path",
        "format",
        "sha256",
        "bytes",
        "method_version",
        "status",
        "generated_at",
        "release_id",
        "download_url",
    ]
    figure_fields = [
        "figure_id",
        "panel",
        "case_id",
        "species_or_dataset",
        "source_file",
        "filter_or_query",
        "script",
        "checksum",
        "release_id",
    ]
    write_csv(OUTPUT_DIR / "case_artifact_registry.csv", artifact_rows, artifact_fields)
    write_csv(OUTPUT_DIR / "figure_mapping.csv", figure_rows, figure_fields)
    write_json(OUTPUT_DIR / "claims.json", claims)

    case_status = {}
    for case_id in CASE_DIRS:
        summary = read_json(CASE_DIRS[case_id] / "summary.json", {})
        case_status[case_id] = {
            "title": CASE_TITLES[case_id],
            "status": summary.get("status", "generated" if summary else "unavailable"),
            "case_version": case_version(summary, case_id),
            "artifact_count": sum(1 for row in artifact_rows if row["case_id"] == case_id),
            "figure_mapping_count": sum(1 for row in figure_rows if row["case_id"] == case_id),
            "download_count": len(summary.get("downloads") or []) if isinstance(summary.get("downloads"), list) else "",
        }

    extractor_contract = read_json(MODEL8_DIR / "feature_extractor_contract.json", {})
    manifest = {
        "release_id": release_id,
        "base_model8_release_id": base_release_id,
        "schema_version": "model8-platform-case-artifact-v2-elemental",
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
        "elemental_semantics_validation": elemental_validation,
        "generated_at": generated,
        "project_root": str(PROJECT_ROOT),
        "model8_dir": str(MODEL8_DIR),
        "output_dir": str(OUTPUT_DIR),
        "model8_species_order": MODEL8_SPECIES_ORDER,
        "model8_species_icons": MODEL8_SPECIES_ICONS,
        "case_status": case_status,
        "artifact_count": len(artifact_rows),
        "figure_mapping_count": len(figure_rows),
        "claim_count": len(claims),
        "status_values": sorted(STATUS_VALUES),
        "required_fields": artifact_fields,
        "figure_mapping_fields": figure_fields,
        "full_database_feature_extractor_contract": extractor_contract,
        "consistency_contract": {
            "front_end_must_use_same_release_id": True,
            "paper_numbers_must_trace_to_download_bundle": True,
            "blocked_or_unavailable_must_show_reason": True,
            "forbidden_terms": ["stoich_driver", "causal driver", "regulator"],
            "allowed_terms": ["stoich_associated", "stoich_predictive_feature", "candidate_priority"],
        },
    }
    write_json(OUTPUT_DIR / "model8_platform_release_manifest.json", manifest)
    bundle = make_zip(OUTPUT_DIR / "model8_case1_5_platform_bundle.zip", artifact_rows)
    manifest["bundle"] = bundle
    write_json(OUTPUT_DIR / "model8_platform_release_manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    payload = build_platform_release()
    print(json.dumps({
        "release_id": payload["release_id"],
        "artifact_count": payload["artifact_count"],
        "figure_mapping_count": payload["figure_mapping_count"],
        "bundle": payload["bundle"],
    }, ensure_ascii=False, indent=2))
