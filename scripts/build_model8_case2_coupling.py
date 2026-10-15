from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    from scripts.model8_elemental_contract import ELEMENTAL_CONTRACT_ID
except ModuleNotFoundError:  # Direct execution from scripts/.
    from model8_elemental_contract import ELEMENTAL_CONTRACT_ID


SPECIES_ORDER = ["ECOLI", "BSUB", "ORYSA", "DROME", "YEAST", "ARATH", "DANRE", "MOUSE"]
EUKARYOTE_CODES = {"ORYSA", "DROME", "YEAST", "ARATH", "DANRE", "MOUSE"}
BACTERIA_CODES = {"ECOLI", "BSUB"}
SEED = 20260729
N_NULL = 1000
NULL_ROW_CAP = 12000
TOP_ENTITY_N = 40
CASE2_VERSION = "model8_case2_coupling_v2_elemental"

FEATURE_PAIRS = [
    {
        "pair_id": "rna_gc_to_protein_n_atoms",
        "x": "transcript_gc_fraction",
        "y": "protein_n_atoms_per_aa",
        "label": "CDS/transcript GC vs protein nitrogen atoms per residue",
        "class": "nucleotide_to_protein_element",
        "primary_covariates": ["log_cds_length", "log_protein_length", "mapping_quality_score"],
    },
    {
        "pair_id": "rna_gc_to_protein_c_atoms",
        "x": "transcript_gc_fraction",
        "y": "protein_c_atoms_per_aa",
        "label": "CDS/transcript GC vs protein carbon atoms per residue",
        "class": "nucleotide_to_protein_element",
        "primary_covariates": ["log_cds_length", "log_protein_length", "mapping_quality_score"],
    },
    {
        "pair_id": "rna_gc_to_protein_s_atoms",
        "x": "transcript_gc_fraction",
        "y": "protein_s_atoms_per_aa",
        "label": "CDS/transcript GC vs protein sulfur atoms per residue",
        "class": "nucleotide_to_protein_element",
        "primary_covariates": ["log_cds_length", "log_protein_length", "mapping_quality_score"],
    },
    {
        "pair_id": "rna_entropy_to_protein_entropy",
        "x": "transcript_entropy",
        "y": "protein_aa_entropy",
        "label": "Nucleotide entropy vs protein amino-acid entropy",
        "class": "complexity_transfer",
        "primary_covariates": ["log_cds_length", "log_protein_length", "transcript_gc_fraction", "mapping_quality_score"],
    },
    {
        "pair_id": "rna_length_to_protein_length",
        "x": "transcript_length",
        "y": "protein_length",
        "label": "Transcript/CDS length vs protein length",
        "class": "translation_length_consistency",
        "primary_covariates": ["transcript_gc_fraction", "mapping_quality_score"],
    },
    {
        "pair_id": "rna_gc_to_protein_complexity",
        "x": "transcript_gc_fraction",
        "y": "protein_aa_entropy",
        "label": "Transcript/CDS GC vs protein complexity",
        "class": "cross_omics_residual",
        "primary_covariates": ["log_cds_length", "log_protein_length", "mapping_quality_score"],
    },
]

