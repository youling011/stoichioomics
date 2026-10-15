#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

try:
    from scripts.model8_elemental_contract import ELEMENTAL_CONTRACT_ID
except ModuleNotFoundError:  # Direct execution from scripts/.
    from model8_elemental_contract import ELEMENTAL_CONTRACT_ID


CASE3_VERSION = "model8_case3_evidence_v2_elemental"
CASE3_SCRIPT = "scripts/build_model8_case3_evidence.py"
CASE2_SCRIPT = "scripts/build_model8_case2_coupling.py"

FEATURE_PAIRS = {
    "rna_gc_to_protein_n_atoms": {
        "x": "transcript_gc_fraction",
        "y": "protein_n_atoms_per_aa",
        "label": "CDS/transcript GC vs protein nitrogen atoms per residue",
    },
    "rna_gc_to_protein_c_atoms": {
        "x": "transcript_gc_fraction",
        "y": "protein_c_atoms_per_aa",
        "label": "CDS/transcript GC vs protein carbon atoms per residue",
    },
    "rna_gc_to_protein_s_atoms": {
        "x": "transcript_gc_fraction",
        "y": "protein_s_atoms_per_aa",
        "label": "CDS/transcript GC vs protein sulfur atoms per residue",
    },
    "rna_entropy_to_protein_entropy": {
        "x": "transcript_entropy",
        "y": "protein_aa_entropy",
        "label": "Nucleotide entropy vs protein amino-acid entropy",
    },
    "rna_length_to_protein_length": {
        "x": "transcript_length",
        "y": "protein_length",
        "label": "Transcript/CDS length vs protein length",
    },
    "rna_gc_to_protein_complexity": {
        "x": "transcript_gc_fraction",
        "y": "protein_aa_entropy",
        "label": "Transcript/CDS GC vs protein complexity",
    },
}

ENTITY_FEATURES = [
    ("cds_length", "CDS length", "bp", "genome/transcript"),
    ("transcript_length", "Transcript length", "nt", "transcript"),
    ("transcript_gc_fraction", "Transcript GC fraction", "fraction", "transcript"),
    ("transcript_entropy", "Transcript nucleotide entropy", "bits", "transcript"),
    ("protein_length", "Protein length", "aa", "protein"),
    ("protein_n_atoms_per_aa", "Protein nitrogen atoms per residue", "atoms/aa", "protein"),
    ("protein_c_atoms_per_aa", "Protein carbon atoms per residue", "atoms/aa", "protein"),
    ("protein_s_atoms_per_aa", "Protein sulfur atoms per residue", "atoms/aa", "protein"),
    ("protein_aa_entropy", "Protein amino-acid entropy", "bits", "protein"),
    ("protein_mw_approx", "Approximate protein MW", "Da", "protein"),
]

FEATURE_COMPLETENESS_FIELDS = [
    "cds_length",
    "transcript_length",
    "transcript_gc_fraction",
    "transcript_entropy",
    "protein_length",
    "protein_c_atoms_per_aa",
    "protein_s_atoms_per_aa",
    "protein_n_atoms_per_aa",
    "protein_aa_entropy",
    "mapping_quality_score",
]

MATCH_FEATURES = [
    "transcript_gc_fraction",
    "log_cds_length",
    "transcript_entropy",
    "log_protein_length",
    "protein_n_atoms_per_aa",
    "protein_c_atoms_per_aa",
    "protein_s_atoms_per_aa",
]

REPORT_LIMITS = {
    "go_terms_per_report": 18,
    "kegg_terms_per_report": 18,
}


def text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    out = str(value).strip()
    if not out or out.lower() in {"nan", "none", "null"}:
        return fallback
    return out


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def rounded(value: Any, digits: int = 6) -> float | None:
    number = to_float(value)
    return round(number, digits) if number is not None else None


def safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text(value, "unknown"))[:120]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with open_text(path) as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_manifest(root: Path) -> tuple[list[dict[str, str]], dict[str, dict[str, str]]]:
    rows = read_csv(root / "data" / "case_studies" / "model8" / "model8_reference_manifest.tsv", "\t")
    rows = [row for row in rows if text(row.get("case_code"))]
    return rows, {row["case_code"]: row for row in rows}


def entity_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        text(row.get("case_code")),
        text(row.get("gene_id")),
        text(row.get("transcript_id")),
        text(row.get("protein_id")),
    )


def collect_candidate_ids(top_rows: list[dict[str, str]]) -> dict[str, set[str]]:
    ids: dict[str, set[str]] = defaultdict(set)
    for row in top_rows:
        code = text(row.get("case_code"))
        for key in ("gene_id", "transcript_id", "protein_id"):
            value = text(row.get(key))
            if value:
                ids[code].add(value.lower())
    return ids


