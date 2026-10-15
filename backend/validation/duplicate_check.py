from __future__ import annotations
from typing import Dict, Any

from .schemas import StandardizedBundle


def build_duplicate_check_report(bundle: StandardizedBundle) -> Dict[str, Any]:
    obs = bundle.obs.copy()
    var = bundle.var.copy()
    report = {
        'duplicate_cell_ids': int(obs.index.duplicated().sum()),
        'duplicate_gene_ids': int(var.index.duplicated().sum()),
        'duplicate_gene_names': int(var['gene_name'].duplicated().sum()) if 'gene_name' in var.columns else None,
    }
    report['barcode_prefixing_detected'] = bool('cell_id' in obs.columns and obs['cell_id'].astype(str).str.contains(':').any())
    report['duplicates_ok'] = bool(report['duplicate_cell_ids'] == 0 and report['duplicate_gene_ids'] == 0)
    return report
