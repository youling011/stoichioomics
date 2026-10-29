from __future__ import annotations

from typing import Any

from django.db.models import Count, Q, Sum

from backend.apps.stoichdb.models import OmicsDataset, Species
from .alignment import validate_alignment_request
from .export import create_export, export_download_path, export_status
from .homepage_cache import homepage_preview
from .profiling import field_profile
from .qc import qc_report
from .registry import catalog_payload, load_registry, write_registry_file
from .schemas import boolish, normalize_omics, normalize_scope, split_csv
from .sources import DatasetSourceResolver, available_species, parse_fields_param, preview_rows, read_header


def overview() -> dict[str, Any]:
    registry = load_registry()
    by_omics = list(
        OmicsDataset.objects.values("omics_type").annotate(
            datasets=Count("id"),
            core_available=Count("id", filter=Q(core_csv_path__gt="")),
            full_available=Count("id", filter=Q(full_csv_path__gt="")),
            core_rows=Sum("row_count_core"),
            full_rows=Sum("row_count_full"),
        ).order_by("omics_type")
    )
    return {
        "title": "Multi-omics Feature Explorer & ML-ready Dataset Builder",
        "registry_version": registry["registry_version"],
        "species_count": Species.objects.count(),
        "omics_count": 3,
        "core_schema_columns": 309,
        "full_schema_columns": 776,
        "ml_eligible_core_fields": registry["summary"]["ml_eligible_core_fields"],
        "schemas": registry["schemas"],
        "dataset_summary": by_omics,
        "policy": registry["rules"],
        "quick_actions": [
            {"label": "Browse Features", "to": "/feature-hub/catalog"},
            {"label": "Build ML Dataset", "to": "/feature-hub/builder"},
            {"label": "Download Source Files", "to": "/downloads"},
        ],
    }


def catalog(params: Any) -> dict[str, Any]:
    return catalog_payload(
        omics=params.get("omics", ""),
        scope=params.get("scope", ""),
        family=params.get("family", ""),
        ml_role=params.get("ml_role", ""),
        search=params.get("search", ""),
    )


def species(params: Any) -> dict[str, Any]:
    return available_species(query=params.get("query", ""), limit=params.get("limit", 100), omics=params.get("omics", ""))


def dataset_detail(species_id: str, omics: str, params: Any) -> dict[str, Any]:
    source = DatasetSourceResolver().resolve(species_id, normalize_omics(omics), normalize_scope(params.get("scope", "core")))
    return {
        "species_id": source.species_id,
        "omics": source.omics,
        "scope": source.scope,
        "dataset_id": source.dataset_id,
        "row_count": source.row_count,
        "schema_version": source.schema_version,
        "source_mode": source.source_mode,
        "path": str(source.path),
        "file_size": source.file_size,
        "fingerprint": source.fingerprint,
        "header": read_header(source),
        "warnings": source.warnings,
    }


def preview(params: Any) -> dict[str, Any]:
    source = DatasetSourceResolver().resolve(params.get("species_id", ""), normalize_omics(params.get("omics", "genome")), normalize_scope(params.get("scope", "core")))
    return preview_rows(source, parse_fields_param(params.get("fields", "")), page=params.get("page", 1), page_size=params.get("page_size", 50), query=params.get("query", ""))


def home_preview(params: Any) -> dict[str, Any]:
    return homepage_preview(
        species_id=params.get("species_id", ""),
        omics=params.get("omics", "proteome"),
        scope=params.get("scope", "core"),
        family=params.get("family", ""),
        force=boolish(params.get("force"), False),
    )


def profile(params: Any) -> dict[str, Any]:
    return field_profile(
        species_id=params.get("species_id", ""),
        omics=params.get("omics", "genome"),
        scope=params.get("scope", "core"),
        field=params.get("field", ""),
        force=boolish(params.get("force"), False),
    )


def qc(payload: dict[str, Any]) -> dict[str, Any]:
    return qc_report(
        species_id=payload.get("species_id", ""),
        omics=payload.get("omics", "genome"),
        fields=split_csv(payload.get("fields") or [], limit=300),
        force=boolish(payload.get("force"), False),
    )


def create_export_job(payload: dict[str, Any]) -> dict[str, Any]:
    return create_export(payload)


def get_export(export_id: str) -> dict[str, Any]:
    return export_status(export_id)


def download_export(export_id: str):
    return export_download_path(export_id)


def build_registry() -> dict[str, Any]:
    try:path=write_registry_file()
    except (OSError,TimeoutError) as exc:raise FeatureHubError('Registry snapshot could not be published to its configured writable state directory') from exc
    return {'path':str(path),'summary':load_registry()['summary']}


def alignment(payload: dict[str, Any]) -> dict[str, Any]:
    return validate_alignment_request(payload.get("omics") or [], payload.get("anchor", ""))

