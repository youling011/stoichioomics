from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from backend.analysis_engine.phase2.comparison_schema import COMPARISON_SCHEMA_VERSION
from backend.analysis_engine.phase2.group_comparison import (
    ARTIFACTS,
    CONTEXT_ARTIFACTS,
    run_hvg_nonhvg_comparison,
    write_unavailable_comparison,
)
from backend.apps.hvg.feature_context import build_hvg_multiomics_feature_context


CASE_CODES = ("ECOLI", "BSUB", "ORYSA", "DROME", "YEAST", "ARATH", "DANRE", "MOUSE")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean(value) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _mapping_validation(status_row: dict) -> tuple[str, list[str]]:
    species_id = _clean(status_row.get("platform_species_id") or status_row.get("species_id"))
    required = {
        "platform_species_id": species_id,
        "scientific_name": _clean(status_row.get("scientific_name")),
        "mapping_evidence": status_row.get("mapping_evidence") or status_row.get("species_mapping_evidence"),
        "validated_by": _clean(status_row.get("validated_by")),
        "validated_at": _clean(status_row.get("validated_at")),
    }
    missing = [key for key, value in required.items() if not value]
    return species_id, missing


def _base_config(code: str, summary: dict, input_path: Path) -> dict:
    return {
        "case_id": f"model8_case5:{code}",
        "case_input_path": input_path.name,
        "case_input_sha256": _sha256(input_path),
        "release_version": summary.get("case_version"),
        "comparison_schema_version": COMPARISON_SCHEMA_VERSION,
        "comparison_omics": ["genome", "transcriptome", "proteome"],
        "comparison_context_enabled": True,
        "comparison_auto_detect_blocks": True,
        "comparison_include_conditional": False,
        "comparison_min_block_match_rate": 0.70,
        "comparison_min_block_mapped_genes": 40,
        "comparison_allow_alias_mapping": True,
        "comparison_require_unique_mapping": True,
        "comparison_allow_version_stripped_unique": True,
        "comparison_source_chunk_size": 50000,
        "comparison_min_group_n": 20,
        "comparison_max_missing_rate": 0.50,
        "comparison_bootstrap_ci_repeats": 500,
        "comparison_bootstrap_max_group_n": 1000,
        "comparison_worker_count": 1,
        "comparison_api_page_size_max": 200,
        "comparison_display_point_cap": 240,
        "comparison_categorical_min_cell_count": 5,
        "comparison_near_constant_tolerance": 1e-12,
        "comparison_high_correlation_threshold": 0.995,
        "comparison_applicability_policy": "v2",
        "comparison_applicable_values": ["all", "coding_only", "protein_proxy_only"],
        "comparison_adjustment_enabled": True,
        "comparison_adjustment_policy": "v2",
        "comparison_composition_adjustment": "clr_v1",
        "comparison_composition_pseudocount_fraction": 1e-6,
        "random_state": 42,
        "hvg_flag_col": "is_hvg",
        "input_baseline_csv": str(input_path),
    }


