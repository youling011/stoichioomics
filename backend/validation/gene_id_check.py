from __future__ import annotations
from typing import Dict, Any
import pandas as pd

from .schemas import StandardizedBundle
from .utils import CORE_STOICH_FIELDS, fraction, non_null_fraction


def build_gene_mapping_report(bundle: StandardizedBundle) -> Dict[str, Any]:
    var = bundle.var.copy()
    expr_gene_ids = pd.Index(var.index.astype(str))

    overlap_genes = pd.Index([])
    only_in_expr = []
    only_in_stoich = []

    if bundle.raw_stoich is not None:
        stoich_gene_ids = pd.Index(bundle.raw_stoich.index.astype(str).unique())
        overlap_genes = expr_gene_ids.intersection(stoich_gene_ids)
        only_in_expr = [str(x) for x in expr_gene_ids.difference(stoich_gene_ids)[:50]]
        only_in_stoich = [str(x) for x in stoich_gene_ids.difference(expr_gene_ids)[:50]]
        overlap_fraction_vs_expression = fraction(len(overlap_genes), len(expr_gene_ids))
        overlap_fraction_vs_stoich = fraction(len(overlap_genes), len(stoich_gene_ids))
        exact_source = 'raw_stoich_file'
    else:
        annotated_mask = pd.Series(False, index=var.index)
        present_cols = [c for c in CORE_STOICH_FIELDS if c in var.columns]
        if present_cols:
            annotated_mask = var[present_cols].notna().any(axis=1)
        overlap_genes = pd.Index(var.index[annotated_mask.values])
        overlap_fraction_vs_expression = fraction(len(overlap_genes), len(expr_gene_ids))
        overlap_fraction_vs_stoich = bundle.phase1_validation.get('gene_overlap_fraction_vs_stoich')
        exact_source = 'phase1_joined_var'

    core_field_coverage = {
        c: non_null_fraction(var[c]) if c in var.columns else 0.0
        for c in CORE_STOICH_FIELDS
    }

    report = {
        'method': exact_source,
        'n_genes_expression': int(len(expr_gene_ids)),
        'n_genes_with_stoich_annotation': int(len(overlap_genes)),
        'overlap_fraction_vs_expression': overlap_fraction_vs_expression,
        'overlap_fraction_vs_stoich': overlap_fraction_vs_stoich,
        'overlap_examples': [str(x) for x in overlap_genes[:20]],
        'only_in_expression_examples': only_in_expr,
        'only_in_stoich_examples': only_in_stoich,
        'gene_id_unique_in_expression': bool(not expr_gene_ids.duplicated().any()),
        'core_field_coverage': core_field_coverage,
        'phase1_overlap_hint': bundle.phase1_validation.get('n_genes_overlap'),
    }
    report['ready_for_stoich_phase2'] = bool(report['n_genes_with_stoich_annotation'] > 0 and overlap_fraction_vs_expression >= 0.5)
    return report