NULL_MODELS = [
    ("N1_ID_PERMUTATION_LENGTH_GC_BIN", "Permute protein feature values within species-specific CDS length and transcript GC bins."),
    ("N2_SYNONYMOUS_CODON_RANDOMIZATION_DEGRADED", "True synonymous recoding requires codon-level CDS features; current model8 bundle uses transcript/CDS proxy features, so this endpoint records a GC-bin codon-bias proxy null."),
    ("N3_GC_LENGTH_MATCHED", "Compare observed association against stricter same-species GC and length matched permutations."),
    ("N4_PROTEIN_SEQUENCE_SHUFFLE_NOT_APPLICABLE", "Only order-dependent protein sequence features qualify; current protein features are composition/summary features."),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    ensure_dir(path.parent)
    if fields is None:
        fields = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_csv_gz(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    ensure_dir(path.parent)
    if fields is None:
        fields = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fields.append(key)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return round(value, 8)
    return value


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_seed(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return (int(digest[:16], 16) ^ SEED) % (2**32)


def norm_id(value: str) -> str:
    value = (value or "").strip()
    for prefix in ("gene:", "transcript:", "protein:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
    return value


def norm_id_noversion(value: str) -> str:
    value = norm_id(value)
    if "." in value:
        left, right = value.rsplit(".", 1)
        if right.isdigit():
            return left
    return value


def to_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def read_feature_map(path: Path, layer: str) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], int]:
    by_entity: dict[str, dict[str, Any]] = {}
    by_entity_noversion: dict[str, dict[str, Any]] = {}
    total = 0
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            total += 1
            entity_id = row.get("entity_id", "")
            if layer == "transcript":
                item = {
                    "transcript_entity_id": entity_id,
                    "transcript_length": to_float(row.get("length")),
                    "transcript_gc_fraction": to_float(row.get("gc_fraction")),
                    "transcript_n_fraction": to_float(row.get("n_fraction")),
                    "transcript_entropy": to_float(row.get("entropy")),
                    "transcript_header": row.get("header", ""),
                }
            else:
                item = {
                    "protein_entity_id": entity_id,
                    "protein_gene_id": row.get("gene_id", ""),
                    "protein_transcript_id": row.get("transcript_id", ""),
                    "protein_length": to_float(row.get("length")),
                    "protein_c_atoms_per_aa": to_float(row.get("c_atoms_per_aa")),
                    "protein_s_atoms_per_aa": to_float(row.get("s_atoms_per_aa")),
                    "protein_n_atoms_per_aa": to_float(row.get("n_atoms_per_aa")),
                    "protein_aa_entropy": to_float(row.get("aa_entropy")),
                    "protein_mw_approx": to_float(row.get("mw_approx")),
                    "protein_header": row.get("header", ""),
                }
            by_entity[norm_id(entity_id)] = item
            by_entity_noversion[norm_id_noversion(entity_id)] = item
    return by_entity, by_entity_noversion, total


def mapping_quality_score(status: str, reason: str) -> float:
    if status == "ok_high":
        return 1.0
    if status == "ok_medium":
        return 0.65
    if status.startswith("ok"):
        return 0.5
    return 0.0


def rank_average(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=float)
    sorted_vals = values[order]
    i = 0
    while i < values.size:
        j = i + 1
        while j < values.size and sorted_vals[j] == sorted_vals[i]:
            j += 1
        avg = (i + j - 1) / 2.0 + 1.0
        ranks[order[i:j]] = avg
        i = j
    return ranks


def pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    if x.size < 3 or y.size < 3:
        return None
    x0 = x - np.mean(x)
    y0 = y - np.mean(y)
    denom = float(np.sqrt(np.sum(x0 * x0) * np.sum(y0 * y0)))
    if denom == 0:
        return 0.0
    return float(np.sum(x0 * y0) / denom)


def spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    if x.size < 3:
        return None
    return pearson(rank_average(x), rank_average(y))


def clean_matrix(rows: list[dict[str, Any]], x_key: str, y_key: str, covariates: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x_vals = []
    y_vals = []
    cov = []
    for row in rows:
        x = to_float(row.get(x_key))
        y = to_float(row.get(y_key))
        if x is None or y is None:
            continue
        c_row = []
        ok = True
        for cov_key in covariates:
            val = to_float(row.get(cov_key))
            if val is None:
                ok = False
                break
            c_row.append(val)
        if ok:
            x_vals.append(x)
            y_vals.append(y)
            cov.append(c_row)
    return np.asarray(x_vals, dtype=float), np.asarray(y_vals, dtype=float), np.asarray(cov, dtype=float)


def residualize(v: np.ndarray, cov: np.ndarray) -> np.ndarray:
    if v.size == 0:
        return v
    if cov.size == 0:
        return v - np.mean(v)
    design = np.column_stack([np.ones(v.size), cov])
    beta, *_ = np.linalg.lstsq(design, v, rcond=None)
    return v - design @ beta


def partial_association(x: np.ndarray, y: np.ndarray, cov: np.ndarray) -> float | None:
    if x.size < 5:
        return None
    return pearson(residualize(x, cov), residualize(y, cov))


def huber_regression_beta(x: np.ndarray, y: np.ndarray, cov: np.ndarray, max_iter: int = 40) -> float | None:
    if x.size < 8:
        return None
    x_std = (x - np.mean(x)) / (np.std(x) or 1.0)
    y_std = (y - np.mean(y)) / (np.std(y) or 1.0)
    parts = [np.ones(x.size), x_std]
    if cov.size:
        cov_std = cov.copy()
        for j in range(cov_std.shape[1]):
            cov_std[:, j] = (cov_std[:, j] - np.mean(cov_std[:, j])) / (np.std(cov_std[:, j]) or 1.0)
        parts.append(cov_std)
    design = np.column_stack(parts)
    beta, *_ = np.linalg.lstsq(design, y_std, rcond=None)
    for _ in range(max_iter):
        resid = y_std - design @ beta
        scale = np.median(np.abs(resid - np.median(resid))) / 0.6745
        if not scale or not math.isfinite(scale):
            break
        cutoff = 1.345 * scale
        weights = np.minimum(1.0, cutoff / np.maximum(np.abs(resid), 1e-12))
        wd = design * weights[:, None]
        wy = y_std * weights
        new_beta, *_ = np.linalg.lstsq(wd, wy, rcond=None)
        if np.max(np.abs(new_beta - beta)) < 1e-6:
            beta = new_beta
            break
        beta = new_beta
    return float(beta[1])


def bh_fdr(rows: list[dict[str, Any]], p_key: str = "empirical_p", out_key: str = "bh_fdr") -> None:
    indexed = [(i, to_float(row.get(p_key))) for i, row in enumerate(rows)]
    indexed = [(i, p) for i, p in indexed if p is not None]
    m = len(indexed)
    if not m:
        return
    indexed.sort(key=lambda item: item[1])
    prev = 1.0
    for rank, (idx, p) in reversed(list(enumerate(indexed, 1))):
        q = min(prev, p * m / rank)
        rows[idx][out_key] = q
        prev = q


def assign_bins(rows: list[dict[str, Any]], strict: bool = False) -> dict[int, str]:
    lengths = np.asarray([float(row["log_cds_length"]) for row in rows], dtype=float)
    gcs = np.asarray([float(row["transcript_gc_fraction"]) for row in rows], dtype=float)
    n_bins = 5 if strict else 4
    l_edges = np.quantile(lengths, np.linspace(0, 1, n_bins + 1))
    g_edges = np.quantile(gcs, np.linspace(0, 1, n_bins + 1))
    out = {}
    for i, row in enumerate(rows):
        lb = int(np.searchsorted(l_edges[1:-1], row["log_cds_length"], side="right"))
        gb = int(np.searchsorted(g_edges[1:-1], row["transcript_gc_fraction"], side="right"))
        out[i] = f"L{lb}_G{gb}"
    return out


def null_spearman(x: np.ndarray, y: np.ndarray, bins: list[str], seed: int, n_null: int = N_NULL) -> np.ndarray:
    rng = np.random.default_rng(seed)
    unique_bins = sorted(set(bins))
    by_bin = {b: np.where(np.asarray(bins) == b)[0] for b in unique_bins}
    rx = rank_average(x)
    ry_base = rank_average(y)
    nulls = np.empty(n_null, dtype=float)
    for i in range(n_null):
        ry_perm = ry_base.copy()
        for idx in by_bin.values():
            if idx.size > 1:
                ry_perm[idx] = rng.permutation(ry_perm[idx])
        nulls[i] = pearson(rx, ry_perm) or 0.0
    return nulls


def empirical_p(observed: float, nulls: np.ndarray) -> float:
    return float((np.sum(np.abs(nulls) >= abs(observed)) + 1) / (nulls.size + 1))


def load_coupled_species(model8_dir: Path, code: str, manifest: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    transcript_by_id, transcript_by_noversion, transcript_total = read_feature_map(model8_dir / code / "features" / "transcript_features.tsv.gz", "transcript")
    protein_by_id, protein_by_noversion, protein_total = read_feature_map(model8_dir / code / "features" / "protein_features.tsv.gz", "protein")
    protein_by_transcript = {norm_id(item.get("protein_transcript_id", "")): item for item in protein_by_id.values() if item.get("protein_transcript_id")}
    protein_by_transcript_noversion = {norm_id_noversion(item.get("protein_transcript_id", "")): item for item in protein_by_id.values() if item.get("protein_transcript_id")}
    mapping_path = model8_dir / code / "mapping" / "id_chains.tsv.gz"
    rows = []
    all_isoform_rows = []
    stats = defaultdict(int)
    with gzip.open(mapping_path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for chain in reader:
            stats["mapping_rows"] += 1
            if chain.get("mapping_status", "").startswith("conflict") or "conflict" in chain.get("reason_code", ""):
                stats["conflict_rows"] += 1
                continue
            transcript_id = norm_id(chain.get("transcript_id") or chain.get("cds_parent_id") or "")
            protein_id = norm_id(chain.get("protein_id") or "")
            t = transcript_by_id.get(transcript_id) or transcript_by_noversion.get(norm_id_noversion(transcript_id))
            p = protein_by_id.get(protein_id) or protein_by_noversion.get(norm_id_noversion(protein_id))
            if p is None and transcript_id:
                p = protein_by_transcript.get(transcript_id) or protein_by_transcript_noversion.get(norm_id_noversion(transcript_id))
            if t is None:
                stats["missing_transcript_feature"] += 1
            if p is None:
                stats["missing_protein_feature"] += 1
            if t is None or p is None:
                continue
            stats["matched_rows"] += 1
            row = {
                "case_code": code,
                "species_id": manifest["species_id"],
                "scientific_name": manifest["scientific_name"],
                "division": manifest["division"],
                "gene_id": norm_id(chain.get("gene_id", "")),
                "transcript_id": transcript_id,
                "protein_id": protein_id or norm_id(p.get("protein_entity_id", "")),
                "is_canonical": str(chain.get("is_canonical", "")).lower() == "true",
                "canonical_rule": chain.get("canonical_rule", ""),
                "mapping_status": chain.get("mapping_status", ""),
                "reason_code": chain.get("reason_code", ""),
                "mapping_quality_score": mapping_quality_score(chain.get("mapping_status", ""), chain.get("reason_code", "")),
                "cds_length": to_float(chain.get("cds_length")) or t.get("transcript_length"),
                "mapping_protein_length": to_float(chain.get("protein_length")),
                **t,
                **p,
            }
            row["protein_length"] = row.get("protein_length") or row.get("mapping_protein_length")
            if row["cds_length"] and row["cds_length"] > 0:
                row["log_cds_length"] = math.log1p(row["cds_length"])
            else:
                row["log_cds_length"] = None
            if row["protein_length"] and row["protein_length"] > 0:
                row["log_protein_length"] = math.log1p(row["protein_length"])
            else:
                row["log_protein_length"] = None
            all_isoform_rows.append(row)
            if code in BACTERIA_CODES or row["is_canonical"]:
                rows.append(row)
    qc = {
        "case_code": code,
        "species_id": manifest["species_id"],
        "scientific_name": manifest["scientific_name"],
        "division": manifest["division"],
        "transcript_feature_rows": transcript_total,
        "protein_feature_rows": protein_total,
        "mapping_rows": stats["mapping_rows"],
        "matched_rows": stats["matched_rows"],
        "main_chain_rows": len(rows),
        "all_isoform_matched_rows": len(all_isoform_rows),
        "missing_transcript_feature": stats["missing_transcript_feature"],
        "missing_protein_feature": stats["missing_protein_feature"],
        "conflict_rows_excluded": stats["conflict_rows"],
        "chain_rate": len(rows) / stats["mapping_rows"] if stats["mapping_rows"] else 0,
        "conflict_rate": stats["conflict_rows"] / stats["mapping_rows"] if stats["mapping_rows"] else 0,
        "main_rule": "gene_to_canonical_transcript_to_protein" if code in EUKARYOTE_CODES else "locus_to_cds_to_protein",
    }
    return rows, qc, all_isoform_rows


def compute_stats_for_species(code: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    stats_rows = []
    null_rows = []
    top_rows = []
    if not rows:
        return stats_rows, null_rows, top_rows
    bin_loose_map = assign_bins(rows, strict=False)
    bin_strict_map = assign_bins(rows, strict=True)
    row_index = {id(row): idx for idx, row in enumerate(rows)}
    for pair in FEATURE_PAIRS:
        x, y, cov = clean_matrix(rows, pair["x"], pair["y"], pair["primary_covariates"])
        if x.size < 20:
            continue
        s = spearman(x, y)
        partial = partial_association(x, y, cov)
        huber = huber_regression_beta(x, y, cov)
        stat = {
            "case_code": code,
            "pair_id": pair["pair_id"],
            "pair_label": pair["label"],
            "pair_class": pair["class"],
            "n_entities": int(x.size),
            "spearman_rho": s,
            "partial_association": partial,
            "huber_beta_standardized": huber,
            "covariates": ";".join(pair["primary_covariates"]),
            "status": "computed",
        }
        stats_rows.append(stat)

        pair_rows = [row for row in rows if to_float(row.get(pair["x"])) is not None and to_float(row.get(pair["y"])) is not None and all(to_float(row.get(k)) is not None for k in pair["primary_covariates"])]
        if len(pair_rows) > NULL_ROW_CAP:
            rng = random.Random(stable_seed(f"{code}:{pair['pair_id']}:cap"))
            pair_rows = [pair_rows[i] for i in sorted(rng.sample(range(len(pair_rows)), NULL_ROW_CAP))]
            x, y, cov = clean_matrix(pair_rows, pair["x"], pair["y"], pair["primary_covariates"])
        loose_bins = [bin_loose_map[row_index[id(row)]] for row in pair_rows]
        strict_bins = [bin_strict_map[row_index[id(row)]] for row in pair_rows]
        for model_id, desc in NULL_MODELS:
            if model_id == "N4_PROTEIN_SEQUENCE_SHUFFLE_NOT_APPLICABLE":
                null_rows.append({
                    "case_code": code,
                    "pair_id": pair["pair_id"],
                    "null_model": model_id,
                    "observed": s,
                    "null_mean": None,
                    "null_sd": None,
                    "excess": None,
                    "empirical_p": None,
                    "bh_fdr": None,
                    "n_null": 0,
                    "status": "not_applicable_current_features",
                    "method": desc,
                })
                continue
            bins = strict_bins if model_id == "N3_GC_LENGTH_MATCHED" else loose_bins
            if model_id == "N2_SYNONYMOUS_CODON_RANDOMIZATION_DEGRADED":
                status = "degraded_gc_bin_proxy_no_true_synonymous_recoding"
            else:
                status = "computed"
            nulls = null_spearman(x, y, bins, stable_seed(f"{code}:{pair['pair_id']}:{model_id}"))
            null_rows.append({
                "case_code": code,
                "pair_id": pair["pair_id"],
                "null_model": model_id,
                "observed": s,
                "null_mean": float(np.mean(nulls)),
                "null_sd": float(np.std(nulls, ddof=1)),
                "excess": None if s is None else float(s - np.mean(nulls)),
                "empirical_p": empirical_p(s or 0.0, nulls),
                "bh_fdr": None,
                "n_null": int(nulls.size),
                "status": status,
                "method": desc,
            })

        design = np.column_stack([np.ones(x.size), x, cov])
        beta, *_ = np.linalg.lstsq(design, y, rcond=None)
        residual = y - design @ beta
        rz = (residual - np.mean(residual)) / (np.std(residual) or 1.0)
        sorted_idx = np.argsort(rz)
        for label, indices in [("negative_residual", sorted_idx[:TOP_ENTITY_N]), ("positive_residual", sorted_idx[-TOP_ENTITY_N:][::-1])]:
            for idx in indices:
                source = pair_rows[int(idx)]
                top_rows.append({
                    "case_code": code,
                    "pair_id": pair["pair_id"],
                    "residual_class": label,
                    "residual_z": float(rz[int(idx)]),
                    "gene_id": source.get("gene_id"),
                    "transcript_id": source.get("transcript_id"),
                    "protein_id": source.get("protein_id"),
                    "x_value": float(x[int(idx)]),
                    "y_value": float(y[int(idx)]),
                    "entity_label_policy": "high residual transformation candidate; not causal driver",
                })
    bh_fdr(null_rows)
    return stats_rows, null_rows, top_rows


def meta_summary(stat_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for pair in FEATURE_PAIRS:
        for group_id, codes in [("six_eukaryotes", EUKARYOTE_CODES), ("two_bacteria", BACTERIA_CODES)]:
            rows = [r for r in stat_rows if r["pair_id"] == pair["pair_id"] and r["case_code"] in codes and r.get("spearman_rho") is not None]
            if not rows:
                continue
            zs = []
            weights = []
            for row in rows:
                rho = max(-0.999999, min(0.999999, float(row["spearman_rho"])))
                zs.append(math.atanh(rho))
                weights.append(max(1, int(row["n_entities"]) - 3))
            z = float(np.average(np.asarray(zs), weights=np.asarray(weights)))
            out.append({
                "group_id": group_id,
                "pair_id": pair["pair_id"],
                "pair_label": pair["label"],
                "species_count": len(rows),
                "weighted_meta_spearman": math.tanh(z),
                "direction_consistent_count": sum(1 for r in rows if (r["spearman_rho"] or 0) >= 0),
                "method": "Fisher z weighted by n_entities-3; bacteria and eukaryotes summarized separately",
            })
    return out


def sensitivity(all_isoform_by_code: dict[str, list[dict[str, Any]]], canonical_stats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    canonical_lookup = {(r["case_code"], r["pair_id"]): r for r in canonical_stats}
    for code, rows in all_isoform_by_code.items():
        for pair in FEATURE_PAIRS:
            x, y, cov = clean_matrix(rows, pair["x"], pair["y"], pair["primary_covariates"])
            sens = spearman(x, y) if x.size >= 20 else None
            base = canonical_lookup.get((code, pair["pair_id"]), {})
            out.append({
                "case_code": code,
                "pair_id": pair["pair_id"],
                "sensitivity_mode": "all_isoforms" if code in EUKARYOTE_CODES else "all_loci_same_as_main_bacteria",
                "main_n": base.get("n_entities"),
                "sensitivity_n": int(x.size),
                "main_spearman": base.get("spearman_rho"),
                "sensitivity_spearman": sens,
                "delta_spearman": None if sens is None or base.get("spearman_rho") is None else sens - base.get("spearman_rho"),
                "status": "computed" if x.size >= 20 else "insufficient_matched_rows",
            })
    return out


def build_case2(model8_dir: Path, output_dir: Path) -> dict[str, Any]:
    ensure_dir(output_dir)
    manifest_rows = read_tsv(model8_dir / "model8_reference_manifest.tsv")
    manifest_by_code = {row["case_code"]: row for row in manifest_rows}
    all_main: list[dict[str, Any]] = []
    all_isoform_by_code: dict[str, list[dict[str, Any]]] = {}
    qc_rows = []
    for code in SPECIES_ORDER:
        main_rows, qc, all_isoforms = load_coupled_species(model8_dir, code, manifest_by_code[code])
        all_main.extend(main_rows)
        all_isoform_by_code[code] = all_isoforms
        qc_rows.append(qc)

    stat_rows: list[dict[str, Any]] = []
    null_rows: list[dict[str, Any]] = []
    top_rows: list[dict[str, Any]] = []
    for code in SPECIES_ORDER:
        rows = [row for row in all_main if row["case_code"] == code]
        s_rows, n_rows, t_rows = compute_stats_for_species(code, rows)
        stat_rows.extend(s_rows)
        null_rows.extend(n_rows)
        top_rows.extend(t_rows)
    bh_fdr(null_rows)
    meta_rows = meta_summary(stat_rows)
    sensitivity_rows = sensitivity(all_isoform_by_code, stat_rows)

    entity_fields = [
        "case_code", "species_id", "scientific_name", "division", "gene_id", "transcript_id", "protein_id", "is_canonical",
        "canonical_rule", "mapping_status", "reason_code", "mapping_quality_score", "cds_length", "transcript_length",
        "transcript_gc_fraction", "transcript_n_fraction", "transcript_entropy", "protein_length", "protein_c_atoms_per_aa",
        "protein_s_atoms_per_aa", "protein_n_atoms_per_aa", "protein_aa_entropy", "protein_mw_approx", "log_cds_length",
        "log_protein_length",
    ]
    write_csv_gz(output_dir / "case2_coupled_entities.csv.gz", all_main, entity_fields)
    write_csv(output_dir / "case2_chain_qc.csv", qc_rows)
    write_csv(output_dir / "case2_coupling_statistics.csv", stat_rows)
    write_csv(output_dir / "case2_null_model_results.csv", null_rows)
    write_csv(output_dir / "case2_meta_summary.csv", meta_rows)
    write_csv(output_dir / "case2_top_transformations.csv", top_rows)
    write_csv(output_dir / "case2_sensitivity_analysis.csv", sensitivity_rows)
    feature_rows = [{**pair, "covariates": ";".join(pair["primary_covariates"])} for pair in FEATURE_PAIRS]
    write_csv(output_dir / "case2_feature_pairs.csv", feature_rows)
    null_spec_rows = [{"null_model": model, "method": method} for model, method in NULL_MODELS]
    write_csv(output_dir / "case2_null_model_spec.csv", null_spec_rows)
    figure_mapping = [
        {"figure_id": "case2_chain_qc", "title": "Species chain rate and conflict rate", "source_file": "case2_chain_qc.csv", "payload_json": "summary.json"},
        {"figure_id": "case2_observed_coupling_heatmap", "title": "Per-species observed Spearman coupling", "source_file": "case2_coupling_statistics.csv", "payload_json": "coupling.json"},
        {"figure_id": "case2_partial_vs_observed", "title": "Observed vs partial association", "source_file": "case2_coupling_statistics.csv", "payload_json": "coupling.json"},
        {"figure_id": "case2_null_comparison", "title": "Observed vs null distribution summary", "source_file": "case2_null_model_results.csv", "payload_json": "null_models.json"},
        {"figure_id": "case2_top_transformations", "title": "High residual transformation candidates", "source_file": "case2_top_transformations.csv", "payload_json": "coupling.json"},
        {"figure_id": "case2_meta_summary", "title": "Eukaryote and bacteria separated meta summary", "source_file": "case2_meta_summary.csv", "payload_json": "coupling.json"},
        {"figure_id": "case2_sensitivity", "title": "Canonical/all-isoform sensitivity", "source_file": "case2_sensitivity_analysis.csv", "payload_json": "sensitivity.json"},
    ]
    write_csv(output_dir / "case2_figure_mapping.csv", figure_mapping)
    statistical_plan = {
        "case_id": "model8_case2_dna_cds_rna_protein_coupling",
        "case_version": CASE2_VERSION,
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
        "generated_at": now_iso(),
        "random_seed": SEED,
        "n_null": N_NULL,
        "species_order": SPECIES_ORDER,
        "feature_pairs": FEATURE_PAIRS,
        "null_models": NULL_MODELS,
        "rules": [
            "Each species is analyzed independently; no species-unstructured stacked entity matrix is used for main evidence.",
            "Six eukaryotes are meta-summarized separately from the two bacteria.",
            "Conflict rows are excluded from main evidence.",
            "Top residual entities are labeled as transformation candidates, not causal drivers.",
            "Observed coupling is sequence-derived association and does not imply expression or protein abundance regulation.",
        ],
        "known_degradations": [
            "True synonymous codon randomization is not fully executable from the current model8 feature bundle because codon-level CDS features/GC3 are not present for all eight species.",
            "N2 is therefore exported as a downgraded GC-bin codon-bias proxy null and is marked as degraded in case2_null_model_results.csv.",
            "Protein sequence shuffle is not applicable to current composition/summary protein features and is marked not_applicable_current_features.",
        ],
    }
    write_json(output_dir / "case2_statistical_plan.json", statistical_plan)

    artifacts = []
    for name in [
        "case2_coupled_entities.csv.gz",
        "case2_chain_qc.csv",
        "case2_coupling_statistics.csv",
        "case2_null_model_results.csv",
        "case2_meta_summary.csv",
        "case2_top_transformations.csv",
        "case2_sensitivity_analysis.csv",
        "case2_feature_pairs.csv",
        "case2_null_model_spec.csv",
        "case2_figure_mapping.csv",
        "case2_statistical_plan.json",
    ]:
        path = output_dir / name
        artifacts.append({"name": name, "path": str(path.relative_to(model8_dir)), "bytes": path.stat().st_size, "sha256": file_sha256(path)})

    summary_payload = {
        "id": "model8_case2",
        "title": "Model-8 Case 2: DNA/CDS-RNA-Protein cross-omics coupling",
        "case_version": CASE2_VERSION,
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
        "status": "implemented_with_declared_degradations",
        "generated_at": now_iso(),
        "species_count": len(SPECIES_ORDER),
        "main_entity_count": len(all_main),
        "feature_pair_count": len(FEATURE_PAIRS),
        "null_model_count": len(NULL_MODELS),
        "n_null": N_NULL,
        "chain_qc": qc_rows,
        "downloads": artifacts,
        "statistical_plan": statistical_plan,
        "finding_boundary": [
            "This case reports sequence-derived DNA/CDS-RNA-Protein association within each species.",
            "It does not claim expression regulation, protein abundance regulation, ecological adaptation, or phylogenetic signal.",
        ],
        "implementation_notes": statistical_plan["known_degradations"],
    }
    coupling_payload = {
        "id": "model8_case2_coupling",
        "feature_pairs": FEATURE_PAIRS,
        "statistics": stat_rows,
        "meta_summary": meta_rows,
        "top_transformations": top_rows[:480],
        "heatmap": {
            "x_labels": [pair["label"] for pair in FEATURE_PAIRS],
            "x_keys": [pair["pair_id"] for pair in FEATURE_PAIRS],
            "y_labels": SPECIES_ORDER,
            "values": [
                [
                    next((row.get("spearman_rho") for row in stat_rows if row["case_code"] == code and row["pair_id"] == pair["pair_id"]), None)
                    for pair in FEATURE_PAIRS
                ]
                for code in SPECIES_ORDER
            ],
        },
    }
    null_payload = {
        "id": "model8_case2_null_models",
        "null_models": null_spec_rows,
        "results": null_rows,
    }
    sensitivity_payload = {
        "id": "model8_case2_sensitivity",
        "rows": sensitivity_rows,
        "policy": {
            "canonical_rule": "Eukaryotes use one canonical chain per gene in main evidence; bacteria use locus/CDS/protein chains.",
            "all_isoform": "All matched isoforms are exported as sensitivity only.",
            "id_conflicts": "Conflict rows are excluded from main evidence; current A1 conflicts are zero in the model8 bundle.",
        },
    }
    write_json(output_dir / "summary.json", summary_payload)
    write_json(output_dir / "coupling.json", coupling_payload)
    write_json(output_dir / "null_models.json", null_payload)
    write_json(output_dir / "sensitivity.json", sensitivity_payload)
    return summary_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Model-8 Case 2 DNA/CDS-RNA-Protein coupling artifacts.")
    parser.add_argument("--model8-dir", default=str(Path(__file__).resolve().parents[1] / "data" / "case_studies" / "model8"))
    parser.add_argument("--output-dir", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model8_dir = Path(args.model8_dir).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else model8_dir / "case2_coupling"
    payload = build_case2(model8_dir, output_dir)
    print(json.dumps({"status": payload["status"], "output_dir": str(output_dir), "downloads": len(payload["downloads"]), "main_entity_count": payload["main_entity_count"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