class Command(BaseCommand):
    help = "Backfill comparison-v2 context and hvg_nonhvg artifacts for frozen Model-8 Case 5 files."

    def add_arguments(self, parser):
        parser.add_argument("--case", default="model8_case5", choices=["model8_case5"])
        parser.add_argument("--species", choices=CASE_CODES)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--write", action="store_true")
        parser.add_argument("--schema-version", default=COMPARISON_SCHEMA_VERSION, choices=[COMPARISON_SCHEMA_VERSION])

    def handle(self, *args, **options):
        if options["dry_run"] and options["write"]:
            raise CommandError("Choose either --dry-run or --write.")
        if options["schema_version"] != COMPARISON_SCHEMA_VERSION:
            raise CommandError(f"Supported schema version is {COMPARISON_SCHEMA_VERSION}.")
        write = bool(options["write"])
        case_root = Path(settings.BASE_DIR) / "data" / "case_studies" / "model8" / "case5_hvg_stoich"
        summary = json.loads((case_root / "summary.json").read_text(encoding="utf-8"))
        statuses = {str(row.get("case_code")): row for row in summary.get("species_status", [])}
        codes = [options["species"]] if options.get("species") else list(CASE_CODES)
        history_rows = []
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        for code in codes:
            input_path = case_root / f"{code}_joined_hvg_stoich.csv.gz"
            if not input_path.exists():
                raise CommandError(f"Missing Case 5 input: {input_path}")
            status_row = statuses.get(code, {})
            output_dir = case_root / "hvg_nonhvg" / code
            previous = {
                path.name: _sha256(path)
                for path in output_dir.glob("hvg_nonhvg_*") if path.is_file()
            } if output_dir.exists() else {}
            backup_dir = None
            if write and previous:
                backup_dir = case_root / "hvg_nonhvg_backups" / timestamp / code
                backup_dir.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(output_dir, backup_dir)

            species_id, missing_mapping = _mapping_validation(status_row)
            work_dir = Path(output_dir) if write else Path(tempfile.mkdtemp(prefix=f"hvg_case5_{code}_"))
            try:
                config = _base_config(code, summary, input_path)
                if missing_mapping:
                    reason = "case5_species_mapping_unvalidated:" + ",".join(missing_mapping)
                    # Emit the v2 failure bundle so an unvalidated case is
                    # explicit and still has the six-file artifact contract.
                    context = build_hvg_multiomics_feature_context(
                        baseline_csv=input_path,
                        output_dir=work_dir,
                        species_id="",
                        requested_omics=config["comparison_omics"],
                        config=config,
                    )
                    result = write_unavailable_comparison(
                        work_dir,
                        reason=reason,
                        config=config,
                        mapping_context=status_row,
                        phase1_metadata={"hvg_label_source": "is_hvg", "case_version": summary.get("case_version")},
                    )
                else:
                    frame = pd.read_csv(input_path)
                    expression_id_col = "expression_gene_id" if "expression_gene_id" in frame.columns else "gene_id"
                    if expression_id_col not in frame.columns or "is_hvg" not in frame.columns:
                        raise ValueError("case5_baseline_missing_expression_gene_id_or_is_hvg")
                    frame = frame.copy()
                    frame["gene_id"] = frame[expression_id_col].map(_clean)
                    if frame["gene_id"].eq("").any() or frame["gene_id"].duplicated().any():
                        raise ValueError("case5_baseline_invalid_gene_id_universe")
                    baseline_path = work_dir / "case5_phase1_hvg_baseline.csv"
                    baseline_path.parent.mkdir(parents=True, exist_ok=True)
                    frame.to_csv(baseline_path, index=False)
                    config["input_baseline_csv"] = str(baseline_path)
                    context = build_hvg_multiomics_feature_context(
                        baseline_csv=baseline_path,
                        output_dir=work_dir,
                        species_id=species_id,
                        requested_omics=config["comparison_omics"],
                        config=config,
                    )
                    config.update({
                        "comparison_input_csv": context.get("comparison_input_csv"),
                        "comparison_feature_provenance_path": context.get("feature_provenance_csv"),
                        "comparison_mapping_summary_path": context.get("mapping_summary_json"),
                        "comparison_context_manifest_path": context.get("assembly_manifest_json"),
                        "comparison_block_coverage_path": context.get("block_coverage_csv"),
                        "comparison_block_status": context.get("block_status") or {},
                        "comparison_context_status": context.get("status"),
                    })
                    if context.get("status") in {"ready", "partial"} and Path(str(context.get("comparison_input_csv"))).exists():
                        context_frame = pd.read_csv(context["comparison_input_csv"])
                        result = run_hvg_nonhvg_comparison(
                            context_frame,
                            config,
                            output_dir=work_dir,
                            phase1_metadata={
                                "hvg_method": frame["hvg_method"].dropna().astype(str).iloc[0] if "hvg_method" in frame and frame["hvg_method"].notna().any() else None,
                                "hvg_label_source": "is_hvg",
                                "case_version": summary.get("case_version"),
                            },
                            mapping_context=status_row,
                        )
                    else:
                        result = write_unavailable_comparison(
                            work_dir,
                            reason=f"validated species source context is {context.get('status')}: {context.get('reason', 'no block passed the v2 gate')}",
                            config=config,
                            mapping_context=status_row,
                            phase1_metadata={"hvg_label_source": "is_hvg", "case_version": summary.get("case_version")},
                        )

                if write and not missing_mapping and work_dir != output_dir:
                    raise RuntimeError("internal_case5_output_path_error")
                generated = {
                    filename: _sha256(work_dir / filename)
                    for filename in [*ARTIFACTS.values(), *CONTEXT_ARTIFACTS.values()]
                    if (work_dir / filename).exists()
                }
                row = {
                    "case_code": code,
                    "mode": "write" if write else "dry_run",
                    "input": input_path.name,
                    "input_sha256": _sha256(input_path),
                    "species_mapping_status": "validated" if not missing_mapping else "unvalidated",
                    "species_id": species_id,
                    "status": result["summary"].get("comparison_status") or result["summary"].get("status"),
                    "counts": result["summary"].get("counts") or {},
                    "previous_artifacts": previous,
                    "backup_dir": str(backup_dir.relative_to(case_root)) if backup_dir else "",
                    "generated_artifacts": generated,
                }
                history_rows.append(row)
                self.stdout.write(json.dumps(row, ensure_ascii=False))
            except Exception as exc:
                if write:
                    build_hvg_multiomics_feature_context(
                        baseline_csv=input_path,
                        output_dir=work_dir,
                        species_id="",
                        requested_omics=["genome", "transcriptome", "proteome"],
                        config=_base_config(code, summary, input_path),
                    )
                    result = write_unavailable_comparison(
                        work_dir,
                        status="failed",
                        reason=f"case5 backfill failed: {type(exc).__name__}: {exc}",
                        config=_base_config(code, summary, input_path),
                        mapping_context=status_row,
                        phase1_metadata={"hvg_label_source": "is_hvg", "case_version": summary.get("case_version")},
                    )
                    row = {
                        "case_code": code, "mode": "write", "input": input_path.name,
                        "input_sha256": _sha256(input_path), "species_mapping_status": "error",
                        "status": "failed", "reason": str(exc), "counts": result["summary"].get("counts") or {},
                        "previous_artifacts": previous, "backup_dir": str(backup_dir.relative_to(case_root)) if backup_dir else "",
                        "generated_artifacts": {filename: _sha256(work_dir / filename) for filename in ARTIFACTS.values() if (work_dir / filename).exists()},
                    }
                    history_rows.append(row)
                    self.stdout.write(json.dumps(row, ensure_ascii=False))
                else:
                    raise
            finally:
                if not write and work_dir.exists():
                    shutil.rmtree(work_dir)

        if write:
            history_path = case_root / "hvg_nonhvg" / "backfill_history.json"
            history_path.parent.mkdir(parents=True, exist_ok=True)
            history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
            history.append({
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "schema_version": COMPARISON_SCHEMA_VERSION,
                "rows": history_rows,
            })
            history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
