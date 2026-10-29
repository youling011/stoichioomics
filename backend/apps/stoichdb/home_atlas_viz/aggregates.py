from __future__ import annotations
from backend.apps.stoichdb.feature_sources import io as feature_io
from collections import Counter, OrderedDict
import copy
import math
import threading
import time
from django.utils.timezone import now
from . import artifacts
from .contracts import (FAMILIES, GROUPS, OMICS, PATTERNS, VERSION, card, digest,
                        family, group_name, group_order, ignored_filters, normalize_filters)
from .distribution import distributions
from .scope import snapshot

_CACHE = OrderedDict()
_LOCK = threading.RLock()
TTL = 60


def clear_visuals_cache():
    with _LOCK:
        _CACHE.clear()


def registered_fields(schemas):
    known = artifacts.resource("home_atlas_fields_v1.json")["fields"]
    lookup = {(r["omics"], r["field"]): r for r in known}
    result, warnings = [], []
    for omics in OMICS:
        versions = [s for s in schemas if s["omics_type"] == omics]
        names = {}
        definitions = set()
        for schema in versions:
            current = {}
            for column in schema["columns_json"]:
                name = column if isinstance(column, str) else column.get("name") or column.get("field")
                if name:
                    current[name] = column if isinstance(column, dict) else {}
                    names[name] = current[name]
            definitions.add(tuple(sorted(current)))
        if len(definitions) > 1:
            warnings.append(f"{omics}: conflicting registered Core schema versions; union disclosed.")
        if not versions:
            warnings.append(f"{omics}: no registered Core schema.")
            continue
        for name, definition in names.items():
            if (omics, name) in lookup:
                result.append(dict(lookup[(omics, name)]))
            else:
                dtype = str(definition.get("type", definition.get("dtype", ""))).lower()
                role = "numeric" if any(x in dtype for x in ("int", "float", "double", "numeric", "number")) else "metadata"
                result.append({"omics": omics, "field": name, "field_id": f"{omics}__{name}",
                               "role": role, "display_family": family(name, omics, role)})
                warnings.append(f"{omics}/{name}: new column classified from registered type.")
    result.sort(key=lambda r: (OMICS.index(r["omics"]), r["field_id"]))
    return result, warnings


def ready(dataset):
    return bool(dataset and dataset["row_count_core"] > 0 and str(dataset["core_csv_path"] or "").strip()
                and str(dataset["status"]).lower() in {"ready", "complete", "ok"})


def budgets(species, datasets):
    by_id = {r["id"]: r for r in species}
    rows = []
    for group in group_order(r["domain"] for r in species):
        ids = {r["id"] for r in species if group_name(r["domain"]) == group}
        layers = {}
        for omics in OMICS:
            selected = [d for d in datasets if d["species_id"] in ids and d["omics_type"] == omics]
            count = sum(ready(d) for d in selected)
            layers[omics] = {"record_count_core": sum(d["row_count_core"] for d in selected),
                             "ready_species": count, "coverage_pct": 100 * count / len(ids) if ids else None,
                             "n_datasets": len(selected)}
        rows.append({"group": group, "species_count": len(ids), "layers": layers})
    total = {"species_count": len(species), "layers": {}}
    for omics in OMICS:
        count = sum(r["layers"][omics]["ready_species"] for r in rows)
        total["layers"][omics] = {"record_count_core": sum(r["layers"][omics]["record_count_core"] for r in rows),
                                  "ready_species": count, "coverage_pct": 100 * count / len(species) if species else None,
                                  "n_datasets": sum(r["layers"][omics]["n_datasets"] for r in rows)}
    return rows, total


def membership(species, datasets):
    index = {(r["species_id"], r["omics_type"]): r for r in datasets}
    core, full = Counter(), Counter()
    for row in species:
        ds = [index.get((row["id"], m)) for m in OMICS]
        core[sum(ready(d) for d in ds)] += 1
        full["".join("1" if d and str(d["full_csv_path"] or "").strip() else "0" for d in ds)] += 1
    return {"core_ready_counts": [{"n_ready_layers": k, "n_species": core[k]} for k in range(4)],
            "full_patterns": [{"pattern": p, "n_species": full[p]} for p in PATTERNS],
            "full_basis": "registered_nonempty_path"}


