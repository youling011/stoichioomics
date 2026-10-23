from __future__ import annotations

"""Build the job-scoped comparison-only Core context after Phase 1."""

import hashlib
import gzip
import io
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from django.db.models import Q

from backend.apps.stoichdb.feature_hub.field_resolution import (
    canonical_context_column,
    resolve_registry_fields,
)
from backend.apps.stoichdb.feature_hub.sources import DatasetSourceResolver, read_header
from backend.apps.stoichdb.models import StorageObject
from backend.analysis_engine.phase2.comparison_schema import COMPARISON_SCHEMA_VERSION

from .feature_mapping import GeneMappingResult, SpeciesMappingIndex, resolve_source_identity


BUILDER_VERSION = "hvg_feature_context_v2"
ALLOWED_OMICS = ("genome", "transcriptome", "proteome")
EXPECTED_CORE_COUNTS = {"genome": 160, "transcriptome": 86, "proteome": 63}
ARTIFACT_NAMES = {
    "context": "hvg_multiomics_core_features.csv",
    "provenance": "hvg_multiomics_feature_provenance.csv",
    "mapping": "hvg_multiomics_mapping_table.csv",
    "mapping_summary": "hvg_multiomics_mapping_summary.json",
    "assembly_manifest": "hvg_multiomics_assembly_manifest.json",
    "block_coverage": "hvg_nonhvg_block_coverage.csv",
}
MAPPING_COLUMNS = [
    "expression_gene_id", "canonical_gene_id", "species_id", "omics",
    "source_entity_id", "mapping_method", "mapping_status", "mapping_confidence",
    "candidate_count", "collision_group", "exclusion_reason", "reason",
]
PROVENANCE_COLUMNS = [
    "feature_key", "output_column", "omics", "registry_name", "registry_role",
    "family", "applicability", "composition_group", "source_dataset_id",
    "source_logical_key_or_basename", "source_sha256", "source_column",
    "hash_source", "source_present", "materialized", "resolution_method", "registry_version",
    "builder_version",
]
COVERAGE_COLUMNS = [
    "omics", "block_status", "dataset_id", "schema_version", "source_sha256",
    "registered_core_fields", "eligible_fields", "conditional_fields", "exclude_fields",
    "source_present_fields", "materialized_eligible_fields", "expression_gene_count",
    "applicable_gene_count", "mapped_gene_count", "raw_match_rate", "applicable_match_rate",
    "tested_fields", "descriptive_only_fields", "skipped_candidate_fields", "significant_fields",
    "status_reason",
]


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _normal(value: Any) -> str:
    return _clean(value).casefold()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is pd.NA or (not isinstance(value, (str, bytes)) and pd.isna(value)):
        return None
    return value


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _atomic_write_csv(path: Path, frame: pd.DataFrame, columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        work = frame.copy()
        if columns:
            for column in columns:
                if column not in work:
                    work[column] = ""
            work = work[columns]
        work.to_csv(tmp, index=False, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _HashingBinaryReader:
    """File wrapper that hashes sequential parser reads without a second scan."""

    def __init__(self, path: Path):
        self._handle = path.open("rb")
        self._digest = hashlib.sha256()
        self.bytes_read = 0
        self._last_position = 0
        self.sequential = True

    def _record(self, start: int, data: bytes) -> bytes:
        if start != self._last_position:
            self.sequential = False
        self._last_position = start + len(data)
        self._digest.update(data)
        self.bytes_read += len(data)
        return data

    def read(self, size: int = -1) -> bytes:
        start = self._handle.tell()
        return self._record(start, self._handle.read(size))

    def read1(self, size: int = -1) -> bytes:
        return self.read(size)

    def readline(self, size: int = -1) -> bytes:
        start = self._handle.tell()
        return self._record(start, self._handle.readline(size))

    def readinto(self, buffer) -> int:
        start = self._handle.tell()
        count = self._handle.readinto(buffer)
        data = bytes(memoryview(buffer)[:count]) if count else b""
        self._record(start, data)
        return count

    def seek(self, *args):
        return self._handle.seek(*args)

    def tell(self):
        return self._handle.tell()

    def readable(self):
        return self._handle.readable()

    def writable(self):
        return False

    def flush(self):
        return self._handle.flush()

    def seekable(self):
        return self._handle.seekable()

    def fileno(self):
        return self._handle.fileno()

    def close(self):
        self._handle.close()

    @property
    def closed(self):
        return self._handle.closed

    def hexdigest(self) -> str:
        return self._digest.hexdigest()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def _rss_mb() -> float | None:
    try:
        import psutil

        return round(float(psutil.Process(os.getpid()).memory_info().rss) / (1024 * 1024), 3)
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class _Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("page_fault_count", wintypes.DWORD),
                    ("peak_working_set_size", ctypes.c_size_t),
                    ("working_set_size", ctypes.c_size_t),
                    ("quota_peak_paged_pool_usage", ctypes.c_size_t),
                    ("quota_paged_pool_usage", ctypes.c_size_t),
                    ("quota_peak_non_paged_pool_usage", ctypes.c_size_t),
                    ("quota_non_paged_pool_usage", ctypes.c_size_t),
                    ("pagefile_usage", ctypes.c_size_t),
                    ("peak_pagefile_usage", ctypes.c_size_t),
                ]

            counters = _Counters()
            counters.cb = ctypes.sizeof(_Counters)
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            ):
                return round(float(counters.peak_working_set_size) / (1024 * 1024), 3)
        except Exception:
            pass
    try:
        import resource

        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return round(value / (1024 * 1024 if os.name == "nt" else 1024), 3)
    except Exception:
        return None


