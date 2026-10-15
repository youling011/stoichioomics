from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.apps.stoichdb.models import EntityRecord

from . import METHOD_VERSION
from .datasource import CompleteCoreDataSource
from .aggregates import correlation, correlation_matrix, deterministic_sample, distribution_stats, histogram, safe_num


def build_complete_cross_omics_payload(species_id: str, base_payload: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "genome": ("exon_atoms_N_per_base", "exon_gc_percent", "promoter_gc_percent", "promoter_exon_gc_delta", "gc_delta_promoter_minus_exon"),
        "transcriptome": ("atoms_per_nt_N", "gc_content", "gc_percent_display", "N_P_ratio", "protein_gravy_proxy", "protein_gravy", "protein_instability_index", "protein_isoelectric_point"),
        "proteome": ("N_atoms_per_aa", "pI", "protein_isoelectric_point", "gravy", "instability_index", "S_atoms_per_aa"),
    }
    gene_map, counts, source_meta = _build_gene_map_from_csv(species_id, fields)
    if not gene_map or not any(counts.values()):
        gene_map, counts, source_meta = _build_gene_map_from_entity_records(species_id, fields)
    rows = []
    for gene_id, entry in gene_map.items():
        has_g = bool(entry.get("genome_entity_id"))
        has_t = bool(entry.get("transcriptome_entity_id"))
        has_p = bool(entry.get("proteome_entity_id"))
        if not (has_g or has_t or has_p):
            continue
        row = dict(entry)
        g_n = safe_num(row.get("genome_exon_atoms_N_per_base"))
        t_n = safe_num(row.get("transcriptome_atoms_per_nt_N"))
        p_n = safe_num(row.get("proteome_N_atoms_per_aa"))
        if g_n is not None and t_n is not None:
            row["dna_to_rna_n_shift"] = float(t_n) - float(g_n)
        if t_n is not None and p_n is not None:
            row["rna_to_protein_n_shift"] = float(p_n) - float(t_n)
        exon_gc = safe_num(row.get("genome_exon_gc_percent"))
        transcript_gc = safe_num(row.get("transcriptome_gc_content"))
        if transcript_gc is None:
            transcript_gc = safe_num(row.get("transcriptome_gc_percent_display"))
        if exon_gc is not None and transcript_gc is not None:
            row["dna_to_rna_gc_delta"] = float(transcript_gc) - float(exon_gc)
        rows.append(row)
    _standardize(rows, "dna_to_rna_n_shift", "dna_to_rna_n_shift_std")
    _standardize(rows, "rna_to_protein_n_shift", "rna_to_protein_n_shift_std")
    _score_candidates(rows)

    g_ids = {k for k, v in gene_map.items() if v.get("genome_entity_id")}
    t_ids = {k for k, v in gene_map.items() if v.get("transcriptome_entity_id")}
    p_ids = {k for k, v in gene_map.items() if v.get("proteome_entity_id")}
    all_three = g_ids & t_ids & p_ids
    g_t = g_ids & t_ids
    t_p = t_ids & p_ids
    join = {
        "genome_n": counts["genome"],
        "transcript_n": counts["transcriptome"],
        "protein_n": counts["proteome"],
        "gene_key_n": len(gene_map),
        "matched_genome_transcript": len(g_t),
        "matched_transcript_protein": len(t_p),
        "matched_all_three": len(all_three),
        "match_rate_all_three": round(len(all_three) / max(1, len(g_ids | t_ids | p_ids)), 6),
    }
    shift_rows = [row for row in rows if safe_num(row.get("dna_to_rna_n_shift_std")) is not None or safe_num(row.get("rna_to_protein_n_shift_std")) is not None]
    scatter = deterministic_sample([_point(row, ("dna_to_rna_n_shift_std", "rna_to_protein_n_shift_std")) for row in shift_rows], 5000)
    scatter = [row for row in scatter if row]
    quadrants = _quadrants(shift_rows)
    x2 = _scatter(rows, "genome_exon_gc_percent", "transcriptome_gc_content")
    x3_n = _scatter(rows, "transcriptome_gc_content", "proteome_N_atoms_per_aa")
    x3_pi = _scatter(rows, "transcriptome_gc_content", "proteome_pI")
    x3_gravy = _scatter(rows, "transcriptome_gc_content", "proteome_gravy")
    ranked = sorted([row for row in rows if safe_num(row.get("candidate_score")) is not None], key=lambda r: safe_num(r.get("candidate_score")) or 0.0, reverse=True)
    corr_fields = [
        "genome_exon_atoms_N_per_base", "genome_exon_gc_percent", "transcriptome_atoms_per_nt_N",
        "transcriptome_gc_content", "proteome_N_atoms_per_aa", "proteome_pI", "proteome_gravy",
    ]
    corr_fields = [field for field in corr_fields if any(safe_num(row.get(field)) is not None for row in rows)]
    heatmap, edges = correlation_matrix(rows, corr_fields)
    shared_counts = _shared_outlier_counts(rows)
    transition_links = _transition_links(rows)
    fingerprint = {
        "match_rate_all_three": join["match_rate_all_three"],
        "dna_to_rna_n_shift_mean": distribution_stats([safe_num(r.get("dna_to_rna_n_shift_std")) for r in rows]).get("mean"),
        "rna_to_protein_n_shift_mean": distribution_stats([safe_num(r.get("rna_to_protein_n_shift_std")) for r in rows]).get("mean"),
        "proteome_n_per_aa": distribution_stats([safe_num(r.get("proteome_N_atoms_per_aa")) for r in rows]).get("mean"),
        "proteome_pi": distribution_stats([safe_num(r.get("proteome_pI")) for r in rows]).get("mean"),
    }
    modules = [
        {"id": "X0", "name": "Cross-omics matched coverage", "status": "implemented", "match_coverage_rows": [
            {"name": "Genome", "value": counts["genome"]}, {"name": "Transcriptome", "value": counts["transcriptome"]},
            {"name": "Proteome", "value": counts["proteome"]}, {"name": "All three", "value": len(all_three)},
        ], "match_rate_rows": [
            {"name": "Genome-Transcript", "value": len(g_t) / max(1, len(g_ids | t_ids))},
            {"name": "Transcript-Protein", "value": len(t_p) / max(1, len(t_ids | p_ids))},
            {"name": "All three", "value": join["match_rate_all_three"]},
        ], "method": "complete canonical_gene_id chain coverage"},
        {"id": "X1", "name": "DNA-RNA-protein resource shift", "status": "implemented", "shift_histograms": {
            "dna_to_rna_n_std": histogram([safe_num(r.get("dna_to_rna_n_shift_std")) for r in rows], 42),
            "rna_to_protein_n_std": histogram([safe_num(r.get("rna_to_protein_n_shift_std")) for r in rows], 42),
        }, "shift_scatter": scatter, "shift_scatter_meta": _scatter_meta(rows, scatter), "quadrants": quadrants, "candidate_table": ranked[:120], "method": "full chain robust-z shifts"},
        {"id": "X2", "name": "DNA-RNA GC consistency", "status": "implemented" if x2 else "limited", "exon_transcript_gc_scatter": x2, "exon_transcript_gc_scatter_meta": _scatter_meta(rows, x2), "residual_candidates": ranked[:120]},
        {"id": "X3", "name": "Translation discordance", "status": "implemented", "gc_protein_n_scatter": x3_n, "gc_pi_scatter": x3_pi, "gc_gravy_scatter": x3_gravy, "gc_protein_n_scatter_meta": _scatter_meta(rows, x3_n), "gc_pi_scatter_meta": _scatter_meta(rows, x3_pi), "gc_gravy_scatter_meta": _scatter_meta(rows, x3_gravy), "discordance_candidates": ranked[:120]},
        {"id": "X4", "name": "Predicted-observed residuals", "status": "limited", "residual_scatter": _scatter(rows, "proteome_pI", "candidate_score"), "candidate_table": ranked[:120], "missing_fields": ["transcript_protein_pi model coefficients"]},
        {"id": "X5", "name": "Shared outlier overlap", "status": "implemented", "shared_outlier_counts": shared_counts, "candidate_table": ranked[:120]},
        {"id": "X6", "name": "Cross-omics coupling matrix", "status": "implemented" if heatmap.get("values") else "limited", "correlation_heatmap": heatmap, "edge_ranking": edges[:50]},
        {"id": "X7", "name": "Species-level cross-omics fingerprint", "status": "implemented", "fingerprint": fingerprint, "feature_ranking": [{"feature": k, "value": v} for k, v in fingerprint.items()], "species_pca": _single_species_fingerprint_projection(species_id, fingerprint), "distance_matrix": _fingerprint_feature_distance_matrix(fingerprint)},
        {"id": "X8", "name": "Integrated candidate dashboard", "status": "implemented", "candidate_table": ranked[:120], "score_components": ["abs_dna_rna_shift", "abs_rna_protein_shift", "abs_gc_delta"]},
    ]
    payload = dict(base_payload or {})
    payload.update({
        "compute_mode": "complete_core",
        "method_version": METHOD_VERSION,
        "join_summary": join,
        "fingerprint": fingerprint,
        "top_transformations": ranked[:120],
        "transformations": ranked[:120],
        "correlation_matrix": heatmap,
        "correlation_matrices": {"pearson": heatmap},
        "cluster_transition_links": transition_links,
        "cross_omics_module_suite": {
            "scope": "complete_core",
            "row_count": len(rows),
            "matched_all_three": len(all_three),
            "modules": modules,
            "method_metadata": {
                "method": "complete canonical gene-chain computation",
                "method_version": METHOD_VERSION,
                "aggregation_scope": source_meta.get("aggregation_scope", "all_available_complete_core_gene_chains"),
                "n_source_rows": counts,
                "n_chain_rows": len(rows),
                "source_meta": source_meta,
                "display_policy": "statistics use all chains; point/table payloads are deterministic display subsets",
            },
        },
        "method_metadata": {
            **(payload.get("method_metadata") if isinstance(payload.get("method_metadata"), dict) else {}),
            "complete_core_v2": {
                "method": "complete canonical gene-chain computation",
                "method_version": METHOD_VERSION,
                "source_scope": source_meta.get("source_scope", "core CSV"),
                "n_source_rows": counts,
                "source_meta": source_meta,
                "n_chain_rows": len(rows),
                "n_all_three": len(all_three),
                "sampling_policy": "deterministic display sampling only",
            },
        },
    })
    payload["module_suite"] = payload["cross_omics_module_suite"]
    return payload