def completeness(datasets, evidence):
    selected = {d["id"]: d for d in datasets}
    latest = {}
    duplicates = 0
    for item in evidence:
        if item["dataset_id"] in selected:
            if item["dataset_id"] in latest:
                duplicates += 1
            else:
                latest[item["dataset_id"]] = item
    sources, layers = Counter(), []
    valid = 0
    for omics in OMICS:
        counts, header, unavailable, total = Counter(), 0, 0, 0
        for dataset in datasets:
            if dataset["omics_type"] != omics:
                continue
            total += 1
            artifact = latest.get(dataset["id"])
            method = (artifact or {}).get("payload_json__source_method") or "no_artifact"
            sources[(omics, method)] += 1
            missing = (artifact or {}).get("payload_json__missing_cells")
            if method == "core_csv_header_plus_summary_missingness" and isinstance(missing, int) and not isinstance(missing, bool) and missing >= 0:
                counts[missing] += 1
                valid += 1
            elif method == "core_csv_header_presence_fallback":
                header += 1
                valid += 1
            else:
                unavailable += 1
        n = sum(counts.values())
        cumulative = 0
        ecdf = {"x_missing_cells": [], "frequency": [], "cdf": []} if n else None
        for value, frequency in sorted(counts.items()):
            cumulative += frequency
            ecdf["x_missing_cells"].append(value)
            ecdf["frequency"].append(frequency)
            ecdf["cdf"].append(cumulative / n)
        layers.append({"omics": omics, "n_assessments": total, "n_summary": n,
                       "n_header_only": header, "n_unavailable": unavailable, "ecdf": ecdf})
    return {"source_counts": [{"omics": m, "source_method": method, "n_datasets": n}
                              for (m, method), n in sorted(sources.items())],
            "layers": layers, "duplicate_artifacts": duplicates}, valid


def cohort_diagnostics(species, datasets, fields, root=None, state_override=None):
    manifest_error = None
    try:
        state = state_override if state_override is not None else artifacts.manifest(root)
        if not isinstance(state["entries"], dict) or not isinstance(state["cohort"]["species"], list):
            raise ValueError("Invalid diagnostic manifest structure")
        if any(not all(k in r for k in ("sid", "species_id", "group")) for r in state["cohort"]["species"]):
            raise ValueError("Invalid cohort member")
    except (OSError, ValueError, KeyError, TypeError):
        manifest_error = "diagnostic_manifest_unreadable"
        state = {"version": "unavailable", "cohort": artifacts.resource("home_atlas_cohort_v1.json"), "entries": {}}
    ids = {r["species_id"] for r in species}
    pk = {r["id"]: r["species_id"] for r in species}
    ds = {(pk[d["species_id"]], d["omics_type"]): d for d in datasets}
    cohort = state["cohort"]
    members = [r for r in cohort["species"] if r["species_id"] in ids]
    cells = []
    for member in members:
        for omics in OMICS:
            entry = state["entries"].get(f'{member["species_id"]}__{omics}')
            expected = digest([r for r in fields if r["omics"] == omics])
            status, reason = artifacts.source_state(entry, ds.get((member["species_id"], omics)), expected)
            if manifest_error:
                status, reason = "unavailable", manifest_error
            cell = {**member, "omics": omics, "status": status, "reason": reason,
                    **{k: None for k in ("n_rows", "n_numeric", "constant_count", "variable_count", "empty_count",
                                         "missing_numeric_cells", "source_sha256", "artifact_version")}}
            if status == "ready":
                try:
                    obj = artifacts.diagnostic(entry, root)
                    cell["artifact_id"] = entry["object_sha256"]
                    cell.update({k: obj[k] for k in ("n_rows", "n_numeric", "constant_count", "variable_count",
                                                     "empty_count", "missing_numeric_cells", "source_sha256")})
                    cell["artifact_version"] = obj["algorithm_version"]
                except (OSError, ValueError, KeyError):
                    cell.update(status="unavailable", reason="artifact_unreadable_or_checksum_mismatch")
            cells.append(cell)
    return {"cohort": {"manifest_version": cohort["version"], "total_named_species": len(cohort["species"]),
                        "n_context_matched": len(members), "members": members},
            "cells": cells, "manifest_version": state["version"]}


