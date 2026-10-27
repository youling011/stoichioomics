from __future__ import annotations
import csv
import hashlib
import numpy as np
import pandas as pd
from ..feature_hub.sources import DatasetSourceResolver
from .contracts import digest

ALGORITHM = "whole-original-core-finite-v1"


def scan_core(species_id, omics, fields, chunksize=50000):
    source = DatasetSourceResolver().resolve(species_id, omics, "core")
    before = source.path.stat()
    numeric = [r for r in fields if r["role"] == "numeric"]
    metadata = [r for r in fields if r["role"] == "metadata"]
    expected = {r["field"] for r in fields}
    import gzip
    opener = gzip.open if source.path.suffix.lower() == ".gz" else open
    with opener(source.path, "rt", encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle), [])
    if len(header) != len(set(header)) or set(header) != expected:
        raise ValueError(f"{species_id}/{omics}: missing, extra, or duplicate Core columns.")
    states = {r["field"]: {"n_valid": 0, "n_missing": 0, "n_zero": 0,
                           "first": None, "variable": False} for r in numeric}
    meta_counts = {r["field"]: 0 for r in metadata}
    primary = {"genome": "gene_id", "transcriptome": "transcript_id", "proteome": "protein_id"}[omics]
    seen = set()
    total = 0
    for chunk in pd.read_csv(source.path, dtype=str, keep_default_na=False, na_filter=False, chunksize=chunksize):
        keys = chunk[primary].str.strip().tolist()
        if any(not key for key in keys) or len(set(keys)) != len(keys) or any(key in seen for key in keys):
            raise ValueError(f"{species_id}/{omics}: empty or duplicate primary key.")
        seen.update(keys)
        total += len(chunk)
        for field in meta_counts:
            meta_counts[field] += int(chunk[field].str.strip().ne("").sum())
        for field, state in states.items():
            values = pd.to_numeric(chunk[field], errors="coerce").to_numpy(dtype=float)
            values = values[np.isfinite(values)]
            state["n_valid"] += len(values)
            state["n_missing"] += len(chunk) - len(values)
            state["n_zero"] += int((values == 0).sum())
            if len(values):
                if state["first"] is None:
                    state["first"] = float(values[0])
                if np.any(values != state["first"]):
                    state["variable"] = True
    if total != source.row_count:
        raise ValueError(f"{species_id}/{omics}: actual rows {total} differ from registered {source.row_count}.")
    profiles = []
    for field in numeric:
        state = states[field["field"]]
        label = "empty" if state["n_valid"] == 0 else "variable" if state["variable"] else "constant"
        profiles.append({**field, "n_source": total, **{k: state[k] for k in ("n_valid", "n_missing", "n_zero")},
                         "state": label, "n_unique_capped_at_2": 0 if label == "empty" else 2 if label == "variable" else 1})
    meta_profiles = [{**field, "n_source": total, "n_nonempty": meta_counts[field["field"]],
                      "n_missing": total - meta_counts[field["field"]]} for field in metadata]
    h = hashlib.sha256()
    with source.path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(block)
    after = source.path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"{species_id}/{omics}: source changed during scan.")
    return {"algorithm_version": ALGORITHM, "species_id": species_id, "omics": omics,
            "n_rows": total, "n_numeric": len(numeric), "n_metadata": len(metadata),
            "constant_count": sum(r["state"] == "constant" for r in profiles),
            "variable_count": sum(r["state"] == "variable" for r in profiles),
            "empty_count": sum(r["state"] == "empty" for r in profiles),
            "missing_numeric_cells": sum(r["n_missing"] for r in profiles),
            "profiles": profiles, "metadata_profiles": meta_profiles,
            "schema_digest": digest(fields), "source_sha256": h.hexdigest(),
            "source_bytes": after.st_size, "source_mtime_ns": after.st_mtime_ns,
            "source_path": str(source.path), "schema_version": source.schema_version}
