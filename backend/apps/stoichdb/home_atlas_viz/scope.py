from __future__ import annotations
import json
from contextlib import contextmanager
from django.db import connection, transaction
from ..models import AnalysisArtifact, OmicsDataset, SchemaRegistry, Species
from ..services import _filtered_species_queryset
from .contracts import OMICS, digest, normalize_filters


@contextmanager
def read_consistent_snapshot():
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield


def snapshot(params):
    with read_consistent_snapshot():
        species = list(Species.objects.order_by("species_id").values(
            "id", "species_id", "display_name", "domain", "clade", "habitat",
            "genome_size_mb", "fingerprint", "searchable_text", "updated_at"))
        allowed = {k for r in species for k in (r["fingerprint"] or {})}
        filters = normalize_filters(params, allowed)
        args = {**filters, "fingerprint_filters": json.dumps(filters["fingerprint_filters"]) if filters["fingerprint_filters"] else ""}
        ids = set(_filtered_species_queryset(**args, include_omics_filter=False,
                                             base_queryset=Species.objects.all()).order_by().values_list("id", flat=True))
        datasets = list(OmicsDataset.objects.filter(omics_type__in=OMICS).order_by("id").values(
            "id", "dataset_id", "species_id", "omics_type", "row_count_core", "schema_version",
            "core_csv_path", "full_csv_path", "status", "updated_at"))
        artifacts = list(AnalysisArtifact.objects.filter(
            artifact_type="species_atlas_core_completeness", dataset__isnull=False,
            dataset__omics_type__in=OMICS).order_by("dataset_id", "-updated_at", "-id").values(
                "id", "dataset_id", "updated_at", "payload_json__source_method", "payload_json__missing_cells"))
        schemas = list(SchemaRegistry.objects.filter(product_type="core", omics_type__in=OMICS)
                       .order_by("schema_id").values("schema_id", "omics_type", "version", "columns_json", "updated_at"))
    return {"species": species, "ids": ids, "datasets": datasets, "artifacts": artifacts,
            "schemas": schemas, "filters": filters,
            "source_revision": digest([species, datasets, artifacts, schemas])}