def _build_gene_map_from_csv(species_id: str, fields: dict[str, tuple[str, ...]]) -> tuple[dict[str, dict[str, Any]], dict[str, int], dict[str, Any]]:
    accum: dict[str, dict[str, Any]] = {}
    counts = {"genome": 0, "transcriptome": 0, "proteome": 0}
    source_details: dict[str, Any] = {}
    row_infos: list[tuple[str, tuple[str, ...], dict[str, Any], tuple[str, ...]]] = []
    parents: dict[str, str] = {}
    alias_groups: dict[str, set[str]] = defaultdict(set)

    for omics, wanted in fields.items():
        try:
            source = CompleteCoreDataSource(species_id, omics)
            rows, meta = source.rows(fields=wanted, optional_full_fields=wanted)
        except Exception as exc:
            source_details[omics] = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
            continue
        counts[omics] = len(rows)
        source_details[omics] = {
            "status": "readable",
            "row_count_source": len(rows),
            "source_scope": meta.get("source_scope"),
            "full_supplement_used": meta.get("full_supplement_used"),
            "optional_full_fields_used": meta.get("optional_full_fields_used"),
            "missing_optional_full_fields": meta.get("missing_optional_full_fields"),
            "full_join_match_n": meta.get("full_join_match_n"),
            "manifest": meta.get("manifest"),
        }
        for row in rows:
            keys = _gene_keys(row, omics)
            if not keys:
                continue
            for key in keys:
                parents.setdefault(key, key)
            first = keys[0]
            for key in keys[1:]:
                _union_gene_key(parents, first, key)
            row_infos.append((omics, wanted, row, keys))

    for _, _, _, keys in row_infos:
        rep = _find_gene_key(parents, keys[0])
        alias_groups[rep].update(keys)
    canonical_by_rep = {rep: _choose_gene_key(aliases) for rep, aliases in alias_groups.items()}

    for omics, wanted, row, keys in row_infos:
        rep = _find_gene_key(parents, keys[0])
        gene_id = canonical_by_rep.get(rep) or keys[0]
        entry = accum.setdefault(gene_id, {"canonical_gene_id": gene_id, "_sums": defaultdict(float), "_ns": defaultdict(int), "_aliases": set()})
        entry["_aliases"].update(alias_groups.get(rep, set(keys)))
        entry[f"{omics}_entity_id"] = entry.get(f"{omics}_entity_id") or row.get("entity_id") or row.get("gene_id") or row.get("transcript_id") or row.get("protein_id")
        entry[f"{omics}_cluster"] = entry.get(f"{omics}_cluster") or row.get("strategy_cluster")
        for field in wanted:
            value = _csv_value(row, omics, field)
            if value is not None:
                key = _prefixed_field(omics, _canonical_field_name(omics, field))
                entry["_sums"][key] += float(value)
                entry["_ns"][key] += 1

    gene_map: dict[str, dict[str, Any]] = {}
    for gene_id, entry in accum.items():
        out = {key: value for key, value in entry.items() if key not in {"_sums", "_ns", "_aliases"}}
        out["gene_alias_n"] = len(entry.get("_aliases") or ())
        for key, total in entry["_sums"].items():
            n = entry["_ns"].get(key) or 0
            if n:
                out[key] = round(float(total) / n, 6)
        gene_map[gene_id] = out
    return gene_map, counts, {
        "source_scope": "core CSV with optional Full field supplement",
        "aggregation_scope": "all_available_complete_core_csv_gene_chains_alias_resolved",
        "gene_key_policy": "union all non-empty canonical_gene_id/gene_id/ensembl_gene_id aliases observed in each CSV row; transcript/protein isoforms are averaged per resolved gene before cross-omics joins",
        "n_gene_alias_groups": len(alias_groups),
        "source_details": source_details,
    }


