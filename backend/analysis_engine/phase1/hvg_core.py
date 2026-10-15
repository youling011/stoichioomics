from __future__ import annotations

from typing import Dict, Literal, Tuple

import numpy as np
import pandas as pd
from scipy import sparse

from backend.analysis_engine.common import ExpressionDataset


DispersionFlavor = Literal["seurat", "cell_ranger"]


def _safe_sample_variance(matrix: sparse.csr_matrix) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = matrix.shape[0]
    sum_x = np.asarray(matrix.sum(axis=0)).ravel().astype(np.float64)
    squared = matrix.copy().astype(np.float64)
    squared.data **= 2
    sum_x2 = np.asarray(squared.sum(axis=0)).ravel()
    mean = sum_x / max(n, 1)
    if n > 1:
        var = (sum_x2 - (sum_x**2) / n) / (n - 1)
    else:
        var = np.zeros_like(mean)
    var[var < 0] = 0.0
    return mean, var, sum_x


def _mean_bins(mean: np.ndarray, flavor: DispersionFlavor, n_bins: int) -> pd.Series:
    means = pd.Series(mean, dtype="float64")
    if flavor == "seurat":
        bins = max(1, int(n_bins))
    elif flavor == "cell_ranger":
        bins = np.r_[-np.inf, np.percentile(mean, np.arange(10, 105, 5)), np.inf]
    else:
        raise ValueError(f"Unsupported dispersion flavor: {flavor}")
    return pd.cut(means, bins=bins, duplicates="drop")


def _mad(values: pd.Series) -> float:
    vals = values.to_numpy(dtype=np.float64)
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return np.nan
    med = np.median(vals)
    return float(np.median(np.abs(vals - med)) * 1.4826)


