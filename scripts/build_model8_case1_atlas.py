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
N_BOOTSTRAP = 1000
BOOTSTRAP_ENTITY_CAP = 1000
PAIRWISE_SAMPLE_CAP = 5000
CASE1_VERSION = "model8_case1_atlas_v2_elemental"

OMICS_FILES = {
    "genome": "genome_features.tsv.gz",
    "transcript": "transcript_features.tsv.gz",
    "protein": "protein_features.tsv.gz",
}

FEATURE_SPECS = [
    {"key": "genome_length", "omics": "genome", "column": "length", "label": "Genome sequence length", "unit": "bp"},
    {"key": "genome_gc_fraction", "omics": "genome", "column": "gc_fraction", "label": "Genome GC fraction", "unit": "fraction"},
    {"key": "genome_n_fraction", "omics": "genome", "column": "n_fraction", "label": "Genome N fraction", "unit": "fraction"},
    {"key": "genome_entropy", "omics": "genome", "column": "entropy", "label": "Genome sequence entropy", "unit": "bits"},
    {"key": "transcript_length", "omics": "transcript", "column": "length", "label": "Transcript/CDS length", "unit": "nt"},
    {"key": "transcript_gc_fraction", "omics": "transcript", "column": "gc_fraction", "label": "Transcript/CDS GC fraction", "unit": "fraction"},
    {"key": "transcript_n_fraction", "omics": "transcript", "column": "n_fraction", "label": "Transcript/CDS N fraction", "unit": "fraction"},
    {"key": "transcript_entropy", "omics": "transcript", "column": "entropy", "label": "Transcript/CDS sequence entropy", "unit": "bits"},
    {"key": "protein_length", "omics": "protein", "column": "length", "label": "Protein length", "unit": "aa"},
    {"key": "protein_c_atoms_per_aa", "omics": "protein", "column": "c_atoms_per_aa", "label": "Protein carbon atoms per residue", "unit": "atoms/aa"},
    {"key": "protein_s_atoms_per_aa", "omics": "protein", "column": "s_atoms_per_aa", "label": "Protein sulfur atoms per residue", "unit": "atoms/aa"},
    {"key": "protein_n_atoms_per_aa", "omics": "protein", "column": "n_atoms_per_aa", "label": "Protein nitrogen atoms per residue", "unit": "atoms/aa"},
    {"key": "protein_aa_entropy", "omics": "protein", "column": "aa_entropy", "label": "Protein amino-acid entropy", "unit": "bits"},
    {"key": "protein_mw_approx", "omics": "protein", "column": "mw_approx", "label": "Protein approximate MW", "unit": "Da"},
]

PREDEFINED_CONTRASTS = [
    ("ECOLI", "BSUB", "E. coli vs B. subtilis"),
    ("ORYSA", "ARATH", "Rice vs Arabidopsis"),
    ("DANRE", "MOUSE", "Zebrafish vs mouse"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    ensure_dir(path.parent)
    if fields is None:
        keys: list[str] = []
        seen = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        fields = keys
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


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


def to_float(text: str) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def robust_summary(values: np.ndarray) -> dict[str, Any]:
    if values.size == 0:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "sd": None,
            "mad": None,
            "q05": None,
            "q25": None,
            "q75": None,
            "q95": None,
            "min": None,
            "max": None,
        }
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median))) if values.size else None
    return {
        "n": int(values.size),
        "mean": float(np.mean(values)),
        "median": median,
        "sd": float(np.std(values, ddof=1)) if values.size > 1 else 0.0,
        "mad": mad,
        "q05": float(np.quantile(values, 0.05)),
        "q25": float(np.quantile(values, 0.25)),
        "q75": float(np.quantile(values, 0.75)),
        "q95": float(np.quantile(values, 0.95)),
        "min": float(np.min(values)),
        "max": float(np.max(values)),
    }


def deterministic_sample(values: np.ndarray, cap: int, seed_text: str) -> np.ndarray:
    if values.size <= cap:
        return values
    rng = random.Random(stable_seed(seed_text))
    indices = rng.sample(range(values.size), cap)
    return values[np.array(indices, dtype=np.int64)]


