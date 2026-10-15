from __future__ import annotations
from typing import Dict, Any
import pandas as pd

from .schemas import StandardizedBundle
from .utils import CORE_STOICH_FIELDS, non_null_fraction


def build_stoich_check_report(bundle: StandardizedBundle) -> Dict[str, Any]:
    var = bundle.var.copy()
    present = [c for c in CORE_STOICH_FIELDS if c in var.columns]
    missing = [c for c in CORE_STOICH_FIELDS if c not in var.columns]
    coverage = {c: non_null_fraction(var[c]) if c in var.columns else 0.0 for c in CORE_STOICH_FIELDS}

    genes_with_any = 0
    if present:
        genes_with_any = int(var[present].notna().any(axis=1).sum())

    report = {
        'stoich_present_in_standardized_var': bool(len(present) > 0),
        'core_fields_present': present,
        'core_fields_missing': missing,
        'field_coverage': coverage,
        'n_genes_with_any_core_stoich': genes_with_any,
        'raw_stoich_file_loaded': bool(bundle.raw_stoich is not None),
    }
    report['ready_for_stoich_phase2'] = bool(genes_with_any > 0 and len(present) >= 3)
    report['minimum_recommended_fields_ok'] = all(c in present for c in ['gc_content', 'length_nt', 'c_per_nt', 'n_per_nt', 'p_per_nt'] if c in CORE_STOICH_FIELDS)
    return report