def _standardized_dispersion(
    mean: np.ndarray,
    variance: np.ndarray,
    *,
    flavor: DispersionFlavor = "seurat",
    n_bins: int = 20,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Scanpy/Seurat-compatible dispersion normalization for log-normalized data."""
    work_mean = mean.astype(np.float64, copy=True)
    work_var = variance.astype(np.float64, copy=True)
    valid = np.isfinite(work_mean) & np.isfinite(work_var)
    work_mean[valid & (work_mean == 0)] = 1e-12

    dispersion = np.divide(
        work_var,
        work_mean,
        out=np.full_like(work_var, np.nan, dtype=np.float64),
        where=valid & (work_mean > 0),
    )
    if flavor == "seurat":
        dispersion[dispersion == 0] = np.nan
        dispersion = np.log(dispersion)
        binned_mean = np.log1p(work_mean)
    else:
        binned_mean = work_mean

    df = pd.DataFrame({"mean": binned_mean, "dispersion": dispersion})
    usable = np.isfinite(df["mean"].to_numpy()) & np.isfinite(df["dispersion"].to_numpy())
    normalized = np.full(mean.shape, np.nan, dtype=np.float64)
    if usable.sum() == 0:
        return dispersion, normalized, binned_mean

    sub = df.loc[usable].copy()
    sub["mean_bin"] = _mean_bins(sub["mean"].to_numpy(dtype=np.float64), flavor, n_bins)
    grouped = sub.groupby("mean_bin", observed=True)["dispersion"]
    if flavor == "seurat":
        stats = grouped.agg(avg="mean", dev="std")
        one_gene_bins = stats["dev"].isna()
        if one_gene_bins.any():
            stats.loc[one_gene_bins, "dev"] = stats.loc[one_gene_bins, "avg"]
            stats.loc[one_gene_bins, "avg"] = 0.0
    else:
        stats = grouped.agg(avg="median", dev=_mad)

    aligned = stats.loc[sub["mean_bin"]].set_index(sub.index)
    dev = aligned["dev"].to_numpy(dtype=np.float64)
    avg = aligned["avg"].to_numpy(dtype=np.float64)
    disp = sub["dispersion"].to_numpy(dtype=np.float64)
    z = np.divide(disp - avg, dev, out=np.zeros_like(disp), where=np.isfinite(dev) & (dev > 0))
    normalized[sub.index.to_numpy()] = z
    return dispersion, normalized, binned_mean


def _sparse_sum_and_sum_squares_clipped(
    matrix: sparse.csr_matrix,
    clip_val: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    counts = matrix.tocsr(copy=False)
    n_genes = counts.shape[1]
    indices = counts.indices
    data = counts.data.astype(np.float64, copy=False)
    clipped = np.minimum(data, clip_val[indices])
    clipped_sum = np.bincount(indices, weights=clipped, minlength=n_genes).astype(np.float64)
    squared_sum = np.bincount(indices, weights=clipped * clipped, minlength=n_genes).astype(np.float64)
    return squared_sum, clipped_sum


def _seurat_v3_normalized_variance(
    matrix: sparse.csr_matrix,
    mean: np.ndarray,
    variance: np.ndarray,
    *,
    span: float = 0.3,
    clip_max: float | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Seurat v3/Scanpy HVG score: regularized-SD normalized variance."""
    try:
        from skmisc.loess import loess
    except ImportError as exc:
        raise ImportError(
            "The standard seurat_v3 HVG method requires scikit-misc "
            "(`pip install scikit-misc`) for the LOESS mean-variance fit."
        ) from exc

    n_cells, n_genes = matrix.shape
    if n_cells < 2:
        raise ValueError("seurat_v3 HVG requires at least two cells.")

    mean = mean.astype(np.float64, copy=False)
    variance = variance.astype(np.float64, copy=False)
    valid = np.isfinite(mean) & np.isfinite(variance) & (mean > 0) & (variance > 0)
    if valid.sum() < 3:
        raise ValueError("seurat_v3 HVG requires at least three non-constant expressed genes.")

    estimated_log_var = np.full(n_genes, np.nan, dtype=np.float64)
    model = loess(np.log10(mean[valid]), np.log10(variance[valid]), span=float(span), degree=2)
    model.fit()
    estimated_log_var[valid] = model.outputs.fitted_values
    regularized_sd = np.sqrt(np.power(10.0, estimated_log_var))

    vmax = float(np.sqrt(n_cells) if clip_max is None else clip_max)
    clip_val = regularized_sd * vmax + mean
    clip_val[~np.isfinite(clip_val)] = np.inf

    squared_sum, clipped_sum = _sparse_sum_and_sum_squares_clipped(matrix, clip_val)
    denominator = (n_cells - 1) * np.square(regularized_sd)
    numerator = (n_cells * np.square(mean)) + squared_sum - (2.0 * clipped_sum * mean)
    normalized_variance = np.divide(
        numerator,
        denominator,
        out=np.full(n_genes, np.nan, dtype=np.float64),
        where=np.isfinite(denominator) & (denominator > 0),
    )
    normalized_variance[~valid] = 0.0
    normalized_variance[normalized_variance < 0] = 0.0
    return normalized_variance, estimated_log_var, regularized_sd


def _rank_scores(scores: np.ndarray, n_top_genes: int) -> Tuple[np.ndarray, np.ndarray]:
    clean = np.nan_to_num(scores, nan=-np.inf, posinf=np.inf, neginf=-np.inf)
    order = np.argsort(clean, kind="mergesort")[::-1]
    ranks = np.empty_like(order)
    ranks[order] = np.arange(1, len(order) + 1)
    is_hvg = ranks <= min(int(n_top_genes), len(order))
    return ranks, is_hvg


def run_hvg_baseline(
    dataset: ExpressionDataset,
    method: str = "dispersion",
    n_top_genes: int = 2000,
    n_bins: int = 20,
    loess_span: float = 0.3,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    matrix = dataset.matrix.tocsr(copy=False)
    mean_expr, variance, sum_x = _safe_sample_variance(matrix)
    csc = matrix.tocsc(copy=False)
    n_cells_by_counts = np.diff(csc.indptr).astype(np.int64)
    mean_nonzero = np.divide(sum_x, np.maximum(n_cells_by_counts, 1), dtype=np.float64)
    raw_dispersion = np.divide(
        variance,
        mean_expr,
        out=np.full_like(variance, np.nan, dtype=np.float64),
        where=mean_expr > 0,
    )

    method_lower = method.lower()
    vst_log10_variance_fit = np.full(dataset.n_genes, np.nan, dtype=np.float64)
    regularized_sd = np.full(dataset.n_genes, np.nan, dtype=np.float64)

    if method_lower in {"vst", "seurat_v3", "seurat_v3_like", "seurat_v3_paper"}:
        hvg_score, vst_log10_variance_fit, regularized_sd = _seurat_v3_normalized_variance(
            matrix,
            mean_expr,
            variance,
            span=loess_span,
        )
        normalized_dispersion = hvg_score.copy()
        dispersion = raw_dispersion
        score_semantics = "seurat_v3_variance_normalized"
        method_family = "seurat_v3"
        input_assumption = "raw_count_matrix_required_by_seurat_v3"
        standard_reference = "Seurat v3 variance stabilizing HVG / Scanpy highly_variable_genes(seurat_v3)"
    elif method_lower in {"seurat", "cell_ranger"}:
        dispersion, normalized_dispersion, _ = _standardized_dispersion(
            mean_expr,
            variance,
            flavor=method_lower,  # type: ignore[arg-type]
            n_bins=n_bins,
        )
        hvg_score = normalized_dispersion.copy()
        score_semantics = f"{method_lower}_mean_bin_normalized_dispersion"
        method_family = method_lower
        input_assumption = "log_normalized_matrix_expected_by_dispersion_flavors"
        standard_reference = f"Scanpy highly_variable_genes({method_lower}) mean-bin normalized dispersion"
    elif method_lower == "dispersion":
        dispersion = raw_dispersion
        normalized_dispersion = raw_dispersion.copy()
        hvg_score = raw_dispersion.copy()
        score_semantics = "raw_variance_to_mean_dispersion"
        method_family = "dispersion"
        input_assumption = "count_or_count_like_non_negative_matrix"
        standard_reference = "Raw variance-to-mean dispersion ranking"
    else:
        raise ValueError(f"Unsupported hvg_method: {method}")

    ranks, is_hvg = _rank_scores(hvg_score, n_top_genes)
    df = pd.DataFrame(
        {
            "gene_id": dataset.gene_ids,
            "gene_name": dataset.gene_names,
            "mean_expr": mean_expr,
            "mean_nonzero_expr": mean_nonzero,
            "variance": variance,
            "dispersion": dispersion,
            "raw_dispersion": raw_dispersion,
            "normalized_dispersion": normalized_dispersion,
            "variances_norm": hvg_score if method_family == "seurat_v3" else np.nan,
            "vst_log10_variance_fit": vst_log10_variance_fit,
            "regularized_sd": regularized_sd,
            "hvg_score": hvg_score,
            "n_cells_detected": n_cells_by_counts,
            "pct_cells_detected": n_cells_by_counts / max(dataset.n_cells, 1),
            "dropout_rate": 1.0 - (n_cells_by_counts / max(dataset.n_cells, 1)),
            "hvg_rank": ranks,
            "is_hvg": is_hvg,
            "hvg_method": method_lower,
            "hvg_score_semantics": score_semantics,
        }
    )
    summary = {
        "n_cells": int(dataset.n_cells),
        "n_genes": int(dataset.n_genes),
        "n_hvgs": int(is_hvg.sum()),
        "method": method_lower,
        "method_family": method_family,
        "hvg_score_semantics": score_semantics,
        "n_top_genes": int(min(int(n_top_genes), len(ranks))),
        "n_bins": int(n_bins),
        "loess_span": float(loess_span),
        "input_assumption": input_assumption,
        "standard_reference": standard_reference,
    }
    return df, summary
