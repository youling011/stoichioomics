from __future__ import annotations
from backend.apps.common.artifact_locations import locate,read_roots,contained,budget_cache
from backend.apps.stoichdb.feature_sources import io as feature_io
import json
import os
from functools import lru_cache
from django.conf import settings
from backend.apps.common.host_paths import Path
from ..storage_objects import root_for_alias
from .contracts import digest

RESOURCE_ROOT = Path(settings.BASE_DIR) / "backend/apps/stoichdb/resources"


def artifact_root(override=None):
    return Path(override) if override else Path(root_for_alias("STOICH_RUNTIME_ROOT")) / "home_atlas_visuals/v1"


def resource(name):
    return json.loads((RESOURCE_ROOT / name).read_text(encoding="utf-8-sig"))


def manifest(root=None):
    base=artifact_root(root)
    location=locate('home_atlas',base,'manifest.json',required=False) if root is None else None
    path=location.target if location else base/'manifest.json'
    if not feature_io.source_available(path):return {'version':'not_built','cohort':resource('home_atlas_cohort_v1.json'),'entries':{}}
    return json.loads(path.read_text(encoding='utf-8'))


def signature(root=None):
    """Only stat source files; HTTP requests never read raw source CSV contents."""
    base = artifact_root(root)
    location=locate("home_atlas",base,"manifest.json",required=False) if root is None else None
    path=location.target if location else base / "manifest.json"
    if not feature_io.source_available(path):
        return "not_built"
    try:
        state = manifest(root)
        parts = [feature_io.source_metadata(path).mtime_ns, feature_io.source_metadata(path).size]
        for key, entry in sorted(state["entries"].items()):
            try:
                stat = feature_io.source_metadata(Path(entry["source_path"]))
                parts.append([key, stat.size, stat.mtime_ns])
            except OSError:
                parts.append([key, "unreadable"])
        return digest(parts)
    except (OSError, ValueError, KeyError):
        try:
            return digest(["unreadable_manifest", feature_io.source_metadata(path).size, feature_io.source_metadata(path).mtime_ns])
        except OSError:
            return "unavailable"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if feature_io.source_exists(temp):
            temp.unlink()


@budget_cache('')
def _read_object(filename, expected_hash):
    path = Path(filename)
    raw = path.read_bytes()
    import hashlib
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("Diagnostic artifact checksum mismatch.")
    return json.loads(raw)


def diagnostic(entry,root=None):
    relative='diagnostics/objects/'+entry['object_file']
    p=contained(artifact_root(root),relative) if root is not None else locate('home_atlas',artifact_root(),relative).target
    return _read_object(str(p),entry['object_sha256'])


def source_state(entry, dataset, schema_digest):
    if not entry:
        return "unavailable", "not_precomputed"
    if not dataset:
        return "unavailable", "dataset_not_registered"
    if (entry.get("registered_core_path") != dataset["core_csv_path"]
            or entry.get("schema_version") != dataset["schema_version"]
            or entry.get("n_rows") != dataset["row_count_core"]
            or entry.get("schema_digest") != schema_digest):
        return "stale", "registered_source_or_schema_changed"
    if str(dataset["status"]).lower() != "ready":
        return "unavailable", "registered_dataset_not_ready"
    try:
        stat = feature_io.source_metadata(Path(entry["source_path"]))
    except OSError:
        return "unavailable", "source_not_readable"
    if stat.size != entry["source_bytes"] or stat.mtime_ns != entry["source_mtime_ns"]:
        return "stale", "source_signature_changed"
    return "ready", None