def _build_gene_map_from_entity_records(species_id: str, fields: dict[str, tuple[str, ...]]) -> tuple[dict[str, dict[str, Any]], dict[str, int], dict[str, Any]]:
    gene_map: dict[str, dict[str, Any]] = {}
    counts = {"genome": 0, "transcriptome": 0, "proteome": 0}
    for omics, wanted in fields.items():
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type=omics)
            .exclude(canonical_gene_id="")
            .only("canonical_gene_id", "entity_id", "gene_name", "strategy_cluster", "numeric_summary", "payload_json")
        )
        for rec in qs.iterator(chunk_size=5000):
            counts[omics] += 1
            gene_id = str(rec.canonical_gene_id or "").strip()
            if not gene_id:
                continue
            entry = gene_map.setdefault(gene_id, {"canonical_gene_id": gene_id})
            entry[f"{omics}_entity_id"] = rec.entity_id
            entry[f"{omics}_cluster"] = rec.strategy_cluster
            payload = rec.payload_json or {}
            numeric = rec.numeric_summary or {}
            for field in wanted:
                value = _value(payload, numeric, field)
                if value is not None:
                    entry[_prefixed_field(omics, _canonical_field_name(omics, field))] = value
    return gene_map, counts, {
        "source_scope": "core EntityRecord fallback",
        "aggregation_scope": "all_available_EntityRecord_canonical_gene_chains",
        "gene_key_policy": "EntityRecord.canonical_gene_id",
    }


