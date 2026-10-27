from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from backend.apps.common.host_paths import Path
from typing import Any, Iterable

from backend.apps.stoichdb.models import OmicsDataset


ID_FIELDS = (
    "entity_id", "gene_id", "canonical_gene_id", "ensembl_gene_id", "transcript_id", "protein_id",
    "gene_name", "gene_symbol", "description", "strategy_cluster", "seqid", "seq_region",
    "start_1", "end_1", "start", "end", "strand", "biotype", "gene_biotype", "transcript_biotype",
)


@dataclass(frozen=True)
class SourceManifest:
    dataset_id: str
    core_path: str
    full_path: str
    core_hash: str
    full_hash: str
    schema_hash: str
    core_header: tuple[str, ...]
    full_header: tuple[str, ...]
    parquet_preferred: bool
    parquet_used: bool


class CompleteCoreDataSource:
    def __init__(self, species_id: str, omics: str):
        self.species_id = species_id
        self.omics = omics
        self.dataset = OmicsDataset.objects.only(
            "dataset_id", "core_csv_path", "full_csv_path", "row_count_core", "row_count_full"
        ).get(species__species_id=species_id, omics_type=omics)
        self.core_path = Path(self.dataset.core_csv_path) if self.dataset.core_csv_path else None
        self.full_path = Path(self.dataset.full_csv_path) if self.dataset.full_csv_path else None
        self.primary_id = {
            "genome": "gene_id",
            "transcriptome": "transcript_id",
            "proteome": "protein_id",
        }.get(omics, "entity_id")

    def header(self, scope: str = "core") -> tuple[str, ...]:
        path = self._path(scope)
        if not path or not path.exists():
            return ()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return tuple(reader.fieldnames or ())

    def manifest(self) -> SourceManifest:
        core_header = self.header("core")
        full_header = self.header("full")
        schema_blob = "\n".join(["core:" + ",".join(core_header), "full:" + ",".join(full_header)])
        return SourceManifest(
            dataset_id=self.dataset.dataset_id,
            core_path=str(self.core_path or ""),
            full_path=str(self.full_path or ""),
            core_hash=_quick_hash(self.core_path),
            full_hash=_quick_hash(self.full_path),
            schema_hash=hashlib.sha256(schema_blob.encode("utf-8")).hexdigest(),
            core_header=core_header,
            full_header=full_header,
            parquet_preferred=True,
            parquet_used=False,
        )

    def rows(self, fields: Iterable[str] = (), optional_full_fields: Iterable[str] = ()) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        fields_set = set(fields or ())
        optional_set = set(optional_full_fields or ())
        core_header = set(self.header("core"))
        full_header = set(self.header("full"))
        read_core_fields = set(ID_FIELDS) | fields_set | (optional_set & core_header)
        rows = self._read_csv("core", read_core_fields)
        duplicate_id_n = _duplicate_id_count(rows, self.omics)
        full_join_match_n = 0
        full_duplicate_id_n = 0
        full_fields_used = tuple(sorted(optional_set & full_header))
        missing_optional = tuple(sorted(optional_set - core_header - full_header))
        if rows and full_fields_used and self.full_path and self.full_path.exists():
            full_rows = self._read_csv("full", set(ID_FIELDS) | set(full_fields_used))
            full_duplicate_id_n = _duplicate_id_count(full_rows, self.omics)
            full_by_key: dict[str, dict[str, Any]] = {}
            for row in full_rows:
                key = identity_key(row, self.omics)
                if key and key not in full_by_key:
                    full_by_key[key] = row
            merged = []
            for row in rows:
                out = dict(row)
                supplement = full_by_key.get(identity_key(row, self.omics))
                if supplement:
                    full_join_match_n += 1
                    for field in full_fields_used:
                        if out.get(field) in (None, "") and supplement.get(field) not in (None, ""):
                            out[field] = supplement.get(field)
                merged.append(out)
            rows = merged
        meta = {
            "source_scope": "core",
            "row_count_source": len(rows),
            "duplicate_id_n": duplicate_id_n,
            "full_supplement_used": bool(full_fields_used),
            "optional_full_fields_used": list(full_fields_used),
            "missing_optional_full_fields": list(missing_optional),
            "full_join_match_n": full_join_match_n,
            "full_duplicate_id_n": full_duplicate_id_n,
            "full_supplement_policy": "left_join_optional_fields_only; core entity universe is never replaced by full rows",
            "manifest": self.manifest().__dict__,
        }
        return rows, meta

    def _path(self, scope: str) -> Path | None:
        return self.full_path if scope == "full" else self.core_path

    def _read_csv(self, scope: str, fields: set[str]) -> list[dict[str, Any]]:
        path = self._path(scope)
        if not path or not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = set(reader.fieldnames or ())
            wanted = header if not fields else (fields & header)
            for raw in reader:
                row = {field: raw.get(field, "") for field in wanted}
                row.setdefault("entity_id", row.get(self.primary_id) or row.get("gene_id") or row.get("transcript_id") or row.get("protein_id") or raw.get("entity_id") or "")
                rows.append(row)
        return rows


def identity_key(row: dict[str, Any], omics: str) -> str:
    for field in {
        "genome": ("entity_id", "gene_id", "canonical_gene_id"),
        "transcriptome": ("entity_id", "transcript_id", "gene_id", "canonical_gene_id"),
        "proteome": ("entity_id", "protein_id", "gene_id", "ensembl_gene_id", "canonical_gene_id"),
    }.get(omics, ("entity_id", "gene_id")):
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def _duplicate_id_count(rows: list[dict[str, Any]], omics: str) -> int:
    seen: set[str] = set()
    duplicate = 0
    for row in rows:
        key = identity_key(row, omics)
        if not key:
            continue
        if key in seen:
            duplicate += 1
        seen.add(key)
    return duplicate


def _quick_hash(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    stat = path.stat()
    h = hashlib.sha256()
    h.update(str(path).encode("utf-8"))
    h.update(str(stat.st_size).encode("ascii"))
    h.update(str(int(stat.st_mtime)).encode("ascii"))
    return h.hexdigest()
