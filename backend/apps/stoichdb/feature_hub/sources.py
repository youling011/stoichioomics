from __future__ import annotations

import csv
import gzip
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from django.db.models import Q

from backend.apps.stoichdb.models import FeatureFile, OmicsDataset, Species, StorageObject
from backend.apps.stoichdb.storage_objects import resolve_storage_object
from .schemas import FeatureHubNotFound, normalize_omics, normalize_scope, safe_int, split_csv


@dataclass
class SourceDescriptor:
    species_id: str
    omics: str
    scope: str
    path: Path
    dataset_id: str
    row_count: int
    schema_version: str
    source_mode: str
    file_size: int
    file_mtime: float
    warnings: list[str]

    @property
    def fingerprint(self) -> str:
        raw = f"{self.path}|{self.file_size}|{self.file_mtime}|{self.schema_version}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _path_exists(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.exists() and path.is_file() else None


def _full_path_next_to_core(core_value: Any) -> Path | None:
    core = _path_exists(core_value)
    if core is None:
        return None
    name = core.name
    candidate_names = list(dict.fromkeys([
        name.replace(".core.", ".full."),
        name.replace(".core.csv", ".full.csv"),
        name.replace("_features.core.csv", "_features.full.csv"),
        name.replace("_features.core.csv", "_features.csv"),
        name.replace(".genome_features.core.csv", ".genome_features.csv"),
        name.replace(".transcriptome.core.v5.csv", ".transcriptome.full.v5.csv"),
        name.replace(".proteome_features.core.csv", ".proteome_features.full.csv"),
    ]))
    for candidate_name in candidate_names:
        candidate = core.with_name(candidate_name)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


class DatasetSourceResolver:
    def resolve(self, species_id: str, omics: str, scope: str = "core") -> SourceDescriptor:
        omics = normalize_omics(omics)
        scope = normalize_scope(scope)
        try:
            dataset = OmicsDataset.objects.select_related("species").get(species__species_id=species_id, omics_type=omics)
        except OmicsDataset.DoesNotExist as exc:
            raise FeatureHubNotFound(f"No registered {omics} dataset for {species_id}") from exc
        if str(dataset.status or "").lower() != "ready":
            raise FeatureHubNotFound(
                f"Registered {omics} dataset for {species_id} is not ready: {dataset.status}"
            )
        warnings: list[str] = []
        path = self._storage_object_path(dataset, scope)
        if path is None:
            path = _path_exists(dataset.core_csv_path if scope == "core" else dataset.full_csv_path)
        if path is None and scope == "full":
            path = _full_path_next_to_core(dataset.core_csv_path)
        if path is None:
            path = self._feature_file_path(dataset, scope)
        if path is None:
            raise FeatureHubNotFound(f"No readable {scope} feature file for {species_id}/{omics}")
        row_count = int(dataset.row_count_core if scope == "core" else dataset.row_count_full)
        if row_count <= 0:
            warnings.append("Registered row count is zero or missing; file existence and header remain authoritative.")
        stat = path.stat()
        return SourceDescriptor(
            species_id=species_id,
            omics=omics,
            scope=scope,
            path=path,
            dataset_id=dataset.dataset_id,
            row_count=row_count,
            schema_version=dataset.schema_version,
            source_mode="file",
            file_size=int(stat.st_size),
            file_mtime=float(stat.st_mtime),
            warnings=warnings,
        )

    def _storage_object_path(self, dataset: OmicsDataset, scope: str) -> Path | None:
        target_name = Path(dataset.core_csv_path if scope == "core" else dataset.full_csv_path).name
        candidates = StorageObject.objects.filter(
            Q(metadata_json__dataset_id=dataset.dataset_id)
            | Q(logical_key__icontains=dataset.dataset_id)
            | Q(relative_path__icontains=target_name)
        ).only("object_uri", "relative_path", "root_alias", "logical_key")[:8]
        for obj in candidates:
            resolved = resolve_storage_object(obj)
            if isinstance(resolved, Path) and resolved.exists() and resolved.is_file():
                name = resolved.name.lower()
                if scope == "core" and "core" in name:
                    return resolved
                if scope == "full" and ("full" in name or ".core." not in name):
                    return resolved
        return None

    def _feature_file_path(self, dataset: OmicsDataset, scope: str) -> Path | None:
        record = FeatureFile.objects.filter(dataset=dataset, file_type=scope).only("path").first()
        return _path_exists(record.path) if record else None