def _mtime_iso(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _valid_sha(value: Any) -> str:
    text = _clean(value).lower()
    return text if re.fullmatch(r"[0-9a-f]{64}", text) else ""


def _stored_hash(source: Any) -> str:
    """Reuse a registered StorageObject hash only when it resolves to this file."""
    try:
        rows = StorageObject.objects.filter(
            Q(metadata_json__dataset_id=source.dataset_id)
            | Q(logical_key__icontains=source.dataset_id)
            | Q(relative_path__icontains=Path(source.path).name)
        ).only("sha256", "object_uri", "relative_path", "root_alias")[:16]
        source_path = Path(source.path).resolve()
        for row in rows:
            value = _valid_sha(row.sha256)
            if not value:
                continue
            object_uri = _clean(row.object_uri)
            relative = _clean(row.relative_path)
            if object_uri and Path(object_uri).exists() and Path(object_uri).resolve() == source_path:
                return value
            if relative and Path(relative).exists() and Path(relative).resolve() == source_path:
                return value
        return ""
    except Exception:
        return ""


def _load_registry(config: dict[str, Any] | None = None) -> tuple[dict[str, Any], str, Path]:
    config = config or {}
    snapshot = config.get("registry_snapshot_path")
    if snapshot:
        path = Path(snapshot).resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload, _sha256(path), path
    injected = config.get("_registry_payload")
    if isinstance(injected, dict) and injected.get("fields"):
        encoded = json.dumps(injected, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return injected, hashlib.sha256(encoded).hexdigest(), Path("registry_snapshot.json")
    project_root = Path(__file__).resolve().parents[3]
    path = project_root / "shared" / "schemas" / "stoich_ml_feature_registry_v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload, _sha256(path), path


def _requested_omics(config: dict[str, Any]) -> list[str]:
    raw = config.get("comparison_omics") or ALLOWED_OMICS
    if isinstance(raw, str):
        values = [part.strip().lower() for part in raw.replace("+", ",").split(",") if part.strip()]
    else:
        values = [str(part).strip().lower() for part in raw if str(part).strip()]
    if "all" in values:
        values = list(ALLOWED_OMICS)
    return [omics for omics in ALLOWED_OMICS if omics in dict.fromkeys(values)]


def _read_baseline(path: str | Path) -> pd.DataFrame:
    target = Path(path)
    sep = "\t" if target.suffix.lower() in {".tsv", ".txt"} else ","
    frame = pd.read_csv(target, sep=sep)
    if "gene_id" not in frame.columns or "is_hvg" not in frame.columns:
        raise ValueError("baseline_missing_gene_id_or_is_hvg")
    frame = frame.copy()
    frame["gene_id"] = frame["gene_id"].map(_clean)
    if frame["gene_id"].eq("").any():
        raise ValueError("empty_expression_gene_id")
    if frame["gene_id"].duplicated().any():
        raise ValueError("duplicate_expression_gene_id")
    return frame


def _binary_mask(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    text = series.fillna("").astype(str).str.strip().str.lower()
    result = pd.Series(pd.NA, index=series.index, dtype="boolean")
    result.loc[numeric.notna()] = numeric.loc[numeric.notna()] != 0
    result.loc[text.isin({"true", "t", "yes", "y", "1", "coding", "valid"})] = True
    result.loc[text.isin({"false", "f", "no", "n", "0", "noncoding", "invalid"})] = False
    return result


def _mask_from_context(context: pd.DataFrame, columns: tuple[str, ...]) -> tuple[pd.Series | None, str]:
    for column in columns:
        if column not in context:
            continue
        parsed = _binary_mask(context[column])
        if parsed.notna().any():
            return parsed, column
    return None, ""


def _biotype_mask(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip().str.casefold()
    result = pd.Series(pd.NA, index=series.index, dtype="boolean")
    noncoding = values.str.contains("non.?coding|pseudogene|lnc.?rna|linc.?rna", regex=True, na=False)
    coding = values.str.contains("protein.?coding|coding|mrna|cds", regex=True, na=False) & ~noncoding
    result.loc[noncoding] = False
    result.loc[coding] = True
    return result


def _biotype_mask_from_context(context: pd.DataFrame, columns: tuple[str, ...]) -> tuple[pd.Series | None, str]:
    for column in columns:
        if column not in context:
            continue
        parsed = _biotype_mask(context[column])
        if parsed.notna().any():
            return parsed, column
    return None, ""


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "comparison_omics", "comparison_include_conditional", "comparison_min_block_match_rate",
        "comparison_min_block_mapped_genes", "comparison_allow_alias_mapping",
        "comparison_require_unique_mapping", "comparison_allow_version_stripped_unique",
        "comparison_source_chunk_size", "comparison_applicability_policy",
        "comparison_adjustment_policy", "comparison_composition_adjustment",
        "comparison_composition_pseudocount_fraction", "comparison_min_group_n",
        "comparison_max_missing_rate", "comparison_bootstrap_ci_repeats",
        "comparison_bootstrap_max_group_n", "comparison_worker_count",
    }
    return {key: _json_safe(config[key]) for key in keys if key in config}


def _source_rows(source: Any, columns: list[str], chunk_size: int, metrics: dict[str, Any]) -> Iterable[dict[str, Any]]:
    if not columns:
        raise ValueError("source_identity_columns_missing")
    raw = _HashingBinaryReader(Path(source.path))
    stream = raw
    text = None
    try:
        if Path(source.path).suffix.lower() == ".gz":
            stream = gzip.GzipFile(fileobj=raw, mode="rb")
        text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
        frames = pd.read_csv(
            text,
            usecols=columns,
            dtype=str,
            keep_default_na=False,
            chunksize=max(1, int(chunk_size)),
            compression=None,
        )
        for chunk in frames:
            chunk = chunk.fillna("")
            metrics["source_rows_scanned"] = int(metrics.get("source_rows_scanned", 0)) + int(chunk.shape[0])
            yield from chunk.to_dict(orient="records")
    finally:
        if text is not None:
            text.close()
        if not raw.closed:
            raw.close()
        metrics["source_bytes_read"] = int(raw.bytes_read)
        metrics["source_sha256"] = raw.hexdigest() if raw.sequential else _sha256(Path(source.path))
        metrics["hash_source"] = "stream_computed"


def _truthy(value: Any) -> bool:
    return _normal(value) in {"1", "true", "t", "yes", "y", "on", "canonical", "primary", "chosen"}


def _choose_duplicate(rows: list[dict[str, Any]], value_columns: list[str]) -> tuple[dict[str, Any] | None, int, str]:
    if len(rows) == 1:
        return rows[0], 0, ""
    first = rows[0]
    if all(tuple(_clean(row.get(column)) for column in value_columns) == tuple(_clean(first.get(column)) for column in value_columns) for row in rows[1:]):
        return first, len(rows) - 1, ""
    flags = ("is_canonical", "canonical", "is_primary", "primary", "chosen", "is_chosen")
    chosen = [row for row in rows if any(field in row and _truthy(row.get(field)) for field in flags)]
    if len(chosen) == 1:
        return chosen[0], len(rows) - 1, ""
    # Transcript and protein Core files are entity-level sources, so several
    # rows can legitimately belong to one canonical gene (isoforms/proteins).
    # The expression-to-canonical mapping is still unique; retain the stable
    # first source row and record the discarded rows instead of treating the
    # normal one-to-many source relationship as an ambiguous gene mapping.
    return first, len(rows) - 1, ""


def _source_provenance(
    source: Any,
    source_sha: str,
    hash_source: str,
    field_resolution: Any,
    meta: dict[str, Any],
    output_column: str,
) -> dict[str, Any]:
    return {
        "feature_key": f"{meta.get('omics')}::{meta.get('field')}",
        "output_column": output_column,
        "omics": meta.get("omics"),
        "registry_name": meta.get("field"),
        "registry_role": meta.get("ml_role") or "exclude",
        "family": meta.get("family") or "other",
        "applicability": meta.get("applicability") or "all",
        "composition_group": meta.get("composition_group") or "",
        "source_dataset_id": getattr(source, "dataset_id", "") if source else "",
        "source_logical_key_or_basename": Path(source.path).name if source else "",
        "source_sha256": source_sha,
        "source_column": field_resolution.source_column if field_resolution else "",
        "hash_source": hash_source,
        "source_present": bool(field_resolution and field_resolution.present),
        "materialized": False,
        "resolution_method": field_resolution.method if field_resolution else "unresolved",
        "registry_version": "",
        "builder_version": BUILDER_VERSION,
    }


def _failure_bundle(output_dir: Path, reason: str, config: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    empty_context = pd.DataFrame(columns=["gene_id", "is_hvg"])
    _atomic_write_csv(output_dir / ARTIFACT_NAMES["context"], empty_context)
    _atomic_write_csv(output_dir / ARTIFACT_NAMES["provenance"], pd.DataFrame(columns=PROVENANCE_COLUMNS), PROVENANCE_COLUMNS)
    _atomic_write_csv(output_dir / ARTIFACT_NAMES["mapping"], pd.DataFrame(columns=MAPPING_COLUMNS), MAPPING_COLUMNS)
    summary = {
        "status": "failed",
        "reason": reason,
        "builder_version": BUILDER_VERSION,
        "requested_omics": _requested_omics(config),
        "blocks": {},
    }
    _atomic_write_text(output_dir / ARTIFACT_NAMES["mapping_summary"], json.dumps(summary, ensure_ascii=False, indent=2))
    _atomic_write_csv(output_dir / ARTIFACT_NAMES["block_coverage"], pd.DataFrame(columns=COVERAGE_COLUMNS), COVERAGE_COLUMNS)
    manifest = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "status": "failed",
        "reason": reason,
        "artifact_paths": {key: value for key, value in ARTIFACT_NAMES.items()},
    }
    _atomic_write_text(output_dir / ARTIFACT_NAMES["assembly_manifest"], json.dumps(manifest, ensure_ascii=False, indent=2))
    return {
        "status": "failed",
        "reason": reason,
        "comparison_input_csv": str((output_dir / ARTIFACT_NAMES["context"]).resolve()),
        "mapping_summary_json": str((output_dir / ARTIFACT_NAMES["mapping_summary"]).resolve()),
        "feature_provenance_csv": str((output_dir / ARTIFACT_NAMES["provenance"]).resolve()),
        "mapping_table_csv": str((output_dir / ARTIFACT_NAMES["mapping"]).resolve()),
        "assembly_manifest_json": str((output_dir / ARTIFACT_NAMES["assembly_manifest"]).resolve()),
        "block_coverage_csv": str((output_dir / ARTIFACT_NAMES["block_coverage"]).resolve()),
        "block_status": {},
        "requested_omics": _requested_omics(config),
        "available_omics": [],
    }


def _performance_payload(block_details: dict[str, dict[str, Any]], context: pd.DataFrame) -> dict[str, Any]:
    return {
        "context_rows": int(context.shape[0]),
        "context_columns": int(context.shape[1]),
        "peak_rss_mb": _rss_mb(),
        "source_blocks": {
            omics: {
                "source_bytes_read": int(details.get("source_bytes_read", 0) or 0),
                "source_rows_scanned": int(details.get("source_rows_scanned", 0) or 0),
                "materialized_columns": int(details.get("materialized_eligible_fields", 0) or 0),
                "runtime_seconds": details.get("runtime_seconds"),
            }
            for omics, details in block_details.items()
        },
    }


def build_hvg_multiomics_feature_context(
    *,
    baseline_csv: str | Path,
    output_dir: str | Path,
    species_id: str,
    requested_omics: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build a comparison-only context from Phase 1 genes and registered Core files."""
    started = time.perf_counter()
    output = Path(output_dir)
    try:
        baseline = _read_baseline(baseline_csv)
    except Exception as exc:
        return _failure_bundle(output, str(exc), config)

    requested = [omics for omics in ALLOWED_OMICS if omics in dict.fromkeys(str(item).lower() for item in (requested_omics or ALLOWED_OMICS))]
    if not requested:
        return _failure_bundle(output, "no_supported_comparison_omics", config)
    if not _clean(species_id) or _normal(species_id) == "unknown":
        return _failure_bundle(output, "missing_species_context", config)

    try:
        registry, registry_sha, registry_path = _load_registry(config)
        registry_version = str(registry.get("registry_version") or "unknown")
        core_by_omics = {
            omics: [
                dict(row)
                for row in registry.get("fields", [])
                if row.get("scope") == "core" and str(row.get("omics") or "").lower() == omics
            ]
            for omics in requested
        }
        if sum(len(rows) for rows in core_by_omics.values()) == 0:
            return _failure_bundle(output, "registry_core_universe_empty", config)
        if registry_path.name == "stoich_ml_feature_registry_v1.json":
            observed = {omics: len(core_by_omics.get(omics, [])) for omics in ALLOWED_OMICS}
            if observed != EXPECTED_CORE_COUNTS:
                return _failure_bundle(output, f"registry_core_universe_count_mismatch:{observed}", config)
    except Exception as exc:
        return _failure_bundle(output, f"registry_load_failed:{type(exc).__name__}", config)

    context = baseline.copy()
    expression_ids = context["gene_id"].astype(str).tolist()
    source_resolver = config.get("_source_resolver") or DatasetSourceResolver()
    block_status: dict[str, dict[str, Any]] = {}
    mapping_rows: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    block_details: dict[str, dict[str, Any]] = {}
    process_order = [omics for omics in ALLOWED_OMICS if omics in requested]

    for omics in process_order:
        block_started = time.perf_counter()
        fields = core_by_omics[omics]
        source = None
        source_sha = ""
        hash_source = ""
        stream_metrics: dict[str, Any] = {"source_rows_scanned": 0, "source_bytes_read": 0}
        stored_source_sha = ""
        resolutions: dict[str, Any] = {}
        rows: list[dict[str, Any]] = []
        source_records: dict[str, dict[str, Any]] = {}
        ambiguous_source: set[str] = set()
        duplicate_source_rows = 0
        block_reason: list[str] = []
        try:
            source = source_resolver.resolve(species_id, omics, scope="core")
            if _clean(getattr(source, "species_id", "")) != _clean(species_id):
                raise ValueError("source_species_mismatch")
            if _clean(getattr(source, "omics", "")) != omics:
                raise ValueError("source_omics_mismatch")
            if not Path(source.path).exists() or not Path(source.path).is_file():
                raise ValueError("source_file_unreadable")
            headers = read_header(source)
            if not headers:
                raise ValueError("source_header_missing")
            resolutions = resolve_registry_fields(headers, fields, omics=omics)
            identity_columns = [
                header for header in headers
                if _normal(header) in {
                    "species_id", "gene_id", "canonical_gene_id", "entity_id", "transcript_id",
                    "protein_id", "ensembl_gene_id", "source_gene_id", "gene_name", "gene_symbol", "locus_tag",
                    "is_coding", "coding_valid", "is_canonical", "is_primary", "chosen",
                }
            ]
            selected_columns = list(dict.fromkeys(identity_columns + [item.source_column for item in resolutions.values() if item.present]))
            stored_source_sha = _stored_hash(source)
            rows = _source_rows(
                source,
                selected_columns,
                int(config.get("comparison_source_chunk_size", 50000)),
                stream_metrics,
            )
            index = SpeciesMappingIndex(species_id, expression_ids)
            grouped: dict[str, list[dict[str, Any]]] = {}
            species_column = next((header for header in selected_columns if _normal(header) == "species_id"), "")
            for row in rows:
                if species_column and _clean(row.get(species_column)) and _normal(row.get(species_column)) != _normal(species_id):
                    raise ValueError("source_species_row_mismatch")
                resolved = resolve_source_identity(index, omics, row)
                if resolved.mapping_status != "mapped" or not resolved.canonical_gene_id:
                    continue
                grouped.setdefault(resolved.canonical_gene_id, []).append(row)
                index.add_source_identity(omics, row, resolved.canonical_gene_id)
            source_sha = stored_source_sha or str(stream_metrics.get("source_sha256") or "")
            hash_source = "storage_object" if stored_source_sha else str(stream_metrics.get("hash_source") or "stream_computed")
            value_columns = [item.source_column for item in resolutions.values() if item.present]
            for canonical, candidates in grouped.items():
                chosen, duplicate_count, duplicate_reason = _choose_duplicate(candidates, value_columns)
                duplicate_source_rows += duplicate_count
                if duplicate_reason:
                    ambiguous_source.add(canonical)
                elif chosen is not None:
                    source_records[canonical] = chosen

            results = index.resolve_many(expression_ids, omics)
            canonical_to_expression: dict[str, list[str]] = {}
            for expression_id, result in results.items():
                if result.mapping_status == "mapped" and result.canonical_gene_id:
                    canonical_to_expression.setdefault(result.canonical_gene_id, []).append(expression_id)
            collision_groups = {
                canonical: ids
                for canonical, ids in canonical_to_expression.items()
                if len(ids) > 1
            }
            for expression_id in expression_ids:
                result = results[expression_id]
                collision_group = ""
                exclusion_reason = ""
                status = result.mapping_status
                canonical = result.canonical_gene_id
                if canonical in collision_groups:
                    collision_group = "canonical_collision:" + hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]
                    status = "ambiguous"
                    exclusion_reason = "ambiguous_canonical_collision"
                elif status == "mapped" and canonical in ambiguous_source:
                    status = "ambiguous"
                    exclusion_reason = "ambiguous_source_rows"
                elif status == "mapped" and canonical not in source_records:
                    status = "unmapped_gene_context"
                    exclusion_reason = "unmapped_gene_context"
                mapping_rows.append({
                    "expression_gene_id": expression_id,
                    "canonical_gene_id": canonical,
                    "species_id": species_id,
                    "omics": omics,
                    "source_entity_id": result.source_entity_id,
                    "mapping_method": result.mapping_method,
                    "mapping_status": status,
                    "mapping_confidence": result.confidence,
                    "candidate_count": result.candidate_count,
                    "collision_group": collision_group,
                    "exclusion_reason": exclusion_reason,
                    "reason": result.reason or exclusion_reason,
                })

            coding_mask, coding_column = _mask_from_context(context, ("genome__coding_valid", "genome__is_coding"))
            if coding_mask is None:
                coding_mask, coding_column = _biotype_mask_from_context(
                    context,
                    ("genome__biotype", "genome__gene_biotype"),
                )
                if coding_mask is not None:
                    coding_column = f"biotype:{coding_column}"
            if coding_mask is None:
                coding_lookup = getattr(index, "coding_by_expression", None)
                coding_by_expression = coding_lookup(results) if callable(coding_lookup) else {}
                if coding_by_expression and any(value is not None for value in coding_by_expression.values()):
                    coding_mask = pd.Series(
                        [coding_by_expression.get(expression_id, pd.NA) for expression_id in expression_ids],
                        index=context.index,
                        dtype="boolean",
                    )
                    coding_column = "GeneIndex.biotype"
            denominator_fallback = False
            if omics == "proteome":
                applicable_mask = coding_mask
                if applicable_mask is None:
                    applicable_mask = pd.Series(True, index=context.index, dtype="boolean")
                    denominator_fallback = True
                    block_reason.append("applicability_denominator_unavailable")
            else:
                applicable_mask = pd.Series(True, index=context.index, dtype="boolean")

            mapping_for_block = [row for row in mapping_rows if row["omics"] == omics]
            mapped_flags = []
            for row in mapping_for_block:
                mapped_flags.append(row["mapping_status"] == "mapped")
            mapped_mask = pd.Series(mapped_flags, index=context.index, dtype=bool)
            valid_count = len(expression_ids)
            applicable_count = int(applicable_mask.fillna(False).sum())
            mapped_count = int((mapped_mask & applicable_mask.fillna(False).astype(bool)).sum())
            raw_mapped_count = int(mapped_mask.sum())
            raw_rate = raw_mapped_count / max(valid_count, 1)
            applicable_rate = mapped_count / max(applicable_count, 1)
            # Proteome uses the reliable coding-gene denominator when it is
            # available; all other blocks use raw valid-expression coverage.
            selected_rate = applicable_rate if omics == "proteome" and not denominator_fallback else raw_rate
            min_rate = float(config.get("comparison_min_block_match_rate", 0.70))
            min_genes = int(config.get("comparison_min_block_mapped_genes", 40))
            expected = len(fields)
            source_present = sum(1 for item in resolutions.values() if item.present)
            eligible = sum(1 for item in fields if item.get("ml_role") == "eligible")
            conditional = sum(1 for item in fields if item.get("ml_role") == "conditional")
            exclude = sum(1 for item in fields if item.get("ml_role") == "exclude")
            missing_candidate = []
            for item in fields:
                if item.get("ml_role") not in {"eligible", "conditional"}:
                    continue
                resolution = resolutions.get(str(item.get("field")))
                if not resolution or not resolution.present:
                    missing_candidate.append(str(item.get("field")))
            mapped_for_gate = mapped_count if omics == "proteome" and not denominator_fallback else raw_mapped_count
            if selected_rate < min_rate or mapped_for_gate < min_genes:
                status = "failed"
                block_reason.append("mapping_below_threshold")
            else:
                status = "partial" if missing_candidate or denominator_fallback else "ready"
            if missing_candidate:
                block_reason.append("missing_source_column")
            if duplicate_source_rows:
                block_reason.append(f"duplicate_source_rows:{duplicate_source_rows}")
            if ambiguous_source:
                block_reason.append(f"ambiguous_source_rows:{len(ambiguous_source)}")

            # Materialize only after mapping/gating decisions are known.  The
            # expression gene order remains exactly the Phase 1 order.
            block_mapping = {row["expression_gene_id"]: row for row in mapping_for_block}
            for field in fields:
                field_name = str(field.get("field") or "")
                resolution = resolutions.get(field_name)
                output_column = canonical_context_column(omics, field_name)
                materialized = False
                if resolution and resolution.present:
                    values: list[str] = []
                    for expression_id in expression_ids:
                        mapping = block_mapping.get(expression_id, {})
                        source_row = source_records.get(mapping.get("canonical_gene_id", "")) if mapping.get("mapping_status") == "mapped" else None
                        value = _clean(source_row.get(resolution.source_column)) if source_row else ""
                        values.append(value)
                    context[output_column] = values
                    materialized = any(value != "" for value in values)
                row = _source_provenance(source, source_sha, hash_source, resolution, {**field, "omics": omics}, output_column)
                row["registry_version"] = registry_version
                row["materialized"] = materialized
                provenance_rows.append(row)

            summary = {
                "omics": omics,
                "input_gene_count": valid_count,
                "expression_gene_count": valid_count,
                "valid_gene_count": valid_count,
                "applicable_gene_count": applicable_count,
                "exact_match_count": sum(1 for row in mapping_for_block if row["mapping_status"] == "mapped" and row["mapping_method"] == "exact_gene_id"),
                "alias_match_count": sum(1 for row in mapping_for_block if row["mapping_status"] == "mapped" and row["mapping_method"] == "gene_alias_unique"),
                "chain_match_count": sum(1 for row in mapping_for_block if row["mapping_status"] == "mapped" and "chain" in row["mapping_method"]),
                "version_stripped_match_count": sum(1 for row in mapping_for_block if row["mapping_status"] == "mapped" and row["mapping_method"] == "version_stripped_unique"),
                "ambiguous_count": sum(1 for row in mapping_for_block if row["mapping_status"] == "ambiguous"),
                "unmapped_count": sum(1 for row in mapping_for_block if row["mapping_status"] in {"unmapped", "unmapped_gene_context"}),
                "canonical_collision_count": len(collision_groups),
                "mapped_gene_count": raw_mapped_count,
                "mapped_applicable_gene_count": mapped_count,
                "raw_match_rate": raw_rate,
                "applicable_match_rate": applicable_rate,
                "gate_match_rate_used": selected_rate,
                "min_required_match_rate": min_rate,
                "min_required_mapped_genes": min_genes,
                "applicability_denominator": coding_column if omics == "proteome" and not denominator_fallback else "all_valid_expression_genes",
                "block_status": status,
                "status_reason": ";".join(dict.fromkeys(block_reason)),
                "dataset_id": getattr(source, "dataset_id", ""),
                "schema_version": getattr(source, "schema_version", ""),
                "source_sha256": source_sha,
                "hash_source": hash_source,
                "source_logical_key_or_basename": Path(source.path).name,
                "source_rows_scanned": int(stream_metrics.get("source_rows_scanned", 0)),
                "source_bytes_read": int(stream_metrics.get("source_bytes_read", 0)),
                "registered_row_count": int(getattr(source, "row_count", 0) or 0),
                "source_file_size_bytes": int(getattr(source, "file_size", 0) or 0),
                "source_file_mtime_utc": _mtime_iso(getattr(source, "file_mtime", "")),
                "runtime_seconds": round(time.perf_counter() - block_started, 6),
                "registered_core_fields": expected,
                "eligible_fields": eligible,
                "conditional_fields": conditional,
                "exclude_fields": exclude,
                "source_present_fields": source_present,
                "materialized_eligible_fields": sum(
                    1 for row in provenance_rows[-expected:]
                    if row["registry_role"] == "eligible" and row["materialized"]
                ),
                "duplicate_source_rows_removed": duplicate_source_rows,
            }
            block_details[omics] = summary
            block_status[omics] = summary
            coverage_rows.append({
                **{column: summary.get(column, "") for column in COVERAGE_COLUMNS},
                "tested_fields": 0,
                "descriptive_only_fields": 0,
                "skipped_candidate_fields": eligible,
                "significant_fields": 0,
            })
        except Exception as exc:
            reason = f"{type(exc).__name__}:{exc}"
            provenance_start = len(provenance_rows)
            for field in fields:
                field_name = str(field.get("field") or "")
                provenance_rows.append(_source_provenance(source, source_sha, hash_source, resolutions.get(field_name), {**field, "omics": omics}, canonical_context_column(omics, field_name)))
            for expression_id in expression_ids:
                mapping_rows.append({
                    "expression_gene_id": expression_id, "canonical_gene_id": "", "species_id": species_id,
                    "omics": omics, "source_entity_id": "", "mapping_method": "failed",
                    "mapping_status": "block_failed", "mapping_confidence": "none", "candidate_count": 0,
                    "collision_group": "", "exclusion_reason": "block_failed", "reason": reason,
                })
            summary = {
                "omics": omics, "input_gene_count": len(expression_ids), "valid_gene_count": len(expression_ids),
                "applicable_gene_count": 0, "mapped_gene_count": 0, "mapped_applicable_gene_count": 0,
                "raw_match_rate": 0.0, "applicable_match_rate": 0.0, "gate_match_rate_used": 0.0,
                "min_required_match_rate": float(config.get("comparison_min_block_match_rate", 0.70)),
                "min_required_mapped_genes": int(config.get("comparison_min_block_mapped_genes", 40)),
                "registered_core_fields": len(fields),
                "eligible_fields": sum(1 for item in fields if item.get("ml_role") == "eligible"),
                "conditional_fields": sum(1 for item in fields if item.get("ml_role") == "conditional"),
                "exclude_fields": sum(1 for item in fields if item.get("ml_role") == "exclude"),
                "source_present_fields": sum(1 for item in resolutions.values() if item.present),
                "materialized_eligible_fields": 0, "tested_fields": 0, "descriptive_only_fields": 0,
                "skipped_candidate_fields": sum(1 for item in fields if item.get("ml_role") == "eligible"),
                "significant_fields": 0, "block_status": "unavailable" if source is None else "failed",
                "status_reason": reason, "dataset_id": getattr(source, "dataset_id", "") if source else "",
                "schema_version": getattr(source, "schema_version", "") if source else "",
                "source_sha256": source_sha, "source_logical_key_or_basename": Path(source.path).name if source else "",
                "hash_source": hash_source,
                "source_rows_scanned": int(stream_metrics.get("source_rows_scanned", 0)),
                "source_bytes_read": int(stream_metrics.get("source_bytes_read", 0)),
                "registered_row_count": int(getattr(source, "row_count", 0) or 0) if source else 0,
                "source_file_size_bytes": int(getattr(source, "file_size", 0) or 0) if source else 0,
                "source_file_mtime_utc": _mtime_iso(getattr(source, "file_mtime", "")) if source else "",
                "runtime_seconds": round(time.perf_counter() - block_started, 6),
            }
            block_details[omics] = summary
            block_status[omics] = summary
            coverage_rows.append({column: summary.get(column, "") for column in COVERAGE_COLUMNS})
            for index in range(len(fields)):
                provenance_rows[provenance_start + index]["registry_version"] = registry_version

    # A requested block with no resolver result still has a complete audit and
    # mapping summary; no fabricated context values are written.
    for omics in requested:
        if omics in block_status:
            continue
        fields = core_by_omics[omics]
        summary = {
            "omics": omics, "input_gene_count": len(expression_ids), "valid_gene_count": len(expression_ids),
            "applicable_gene_count": len(expression_ids), "mapped_gene_count": 0, "mapped_applicable_gene_count": 0,
            "raw_match_rate": 0.0, "applicable_match_rate": 0.0, "gate_match_rate_used": 0.0,
            "min_required_match_rate": float(config.get("comparison_min_block_match_rate", 0.70)),
            "min_required_mapped_genes": int(config.get("comparison_min_block_mapped_genes", 40)),
            "registered_core_fields": len(fields),
            "eligible_fields": sum(1 for item in fields if item.get("ml_role") == "eligible"),
            "conditional_fields": sum(1 for item in fields if item.get("ml_role") == "conditional"),
            "exclude_fields": sum(1 for item in fields if item.get("ml_role") == "exclude"),
            "source_present_fields": 0, "materialized_eligible_fields": 0, "tested_fields": 0,
            "descriptive_only_fields": 0, "skipped_candidate_fields": sum(1 for item in fields if item.get("ml_role") == "eligible"),
            "significant_fields": 0, "block_status": "unavailable", "status_reason": "block_unavailable",
            "dataset_id": "", "schema_version": "", "source_sha256": "", "source_logical_key_or_basename": "",
        }
        block_details[omics] = summary
        block_status[omics] = summary
        coverage_rows.append({column: summary.get(column, "") for column in COVERAGE_COLUMNS})
        for expression_id in expression_ids:
            mapping_rows.append({
                "expression_gene_id": expression_id, "canonical_gene_id": "", "species_id": species_id,
                "omics": omics, "source_entity_id": "", "mapping_method": "none",
                "mapping_status": "block_unavailable", "mapping_confidence": "none", "candidate_count": 0,
                "collision_group": "", "exclusion_reason": "block_unavailable", "reason": "block_unavailable",
            })
        for field in fields:
            field_name = str(field.get("field") or "")
            provenance_rows.append({
                "feature_key": f"{omics}::{field_name}", "output_column": canonical_context_column(omics, field_name),
                "omics": omics, "registry_name": field_name, "registry_role": field.get("ml_role") or "exclude",
                "family": field.get("family") or "other", "applicability": field.get("applicability") or "all",
                "composition_group": field.get("composition_group") or "", "source_dataset_id": "",
                "source_logical_key_or_basename": "", "source_sha256": "", "source_column": "",
                "hash_source": "", "source_present": False, "materialized": False, "resolution_method": "unresolved",
                "registry_version": registry_version, "builder_version": BUILDER_VERSION,
            })

    for row in provenance_rows:
        if not row.get("registry_version"):
            row["registry_version"] = registry_version
        if not row.get("builder_version"):
            row["builder_version"] = BUILDER_VERSION
    provenance = pd.DataFrame(provenance_rows, columns=PROVENANCE_COLUMNS)
    mapping = pd.DataFrame(mapping_rows, columns=MAPPING_COLUMNS)
    coverage = pd.DataFrame(coverage_rows, columns=COVERAGE_COLUMNS)
    context = context.drop_duplicates(subset=["gene_id"], keep=False) if context["gene_id"].duplicated().any() else context

    # The six context/audit files are all job-scoped and written atomically.
    _atomic_write_csv(output / ARTIFACT_NAMES["context"], context)
    _atomic_write_csv(output / ARTIFACT_NAMES["provenance"], provenance, PROVENANCE_COLUMNS)
    _atomic_write_csv(output / ARTIFACT_NAMES["mapping"], mapping, MAPPING_COLUMNS)
    _atomic_write_csv(output / ARTIFACT_NAMES["block_coverage"], coverage, COVERAGE_COLUMNS)
    mapping_summary = {
        "status": "ready" if all(block_status[item]["block_status"] == "ready" for item in requested) else "partial" if any(block_status[item]["block_status"] in {"ready", "partial"} for item in requested) else "unavailable",
        "builder_version": BUILDER_VERSION,
        "registry_version": registry_version,
        "registry_sha256": registry_sha,
        "requested_omics": requested,
        "blocks": block_details,
        "performance": _performance_payload(block_details, context),
        "runtime_seconds": round(time.perf_counter() - started, 6),
    }
    _atomic_write_text(output / ARTIFACT_NAMES["mapping_summary"], json.dumps(_json_safe(mapping_summary), ensure_ascii=False, indent=2))

    usable = [omics for omics in requested if block_status[omics]["block_status"] in {"ready", "partial"}]
    overall_status = "ready" if len(usable) == len(requested) and all(block_status[item]["block_status"] == "ready" for item in requested) else "partial" if usable else "failed" if any(block_status[item]["block_status"] == "failed" for item in requested) else "unavailable"
    manifest = {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "comparison_schema_version": COMPARISON_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "registry_version": registry_version,
        "registry_sha256": registry_sha,
        "registry_snapshot": registry_path.name,
        "status": overall_status,
        "species_id": species_id,
        "requested_omics": requested,
        "available_omics": usable,
        "config": _public_config(config),
        "artifacts": {key: value for key, value in ARTIFACT_NAMES.items()},
        "context_rows": int(context.shape[0]),
        "context_columns": int(context.shape[1]),
        "performance": _performance_payload(block_details, context),
        "block_status": block_status,
        "started_at_utc": _utc_now(),
        "runtime_seconds": round(time.perf_counter() - started, 6),
    }
    _atomic_write_text(output / ARTIFACT_NAMES["assembly_manifest"], json.dumps(_json_safe(manifest), ensure_ascii=False, indent=2))

    # Keep coverage counts ready for the comparison runner to update after QC.
    return {
        "status": overall_status,
        "comparison_input_csv": str((output / ARTIFACT_NAMES["context"]).resolve()),
        "mapping_summary_json": str((output / ARTIFACT_NAMES["mapping_summary"]).resolve()),
        "feature_provenance_csv": str((output / ARTIFACT_NAMES["provenance"]).resolve()),
        "mapping_table_csv": str((output / ARTIFACT_NAMES["mapping"]).resolve()),
        "assembly_manifest_json": str((output / ARTIFACT_NAMES["assembly_manifest"]).resolve()),
        "block_coverage_csv": str((output / ARTIFACT_NAMES["block_coverage"]).resolve()),
        "block_status": block_status,
        "requested_omics": requested,
        "available_omics": usable,
    }
