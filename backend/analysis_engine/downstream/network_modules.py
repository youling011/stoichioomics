from __future__ import annotations

from pathlib import Path
from typing import Dict

import pandas as pd


def run_network_module_outputs(classified: pd.DataFrame, output_dir: str | Path) -> Dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    class_col = "stoich_class" if "stoich_class" in classified.columns else None
    if class_col:
        rows = []
        for module_id, (label, group) in enumerate(classified.groupby(class_col, dropna=False), start=1):
            rows.append({
                "module_id": f"class_{module_id}",
                "module_label": str(label),
                "gene_count": int(group.shape[0]),
                "top_gene_examples": "|".join(group.get("gene_id", pd.Series(group.index.astype(str))).astype(str).head(10).tolist()),
                "enrichment_status": "class_based_module_no_ppi_edges",
            })
        modules = pd.DataFrame(rows)
    else:
        modules = pd.DataFrame([{
            "module_id": "not_run",
            "module_label": "No network or stoich class available",
            "gene_count": int(classified.shape[0]),
            "top_gene_examples": "",
            "enrichment_status": "skipped_no_network",
        }])
    path = out / "ppi_module_enrichment.csv"
    modules.to_csv(path, index=False)
    return {"ppi_module_enrichment": str(path.resolve())}