def read_header(source: SourceDescriptor) -> list[str]:
    opener = gzip.open if source.path.suffix.lower() == ".gz" else open
    with opener(source.path, "rt", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle), [])


def iter_rows(source: SourceDescriptor, selected_fields: list[str] | None = None) -> Iterator[dict[str, Any]]:
    selected = list(dict.fromkeys(selected_fields or []))
    opener = gzip.open if source.path.suffix.lower() == ".gz" else open
    with opener(source.path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        if selected:
            for field in selected:
                if field not in header:
                    raise FeatureHubNotFound(f"Field {field} is not present in {source.species_id}/{source.omics}/{source.scope}")
        for row in reader:
            if not isinstance(row, dict):
                continue
            yield {field: row.get(field, "") for field in selected} if selected else row


def preview_rows(source: SourceDescriptor, fields: list[str], *, page: Any = 1, page_size: Any = 50, query: str = "") -> dict[str, Any]:
    page = safe_int(page, 1, minimum=1, maximum=100000)
    page_size = safe_int(page_size, 50, minimum=1, maximum=200)
    header = read_header(source)
    requested = fields or header[: min(24, len(header))]
    columns = [field for field in requested if field in header]
    if not columns:
        raise FeatureHubNotFound("No requested preview fields exist in the source file")
    id_columns = [field for field in ["species_id", "gene_id", "transcript_id", "protein_id", "entity_id"] if field in header]
    scan_columns = list(dict.fromkeys(id_columns + columns))
    start = (page - 1) * page_size
    rows: list[dict[str, Any]] = []
    matched = 0
    q = str(query or "").strip().lower()
    for row in iter_rows(source, scan_columns):
        if q and not any(q in str(row.get(col, "")).lower() for col in scan_columns):
            continue
        if matched >= start and len(rows) < page_size:
            rows.append({col: row.get(col, "") for col in columns})
        matched += 1
        if len(rows) >= page_size and not q and source.row_count > 0:
            break
    total = matched if q or source.row_count <= 0 else source.row_count
    return {
        "species_id": source.species_id,
        "omics": source.omics,
        "scope": source.scope,
        "total_rows": total,
        "displayed_rows": len(rows),
        "page": page,
        "page_size": page_size,
        "columns": columns,
        "rows": rows,
        "source_mode": source.source_mode,
        "schema_version": source.schema_version,
        "warnings": source.warnings,
    }


def available_species(query: str = "", limit: Any = 100, omics: str = "") -> dict[str, Any]:
    limit = safe_int(limit, 100, minimum=1, maximum=500)
    qs = Species.objects.all()
    if query:
        q = str(query).strip()
        qs = qs.filter(Q(species_id__icontains=q) | Q(display_name__icontains=q) | Q(short_name__icontains=q) | Q(taxonomy_id__icontains=q) | Q(searchable_text__icontains=q))
    qs = qs.only("species_id", "display_name", "short_name", "taxonomy_id").order_by("display_name")[:limit]
    species_rows = list(qs)
    species_ids = [row.species_id for row in species_rows]
    dataset_qs = OmicsDataset.objects.filter(species__species_id__in=species_ids)
    if omics:
        dataset_qs = dataset_qs.filter(omics_type=normalize_omics(omics))
    availability: dict[str, dict[str, Any]] = {}
    for ds in dataset_qs.select_related("species").only("species__species_id", "omics_type", "row_count_core", "row_count_full", "core_csv_path", "full_csv_path", "status"):
        if str(ds.status or "").lower() != "ready":
            continue
        item = availability.setdefault(ds.species.species_id, {})
        item[ds.omics_type] = {
            "core_rows": ds.row_count_core,
            "full_rows": ds.row_count_full,
            "core_available": bool(ds.core_csv_path),
            "full_available": bool(ds.full_csv_path),
        }
    return {
        "items": [
            {
                "species_id": sp.species_id,
                "display_name": sp.display_name,
                "scientific_name": sp.display_name,
                "taxid": sp.taxonomy_id,
                "omics": availability.get(sp.species_id, {}),
            }
            for sp in species_rows
        ],
        "limit": limit,
    }


def parse_fields_param(value: Any) -> list[str]:
    return split_csv(value, limit=500)