def build_payload(kind, params=None, root=None, use_cache=True, diagnostic_state=None):
    params = params or {}
    filters = normalize_filters({} if kind == "home" else params)
    token = digest(diagnostic_state) if diagnostic_state is not None else artifacts.signature(root)
    key = digest([kind, filters, token, str(root or ""), artifacts.resource("home_atlas_fields_v1.json")])
    with _LOCK:
        cached = _CACHE.get(key)
        if use_cache and cached and time.monotonic() - cached[0] < TTL:
            base = cached[1]
        else:
            snap = snapshot({} if kind == "home" else params)
            fields, schema_warnings = registered_fields(snap["schemas"])
            species = snap["species"] if kind == "home" else [r for r in snap["species"] if r["id"] in snap["ids"]]
            pks = {r["id"] for r in species}
            datasets = [d for d in snap["datasets"] if d["species_id"] in pks]
            revision = digest([snap["source_revision"], token, fields])
            scope_id = digest([snap["filters"], [r["species_id"] for r in species], revision])
            meta = {"contract_version": VERSION, "scope_kind": "registry" if kind == "home" else "registry_context",
                    "scope_id": scope_id, "source_revision": revision, "applied_filters": snap["filters"],
                    "group_order": group_order(r["domain"] for r in species), "omics_order": list(OMICS),
                    "schema_digest": digest(fields), "generated_at": now().isoformat()}
            rows, total = budgets(species, datasets)
            cards = {}
            if kind == "home":
                groups = [{"group": r["group"], "species_count": r["species_count"],
                           "share_pct": 100 * r["species_count"] / len(species)} for r in rows]
                cards["H1"] = card("H1", {"total_species": len(species), "groups": groups}, meta, "species",
                                   len(species), method="count_registered_species_by_platform_group")
                links = [{"group": r["group"], "omics": m, "registered_core_rows": r["layers"][m]["record_count_core"]}
                         for r in rows for m in OMICS]
                cards["H2"] = card("H2", {"n_datasets": len(datasets), "links": links,
                    "source_totals": {r["group"]: sum(r["layers"][m]["record_count_core"] for m in OMICS) for r in rows},
                    "target_totals": {m: total["layers"][m]["record_count_core"] for m in OMICS},
                    "total_core_records": sum(d["row_count_core"] for d in datasets)}, meta, "datasets",
                    len(datasets), method="sum_registered_core_rows")
                counts = Counter((r["display_family"], r["omics"]) for r in fields)
                cards["H3"] = card("H3", {"fields": fields, "family_order": list(FAMILIES),
                    "cells": [{"family": f, "omics": m, "field_count": counts[(f, m)]} for f in FAMILIES for m in OMICS],
                    "column_counts": dict(Counter(r["omics"] for r in fields)), "schema_digest": digest(fields)},
                    meta, "raw_core_columns", len(fields), method="mutually_exclusive_original_column_families",
                    evidence="registered_schema", status="partial" if schema_warnings else None,
                    warnings=schema_warnings, complete=not schema_warnings)
            else:
                cards["D1"] = card("D1", {"rows": rows, "all_groups": total, "n_datasets": len(datasets)}, meta,
                                   "species", len(species), method="registered_rows_and_separate_ready_species")
                rain = distributions(species)
                cards["D2"] = card("D2", {"groups": rain}, meta, "species", len(species),
                    n_valid=sum(r["n_valid"] for r in rain), method="all_positive_Mb_log10_Scott_KDE_240_linear_quantiles")
                cards["D3"] = card("D3", membership(species, datasets), meta, "species", len(species),
                                   method="all_eight_registered_full_path_intersections")
                evidence, n_valid = completeness(datasets, snap["artifacts"])
                warnings = ([f'{evidence["duplicate_artifacts"]} duplicate artifact rows resolved deterministically.']
                            if evidence["duplicate_artifacts"] else [])
                if n_valid < len(datasets):
                    warnings.append(f"{len(datasets) - n_valid} assessments have absent, unknown, or invalid numeric evidence.")
                cards["D4"] = card("D4", evidence, meta, "datasets", len(datasets), n_valid=n_valid,
                    method="exact_frequency_ECDF_of_cached_summary_missing_cells", evidence="cached_completeness_evidence",
                    status="partial" if n_valid < len(datasets) else None, warnings=warnings)
                diagnostics = cohort_diagnostics(species, datasets, fields, root, diagnostic_state)
                n_valid = sum(r["status"] == "ready" for r in diagnostics["cells"])
                n_source = len(diagnostics["cells"])
                cards["D5"] = card("D5", diagnostics, meta, "core_tables", n_source, n_valid=n_valid,
                    method="whole_original_core_finite_cell_profiles", evidence="whole_core_scan",
                    status="partial" if n_valid < n_source else None,
                    complete=n_valid == n_source, warnings=[r["reason"] for r in diagnostics["cells"] if r["reason"]])
                meta["cohort_manifest_version"] = diagnostics["cohort"]["manifest_version"]
                # Layout-only schema counts retain the old card's typography budget, not D5 statistics.
                from ..services import _atlas_core_field_counts
                meta["legacy_layout_field_counts"] = _atlas_core_field_counts()
            base = {"meta": meta, "cards": cards}
            if use_cache:
                _CACHE[key] = (time.monotonic(), base)
                while len(_CACHE) > 32:
                    _CACHE.popitem(last=False)
    return {"meta": {**base["meta"], "ignored_for_context": ignored_filters(params)}, "cards": base["cards"]}
