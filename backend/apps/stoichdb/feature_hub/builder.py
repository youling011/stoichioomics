from __future__ import annotations

from typing import Any

from .registry import field_lookup
from .schemas import FeatureHubError, normalize_omics


def split_x_metadata(omics: str, fields: list[str], *, include_metadata: list[str] | None = None) -> dict[str, Any]:
    omics = normalize_omics(omics)
    lookup = field_lookup(omics, "core")
    requested = [field for field in fields if field in lookup]
    if not requested:
        raise FeatureHubError("No valid Core fields selected")
    x_fields = [field for field in requested if lookup[field]["ml_role"] in {"eligible", "conditional"}]
    metadata_fields = [
        field for field, meta in lookup.items()
        if meta["semantic_type"] in {"identifier", "metadata_text", "coordinate", "categorical_code"}
    ]
    for field in include_metadata or []:
        if field in lookup and field not in metadata_fields:
            metadata_fields.append(field)
    return {
        "omics": omics,
        "x_fields": x_fields,
        "metadata_fields": metadata_fields,
        "excluded_from_x": [field for field in requested if field not in x_fields],
        "preprocessing_recipe": preprocessing_recipe(omics, x_fields),
    }


def preprocessing_recipe(omics: str, fields: list[str]) -> dict[str, Any]:
    lookup = field_lookup(omics, "core")
    return {
        "fit_scope": "train_fold_only",
        "forbidden_global_fit": ["StandardScaler", "RobustScaler", "MinMaxScaler", "mean_imputer", "median_imputer", "PCA", "supervised_feature_selection", "target_encoding"],
        "steps": [
            {
                "field": field,
                "semantic_type": lookup[field].get("semantic_type"),
                "scaling_hint": lookup[field].get("scaling_hint"),
                "transform_hint": lookup[field].get("transform_hint"),
                "composition_group": lookup[field].get("composition_group"),
                "applicability": lookup[field].get("applicability"),
            }
            for field in fields
            if field in lookup
        ],
    }

