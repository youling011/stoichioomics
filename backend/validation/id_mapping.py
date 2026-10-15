from __future__ import annotations

from typing import Any, Dict, Tuple

import pandas as pd

from .schemas import StandardizedBundle
from .utils import CORE_STOICH_FIELDS, fraction


def _normalise_id(value: Any) -> str:
    return str(value).strip()


def build_strict_id_mapping(bundle: StandardizedBundle) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    var = bundle.var.copy()
    if "gene_id" not in var.columns:
        var.insert(0, "gene_id", var.index.astype(str))
    var["gene_id"] = var["gene_id"].map(_normalise_id)

    stoich_source = bundle.raw_stoich.copy() if bundle.raw_stoich is not None else None
    if stoich_source is not None:
        if "gene_id" not in stoich_source.columns:
            stoich_source.insert(0, "gene_id", stoich_source.index.astype(str))
        stoich_source["gene_id"] = stoich_source["gene_id"].map(_normalise_id)
        stoich_ids = pd.Index(stoich_source["gene_id"].astype(str))
        source = "raw_stoich_file"
    else:
        present = [c for c in CORE_STOICH_FIELDS if c in var.columns]
        annotated = var[present].notna().any(axis=1) if present else pd.Series(False, index=var.index)
        stoich_source = var.loc[annotated, ["gene_id"] + present].copy()
        stoich_ids = pd.Index(stoich_source["gene_id"].astype(str))
        source = "standardized_var"

    expr_counts = var["gene_id"].value_counts()
    stoich_counts = pd.Series(stoich_ids).value_counts() if len(stoich_ids) else pd.Series(dtype=int)
    stoich_set = set(stoich_ids.astype(str))

    rows = []
    for _, row in var.iterrows():
        gene_id = _normalise_id(row.get("gene_id"))
        matched = gene_id in stoich_set
        expr_dup = int(expr_counts.get(gene_id, 0))
        stoich_dup = int(stoich_counts.get(gene_id, 0)) if not stoich_counts.empty else 0
        rows.append({
            "expression_gene_id": gene_id,
            "mapped_gene_id": gene_id if matched else None,
            "mapping_status": "matched" if matched else "unmatched_expression",
            "mapping_method": "exact_gene_id",
            "mapping_confidence": 1.0 if matched and expr_dup == 1 and stoich_dup == 1 else (0.5 if matched else 0.0),
            "expression_duplicate_count": expr_dup,
            "stoich_duplicate_count": stoich_dup,
            "is_conflict": bool(expr_dup > 1 or stoich_dup > 1),
        })
    mapping = pd.DataFrame(rows)

    conflict_ids = set(expr_counts[expr_counts > 1].index.astype(str)).union(
        set(stoich_counts[stoich_counts > 1].index.astype(str)) if not stoich_counts.empty else set()
    )
    conflicts = mapping.loc[mapping["expression_gene_id"].isin(conflict_ids)].copy()
    if not conflicts.empty:
        conflicts["conflict_reason"] = conflicts.apply(
            lambda r: ";".join([
                reason for reason, flag in [
                    ("duplicate_in_expression", int(r["expression_duplicate_count"]) > 1),
                    ("duplicate_in_stoich", int(r["stoich_duplicate_count"]) > 1),
                ] if flag
            ]),
            axis=1,
        )
    else:
        conflicts = pd.DataFrame(columns=list(mapping.columns) + ["conflict_reason"])

    unmatched_expr = mapping.loc[mapping["mapping_status"] == "unmatched_expression"].copy()
    stoich_only = sorted(set(stoich_ids.astype(str)).difference(set(var["gene_id"].astype(str))))
    stoich_only_df = pd.DataFrame({
        "expression_gene_id": [None] * len(stoich_only),
        "mapped_gene_id": stoich_only,
        "mapping_status": ["unmatched_stoich"] * len(stoich_only),
        "mapping_method": ["exact_gene_id"] * len(stoich_only),
        "mapping_confidence": [0.0] * len(stoich_only),
    })
    unmatched = pd.concat([unmatched_expr, stoich_only_df], ignore_index=True, sort=False)

    matched_n = int((mapping["mapping_status"] == "matched").sum())
    summary = {
        "mapping_source": source,
        "mapping_policy": "strict_exact_gene_id",
        "expression_gene_count": int(var.shape[0]),
        "stoich_gene_count": int(len(stoich_ids)),
        "matched_gene_count": matched_n,
        "unmatched_expression_gene_count": int(unmatched_expr.shape[0]),
        "unmatched_stoich_gene_count": int(len(stoich_only)),
        "conflict_gene_count": int(conflicts["expression_gene_id"].nunique()) if not conflicts.empty else 0,
        "match_rate": fraction(matched_n, int(var.shape[0])),
        "minimum_phase2_match_rate": 0.70,
    }
    summary["ready_for_phase2_stoich"] = bool(summary["match_rate"] >= summary["minimum_phase2_match_rate"])
    return mapping, conflicts, unmatched, summary
