from __future__ import annotations

import numpy as np
import pandas as pd


def build_candidate_score_components(classified: pd.DataFrame) -> pd.DataFrame:
    work = classified.copy()
    gene = work.get("gene_id", pd.Series(work.index.astype(str), index=work.index)).astype(str)
    rank = pd.to_numeric(work.get("hvg_rank"), errors="coerce")
    max_rank = np.nanmax(rank.to_numpy()) if rank.notna().any() else 1.0
    rank_component = 1.0 - ((rank - 1.0) / max(max_rank, 1.0))
    hvg_component = work.get("is_hvg", pd.Series(False, index=work.index)).fillna(False).astype(bool).astype(float)
    excess_component = pd.to_numeric(work.get("stoich_excess_var"), errors="coerce").abs()
    if excess_component.notna().any() and excess_component.max() > excess_component.min():
        excess_component = (excess_component - excess_component.min()) / (excess_component.max() - excess_component.min())
    else:
        excess_component = pd.Series(0.0, index=work.index)
    explained_component = pd.to_numeric(work.get("stoich_explained_fraction"), errors="coerce").clip(lower=0)
    if explained_component.notna().any() and explained_component.max() > explained_component.min():
        explained_component = (explained_component - explained_component.min()) / (explained_component.max() - explained_component.min())
    else:
        explained_component = pd.Series(0.0, index=work.index)
    out = pd.DataFrame({
        "gene_id": gene,
        "gene_name": work.get("gene_name", gene).astype(str),
        "rank_component": rank_component.fillna(0.0).clip(0, 1),
        "hvg_component": hvg_component,
        "stoich_excess_component": excess_component.fillna(0.0).clip(0, 1),
        "stoich_explained_component": explained_component.fillna(0.0).clip(0, 1),
        "stoich_class": work.get("stoich_class", pd.Series("", index=work.index)).astype(str),
    })
    out["candidate_score"] = (
        0.35 * out["rank_component"]
        + 0.20 * out["hvg_component"]
        + 0.25 * out["stoich_excess_component"]
        + 0.20 * out["stoich_explained_component"]
    )
    return out.sort_values("candidate_score", ascending=False).reset_index(drop=True)