def _gene_keys(row: dict[str, Any], omics: str) -> tuple[str, ...]:
    fields = ("canonical_gene_id", "gene_id", "ensembl_gene_id")
    values: list[str] = []
    for field in fields:
        value = _clean_gene_key(row.get(field))
        if value:
            values.append(value)
            if "." in value:
                base = value.split(".", 1)[0]
                if base:
                    values.append(base)
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _clean_gene_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"na", "none", "null", "-", "nan"}:
        return ""
    return text


def _find_gene_key(parents: dict[str, str], key: str) -> str:
    parents.setdefault(key, key)
    root = key
    while parents[root] != root:
        root = parents[root]
    while parents[key] != key:
        parent = parents[key]
        parents[key] = root
        key = parent
    return root


def _union_gene_key(parents: dict[str, str], left: str, right: str) -> None:
    left_root = _find_gene_key(parents, left)
    right_root = _find_gene_key(parents, right)
    if left_root == right_root:
        return
    parents[right_root] = left_root


def _choose_gene_key(aliases: set[str]) -> str:
    def score(value: str) -> tuple[int, int, str]:
        upper = value.upper()
        is_gene_like = upper.startswith(("ENS", "AT", "OS", "LOC", "XM_", "XP_"))
        has_version = "." in value
        return (0 if is_gene_like else 1, 1 if has_version else 0, len(value), value)

    return sorted(aliases, key=score)[0] if aliases else ""


