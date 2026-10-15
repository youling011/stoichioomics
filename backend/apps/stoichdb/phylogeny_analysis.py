from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
import math
from typing import Any

import numpy as np
from Bio import Phylo
from scipy import optimize, stats


class PhylogenyAnalysisError(ValueError):
    pass


@dataclass(frozen=True)
class TreeMatrix:
    tips: list[str]
    covariance: np.ndarray
    distance: np.ndarray


def parse_newick(newick: str):
    if not newick or not newick.strip():
        raise PhylogenyAnalysisError("Empty Newick tree.")
    return Phylo.read(StringIO(newick), "newick")


def terminal_names(tree) -> list[str]:
    names = []
    for terminal in tree.get_terminals():
        if not terminal.name:
            raise PhylogenyAnalysisError("Every terminal tip must have a name.")
        names.append(terminal.name)
    return names


def has_complete_branch_lengths(tree) -> bool:
    for clade in tree.find_clades(order="level"):
        if clade is tree.root:
            continue
        if clade.branch_length is None:
            return False
        if not math.isfinite(float(clade.branch_length)):
            return False
    return True


def tree_matrix_from_newick(newick: str, requested_tips: list[str] | None = None) -> TreeMatrix:
    tree = parse_newick(newick)
    if not has_complete_branch_lengths(tree):
        raise PhylogenyAnalysisError("Tree has no complete branch lengths; lambda/PGLS are disabled.")
    all_tips = terminal_names(tree)
    tips = [tip for tip in (requested_tips or all_tips) if tip in all_tips]
    if len(tips) < 3:
        raise PhylogenyAnalysisError("At least three matched tips are required.")

    root_depth = tree.depths(unit_branch_lengths=False)
    distance = np.zeros((len(tips), len(tips)), dtype=float)
    covariance = np.zeros((len(tips), len(tips)), dtype=float)
    terminals = {terminal.name: terminal for terminal in tree.get_terminals()}
    for i, left in enumerate(tips):
        left_clade = terminals[left]
        covariance[i, i] = float(root_depth[left_clade])
        for j in range(i + 1, len(tips)):
            right = tips[j]
            right_clade = terminals[right]
            distance_ij = float(tree.distance(left_clade, right_clade))
            mrca = tree.common_ancestor(left_clade, right_clade)
            shared = float(root_depth[mrca])
            distance[i, j] = distance[j, i] = distance_ij
            covariance[i, j] = covariance[j, i] = shared
    return TreeMatrix(tips=tips, covariance=covariance, distance=distance)


def lambda_covariance(covariance: np.ndarray, lam: float) -> np.ndarray:
    lam = min(1.0, max(0.0, float(lam)))
    out = np.array(covariance, dtype=float, copy=True)
    off_diag = ~np.eye(out.shape[0], dtype=bool)
    out[off_diag] *= lam
    jitter = max(float(np.nanmax(np.diag(out))) * 1e-8, 1e-8)
    out += np.eye(out.shape[0]) * jitter
    return out


def _neg_log_likelihood(y: np.ndarray, covariance: np.ndarray, lam: float) -> float:
    cov = lambda_covariance(covariance, lam)
    X = np.ones((len(y), 1), dtype=float)
    beta, residuals, sigma2, logdet = _gls_core(y, X, cov)
    if not math.isfinite(sigma2) or sigma2 <= 0:
        return float("inf")
    n = len(y)
    return 0.5 * (n * (math.log(2.0 * math.pi) + math.log(sigma2)) + logdet + n)


def pagel_lambda(y_values: list[float], covariance: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y_values, dtype=float)
    if y.ndim != 1 or len(y) < 4:
        raise PhylogenyAnalysisError("At least four numeric observations are required for lambda.")
    if np.isnan(y).any():
        raise PhylogenyAnalysisError("Trait vector contains missing values.")

    result = optimize.minimize_scalar(
        lambda value: _neg_log_likelihood(y, covariance, value),
        bounds=(0.0, 1.0),
        method="bounded",
        options={"xatol": 1e-4},
    )
    lam = float(result.x)
    ll_opt = -float(result.fun)
    ll_zero = -_neg_log_likelihood(y, covariance, 0.0)
    lr = max(0.0, 2.0 * (ll_opt - ll_zero))
    p_value = float(stats.chi2.sf(lr, 1))
    return {
        "lambda": round(lam, 6),
        "log_likelihood": round(ll_opt, 6),
        "lr_vs_lambda0": round(lr, 6),
        "p_value": p_value,
        "n": int(len(y)),
        "optimizer_success": bool(result.success),
    }