def load_annotation_index(root: Path, keys_by_code: dict[str, set[str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    path = root / "data" / "case_studies" / "model8" / "a3_annotation" / "entity_function_rows.tsv.gz"
    index: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    if not path.exists():
        return index
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            code = text(row.get("code"))
            keys = keys_by_code.get(code)
            if not keys:
                continue
            matched: set[str] = set()
            entity_id = text(row.get("entity_id")).lower()
            if entity_id in keys:
                matched.add(entity_id)
            gene_tokens = {token.lower() for token in re.split(r"[\s,;|]+", text(row.get("gene_names"))) if token}
            matched.update(gene_tokens & keys)
            for key in matched:
                index[(code, key)].append({
                    "source": text(row.get("source")),
                    "entity_id": text(row.get("entity_id")),
                    "entity_namespace": text(row.get("entity_namespace")),
                    "gene_names": text(row.get("gene_names")),
                    "term_type": text(row.get("term_type")),
                    "term_id": text(row.get("term_id")),
                    "term_label": text(row.get("term_label")),
                    "evidence_or_release": text(row.get("evidence_or_release")),
                })
    return index


def annotations_for(index: dict[tuple[str, str], list[dict[str, str]]], code: str, row: dict[str, Any]) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for key in ("gene_id", "transcript_id", "protein_id"):
        value = text(row.get(key)).lower()
        for ann in index.get((code, value), []):
            sig = (ann.get("source", ""), ann.get("entity_id", ""), ann.get("term_type", ""), ann.get("term_id", ""))
            if sig not in seen:
                seen.add(sig)
                collected.append(ann)
    return collected


def annotation_summary(annotations: list[dict[str, str]]) -> dict[str, Any]:
    go = [row for row in annotations if row.get("source") == "UniProt_GO" or row.get("term_type") == "GO"]
    kegg = [row for row in annotations if row.get("source") == "KEGG"]
    term_ids = {row.get("term_id") for row in annotations if row.get("term_id")}
    external_ids = {row.get("entity_id") for row in annotations if row.get("entity_id")}
    return {
        "go_count": len({row.get("term_id") for row in go if row.get("term_id")}),
        "kegg_count": len({row.get("term_id") for row in kegg if row.get("term_id")}),
        "term_count": len(term_ids),
        "external_id_count": len(external_ids),
        "annotation_completeness": min(1.0, math.log10(1 + len(term_ids) + len(external_ids)) / 2.0) if term_ids or external_ids else 0.0,
        "availability": "function_available" if term_ids else "function_unavailable_numeric_candidate",
    }


def feature_completeness(row: dict[str, Any]) -> float:
    present = sum(1 for key in FEATURE_COMPLETENESS_FIELDS if to_float(row.get(key)) is not None)
    return present / len(FEATURE_COMPLETENESS_FIELDS)


def rank_desc(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1], reverse=True)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + 1 + j) / 2
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def build_null_index(null_rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in null_rows:
        if text(row.get("status")).startswith("not_applicable"):
            continue
        grouped[(text(row.get("case_code")), text(row.get("pair_id")))].append(row)
    out = {}
    for key, rows in grouped.items():
        primary = next((row for row in rows if row.get("null_model") == "N1_ID_PERMUTATION_LENGTH_GC_BIN"), rows[0])
        out[key] = primary
    return out


def build_entity_index(rows: list[dict[str, str]]) -> tuple[dict[tuple[str, str, str, str], dict[str, str]], dict[str, list[dict[str, str]]]]:
    by_key = {entity_key(row): row for row in rows}
    by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_code[text(row.get("case_code"))].append(row)
    return by_key, by_code


def enrich_candidate_pool(
    top_rows: list[dict[str, str]],
    entities_by_key: dict[tuple[str, str, str, str], dict[str, str]],
    null_index: dict[tuple[str, str], dict[str, str]],
    sensitivity_index: dict[tuple[str, str], dict[str, str]],
    annotation_index: dict[tuple[str, str], list[dict[str, str]]],
    manifest_by_code: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for row in top_rows:
        code = text(row.get("case_code"))
        pair_id = text(row.get("pair_id"))
        entity = entities_by_key.get(entity_key(row), {})
        merged = {**entity, **row}
        annotations = annotations_for(annotation_index, code, merged)
        ann = annotation_summary(annotations)
        null = null_index.get((code, pair_id), {})
        sensitivity = sensitivity_index.get((code, pair_id), {})
        residual_z = to_float(row.get("residual_z")) or 0.0
        merged.update({
            "case_code": code,
            "species_id": text(merged.get("species_id")) or text(manifest_by_code.get(code, {}).get("species_id")),
            "scientific_name": text(merged.get("scientific_name")) or text(manifest_by_code.get(code, {}).get("scientific_name")),
            "division": text(merged.get("division")) or text(manifest_by_code.get(code, {}).get("division")),
            "candidate_direction": text(row.get("residual_class")),
            "candidate_role": "primary_extreme",
            "abs_residual_z": abs(residual_z),
            "observed_minus_null": abs(to_float(null.get("excess")) or 0.0),
            "mapping_confidence": to_float(merged.get("mapping_quality_score")) or 0.0,
            "feature_completeness": feature_completeness(merged),
            "annotation_completeness": ann["annotation_completeness"],
            "annotation_availability": ann["availability"],
            "go_count": ann["go_count"],
            "kegg_count": ann["kegg_count"],
            "external_id_count": ann["external_id_count"],
            "null_model": text(null.get("null_model")),
            "observed": rounded(null.get("observed")),
            "null_mean": rounded(null.get("null_mean")),
            "null_sd": rounded(null.get("null_sd")),
            "excess": rounded(null.get("excess")),
            "empirical_p": rounded(null.get("empirical_p")),
            "bh_fdr": rounded(null.get("bh_fdr")),
            "isoform_sensitivity_status": text(sensitivity.get("status")),
            "isoform_delta_spearman": rounded(sensitivity.get("delta_spearman")),
            "entity_label_policy": "stoichiometric residual candidate; not causal driver, regulator, or adaptive proof",
        })
        pool.append(merged)

    for (code, direction), rows in group_by(pool, ("case_code", "candidate_direction")).items():
        metrics = [
            ("abs_residual_z", "rank_abs_residual"),
            ("observed_minus_null", "rank_observed_minus_null"),
            ("mapping_confidence", "rank_mapping_confidence"),
            ("feature_completeness", "rank_feature_completeness"),
            ("annotation_completeness", "rank_annotation_completeness"),
        ]
        for metric, rank_name in metrics:
            ranks = rank_desc([float(row.get(metric) or 0.0) for row in rows])
            for row, rank in zip(rows, ranks):
                row[rank_name] = rank
        for row in rows:
            row["candidate_priority"] = sum(float(row.get(rank_name) or 0.0) for _, rank_name in metrics)
            row["weighted_priority_sensitivity"] = (
                2.0 * float(row.get("rank_abs_residual") or 0.0)
                + float(row.get("rank_observed_minus_null") or 0.0)
                + float(row.get("rank_mapping_confidence") or 0.0)
                + float(row.get("rank_feature_completeness") or 0.0)
                + 0.5 * float(row.get("rank_annotation_completeness") or 0.0)
            )
            row["selection_group"] = f"{code}:{direction}"
    return pool


def group_by(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    out: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[tuple(row.get(key) for key in keys)].append(row)
    return out


def choose_extreme_candidates(pool: list[dict[str, Any]], manifest_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for manifest in manifest_rows:
        code = manifest["case_code"]
        for direction in ("positive_residual", "negative_residual"):
            rows = [
                row for row in pool
                if row.get("case_code") == code and row.get("candidate_direction") == direction
            ]
            if not rows:
                continue
            chosen = sorted(
                rows,
                key=lambda row: (float(row.get("candidate_priority") or 999999), -float(row.get("abs_residual_z") or 0.0)),
            )[0]
            chosen["selection_status"] = "selected"
            selected.append(chosen)
    return selected


def regression_residuals(rows: list[dict[str, str]], pair_id: str) -> dict[tuple[str, str, str, str], float]:
    spec = FEATURE_PAIRS[pair_id]
    points: list[tuple[tuple[str, str, str, str], float, float]] = []
    for row in rows:
        x = to_float(row.get(spec["x"]))
        y = to_float(row.get(spec["y"]))
        if x is None or y is None:
            continue
        points.append((entity_key(row), x, y))
    if len(points) < 3:
        return {}
    xs = [x for _, x, _ in points]
    ys = [y for _, _, y in points]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denom = sum((x - x_mean) ** 2 for x in xs)
    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denom if denom else 0.0
    intercept = y_mean - slope * x_mean
    raw = [(key, y - (intercept + slope * x)) for key, x, y in points]
    residual_values = [value for _, value in raw]
    center = sum(residual_values) / len(residual_values)
    variance = sum((value - center) ** 2 for value in residual_values) / max(1, len(residual_values) - 1)
    sd = math.sqrt(variance) or 1.0
    return {key: (value - center) / sd for key, value in raw}


def species_scales(rows: list[dict[str, str]]) -> dict[str, float]:
    scales = {}
    for feature in MATCH_FEATURES:
        values = [to_float(row.get(feature)) for row in rows]
        clean = [value for value in values if value is not None]
        if len(clean) < 2:
            scales[feature] = 1.0
            continue
        med = median(clean)
        mad = median([abs(value - med) for value in clean]) or 0.0
        if mad:
            scales[feature] = mad * 1.4826
        else:
            mean = sum(clean) / len(clean)
            scales[feature] = math.sqrt(sum((value - mean) ** 2 for value in clean) / max(1, len(clean) - 1)) or 1.0
    return scales


def match_distance(target: dict[str, Any], candidate: dict[str, Any], scales: dict[str, float]) -> tuple[float, dict[str, float | None]]:
    diffs: dict[str, float | None] = {}
    total = 0.0
    used = 0
    for feature in MATCH_FEATURES:
        a = to_float(target.get(feature))
        b = to_float(candidate.get(feature))
        if a is None or b is None:
            diffs[f"{feature}_diff"] = None
            continue
        diff = b - a
        diffs[f"{feature}_diff"] = round(diff, 6)
        total += abs(diff) / (scales.get(feature) or 1.0)
        used += 1
    return (total / used if used else 999999.0), diffs


def choose_matched_controls(
    selected_extremes: list[dict[str, Any]],
    entities_by_code: dict[str, list[dict[str, str]]],
    null_index: dict[tuple[str, str], dict[str, str]],
    sensitivity_index: dict[tuple[str, str], dict[str, str]],
    annotation_index: dict[tuple[str, str], list[dict[str, str]]],
    manifest_by_code: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    controls = []
    control_rows = []
    by_code = group_by(selected_extremes, ("case_code",))
    for (code,), rows in by_code.items():
        target = sorted(rows, key=lambda row: -float(row.get("abs_residual_z") or 0.0))[0]
        pair_id = text(target.get("pair_id"))
        species_rows = entities_by_code.get(code, [])
        selected_keys = {entity_key(row) for row in rows}
        residuals = regression_residuals(species_rows, pair_id)
        scales = species_scales(species_rows)
        candidates = []
        for candidate in species_rows:
            key = entity_key(candidate)
            if key in selected_keys:
                continue
            if feature_completeness(candidate) < 0.8:
                continue
            residual_z = residuals.get(key)
            if residual_z is None:
                continue
            distance, diffs = match_distance(target, candidate, scales)
            median_penalty = abs(residual_z)
            candidates.append((distance + median_penalty * 0.5, distance, residual_z, candidate, diffs))
        if not candidates:
            continue
        _score, distance, residual_z, control_entity, diffs = sorted(candidates, key=lambda item: item[0])[0]
        annotations = annotations_for(annotation_index, code, control_entity)
        ann = annotation_summary(annotations)
        null = null_index.get((code, pair_id), {})
        sensitivity = sensitivity_index.get((code, pair_id), {})
        control = {
            **control_entity,
            "case_code": code,
            "species_id": text(control_entity.get("species_id")) or text(manifest_by_code.get(code, {}).get("species_id")),
            "scientific_name": text(control_entity.get("scientific_name")) or text(manifest_by_code.get(code, {}).get("scientific_name")),
            "division": text(control_entity.get("division")) or text(manifest_by_code.get(code, {}).get("division")),
            "pair_id": pair_id,
            "pair_label": FEATURE_PAIRS[pair_id]["label"],
            "candidate_direction": "matched_control",
            "candidate_role": "matched_background_control",
            "residual_z": round(residual_z, 6),
            "abs_residual_z": round(abs(residual_z), 6),
            "observed_minus_null": abs(to_float(null.get("excess")) or 0.0),
            "mapping_confidence": to_float(control_entity.get("mapping_quality_score")) or 0.0,
            "feature_completeness": feature_completeness(control_entity),
            "annotation_completeness": ann["annotation_completeness"],
            "annotation_availability": ann["availability"],
            "go_count": ann["go_count"],
            "kegg_count": ann["kegg_count"],
            "external_id_count": ann["external_id_count"],
            "null_model": text(null.get("null_model")),
            "observed": rounded(null.get("observed")),
            "null_mean": rounded(null.get("null_mean")),
            "null_sd": rounded(null.get("null_sd")),
            "excess": rounded(null.get("excess")),
            "empirical_p": rounded(null.get("empirical_p")),
            "bh_fdr": rounded(null.get("bh_fdr")),
            "isoform_sensitivity_status": text(sensitivity.get("status")),
            "isoform_delta_spearman": rounded(sensitivity.get("delta_spearman")),
            "candidate_priority": "",
            "selection_status": "selected_matched_control",
            "matched_to_direction": text(target.get("candidate_direction")),
            "matched_to_gene_id": text(target.get("gene_id")),
            "matched_to_transcript_id": text(target.get("transcript_id")),
            "matched_to_protein_id": text(target.get("protein_id")),
            "matched_control_distance": round(distance, 6),
            "matching_rule": "same species; minimize robust-scaled distance across transcript GC, CDS/protein length, nucleotide entropy, and protein N/C/S composition; prefer near-median residual",
            "entity_label_policy": "matched background control; not causal driver, regulator, or adaptive proof",
            **diffs,
        }
        controls.append(control)
        control_rows.append({
            "case_code": code,
            "scientific_name": control["scientific_name"],
            "pair_id": pair_id,
            "target_direction": target.get("candidate_direction"),
            "target_gene_id": target.get("gene_id"),
            "target_transcript_id": target.get("transcript_id"),
            "target_protein_id": target.get("protein_id"),
            "control_gene_id": control.get("gene_id"),
            "control_transcript_id": control.get("transcript_id"),
            "control_protein_id": control.get("protein_id"),
            "matched_control_distance": control["matched_control_distance"],
            "control_residual_z": control["residual_z"],
            "matching_rule": control["matching_rule"],
            **diffs,
        })
    return controls, control_rows


def percentile_map(rows: list[dict[str, Any]], features: list[str]) -> dict[tuple[tuple[str, str, str, str], str], float | None]:
    out = {}
    for feature in features:
        values = [(entity_key(row), to_float(row.get(feature))) for row in rows]
        clean = sorted((value, key) for key, value in values if value is not None)
        n = len(clean)
        ranks = {}
        for idx, (value, key) in enumerate(clean, start=1):
            ranks[key] = idx / n if n else None
        for key, _ in values:
            out[(key, feature)] = ranks.get(key)
    return out


def build_feature_profile(row: dict[str, Any], percentiles: dict[tuple[tuple[str, str, str, str], str], float | None]) -> list[dict[str, Any]]:
    key = entity_key(row)
    profile = []
    for feature, label, unit, omics_layer in ENTITY_FEATURES:
        profile.append({
            "omics_layer": omics_layer,
            "feature": feature,
            "label": label,
            "unit": unit,
            "value": rounded(row.get(feature), 6),
            "same_species_percentile": rounded(percentiles.get((key, feature)), 4),
            "coverage": "entity_level_case2_coupled_chain",
        })
    return profile


def split_function_panel(annotations: list[dict[str, str]], manifest: dict[str, str]) -> dict[str, Any]:
    go_terms = []
    kegg_terms = []
    seen_go = set()
    seen_kegg = set()
    for row in annotations:
        if row.get("source") == "UniProt_GO" or row.get("term_type") == "GO":
            sig = (row.get("term_id"), row.get("term_label"))
            if row.get("term_id") and sig not in seen_go:
                seen_go.add(sig)
                go_terms.append({
                    "term_id": row.get("term_id"),
                    "term_label": row.get("term_label"),
                    "source": row.get("source"),
                    "evidence_or_release": row.get("evidence_or_release") or manifest.get("go_release", ""),
                })
        if row.get("source") == "KEGG":
            sig = (row.get("term_type"), row.get("term_id"))
            if row.get("term_id") and sig not in seen_kegg:
                seen_kegg.add(sig)
                kegg_terms.append({
                    "term_type": row.get("term_type"),
                    "term_id": row.get("term_id"),
                    "term_label": row.get("term_label"),
                    "source": row.get("source"),
                    "evidence_or_release": row.get("evidence_or_release") or manifest.get("kegg_release", ""),
                })
    return {
        "available": bool(go_terms or kegg_terms),
        "go": {
            "release": manifest.get("go_release", ""),
            "count": len(go_terms),
            "terms": go_terms[:REPORT_LIMITS["go_terms_per_report"]],
        },
        "kegg": {
            "release": manifest.get("kegg_release", ""),
            "count": len(kegg_terms),
            "terms": kegg_terms[:REPORT_LIMITS["kegg_terms_per_report"]],
        },
        "unavailable_reason": "" if go_terms or kegg_terms else "No GO/KEGG term matched the gene/transcript/protein identifiers in the local A3 annotation bundle; numeric candidate retained.",
    }


def report_identity(row: dict[str, Any], manifest: dict[str, str], annotations: list[dict[str, str]]) -> dict[str, Any]:
    external = sorted({ann.get("entity_id", "") for ann in annotations if ann.get("entity_id")})
    gene_names = sorted({ann.get("gene_names", "") for ann in annotations if ann.get("gene_names")})
    return {
        "case_code": row.get("case_code"),
        "species_id": row.get("species_id") or manifest.get("species_id", ""),
        "scientific_name": row.get("scientific_name") or manifest.get("scientific_name", ""),
        "division": row.get("division") or manifest.get("division", ""),
        "gene_id": row.get("gene_id", ""),
        "transcript_id": row.get("transcript_id", ""),
        "protein_id": row.get("protein_id", ""),
        "symbol": gene_names[0].split()[0] if gene_names else "",
        "description": gene_names[0] if gene_names else "",
        "external_ids": external[:12],
        "mapping_confidence": rounded(row.get("mapping_quality_score")),
        "mapping_status": row.get("mapping_status", ""),
        "canonical_rule": row.get("canonical_rule", ""),
    }


def build_reports(
    rows_24: list[dict[str, Any]],
    entities_by_code: dict[str, list[dict[str, str]]],
    annotation_index: dict[tuple[str, str], list[dict[str, str]]],
    manifest_by_code: dict[str, dict[str, str]],
    source_checksums: dict[str, str],
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    reports = []
    feature_rows = []
    trace_rows = []
    percentiles_by_code = {
        code: percentile_map(rows, [feature for feature, *_ in ENTITY_FEATURES])
        for code, rows in entities_by_code.items()
    }
    report_root = output_dir / "reports"
    if report_root.exists():
        shutil.rmtree(report_root)
    for row in rows_24:
        code = text(row.get("case_code"))
        manifest = manifest_by_code.get(code, {})
        annotations = annotations_for(annotation_index, code, row)
        profile = build_feature_profile(row, percentiles_by_code.get(code, {}))
        direction = text(row.get("candidate_direction"))
        entity_id = text(row.get("protein_id")) or text(row.get("transcript_id")) or text(row.get("gene_id"))
        report_dir = report_root / safe_slug(code) / safe_slug(direction) / safe_slug(entity_id)
        report_path = report_dir / "report.json"
        cross = {
            "pair_id": row.get("pair_id"),
            "pair_label": FEATURE_PAIRS.get(text(row.get("pair_id")), {}).get("label", ""),
            "observed_shift": rounded(row.get("residual_z")),
            "null_expectation": row.get("null_mean"),
            "observed_minus_null": row.get("excess"),
            "cross_omics_residual": rounded(row.get("residual_z")),
            "empirical_p": row.get("empirical_p"),
            "fdr": row.get("bh_fdr"),
            "null_model": row.get("null_model"),
            "isoform_sensitivity": {
                "status": row.get("isoform_sensitivity_status"),
                "delta_spearman": row.get("isoform_delta_spearman"),
            },
        }
        matched = {
            "matching_rule": row.get("matching_rule", ""),
            "distance": row.get("matched_control_distance", ""),
            "background_entity_id": row.get("control_protein_id") or row.get("protein_id", ""),
            "target_entity_id": row.get("matched_to_protein_id", ""),
            "differences": {
                key: row.get(key)
                for key in row
                if key.endswith("_diff")
            },
        }
        traceability = {
            "original_row": {
                "case2_top_transformations_key": f"{code}|{row.get('pair_id')}|{row.get('gene_id')}|{row.get('transcript_id')}|{row.get('protein_id')}",
                "case2_coupled_entities_key": "|".join(entity_key(row)),
            },
            "input_checksums": source_checksums,
            "script": CASE3_SCRIPT,
            "upstream_script": CASE2_SCRIPT,
            "chart_source_file": "case3_figure_mapping.csv",
            "allowed_interpretation": "selected extreme or matched-control entity in a descriptive cross-omics stoichiometric evidence chain",
            "forbidden_interpretation": "driver, causal regulator, adaptive proof, or manually favored gene label",
        }
        payload = {
            "report_id": f"{code}_{direction}_{entity_id}",
            "case_version": CASE3_VERSION,
            "selection_badge": {
                "label": "Model-8 case evidence",
                "why_selected": row.get("selection_reason", ""),
                "role": row.get("candidate_role"),
                "direction": direction,
                "annotation_availability": row.get("annotation_availability"),
            },
            "identity": report_identity(row, manifest, annotations),
            "feature_profile": profile,
            "cross_omics_evidence": cross,
            "matched_control": matched,
            "function": split_function_panel(annotations, manifest),
            "traceability": traceability,
            "limitations": [
                "Candidate priority is rank aggregation over descriptive evidence and must not be interpreted as causality.",
                "Function annotations are attached only where local GO/KEGG identifiers match; unannotated numeric extremes remain valid numeric candidates.",
                "Matched controls are computational background entities matched on GC, length, entropy, and protein composition, not biological negative controls.",
            ],
        }
        write_json(report_path, payload)
        reports.append({
            "report_id": payload["report_id"],
            "case_code": code,
            "scientific_name": payload["identity"]["scientific_name"],
            "direction": direction,
            "candidate_role": row.get("candidate_role"),
            "gene_id": row.get("gene_id"),
            "transcript_id": row.get("transcript_id"),
            "protein_id": row.get("protein_id"),
            "pair_id": row.get("pair_id"),
            "residual_z": rounded(row.get("residual_z")),
            "candidate_priority": row.get("candidate_priority"),
            "annotation_availability": row.get("annotation_availability"),
            "go_count": row.get("go_count"),
            "kegg_count": row.get("kegg_count"),
            "report_path": str(report_path.relative_to(output_dir)).replace(os.sep, "/"),
        })
        for feature in profile:
            feature_rows.append({
                "report_id": payload["report_id"],
                "case_code": code,
                "direction": direction,
                **feature,
            })
        trace_rows.append({
            "report_id": payload["report_id"],
            "case_code": code,
            "direction": direction,
            "input_checksums": json.dumps(source_checksums, ensure_ascii=False, sort_keys=True),
            "script": CASE3_SCRIPT,
            "upstream_script": CASE2_SCRIPT,
            "allowed_interpretation": traceability["allowed_interpretation"],
            "forbidden_interpretation": traceability["forbidden_interpretation"],
        })
    return reports, feature_rows, trace_rows


def build_sensitivity_rows(pool: list[dict[str, Any]], selected_extremes: list[dict[str, Any]], controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected_keys = {(row.get("case_code"), row.get("candidate_direction"), entity_key(row)) for row in selected_extremes}
    weighted_best: dict[tuple[str, str], tuple[str, str, str, str]] = {}
    for (code, direction), rows in group_by(pool, ("case_code", "candidate_direction")).items():
        chosen = sorted(rows, key=lambda row: (float(row.get("weighted_priority_sensitivity") or 999999), -float(row.get("abs_residual_z") or 0.0)))[0]
        weighted_best[(code, direction)] = entity_key(chosen)
    rows = []
    for row in selected_extremes + controls:
        code = row.get("case_code")
        direction = row.get("candidate_direction")
        weighted_key = weighted_best.get((code, direction))
        stable = "not_applicable_matched_control" if direction == "matched_control" else ("stable" if weighted_key == entity_key(row) else "changes_under_weighted_sensitivity")
        rows.append({
            "case_code": code,
            "scientific_name": row.get("scientific_name"),
            "candidate_direction": direction,
            "candidate_role": row.get("candidate_role"),
            "gene_id": row.get("gene_id"),
            "transcript_id": row.get("transcript_id"),
            "protein_id": row.get("protein_id"),
            "pair_id": row.get("pair_id"),
            "equal_weight_priority": row.get("candidate_priority"),
            "weighted_priority_sensitivity": row.get("weighted_priority_sensitivity", ""),
            "weighted_selection_stability": stable,
            "isoform_sensitivity_status": row.get("isoform_sensitivity_status"),
            "isoform_delta_spearman": row.get("isoform_delta_spearman"),
            "matched_control_distance": row.get("matched_control_distance", ""),
        })
    return rows


def source_file_info(root: Path, output_dir: Path) -> dict[str, str]:
    rels = {
        "case2_top_transformations": root / "data" / "case_studies" / "model8" / "case2_coupling" / "case2_top_transformations.csv",
        "case2_coupled_entities": root / "data" / "case_studies" / "model8" / "case2_coupling" / "case2_coupled_entities.csv.gz",
        "case2_null_model_results": root / "data" / "case_studies" / "model8" / "case2_coupling" / "case2_null_model_results.csv",
        "case2_sensitivity_analysis": root / "data" / "case_studies" / "model8" / "case2_coupling" / "case2_sensitivity_analysis.csv",
        "model8_reference_manifest": root / "data" / "case_studies" / "model8" / "model8_reference_manifest.tsv",
        "a3_function_annotations": root / "data" / "case_studies" / "model8" / "a3_annotation" / "entity_function_rows.tsv.gz",
    }
    info = {}
    for name, path in rels.items():
        info[name] = file_sha256(path) if path.exists() else "missing"
    return info


def artifact_downloads(output_dir: Path) -> list[dict[str, Any]]:
    names = [
        "candidate_selection_table.csv",
        "entity_evidence_24.csv",
        "matched_controls.csv",
        "candidate_sensitivity.csv",
        "case3_report_index.csv",
        "case3_annotation_links.csv",
        "case3_feature_profile.csv",
        "case3_traceability.csv",
        "case3_figure_mapping.csv",
        "case3_statistical_plan.json",
    ]
    downloads = []
    for name in names:
        path = output_dir / name
        if path.exists():
            downloads.append({"name": name, "path": str(path), "bytes": path.stat().st_size, "sha256": file_sha256(path)})
    return downloads


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else root / "data" / "case_studies" / "model8" / "case3_evidence"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows, manifest_by_code = load_manifest(root)
    case2_dir = root / "data" / "case_studies" / "model8" / "case2_coupling"
    top_rows = read_csv(case2_dir / "case2_top_transformations.csv")
    null_rows = read_csv(case2_dir / "case2_null_model_results.csv")
    sensitivity_rows_raw = read_csv(case2_dir / "case2_sensitivity_analysis.csv")
    entity_rows = read_csv(case2_dir / "case2_coupled_entities.csv.gz")

    null_index = build_null_index(null_rows)
    sensitivity_index = {(row["case_code"], row["pair_id"]): row for row in sensitivity_rows_raw}
    entities_by_key, entities_by_code = build_entity_index(entity_rows)

    keys_by_code = collect_candidate_ids(top_rows)
    annotation_index = load_annotation_index(root, keys_by_code)
    pool = enrich_candidate_pool(top_rows, entities_by_key, null_index, sensitivity_index, annotation_index, manifest_by_code)
    selected_extremes = choose_extreme_candidates(pool, manifest_rows)

    control_prelim, matched_control_rows = choose_matched_controls(
        selected_extremes,
        entities_by_code,
        null_index,
        sensitivity_index,
        annotation_index,
        manifest_by_code,
    )
    for control in control_prelim:
        for key in ("gene_id", "transcript_id", "protein_id"):
            value = text(control.get(key))
            if value:
                keys_by_code[control["case_code"]].add(value.lower())
    annotation_index = load_annotation_index(root, keys_by_code)
    controls, matched_control_rows = choose_matched_controls(
        selected_extremes,
        entities_by_code,
        null_index,
        sensitivity_index,
        annotation_index,
        manifest_by_code,
    )

    for row in selected_extremes:
        row["selection_reason"] = (
            f"Selected within {row.get('case_code')} {row.get('candidate_direction')} by equal-weight rank aggregation: "
            f"|residual| rank {row.get('rank_abs_residual')}, observed-null rank {row.get('rank_observed_minus_null')}, "
            f"mapping rank {row.get('rank_mapping_confidence')}, feature-completeness rank {row.get('rank_feature_completeness')}, "
            f"annotation-completeness rank {row.get('rank_annotation_completeness')}."
        )
    for row in controls:
        row["selection_reason"] = (
            f"Selected as same-species matched background control for {row.get('matched_to_protein_id') or row.get('matched_to_transcript_id')}; "
            f"distance={row.get('matched_control_distance')} with near-median residual z={row.get('residual_z')}."
        )

    rows_24 = selected_extremes + controls
    rows_24 = sorted(rows_24, key=lambda row: (row.get("case_code", ""), {"positive_residual": 0, "negative_residual": 1, "matched_control": 2}.get(row.get("candidate_direction"), 9)))
    source_checksums = source_file_info(root, output_dir)
    report_index, feature_profile_rows, trace_rows = build_reports(
        rows_24,
        entities_by_code,
        annotation_index,
        manifest_by_code,
        source_checksums,
        output_dir,
    )

    annotation_link_rows = []
    for row in rows_24:
        code = row.get("case_code")
        for ann in annotations_for(annotation_index, code, row):
            annotation_link_rows.append({
                "case_code": code,
                "direction": row.get("candidate_direction"),
                "gene_id": row.get("gene_id"),
                "transcript_id": row.get("transcript_id"),
                "protein_id": row.get("protein_id"),
                **ann,
            })

    pool_fields = [
        "case_code", "scientific_name", "division", "pair_id", "candidate_direction",
        "gene_id", "transcript_id", "protein_id", "residual_z", "abs_residual_z",
        "observed_minus_null", "mapping_confidence", "feature_completeness",
        "annotation_completeness", "candidate_priority", "weighted_priority_sensitivity",
        "rank_abs_residual", "rank_observed_minus_null", "rank_mapping_confidence",
        "rank_feature_completeness", "rank_annotation_completeness", "go_count", "kegg_count",
        "annotation_availability", "selection_status", "entity_label_policy",
    ]
    evidence_fields = [
        "case_code", "species_id", "scientific_name", "division", "candidate_direction",
        "candidate_role", "pair_id", "gene_id", "transcript_id", "protein_id",
        "residual_z", "abs_residual_z", "candidate_priority", "observed", "null_mean",
        "excess", "empirical_p", "bh_fdr", "mapping_status", "mapping_quality_score",
        "feature_completeness", "annotation_completeness", "go_count", "kegg_count",
        "annotation_availability", "isoform_sensitivity_status", "isoform_delta_spearman",
        "matched_to_protein_id", "matched_control_distance", "selection_reason",
        "entity_label_policy",
    ]
    match_fields = [
        "case_code", "scientific_name", "pair_id", "target_direction", "target_gene_id",
        "target_transcript_id", "target_protein_id", "control_gene_id", "control_transcript_id",
        "control_protein_id", "matched_control_distance", "control_residual_z", "matching_rule",
    ] + [f"{feature}_diff" for feature in MATCH_FEATURES]
    sensitivity_fields = [
        "case_code", "scientific_name", "candidate_direction", "candidate_role", "gene_id",
        "transcript_id", "protein_id", "pair_id", "equal_weight_priority",
        "weighted_priority_sensitivity", "weighted_selection_stability",
        "isoform_sensitivity_status", "isoform_delta_spearman", "matched_control_distance",
    ]
    report_fields = [
        "report_id", "case_code", "scientific_name", "direction", "candidate_role", "gene_id",
        "transcript_id", "protein_id", "pair_id", "residual_z", "candidate_priority",
        "annotation_availability", "go_count", "kegg_count", "report_path",
    ]
    annotation_fields = [
        "case_code", "direction", "gene_id", "transcript_id", "protein_id", "source",
        "entity_id", "entity_namespace", "gene_names", "term_type", "term_id",
        "term_label", "evidence_or_release",
    ]
    feature_fields = [
        "report_id", "case_code", "direction", "omics_layer", "feature", "label", "unit",
        "value", "same_species_percentile", "coverage",
    ]
    trace_fields = [
        "report_id", "case_code", "direction", "input_checksums", "script",
        "upstream_script", "allowed_interpretation", "forbidden_interpretation",
    ]
    figure_rows = [
        {
            "figure_id": "case3_priority_scatter",
            "source_file": "candidate_selection_table.csv",
            "chart_type": "scatter",
            "x": "abs_residual_z",
            "y": "observed_minus_null",
            "color": "candidate_direction",
            "purpose": "show why extreme candidates were selected by residual and null-excess evidence",
        },
        {
            "figure_id": "case3_matched_control_distance",
            "source_file": "matched_controls.csv",
            "chart_type": "bar",
            "x": "case_code",
            "y": "matched_control_distance",
            "color": "target_direction",
            "purpose": "audit control-match distance across eight species",
        },
        {
            "figure_id": "case3_annotation_availability",
            "source_file": "entity_evidence_24.csv",
            "chart_type": "stacked_bar",
            "x": "case_code",
            "y": "go_count;kegg_count",
            "color": "candidate_direction",
            "purpose": "separate numeric candidates from function-annotated candidates",
        },
    ]
    statistical_plan = {
        "case_version": CASE3_VERSION,
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_algorithm": "equal_weight_rank_aggregation",
        "candidate_priority_formula": "rank(|cross_omics_residual|)+rank(observed_minus_null)+rank(mapping_confidence)+rank(feature_completeness)+rank(annotation_completeness)",
        "selection_constraints": [
            "select positive and negative residual candidates separately within each species",
            "select one same-species matched-control entity per species using GC, length, entropy, and protein N/C/S composition",
            "do not manually alter candidates based on famous genes, GO significance, or researcher preference",
            "unannotated numeric extremes are retained and function panels are marked unavailable",
        ],
        "forbidden_terms": ["driver", "causal", "regulator", "adaptive proof"],
        "source_checksums": source_checksums,
    }

    write_csv(output_dir / "candidate_selection_table.csv", sorted(pool, key=lambda row: (row.get("case_code", ""), row.get("candidate_direction", ""), float(row.get("candidate_priority") or 999999))), pool_fields)
    write_csv(output_dir / "entity_evidence_24.csv", rows_24, evidence_fields)
    write_csv(output_dir / "matched_controls.csv", matched_control_rows, match_fields)
    write_csv(output_dir / "candidate_sensitivity.csv", build_sensitivity_rows(pool, selected_extremes, controls), sensitivity_fields)
    write_csv(output_dir / "case3_report_index.csv", report_index, report_fields)
    write_csv(output_dir / "case3_annotation_links.csv", annotation_link_rows, annotation_fields)
    write_csv(output_dir / "case3_feature_profile.csv", feature_profile_rows, feature_fields)
    write_csv(output_dir / "case3_traceability.csv", trace_rows, trace_fields)
    write_csv(output_dir / "case3_figure_mapping.csv", figure_rows, list(figure_rows[0].keys()))
    write_json(output_dir / "case3_statistical_plan.json", statistical_plan)

    summary = {
        "case_id": "model8_case3_evidence",
        "case_title": "Case 3. Eight-model-organism extreme candidate entity evidence chain",
        "status": "implemented",
        "case_version": CASE3_VERSION,
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
        "generated_at_utc": statistical_plan["generated_at_utc"],
        "species_count": len(manifest_rows),
        "formal_report_count": len(rows_24),
        "primary_candidate_count": len(selected_extremes),
        "matched_control_count": len(controls),
        "candidate_pool_count": len(pool),
        "annotation_available_count": sum(1 for row in rows_24 if row.get("annotation_availability") == "function_available"),
        "numeric_candidate_count": sum(1 for row in rows_24 if row.get("annotation_availability") != "function_available"),
        "selection_algorithm": statistical_plan["candidate_priority_formula"],
        "downloads": artifact_downloads(output_dir),
        "filters": {
            "species": [{"case_code": row["case_code"], "scientific_name": row["scientific_name"], "division": row["division"]} for row in manifest_rows],
            "directions": ["positive_residual", "negative_residual", "matched_control"],
            "annotation_availability": ["function_available", "function_unavailable_numeric_candidate"],
        },
        "finding": (
            "Eight fixed model organisms now have 24 traceable entity-level evidence reports: one positive residual candidate, "
            "one negative residual candidate, and one same-species matched background control per species."
        ),
        "method": (
            "Case 2 high-confidence cross-omics residual outputs were joined to entity-level feature chains, null-model statistics, "
            "isoform sensitivity rows, and local GO/KEGG annotation records. Candidates were selected by equal-weight rank aggregation; "
            "matched controls minimize robust-scaled GC, length, entropy, and protein N/C/S composition distance while remaining near the residual median."
        ),
        "limitations": [
            "The evidence chain is descriptive and cannot be labeled as causal, regulatory, or adaptive proof.",
            "GO/KEGG panels are unavailable for candidates whose identifiers do not match the local A3 annotation bundle.",
            "Matched controls are computational background matches, not experimental negative controls.",
        ],
    }
    candidates_payload = {
        "candidate_pool": sorted(pool, key=lambda row: (row.get("case_code", ""), row.get("candidate_direction", ""), float(row.get("candidate_priority") or 999999)))[:240],
        "selected_entities": rows_24,
        "matched_controls": matched_control_rows,
    }
    reports_payload = {
        "report_index": report_index,
        "representative_reports": report_index[:12],
        "formal_report_count": len(report_index),
        "report_root": str(output_dir / "reports"),
    }
    sensitivity_payload = {
        "sensitivity_rows": build_sensitivity_rows(pool, selected_extremes, controls),
        "statistical_plan": statistical_plan,
    }

    write_json(output_dir / "summary.json", summary)
    write_json(output_dir / "candidates.json", candidates_payload)
    write_json(output_dir / "reports.json", reports_payload)
    write_json(output_dir / "sensitivity.json", sensitivity_payload)

    print(json.dumps({
        "output_dir": str(output_dir),
        "formal_report_count": len(rows_24),
        "candidate_pool_count": len(pool),
        "annotation_available_count": summary["annotation_available_count"],
        "downloads": len(summary["downloads"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