def _canonical_field_name(omics: str, field: str) -> str:
    if omics == "transcriptome" and field == "protein_gravy":
        return "protein_gravy_proxy"
    if omics in {"transcriptome", "proteome"} and field == "protein_isoelectric_point":
        return "pI"
    return field


def _csv_value(row: dict[str, Any], omics: str, field: str) -> float | None:
    aliases = [field]
    if omics == "transcriptome":
        if field == "gc_content":
            aliases = ["gc_percent_display", "gc_content"]
        elif field == "gc_percent_display":
            aliases.extend(["gc_content"])
        elif field == "protein_gravy_proxy":
            aliases.extend(["protein_gravy"])
        elif field == "protein_gravy":
            aliases.extend(["protein_gravy_proxy"])
        elif field == "protein_isoelectric_point":
            aliases.extend(["pI"])
    elif omics == "proteome":
        if field == "pI":
            aliases.extend(["protein_isoelectric_point"])
        elif field == "protein_isoelectric_point":
            aliases.extend(["pI"])
    for alias in aliases:
        value = safe_num(row.get(alias))
        if value is None:
            continue
        value = float(value)
        if omics == "transcriptome" and field in {"gc_content", "gc_percent_display"} and alias == "gc_content" and 0 <= value <= 1:
            value *= 100.0
        return value
    return None


def _value(payload: dict[str, Any], numeric: dict[str, Any], field: str) -> float | None:
    for source in (numeric, payload):
        value = safe_num(source.get(field))
        if value is not None:
            return float(value)
    return None


def _prefixed_field(omics: str, field: str) -> str:
    return f"{omics}_{field}"


