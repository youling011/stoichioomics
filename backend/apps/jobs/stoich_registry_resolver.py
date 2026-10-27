from __future__ import annotations

import json
import re
from backend.apps.common.host_paths import Path
from typing import Any, Dict, Iterable

import pandas as pd
from django.db.models import Q

from backend.apps.jobs.models import AnalysisJob, JobFile
from backend.apps.stoichdb.feature_hub.sources import DatasetSourceResolver
from backend.apps.stoichdb.models import Species
from backend.validation.stoich_readiness import inspect_stoich_readiness


ID_CANDIDATES = [
    "gene_id",
    "gene",
    "geneid",
    "entity_id",
    "transcript_id",
    "protein_id",
    "locus_tag",
    "id",
]


def _safe_name(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return clean.strip("._") or "unknown"


def _nested_get(mapping: Dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_value(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _resolve_species_id(species_hint: str) -> str:
    if not species_hint:
        return ""
    species = Species.objects.filter(
        Q(species_id__iexact=species_hint)
        | Q(display_name__iexact=species_hint)
        | Q(short_name__iexact=species_hint)
        | Q(source_species_id__iexact=species_hint)
        | Q(taxonomy_id__iexact=species_hint)
    ).only("species_id").first()
    return species.species_id if species else species_hint


def _request_context(job: AnalysisJob, user_overrides: Dict[str, Any] | None) -> Dict[str, str]:
    metadata = job.metadata_json or {}
    overrides = user_overrides or {}
    species_hint = _first_value(
        _nested_get(overrides, ("phase2_stoich", "species_id")),
        _nested_get(overrides, ("phase1_analysis", "species_id")),
        _nested_get(overrides, ("input_adapter", "species_id")),
        _nested_get(overrides, ("stoich", "species_id")),
        metadata.get("species_id"),
        metadata.get("species"),
        metadata.get("target_species_id"),
        metadata.get("stoich_species_id"),
    )
    omics = _first_value(
        _nested_get(overrides, ("phase2_stoich", "omics")),
        _nested_get(overrides, ("phase2_stoich", "omics_type")),
        _nested_get(overrides, ("phase1_analysis", "omics")),
        _nested_get(overrides, ("input_adapter", "omics_type")),
        metadata.get("omics_type"),
        metadata.get("omics"),
        "transcriptome",
    ).lower()
    scope = _first_value(
        _nested_get(overrides, ("phase2_stoich", "feature_set")),
        _nested_get(overrides, ("stoich", "feature_set")),
        metadata.get("feature_set"),
        "core",
    ).lower()
    if omics not in {"genome", "transcriptome", "proteome"}:
        omics = "transcriptome"
    if scope not in {"core", "full"}:
        scope = "core"
    return {
        "species_hint": species_hint,
        "species_id": _resolve_species_id(species_hint),
        "omics": omics,
        "feature_set": scope,
        "sequence_feature_job_id": _first_value(
            _nested_get(overrides, ("phase2_stoich", "sequence_feature_job_id")),
            _nested_get(overrides, ("stoich", "sequence_feature_job_id")),
            metadata.get("sequence_feature_job_id"),
        ),
    }


def _gene_id_column(columns: Iterable[str]) -> str | None:
    normalized = {str(col).strip().lower().replace("-", "_"): str(col) for col in columns}
    for candidate in ID_CANDIDATES:
        if candidate in normalized:
            return normalized[candidate]
    return None


def _materialize_feature_table(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(source_path, sep="\t" if source_path.suffix.lower() in {".tsv", ".txt"} else ",")
    gene_col = _gene_id_column(df.columns)
    if gene_col is None:
        if len(df.columns) == 0:
            raise ValueError("Registered stoich feature file has no columns.")
        gene_col = str(df.columns[0])
    if gene_col != "gene_id":
        df = df.rename(columns={gene_col: "gene_id"})
    if "gene_id" not in df.columns:
        raise ValueError("Registered stoich feature file cannot be normalized to a gene_id column.")
    df["gene_id"] = df["gene_id"].astype(str)
    df.to_csv(target_path, index=False, encoding="utf-8")


def _sequence_feature_path(sequence_job_id: str) -> Path | None:
    if not sequence_job_id:
        return None
    try:
        from backend.apps.sequence_analysis.services import output_path

        return output_path(sequence_job_id, "features")
    except Exception:
        return None


def resolve_registry_stoich_for_job(
    job: AnalysisJob,
    raw_dir: str | Path,
    *,
    user_overrides: Dict[str, Any] | None = None,
    expression_gene_ids: Iterable[str] | None = None,
    existing_stoich_file: str | None = None,
) -> Dict[str, Any]:
    raw = Path(raw_dir)
    raw.mkdir(parents=True, exist_ok=True)
    context = _request_context(job, user_overrides)
    report: Dict[str, Any] = {
        "strategy": "user_upload_then_registry_then_sequence_upload",
        "status": "not_attempted",
        "phase2_ready": False,
        "source": None,
        "species_hint": context["species_hint"],
        "species_id": context["species_id"],
        "omics": context["omics"],
        "feature_set": context["feature_set"],
        "sequence_feature_job_id": context["sequence_feature_job_id"],
        "file": existing_stoich_file,
        "message": "",
    }

    if existing_stoich_file:
        report.update({
            "status": "user_uploaded_feature_table",
            "source": "user_upload",
            "phase2_ready": True,
            "message": "User-uploaded stoich feature table has priority over registry lookup.",
        })
        return report

    sequence_source = _sequence_feature_path(context["sequence_feature_job_id"])

    if not context["species_id"] and sequence_source is None:
        report.update({
            "status": "needs_species_context",
            "source": "missing_context",
            "sequence_upload_required": True,
            "sequence_upload_endpoint": "/sequence-analysis",
            "message": "No species_id was provided; registry stoich features cannot be resolved automatically.",
        })
        return report

    registry_error = None
    source = None
    if context["species_id"]:
        try:
            source = DatasetSourceResolver().resolve(context["species_id"], context["omics"], context["feature_set"])
        except Exception as exc:
            registry_error = exc

    if source is None and sequence_source is None:
        report.update({
            "status": "registry_feature_not_found",
            "source": "registry",
            "sequence_upload_required": True,
            "sequence_upload_endpoint": "/sequence-analysis",
            "message": f"No registered {context['feature_set']} stoich feature file for {context['species_id']}/{context['omics']}: {registry_error}",
        })
        return report

    if source is None and sequence_source is not None:
        target_name = f"sequence_{_safe_name(context['sequence_feature_job_id'])}_stoich_features.csv"
        target = raw / target_name
        try:
            _materialize_feature_table(sequence_source, target)
        except Exception as exc:
            report.update({
                "status": "sequence_feature_materialize_failed",
                "source": "sequence_analysis",
                "sequence_upload_required": True,
                "sequence_upload_endpoint": "/sequence-analysis",
                "sequence_source_path": str(sequence_source),
                "message": str(exc),
            })
            return report
        readiness = inspect_stoich_readiness(target, expression_gene_ids=expression_gene_ids)
        JobFile.objects.get_or_create(
            job=job,
            relative_path=str(target.relative_to(Path(job.workspace_path))),
            defaults={"file_name": target.name, "category": "raw_sequence_stoich"},
        )
        report.update({
            "status": "sequence_feature_materialized",
            "source": "sequence_analysis",
            "file": target.name,
            "relative_path": str(target.relative_to(Path(job.workspace_path))),
            "sequence_source_path": str(sequence_source),
            "phase2_ready": bool(readiness.get("phase2_ready")),
            "readiness": readiness,
            "message": "Sequence-analysis stoich feature table was copied into the job raw directory and will be used for Phase 2.",
        })
        return report

    target_name = (
        f"registry_{_safe_name(context['species_id'])}_{_safe_name(context['omics'])}_"
        f"{_safe_name(context['feature_set'])}_stoich_features.csv"
    )
    target = raw / target_name
    try:
        _materialize_feature_table(source.path, target)
    except Exception as exc:
        report.update({
            "status": "registry_feature_materialize_failed",
            "source": "registry",
            "sequence_upload_required": True,
            "sequence_upload_endpoint": "/sequence-analysis",
            "registry_source_path": str(source.path),
            "message": str(exc),
        })
        return report

    readiness = inspect_stoich_readiness(target, expression_gene_ids=expression_gene_ids)
    JobFile.objects.get_or_create(
        job=job,
        relative_path=str(target.relative_to(Path(job.workspace_path))),
        defaults={"file_name": target.name, "category": "raw_registry_stoich"},
    )
    report.update({
        "status": "registry_feature_materialized",
        "source": "registry",
        "file": target.name,
        "relative_path": str(target.relative_to(Path(job.workspace_path))),
        "registry_source_path": str(source.path),
        "dataset_id": source.dataset_id,
        "schema_version": source.schema_version,
        "row_count": source.row_count,
        "size_bytes": int(target.stat().st_size),
        "phase2_ready": bool(readiness.get("phase2_ready")),
        "readiness": readiness,
        "message": "Registered stoich feature table was copied into the job raw directory and will be used for Phase 2.",
    })
    return report


def write_registry_resolution_report(job: AnalysisJob, report: Dict[str, Any]) -> None:
    path = Path(job.workspace_path) / "configs" / "stoich_registry_resolution.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