def _gls_core(y: np.ndarray, X: np.ndarray, covariance: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    inv_cov = np.linalg.pinv(covariance)
    xt_vinv = X.T @ inv_cov
    beta = np.linalg.pinv(xt_vinv @ X) @ xt_vinv @ y
    residuals = y - X @ beta
    rss = float(residuals.T @ inv_cov @ residuals)
    n = len(y)
    k = X.shape[1]
    sigma2 = rss / max(n - k, 1)
    sign, logdet = np.linalg.slogdet(covariance)
    if sign <= 0:
        logdet = float("nan")
    return beta, residuals, sigma2, float(logdet)


def fit_linear_model(y_values: list[float], x_columns: dict[str, list[float]], covariance: np.ndarray | None = None) -> dict[str, Any]:
    names = ["Intercept"] + list(x_columns.keys())
    y = np.asarray(y_values, dtype=float)
    cols = [np.ones(len(y), dtype=float)]
    for name in names[1:]:
        cols.append(np.asarray(x_columns[name], dtype=float))
    X = np.column_stack(cols)
    mask = np.isfinite(y)
    for col in cols:
        mask &= np.isfinite(col)
    y = y[mask]
    X = X[mask, :]
    if covariance is not None:
        covariance = np.asarray(covariance, dtype=float)[np.ix_(mask, mask)]
    if len(y) <= X.shape[1] + 1:
        raise PhylogenyAnalysisError("Not enough complete observations for model fitting.")

    cov = np.eye(len(y), dtype=float) if covariance is None else covariance
    beta, residuals, sigma2, logdet = _gls_core(y, X, cov)
    inv_cov = np.linalg.pinv(cov)
    xt_vinv_x = X.T @ inv_cov @ X
    beta_cov = np.linalg.pinv(xt_vinv_x) * sigma2
    se = np.sqrt(np.maximum(np.diag(beta_cov), 0.0))
    t_values = beta / np.where(se == 0.0, np.nan, se)
    df = max(len(y) - X.shape[1], 1)
    p_values = 2.0 * stats.t.sf(np.abs(t_values), df)
    fitted = X @ beta
    rss = float(residuals.T @ inv_cov @ residuals)
    tss = float(np.sum((y - np.mean(y)) ** 2))
    return {
        "n": int(len(y)),
        "df_resid": int(df),
        "terms": [
            {
                "term": name,
                "beta": float(beta[idx]),
                "std_error": float(se[idx]),
                "t_value": float(t_values[idx]) if math.isfinite(float(t_values[idx])) else None,
                "p_value": float(p_values[idx]) if math.isfinite(float(p_values[idx])) else None,
            }
            for idx, name in enumerate(names)
        ],
        "rss": rss,
        "r_squared": None if tss <= 0 else float(1.0 - np.sum(residuals**2) / tss),
        "sigma2": float(sigma2),
        "logdet": logdet,
        "residuals": [float(value) for value in residuals],
        "fitted": [float(value) for value in fitted],
    }


def parse_formula(formula: str, allowed_features: set[str]) -> tuple[str, list[str]]:
    if "~" not in formula:
        raise PhylogenyAnalysisError("Formula must use the form 'y ~ x1 + x2'.")
    left, right = [part.strip() for part in formula.split("~", 1)]
    predictors = [item.strip() for item in right.split("+") if item.strip()]
    if not left or not predictors:
        raise PhylogenyAnalysisError("Formula requires one response and at least one predictor.")
    fields = [left] + predictors
    illegal = [field for field in fields if field not in allowed_features]
    if illegal:
        raise PhylogenyAnalysisError(f"Unsupported feature(s): {', '.join(illegal)}")
    return left, predictors