def _standardize(rows: list[dict[str, Any]], source: str, target: str) -> None:
    values = sorted(float(v) for v in (safe_num(row.get(source)) for row in rows) if v is not None)
    if not values:
        return
    median = values[len(values) // 2]
    deviations = sorted(abs(v - median) for v in values)
    mad = deviations[len(deviations) // 2] or 1.0
    for row in rows:
        value = safe_num(row.get(source))
        if value is not None:
            row[target] = round((float(value) - median) / mad, 6)


def _score_candidates(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        parts = [abs(float(v)) for v in (
            safe_num(row.get("dna_to_rna_n_shift_std")),
            safe_num(row.get("rna_to_protein_n_shift_std")),
            safe_num(row.get("dna_to_rna_gc_delta")),
        ) if v is not None]
        if parts:
            row["candidate_score"] = round(sum(parts) / len(parts), 6)
            row["gene_id"] = row.get("canonical_gene_id")


_POINT_FIELD_ALIASES = {
    "genome_exon_gc_percent": "exon_gc_percent",
    "transcriptome_gc_content": "transcript_gc",
    "proteome_N_atoms_per_aa": "proteome_n_per_aa",
    "proteome_pI": "pI",
    "proteome_gravy": "gravy",
}


def _point(row: dict[str, Any], fields: tuple[str, str]) -> dict[str, Any] | None:
    x = safe_num(row.get(fields[0]))
    y = safe_num(row.get(fields[1]))
    if x is None or y is None:
        return None
    point = {
        "entity_id": row.get("canonical_gene_id"),
        "gene_id": row.get("canonical_gene_id"),
        fields[0]: round(float(x), 6),
        fields[1]: round(float(y), 6),
    }
    for source, alias in _POINT_FIELD_ALIASES.items():
        value = safe_num(row.get(source))
        if value is not None:
            point[alias] = round(float(value), 6)
    return point


def _scatter(rows: list[dict[str, Any]], x_field: str, y_field: str) -> list[dict[str, Any]]:
    points = [_point(row, (x_field, y_field)) for row in rows]
    return deterministic_sample([point for point in points if point], 5000)


def _scatter_meta(source_rows: list[dict[str, Any]], display_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"n_source_rows": len(source_rows), "n_pair_valid": len(display_rows), "display_n": len(display_rows), "sampling_policy": "deterministic_display_sample"}


def _quadrants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = defaultdict(int)
    for row in rows:
        x = safe_num(row.get("dna_to_rna_n_shift_std"))
        y = safe_num(row.get("rna_to_protein_n_shift_std"))
        if x is None or y is None:
            continue
        label = ("DNA up" if x >= 0 else "DNA down") + " / " + ("protein up" if y >= 0 else "protein down")
        counts[label] += 1
    return [{"name": key, "value": value} for key, value in sorted(counts.items())]


def _shared_outlier_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = sorted(rows, key=lambda row: safe_num(row.get("candidate_score")) or 0.0, reverse=True)
    top_n = max(1, int(len(scored) * 0.05)) if scored else 0
    return [{"name": "top_5pct_integrated_candidates", "value": top_n}, {"name": "background", "value": max(0, len(scored) - top_n)}]



def _single_species_fingerprint_projection(species_id: str, fingerprint: dict[str, Any]) -> dict[str, Any]:
    numeric_values = [float(value) for value in (safe_num(v) for v in fingerprint.values()) if value is not None]
    x = numeric_values[0] if numeric_values else 0.0
    y = numeric_values[1] if len(numeric_values) > 1 else 0.0
    return {
        "method": "complete_core_current_species_fingerprint_projection",
        "fields": [key for key, value in fingerprint.items() if safe_num(value) is not None],
        "points": [{"species_id": species_id, "display_name": species_id, "x": round(x, 6), "y": round(y, 6), "cluster": "current_species"}],
        "umap_points": [],
        "umap_available": False,
        "explained_variance_ratio": [1.0 if numeric_values else 0.0, 0.0],
        "ordination_meta": {
            "fit_n": 1 if numeric_values else 0,
            "display_n": 1 if numeric_values else 0,
            "sampling_policy": "none",
            "method_version": METHOD_VERSION,
            "note": "Full cross-species ordination is not borrowed from stored mode; materialize a release artifact to compare all species.",
        },
    }


def _fingerprint_feature_distance_matrix(fingerprint: dict[str, Any], limit: int = 28) -> dict[str, Any]:
    numeric = [
        (str(key), float(value))
        for key, value in ((key, safe_num(value)) for key, value in fingerprint.items())
        if value is not None
    ][:limit]
    labels = [key for key, _ in numeric]
    if not numeric:
        return {"x_labels": [], "y_labels": [], "values": [], "method": "complete_core_current_species_fingerprint_feature_distance", "method_version": METHOD_VERSION}
    magnitudes = [abs(value) for _, value in numeric]
    scale = max(magnitudes) or 1.0
    values = []
    for y_idx, (_, y_value) in enumerate(numeric):
        for x_idx, (_, x_value) in enumerate(numeric):
            distance = abs(x_value - y_value) / scale
            values.append([x_idx, y_idx, round(float(min(2.0, distance)), 6)])
    return {
        "x_labels": labels,
        "y_labels": labels,
        "values": values,
        "method": "complete_core_current_species_fingerprint_feature_distance",
        "method_version": METHOD_VERSION,
        "n_features": len(labels),
        "note": "Complete core computes the selected species on demand; without a materialized all-species Complete core fingerprint artifact this matrix shows within-species fingerprint feature distances, not all-species distances.",
    }


def _transition_links(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = defaultdict(int)
    for row in rows:
        g = row.get("genome_cluster")
        t = row.get("transcriptome_cluster")
        p = row.get("proteome_cluster")
        if g and t:
            counts[(f"Genome:{g}", f"Transcriptome:{t}", "genome_to_transcriptome")] += 1
        if t and p:
            counts[(f"Transcriptome:{t}", f"Proteome:{p}", "transcriptome_to_proteome")] += 1
    out = []
    for (source, target, transition), count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:40]:
        out.append({"source": source, "target": target, "value": int(count), "transition": transition})
    return out
