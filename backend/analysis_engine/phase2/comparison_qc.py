from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


TRUE_VALUES = {"1", "true", "t", "yes", "y", "hvg", "coding", "valid"}
FALSE_VALUES = {"0", "false", "f", "no", "n", "non_hvg", "non-hvg", "noncoding", "invalid"}


def coerce_hvg_mask(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    numeric = pd.to_numeric(series, errors="coerce")
    text = series.fillna("").astype(str).str.strip().str.lower()
    out = pd.Series(False, index=series.index, dtype=bool)
    out.loc[numeric.notna()] = numeric.loc[numeric.notna()] != 0
    out.loc[text.isin(TRUE_VALUES)] = True
    out.loc[text.isin(FALSE_VALUES)] = False
    return out


def _binary_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype("Float64")
    numeric = pd.to_numeric(series, errors="coerce")
    text = series.fillna("").astype(str).str.strip().str.lower()
    out = pd.Series(pd.NA, index=series.index, dtype="Float64")
    valid_numeric = numeric.notna() & numeric.isin([0, 1])
    out.loc[valid_numeric] = numeric.loc[valid_numeric]
    out.loc[text.isin(TRUE_VALUES)] = 1.0
    out.loc[text.isin(FALSE_VALUES)] = 0.0
    return out.astype(float)


def _append_warning(current: Any, warning: str) -> str:
    values = [item for item in str(current or "").split(";") if item]
    if warning not in values:
        values.append(warning)
    return ";".join(values)


def _applicability_mask(df: pd.DataFrame, meta: dict[str, Any]) -> tuple[pd.Series | None, str]:
    applicability = str(meta.get("applicability") or "all")
    if applicability == "all":
        return pd.Series(True, index=df.index, dtype=bool), "all"
    if applicability == "coding_only":
        candidates = [
            meta.get("applicability_column"), "genome__coding_valid", "genome__is_coding",
            "coding_valid", "is_coding",
        ]
        for column in candidates:
            if column and str(column) in df.columns:
                parsed = _binary_series(df[str(column)]).astype("boolean")
                if parsed.notna().any():
                    return parsed, str(column)
        return None, ""
    if applicability == "protein_proxy_only":
        candidates = [
            meta.get("applicability_column"), "transcriptome__orf_valid", "transcriptome__orf_len_aa",
            "orf_valid", "orf_len_aa",
        ]
        for column in candidates:
            if not column or str(column) not in df.columns:
                continue
            if "len_aa" in str(column).lower():
                values = pd.to_numeric(df[str(column)], errors="coerce")
                if values.notna().any():
                    return (values > 0).astype("boolean"), str(column)
            else:
                parsed = _binary_series(df[str(column)]).astype("boolean")
                if parsed.notna().any():
                    return parsed, str(column)
        return None, ""
    return None, "unsupported"


def _set_final_status(meta: dict[str, Any], status: str, reason: str) -> None:
    meta["status"] = status
    meta["reason"] = reason
    meta["analysis_status"] = status
    meta["analysis_reason"] = reason


def run_comparison_qc(
    df: pd.DataFrame,
    selected: list[dict[str, Any]],
    audit: pd.DataFrame,
    *,
    hvg_flag_col: str = "is_hvg",
    min_group_n: int = 20,
    max_missing_rate: float = 0.50,
    applicable_values: set[str] | None = None,
    near_constant_tolerance: float = 1e-12,
    high_correlation_threshold: float = 0.995,
) -> tuple[list[dict[str, Any]], pd.DataFrame, dict[str, pd.Series]]:
    hvg_mask = coerce_hvg_mask(df[hvg_flag_col])
    total_hvg = int(hvg_mask.sum())
    total_nonhvg = int((~hvg_mask).sum())
    prepared: dict[str, pd.Series] = {}
    selected_by_key = {row["feature_key"]: dict(row) for row in selected}
    allowed_applicability = applicable_values or {"all", "coding_only", "protein_proxy_only"}

    for feature_key, meta in selected_by_key.items():
        source = str(meta.get("source_column") or "")
        semantic = str(meta.get("semantic_type") or "continuous")
        applicability = str(meta.get("applicability") or "all")
        if applicability not in allowed_applicability:
            _set_final_status(meta, "skipped", "not_applicable")
            continue
        if not source or source not in df.columns:
            _set_final_status(meta, "skipped", "missing_source_column")
            continue
        applicability_mask, mask_source = _applicability_mask(df, meta)
        if applicability_mask is None:
            _set_final_status(meta, "skipped", "missing_applicability_mask" if applicability in {"coding_only", "protein_proxy_only"} else "not_applicable")
            meta.update({
                "n_applicable_total": 0, "n_applicable_hvg": 0, "n_applicable_non_hvg": 0,
                "n_valid_hvg": 0, "n_valid_non_hvg": 0,
            })
            continue
        applicable_bool = applicability_mask.fillna(False).astype(bool)
        warnings = str(meta.get("warnings") or "")
        if applicability_mask.isna().any():
            warnings = _append_warning(warnings, f"applicability_mask_missing_rows:n={int(applicability_mask.isna().sum())}")

        raw = df[source]
        nonfinite_n = 0
        out_of_range_n = 0
        if semantic == "binary":
            values = _binary_series(raw)
            nonfinite_n = int(raw.notna().sum() - values.notna().sum())
        elif semantic in {"continuous", "count", "composition"}:
            values = pd.to_numeric(raw, errors="coerce").astype(float)
            finite = np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))
            nonfinite_n = int((raw.notna() & ~pd.Series(finite, index=raw.index)).sum())
            values.loc[~finite] = np.nan
            bounded_min = meta.get("bounded_min")
            bounded_max = meta.get("bounded_max")
            invalid_bounds = pd.Series(False, index=values.index)
            if bounded_min is not None:
                below = values < float(bounded_min)
                invalid_bounds |= below
                if float(bounded_min) >= 0 and below.any():
                    warnings = _append_warning(warnings, f"invalid_negative:n={int(below.sum())}")
            if bounded_max is not None:
                invalid_bounds |= values > float(bounded_max)
            if invalid_bounds.any():
                out_of_range_n = int(invalid_bounds.sum())
                warnings = _append_warning(warnings, f"out_of_registry_range:n={out_of_range_n}")
                if bounded_max is not None and float(bounded_max) <= 1 and out_of_range_n >= max(1, int(raw.notna().sum() * 0.5)):
                    warnings = _append_warning(warnings, "unit_anomaly")
                values.loc[invalid_bounds] = np.nan
        elif semantic == "categorical_code":
            values = raw.astype("string").str.strip().replace("", pd.NA)
        else:
            _set_final_status(meta, "skipped", "schema_type_error")
            continue

        # v2 semantics: applicability is row-level, while a real numeric zero
        # in an applicable row remains a valid observation.
        values = values.where(applicable_bool, np.nan)
        n_applicable_total = int(applicable_bool.sum())
        n_applicable_hvg = int((applicable_bool & hvg_mask).sum())
        n_applicable_nonhvg = int((applicable_bool & ~hvg_mask).sum())
        hvg_values = values.loc[hvg_mask & applicable_bool].dropna()
        nonhvg_values = values.loc[(~hvg_mask) & applicable_bool].dropna()
        n_hvg = int(hvg_values.shape[0])
        n_nonhvg = int(nonhvg_values.shape[0])
        missing_hvg = max(n_applicable_hvg - n_hvg, 0)
        missing_nonhvg = max(n_applicable_nonhvg - n_nonhvg, 0)
        missing_rate_hvg = missing_hvg / max(n_applicable_hvg, 1)
        missing_rate_nonhvg = missing_nonhvg / max(n_applicable_nonhvg, 1)

        meta.update({
            "n_hvg": n_hvg, "n_nonhvg": n_nonhvg,
            "missing_hvg": missing_hvg, "missing_nonhvg": missing_nonhvg,
            "missing_rate_hvg": missing_rate_hvg, "missing_rate_nonhvg": missing_rate_nonhvg,
            "missing_rate": max(missing_rate_hvg, missing_rate_nonhvg),
            "nonfinite_n": nonfinite_n, "out_of_range_n": out_of_range_n,
            "warnings": warnings, "applicability_column": mask_source,
            "n_applicable_total": n_applicable_total, "n_applicable_hvg": n_applicable_hvg,
            "n_applicable_nonhvg": n_applicable_nonhvg, "n_valid_hvg": n_hvg,
            "n_valid_nonhvg": n_nonhvg,
        })
        if nonfinite_n:
            meta["warnings"] = _append_warning(meta["warnings"], f"non_finite_values:n={nonfinite_n}")
        if n_applicable_total == 0:
            _set_final_status(meta, "skipped", "missing_applicability_mask")
        elif n_hvg + n_nonhvg == 0:
            reason = "out_of_range" if out_of_range_n else "schema_type_error" if raw.notna().any() else "all_missing"
            _set_final_status(meta, "skipped", reason)
        elif n_hvg == 0 or n_nonhvg == 0:
            _set_final_status(meta, "skipped", "insufficient_group_n")
        elif n_hvg < min_group_n or n_nonhvg < min_group_n:
            _set_final_status(meta, "skipped", "insufficient_group_n")
        elif max(missing_rate_hvg, missing_rate_nonhvg) > max_missing_rate:
            _set_final_status(meta, "skipped", "high_missing_rate")
        elif values.dropna().nunique() < 2:
            _set_final_status(meta, "skipped", "constant")
        elif semantic in {"continuous", "count", "composition"} and float(values.dropna().std(ddof=0)) <= near_constant_tolerance:
            _set_final_status(meta, "skipped", "near_constant")
        else:
            _set_final_status(meta, "tested", "")
            if meta.get("family") == "length_count" or any(token in str(meta.get("feature_name") or "").lower() for token in ("total_atoms", "total_mass", "molecular_weight", "mw_da")):
                meta["warnings"] = _append_warning(meta["warnings"], "length_related_proxy")
            if meta.get("composition_group"):
                meta["warnings"] = _append_warning(meta["warnings"], "compositional_dependence")
            prepared[feature_key] = values

    signatures: dict[int, list[str]] = {}
    for feature_key, values in prepared.items():
        signature = int(pd.util.hash_pandas_object(values, index=False).sum())
        signatures.setdefault(signature, []).append(feature_key)
    for keys in signatures.values():
        if len(keys) < 2:
            continue
        ordered = sorted(keys)
        representative = ordered[0]
        for feature_key in ordered[1:]:
            if prepared[representative].equals(prepared[feature_key]):
                _set_final_status(selected_by_key[feature_key], "descriptive_only", f"duplicate_of:{representative}")
                selected_by_key[feature_key]["duplicate_of"] = representative
                prepared.pop(feature_key, None)

    numeric_keys = [key for key, values in prepared.items() if pd.api.types.is_numeric_dtype(values)]
    if len(numeric_keys) > 1:
        correlations = pd.concat({key: prepared[key] for key in numeric_keys}, axis=1).corr(
            method="spearman", min_periods=max(min_group_n * 2, 10)
        )
        for left_index, left in enumerate(numeric_keys):
            for right in numeric_keys[left_index + 1:]:
                correlation = correlations.at[left, right]
                if np.isfinite(correlation) and abs(float(correlation)) >= high_correlation_threshold:
                    selected_by_key[left]["warnings"] = _append_warning(selected_by_key[left].get("warnings"), f"high_correlation:{right}")
                    selected_by_key[right]["warnings"] = _append_warning(selected_by_key[right].get("warnings"), f"high_correlation:{left}")

    updates = pd.DataFrame(selected_by_key.values())
    if not audit.empty and not updates.empty:
        audit = audit.set_index("feature_key", drop=False)
        updates = updates.set_index("feature_key", drop=False)
        for column in updates.columns:
            if column not in audit.columns:
                audit[column] = None
            audit.loc[updates.index, column] = updates[column]
        audit = audit.reset_index(drop=True)
    if not audit.empty and "analysis_status" in audit.columns:
        audit["analysis_status"] = audit["status"]
        audit["analysis_reason"] = audit["reason"]

    tested = [selected_by_key[key] for key in prepared]
    return tested, audit, prepared
