from __future__ import annotations

from dataclasses import dataclass
from typing import Any


OMICS_TYPES = {"genome", "transcriptome", "proteome"}
SCOPES = {"core", "full"}


class FeatureHubError(ValueError):
    status_code = 400


class FeatureHubNotFound(FeatureHubError):
    status_code = 404


def normalize_omics(value: Any) -> str:
    omics = str(value or "").strip().lower()
    aliases = {
        "rna": "transcriptome",
        "transcript": "transcriptome",
        "transcripts": "transcriptome",
        "protein": "proteome",
        "proteins": "proteome",
    }
    omics = aliases.get(omics, omics)
    if omics not in OMICS_TYPES:
        raise FeatureHubError(f"Unsupported omics value: {value}")
    return omics


def normalize_scope(value: Any) -> str:
    scope = str(value or "core").strip().lower()
    if scope not in SCOPES:
        raise FeatureHubError(f"Unsupported scope value: {value}")
    return scope


def split_csv(value: Any, *, limit: int = 500) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw_items = value
    else:
        raw_items = str(value or "").replace("\n", ",").split(",")
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def safe_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 100000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def boolish(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class DatasetSpec:
    species_id: str
    omics: str
    scope: str = "core"

