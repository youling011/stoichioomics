from __future__ import annotations

from typing import Any, Dict


MODE_REQUIREMENTS = {
    "global_hvg": {"required": ["expression_matrix"]},
    "group_aware_hvg": {"required_any": ["cluster", "cell_type"], "min_groups": 2},
    "condition_aware_hvg": {"required": ["condition"], "min_conditions": 2},
    "timecourse_hvg": {"required": ["timepoint"], "min_timepoints": 2},
    "sample_consensus_hvg": {"required": ["sample_id"], "min_samples": 2},
    "trajectory_hvg": {"required": ["pseudotime"], "numeric_required": True},
    "phase2_stoich": {"required": ["phase1_hvg_baseline", "stoich_features", "sufficient_id_overlap"]},
}

PRIMARY_PRIORITY = [
    "timecourse_hvg",
    "condition_aware_hvg",
    "group_aware_hvg",
    "trajectory_hvg",
    "sample_consensus_hvg",
    "global_hvg",
]


def _field_available(mapping: Dict[str, Any], field: str) -> bool:
    return bool((mapping.get("standard_fields") or {}).get(field))


def build_capability_matrix(
    expression_ready: bool,
    metadata_mapping: Dict[str, Any],
    stoich_readiness: Dict[str, Any],
) -> Dict[str, Any]:
    matrix: Dict[str, Any] = {}
    if expression_ready:
        matrix["global_hvg"] = {"status": "available", "reason_code": "expression_matrix_ready", "required_fields": []}
    else:
        matrix["global_hvg"] = {"status": "blocked", "reason_code": "no_expression_matrix", "required_fields": ["expression_matrix"]}

    for mode, fields in [
        ("condition_aware_hvg", ["condition"]),
        ("timecourse_hvg", ["timepoint"]),
        ("sample_consensus_hvg", ["sample_id"]),
        ("trajectory_hvg", ["pseudotime"]),
    ]:
        missing = [f for f in fields if not _field_available(metadata_mapping, f)]
        matrix[mode] = (
            {"status": "available", "reason_code": "metadata_field_available", "required_fields": fields}
            if expression_ready and not missing
            else {"status": "skipped", "reason_code": f"no_{fields[0]}_field", "required_fields": fields, "missing_fields": missing}
        )

    group_fields = [f for f in ["cluster", "cell_type"] if _field_available(metadata_mapping, f)]
    matrix["group_aware_hvg"] = (
        {"status": "available", "reason_code": "group_field_available", "required_any": ["cluster", "cell_type"], "selected_fields": group_fields}
        if expression_ready and group_fields
        else {"status": "skipped", "reason_code": "no_cluster_or_cell_type_field", "required_any": ["cluster", "cell_type"]}
    )

    phase2_ready = bool(stoich_readiness.get("phase2_ready"))
    matrix["phase2_stoich"] = (
        {"status": "available", "reason_code": "stoich_ready", "metadata_required": False, "details": stoich_readiness}
        if expression_ready and phase2_ready
        else {
            "status": "skipped",
            "reason_code": stoich_readiness.get("reason_code") or "phase2_not_ready",
            "metadata_required": False,
            "details": stoich_readiness,
        }
    )
    primary_mode = "global_hvg"
    for mode in PRIMARY_PRIORITY:
        if matrix.get(mode, {}).get("status") == "available":
            primary_mode = mode
            break
    auxiliary_modes = [
        mode for mode in ["global_hvg", "condition_aware_hvg", "timecourse_hvg", "group_aware_hvg", "sample_consensus_hvg", "trajectory_hvg"]
        if mode != primary_mode and matrix.get(mode, {}).get("status") == "available"
    ]
    return {
        "modes": matrix,
        "primary_mode": primary_mode,
        "auxiliary_modes": auxiliary_modes,
        "available_modes": [mode for mode, item in matrix.items() if item.get("status") == "available"],
        "skipped_modes": [mode for mode, item in matrix.items() if item.get("status") == "skipped"],
        "blocked_modes": [mode for mode, item in matrix.items() if item.get("status") == "blocked"],
    }
