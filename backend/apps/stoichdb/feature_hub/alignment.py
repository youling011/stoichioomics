from __future__ import annotations

from typing import Any

from .schemas import FeatureHubError


def validate_alignment_request(omics: list[str], strategy: str = "") -> dict[str, Any]:
    selected = [str(item).strip().lower() for item in omics if str(item).strip()]
    if len(selected) <= 1:
        return {"mode": "single_omics", "allowed": True, "message": "Single-omics export does not require ID alignment."}
    if not strategy:
        return {
            "mode": "separate_files",
            "allowed": True,
            "message": "Multiple omics are exported as separate matrices by default. Row-order merging is not allowed.",
        }
    if strategy not in {"gene", "transcript", "protein"}:
        raise FeatureHubError("Unsupported alignment anchor. Use gene, transcript, or protein.")
    return {
        "mode": "merge_by_id",
        "allowed": True,
        "anchor": strategy,
        "message": "Explicit ID alignment requested. Mapping coverage must be checked before horizontal merge output is trusted.",
    }