def bootstrap_median_ci(values: np.ndarray, seed: int, n_bootstrap: int = N_BOOTSTRAP) -> dict[str, Any]:
    if values.size == 0:
        return {"bootstrap_n": 0, "draw_size": 0, "median_ci_low": None, "median_ci_high": None, "bootstrap_median_sd": None}
    rng = np.random.default_rng(seed)
    draw_size = int(min(values.size, BOOTSTRAP_ENTITY_CAP))
    draws = rng.choice(values, size=(n_bootstrap, draw_size), replace=True)
    medians = np.median(draws, axis=1)
    return {
        "bootstrap_n": int(n_bootstrap),
        "draw_size": draw_size,
        "median_ci_low": float(np.quantile(medians, 0.025)),
        "median_ci_high": float(np.quantile(medians, 0.975)),
        "bootstrap_median_sd": float(np.std(medians, ddof=1)),
    }


def read_feature_table(path: Path, columns: list[str]) -> tuple[dict[str, np.ndarray], int, list[str]]:
    values: dict[str, list[float]] = {column: [] for column in columns}
    headers: list[str] = []
    total_rows = 0
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        headers = reader.fieldnames or []
        for row in reader:
            total_rows += 1
            for column in columns:
                val = to_float(row.get(column, ""))
                if val is not None:
                    values[column].append(val)
    arrays = {column: np.asarray(items, dtype=float) for column, items in values.items()}
    return arrays, total_rows, headers


def load_canonical_sets(model8_dir: Path, code: str) -> dict[str, set[str]]:
    path = model8_dir / code / "mapping" / "id_chains.tsv.gz"
    out = {"transcript": set(), "protein": set()}
    if not path.exists():
        return out
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            if str(row.get("is_canonical", "")).lower() != "true":
                continue
            transcript_id = row.get("transcript_id") or row.get("cds_parent_id") or ""
            protein_id = row.get("protein_id") or ""
            if transcript_id:
                out["transcript"].add(transcript_id)
            if protein_id:
                out["protein"].add(protein_id)
    return out


def read_feature_table_filtered(path: Path, columns: list[str], allowed_ids: set[str]) -> dict[str, np.ndarray]:
    values: dict[str, list[float]] = {column: [] for column in columns}
    if not allowed_ids:
        return {column: np.asarray([], dtype=float) for column in columns}
    with gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            entity_id = row.get("entity_id") or row.get("transcript_id") or row.get("protein_id") or ""
            if entity_id not in allowed_ids:
                continue
            for column in columns:
                val = to_float(row.get(column, ""))
                if val is not None:
                    values[column].append(val)
    return {column: np.asarray(items, dtype=float) for column, items in values.items()}


def cliff_delta_sample(a: np.ndarray, b: np.ndarray, seed_text: str) -> float | None:
    a_s = deterministic_sample(a, min(PAIRWISE_SAMPLE_CAP, 2000), seed_text + ":a")
    b_s = deterministic_sample(b, min(PAIRWISE_SAMPLE_CAP, 2000), seed_text + ":b")
    if a_s.size == 0 or b_s.size == 0:
        return None
    greater = 0
    less = 0
    for value in a_s:
        greater += int(np.sum(value > b_s))
        less += int(np.sum(value < b_s))
    return float((greater - less) / (a_s.size * b_s.size))


def wasserstein_quantile(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.size == 0 or b.size == 0:
        return None
    qs = np.linspace(0.01, 0.99, 99)
    return float(np.mean(np.abs(np.quantile(a, qs) - np.quantile(b, qs))))


def standardized_median_difference(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.size == 0 or b.size == 0:
        return None
    pooled = math.sqrt((float(np.var(a)) + float(np.var(b))) / 2.0)
    if pooled == 0:
        mad_a = float(np.median(np.abs(a - np.median(a)))) if a.size else 0.0
        mad_b = float(np.median(np.abs(b - np.median(b)))) if b.size else 0.0
        pooled = (mad_a + mad_b) / 2.0
    if pooled == 0:
        return 0.0
    return float((np.median(a) - np.median(b)) / pooled)


def pca_payload(matrix: np.ndarray, species_rows: list[dict[str, Any]], feature_keys: list[str]) -> dict[str, Any]:
    if matrix.shape[0] < 2 or matrix.shape[1] < 2:
        return {"available": False, "reason": "matrix too small"}
    clean = np.nan_to_num(matrix, nan=0.0)
    clean = clean - clean.mean(axis=0, keepdims=True)
    u, s, vt = np.linalg.svd(clean, full_matrices=False)
    coords = u[:, :2] * s[:2]
    denom = float(np.sum(s ** 2)) or 1.0
    loadings = vt[:2, :].T
    return {
        "available": True,
        "explained_variance_ratio": [float((s[i] ** 2) / denom) if i < len(s) else 0.0 for i in range(2)],
        "points": [
            {
                "case_code": row["case_code"],
                "species_id": row["species_id"],
                "scientific_name": row["scientific_name"],
                "division": row["division"],
                "pc1": float(coords[i, 0]),
                "pc2": float(coords[i, 1]) if coords.shape[1] > 1 else 0.0,
            }
            for i, row in enumerate(species_rows)
        ],
        "loadings": [
            {"feature": feature_keys[i], "pc1": float(loadings[i, 0]), "pc2": float(loadings[i, 1]) if loadings.shape[1] > 1 else 0.0}
            for i in range(len(feature_keys))
        ],
    }


def build_case1(model8_dir: Path, output_dir: Path) -> dict[str, Any]:
    manifest_rows = read_tsv(model8_dir / "model8_reference_manifest.tsv")
    manifest_by_code = {row["case_code"]: row for row in manifest_rows}
    ensure_dir(output_dir)

    feature_by_omics: dict[str, list[dict[str, str]]] = defaultdict(list)
    for spec in FEATURE_SPECS:
        feature_by_omics[spec["omics"]].append(spec)

    raw_values: dict[str, dict[str, np.ndarray]] = {}
    summary_rows: list[dict[str, Any]] = []
    bootstrap_rows: list[dict[str, Any]] = []
    species_rows: list[dict[str, Any]] = []
    sensitivity_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []

    for code in SPECIES_ORDER:
        manifest = manifest_by_code[code]
        species_row = {
            "case_code": code,
            "species_id": manifest["species_id"],
            "scientific_name": manifest["scientific_name"],
            "division": manifest["division"],
            "tax_id": manifest["tax_id"],
            "assembly_accession": manifest["assembly_accession"],
            "genome_release": manifest["genome_release"],
            "reference_identity_rule": manifest["reference_identity_rule"],
            "qc_status": manifest["qc_status"],
        }
        canonical = load_canonical_sets(model8_dir, code)
        for omics, specs in feature_by_omics.items():
            path = model8_dir / code / "features" / OMICS_FILES[omics]
            columns = [spec["column"] for spec in specs]
            arrays, total_rows, headers = read_feature_table(path, columns)
            coverage_rows.append({
                "case_code": code,
                "omics": omics,
                "feature_file": str(path.relative_to(model8_dir)),
                "total_rows": total_rows,
                "available_columns": ";".join(headers),
                "sha256": file_sha256(path),
            })
            for spec in specs:
                key = spec["key"]
                values = arrays[spec["column"]]
                raw_values.setdefault(code, {})[key] = values
                stats = robust_summary(values)
                summary_rows.append({
                    **species_row,
                    "omics": omics,
                    "feature": key,
                    "feature_label": spec["label"],
                    "source_column": spec["column"],
                    "unit": spec["unit"],
                    **stats,
                })
                ci = bootstrap_median_ci(values, seed=stable_seed(f"{code}:{key}:bootstrap"))
                bootstrap_rows.append({
                    "case_code": code,
                    "species_id": manifest["species_id"],
                    "scientific_name": manifest["scientific_name"],
                    "division": manifest["division"],
                    "omics": omics,
                    "feature": key,
                    "feature_label": spec["label"],
                    "statistic": "median",
                    "full_entity_n": int(values.size),
                    **ci,
                    "bootstrap_mode": "entity_resampling",
                    "random_seed": SEED,
                    "large_table_draw_cap": BOOTSTRAP_ENTITY_CAP,
                })
                if values.size:
                    trimmed = values[(values >= np.quantile(values, 0.01)) & (values <= np.quantile(values, 0.99))]
                else:
                    trimmed = values
                sensitivity_rows.append({
                    "case_code": code,
                    "omics": omics,
                    "feature": key,
                    "sensitivity_mode": "remove_extreme_1pct_each_tail",
                    "baseline_median": stats["median"],
                    "sensitivity_median": robust_summary(trimmed)["median"],
                    "baseline_n": int(values.size),
                    "sensitivity_n": int(trimmed.size),
                    "status": "computed",
                })
            if omics in {"transcript", "protein"}:
                allowed = canonical[omics]
                filtered = read_feature_table_filtered(path, columns, allowed)
                for spec in specs:
                    key = spec["key"]
                    base = robust_summary(arrays[spec["column"]])
                    filt = robust_summary(filtered[spec["column"]])
                    sensitivity_rows.append({
                        "case_code": code,
                        "omics": omics,
                        "feature": key,
                        "sensitivity_mode": "canonical_only",
                        "baseline_median": base["median"],
                        "sensitivity_median": filt["median"],
                        "baseline_n": int(arrays[spec["column"]].size),
                        "sensitivity_n": int(filtered[spec["column"]].size),
                        "status": "computed" if filtered[spec["column"]].size else "not_available",
                    })
            else:
                for spec in specs:
                    base = robust_summary(arrays[spec["column"]])
                    sensitivity_rows.append({
                        "case_code": code,
                        "omics": omics,
                        "feature": spec["key"],
                        "sensitivity_mode": "canonical_only",
                        "baseline_median": base["median"],
                        "sensitivity_median": base["median"],
                        "baseline_n": int(arrays[spec["column"]].size),
                        "sensitivity_n": int(arrays[spec["column"]].size),
                        "status": "not_applicable_genome_layer",
                    })
        species_rows.append(species_row)

    feature_keys = [spec["key"] for spec in FEATURE_SPECS]
    matrix_rows: list[dict[str, Any]] = []
    medians_by_code: dict[str, dict[str, float | None]] = defaultdict(dict)
    for row in summary_rows:
        medians_by_code[row["case_code"]][row["feature"]] = row["median"]

    feature_stats: dict[str, tuple[float, float]] = {}
    for key in feature_keys:
        vals = [medians_by_code[code].get(key) for code in SPECIES_ORDER]
        clean = np.asarray([v for v in vals if v is not None], dtype=float)
        center = float(np.mean(clean)) if clean.size else 0.0
        spread = float(np.std(clean)) if clean.size else 1.0
        if spread == 0:
            spread = 1.0
        feature_stats[key] = (center, spread)

    matrix_np = np.zeros((len(SPECIES_ORDER), len(feature_keys)), dtype=float)
    for i, code in enumerate(SPECIES_ORDER):
        meta = manifest_by_code[code]
        out = {
            "case_code": code,
            "species_id": meta["species_id"],
            "scientific_name": meta["scientific_name"],
            "division": meta["division"],
        }
        for j, key in enumerate(feature_keys):
            raw = medians_by_code[code].get(key)
            center, spread = feature_stats[key]
            z = None if raw is None else (float(raw) - center) / spread
            matrix_np[i, j] = 0.0 if z is None else z
            out[f"{key}_median"] = raw
            out[f"{key}_zscore"] = z
        matrix_rows.append(out)

    pairwise_rows: list[dict[str, Any]] = []
    distance_rows: list[dict[str, Any]] = []
    for i, code_a in enumerate(SPECIES_ORDER):
        for code_b in SPECIES_ORDER[i + 1:]:
            dist = float(np.linalg.norm(matrix_np[SPECIES_ORDER.index(code_a)] - matrix_np[SPECIES_ORDER.index(code_b)]))
            distance_rows.append({
                "species_a": code_a,
                "species_b": code_b,
                "euclidean_distance_zscore_median_matrix": dist,
                "predefined_contrast": any({code_a, code_b} == {x, y} for x, y, _ in PREDEFINED_CONTRASTS),
            })
            for spec in FEATURE_SPECS:
                key = spec["key"]
                a = raw_values[code_a][key]
                b = raw_values[code_b][key]
                pairwise_rows.append({
                    "contrast": f"{code_a}_vs_{code_b}",
                    "contrast_label": next((label for x, y, label in PREDEFINED_CONTRASTS if {x, y} == {code_a, code_b}), "all model-8 pair"),
                    "species_a": code_a,
                    "species_b": code_b,
                    "omics": spec["omics"],
                    "feature": key,
                    "feature_label": spec["label"],
                    "n_a": int(a.size),
                    "n_b": int(b.size),
                    "median_a": robust_summary(a)["median"],
                    "median_b": robust_summary(b)["median"],
                    "standardized_median_difference": standardized_median_difference(a, b),
                    "cliffs_delta_sampled": cliff_delta_sample(a, b, f"{code_a}:{code_b}:{key}"),
                    "wasserstein_distance_quantile": wasserstein_quantile(a, b),
                    "sample_cap": PAIRWISE_SAMPLE_CAP,
                    "predefined_contrast": any({code_a, code_b} == {x, y} for x, y, _ in PREDEFINED_CONTRASTS),
                })

    for spec in FEATURE_SPECS:
        key = spec["key"]
        bacteria = np.concatenate([raw_values[code][key] for code in SPECIES_ORDER if code in BACTERIA_CODES])
        euks = np.concatenate([raw_values[code][key] for code in SPECIES_ORDER if code in EUKARYOTE_CODES])
        pairwise_rows.append({
            "contrast": "BACTERIA_vs_SIX_EUKARYOTES",
            "contrast_label": "Bacteria vs six eukaryotes descriptive aggregate",
            "species_a": "ECOLI+BSUB",
            "species_b": "ORYSA+DROME+YEAST+ARATH+DANRE+MOUSE",
            "omics": spec["omics"],
            "feature": key,
            "feature_label": spec["label"],
            "n_a": int(bacteria.size),
            "n_b": int(euks.size),
            "median_a": robust_summary(bacteria)["median"],
            "median_b": robust_summary(euks)["median"],
            "standardized_median_difference": standardized_median_difference(bacteria, euks),
            "cliffs_delta_sampled": cliff_delta_sample(bacteria, euks, f"bacteria:euk:{key}"),
            "wasserstein_distance_quantile": wasserstein_quantile(bacteria, euks),
            "sample_cap": PAIRWISE_SAMPLE_CAP,
            "predefined_contrast": True,
        })

    pca = pca_payload(matrix_np, species_rows, feature_keys)
    feature_rank_rows = []
    for spec in FEATURE_SPECS:
        key = spec["key"]
        values = [(code, medians_by_code[code].get(key)) for code in SPECIES_ORDER]
        values = [(code, value) for code, value in values if value is not None]
        values.sort(key=lambda item: item[1], reverse=True)
        for rank, (code, value) in enumerate(values, 1):
            feature_rank_rows.append({
                "feature": key,
                "feature_label": spec["label"],
                "rank_desc": rank,
                "case_code": code,
                "median": value,
            })

    distribution_samples = []
    ecdf_rows = []
    for code in SPECIES_ORDER:
        for spec in FEATURE_SPECS:
            key = spec["key"]
            vals = deterministic_sample(raw_values[code][key], 400, f"{code}:{key}:distribution")
            for value in vals:
                distribution_samples.append({"case_code": code, "feature": key, "value": float(value)})
            if vals.size:
                sorted_vals = np.sort(vals)
                for q in np.linspace(0.05, 0.95, 19):
                    ecdf_rows.append({"case_code": code, "feature": key, "q": float(q), "value": float(np.quantile(sorted_vals, q))})

    figure_mapping_rows = [
        {"figure_id": "case1_heatmap", "title": "8 x frozen-feature z-score heatmap", "source_file": "model8_fingerprint_matrix.csv", "payload_json": "matrix.json"},
        {"figure_id": "case1_pca", "title": "Two-dimensional PCA projection", "source_file": "model8_fingerprint_matrix.csv;pca_coordinates.csv", "payload_json": "matrix.json"},
        {"figure_id": "case1_parallel_coordinates", "title": "Parallel coordinates over z-scored medians", "source_file": "model8_fingerprint_matrix.csv", "payload_json": "matrix.json"},
        {"figure_id": "case1_pairwise_distance", "title": "Pairwise z-score Euclidean distance", "source_file": "pairwise_distance_matrix.csv", "payload_json": "pairwise.json"},
        {"figure_id": "case1_feature_rank", "title": "Feature rank by species median", "source_file": "feature_rank.csv", "payload_json": "matrix.json"},
        {"figure_id": "case1_distribution_violin_ecdf", "title": "Entity distribution samples and ECDF quantiles", "source_file": "distribution_samples.csv;ecdf_quantiles.csv", "payload_json": "summary.json"},
        {"figure_id": "case1_bootstrap_ci", "title": "Bootstrap median confidence intervals", "source_file": "bootstrap_ci.csv", "payload_json": "summary.json"},
        {"figure_id": "case1_sensitivity", "title": "Canonical-only and trimmed-entity sensitivity", "source_file": "sensitivity_analysis.csv", "payload_json": "sensitivity.json"},
    ]

    write_csv(output_dir / "model8_species_summary.csv", summary_rows)
    write_csv(output_dir / "model8_fingerprint_matrix.csv", matrix_rows)
    write_csv(output_dir / "pairwise_effects.csv", pairwise_rows)
    write_csv(output_dir / "pairwise_distance_matrix.csv", distance_rows)
    write_csv(output_dir / "bootstrap_ci.csv", bootstrap_rows)
    write_csv(output_dir / "sensitivity_analysis.csv", sensitivity_rows)
    write_csv(output_dir / "feature_rank.csv", feature_rank_rows)
    write_csv(output_dir / "distribution_samples.csv", distribution_samples)
    write_csv(output_dir / "ecdf_quantiles.csv", ecdf_rows)
    write_csv(output_dir / "figure_mapping.csv", figure_mapping_rows)
    write_csv(output_dir / "feature_file_coverage.csv", coverage_rows)
    write_csv(output_dir / "pca_coordinates.csv", pca.get("points", []))
    write_csv(output_dir / "pca_loadings.csv", pca.get("loadings", []))

    frozen_plan = {
        "case_id": "model8_case1_cross_domain_stoichiometric_fingerprint_atlas",
        "case_version": CASE1_VERSION,
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
        "generated_at": now_iso(),
        "random_seed": SEED,
        "n_bootstrap": N_BOOTSTRAP,
        "bootstrap_entity_draw_cap": BOOTSTRAP_ENTITY_CAP,
        "pairwise_sample_cap": PAIRWISE_SAMPLE_CAP,
        "species_order": SPECIES_ORDER,
        "frozen_features": FEATURE_SPECS,
        "predefined_contrasts": [
            {"species_a": a, "species_b": b, "label": label} for a, b, label in PREDEFINED_CONTRASTS
        ] + [{"species_a": "ECOLI+BSUB", "species_b": "six_eukaryotes", "label": "descriptive aggregate only"}],
        "interpretation_boundary": [
            "This fixed eight-species case is a reference-coordinate and descriptive distribution analysis.",
            "It must not be written as whole-database generality, ecological adaptation, or phylogenetic signal.",
        ],
    }
    write_json(output_dir / "case1_statistical_plan.json", frozen_plan)

    artifacts = []
    for name in [
        "model8_species_summary.csv",
        "model8_fingerprint_matrix.csv",
        "pairwise_effects.csv",
        "pairwise_distance_matrix.csv",
        "bootstrap_ci.csv",
        "sensitivity_analysis.csv",
        "figure_mapping.csv",
        "feature_rank.csv",
        "distribution_samples.csv",
        "ecdf_quantiles.csv",
        "feature_file_coverage.csv",
        "pca_coordinates.csv",
        "pca_loadings.csv",
        "case1_statistical_plan.json",
    ]:
        path = output_dir / name
        artifacts.append({"name": name, "path": str(path.relative_to(model8_dir)), "sha256": file_sha256(path), "bytes": path.stat().st_size})

    summary_payload = {
        "id": "model8_case1",
        "title": "Model-8 Atlas: cross-domain sequence stoichiometric fingerprint atlas",
        "case_version": CASE1_VERSION,
        "elemental_contract_id": ELEMENTAL_CONTRACT_ID,
        "status": "implemented",
        "generated_at": now_iso(),
        "source_release": json.loads((model8_dir / "model8_release_manifest.json").read_text(encoding="utf-8")),
        "species_count": len(SPECIES_ORDER),
        "omics_layers": ["genome", "transcript", "protein"],
        "feature_count": len(FEATURE_SPECS),
        "entity_row_coverage": coverage_rows,
        "statistical_plan": frozen_plan,
        "species": species_rows,
        "feature_catalog": FEATURE_SPECS,
        "downloads": artifacts,
        "summary_table_preview": summary_rows[:24],
        "matrix_preview": matrix_rows,
        "bootstrap_preview": bootstrap_rows[:24],
        "figure_mapping": figure_mapping_rows,
        "scientific_result_boundary": [
            "Full-entity robust summaries are computed from the local Model-8 A0-A3 feature tables.",
            "Z-scores are visualization coordinates only; raw medians, units, and distribution summaries are retained.",
            "Pairwise effects are descriptive and use pre-fixed contrasts plus all-pair distance support.",
            "Canonical-only sensitivity is available for transcript/protein layers through A1 id_chains; genome layer is not applicable.",
        ],
        "implementation_notes": [
            "The feature extraction inputs are the Model-8 A0-A3 feature tables generated from the project's full-feature extraction-compatible script path.",
            f"Bootstrap uses {N_BOOTSTRAP} replicates. For large tables, each replicate draws at most {BOOTSTRAP_ENTITY_CAP} entities; this is recorded in bootstrap_ci.csv.",
            "No new phylogeny, ecological adaptation, or whole-database generalization claim is introduced.",
        ],
    }
    matrix_payload = {
        "id": "model8_case1_matrix",
        "features": FEATURE_SPECS,
        "rows": matrix_rows,
        "zscore_matrix": {
            "x_labels": [spec["label"] for spec in FEATURE_SPECS],
            "x_keys": feature_keys,
            "y_labels": [manifest_by_code[code]["scientific_name"] for code in SPECIES_ORDER],
            "values": matrix_np.tolist(),
        },
        "pca": pca,
        "feature_rank": feature_rank_rows,
        "parallel_coordinates": matrix_rows,
    }
    pairwise_payload = {
        "id": "model8_case1_pairwise",
        "predefined_contrasts": frozen_plan["predefined_contrasts"],
        "pairwise_distance": distance_rows,
        "effects": pairwise_rows,
    }
    sensitivity_payload = {
        "id": "model8_case1_sensitivity",
        "rows": sensitivity_rows,
        "bootstrap_ci": bootstrap_rows,
        "policy": {
            "canonical_all_isoform": "canonical-only sensitivity for transcript/protein; all-entity baseline retained",
            "core_full": "current A0-A3 bundle supplies full feature tables; no separate core table is available in this model8 bundle",
            "extreme_length": "1st-99th percentile retained sensitivity computed for every feature",
            "alternative_normalization": "raw medians and cross-species z-scores are both exported",
        },
    }
    write_json(output_dir / "summary.json", summary_payload)
    write_json(output_dir / "matrix.json", matrix_payload)
    write_json(output_dir / "pairwise.json", pairwise_payload)
    write_json(output_dir / "sensitivity.json", sensitivity_payload)
    return summary_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Model-8 Case 1 cross-domain stoichiometric fingerprint atlas artifacts.")
    parser.add_argument("--model8-dir", default=str(Path(__file__).resolve().parents[1] / "data" / "case_studies" / "model8"))
    parser.add_argument("--output-dir", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model8_dir = Path(args.model8_dir).resolve()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else model8_dir / "case1_atlas"
    payload = build_case1(model8_dir, output_dir)
    print(json.dumps({"status": payload["status"], "output_dir": str(output_dir), "downloads": len(payload["downloads"])}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
