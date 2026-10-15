from __future__ import annotations

"""Shared resolution contract for registered Core fields.

The Feature Hub owns the canonical registry names.  This module only resolves
those names to columns that are actually present in a source or a comparison
context; it never invents a value or silently chooses between two candidates.
"""

from dataclasses import dataclass
from typing import Any, Iterable


SCHEMA_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "transcriptome": {
        "length_nt_total": ("length_nt", "transcript_length"),
        "gc_content": ("transcript_gc_fraction",),
        "nt_entropy": ("transcript_entropy",),
        "atoms_per_nt_C": ("c_per_nt",),
        "atoms_per_nt_N": ("n_per_nt",),
        "atoms_per_nt_P": ("p_per_nt",),
        "protein_mw_Da": ("protein_mw_da",),
    },
    "proteome": {
        "length_aa": ("protein_length", "length"),
        "C_atoms_per_aa": ("c_atoms_per_aa",),
        "N_atoms_per_aa": ("n_atoms_per_aa",),
        "S_atoms_per_aa": ("s_atoms_per_aa",),
        "aa_entropy_bits": ("aa_entropy",),
        "mw_da": ("mw_approx",),
    },
}

NAMESPACE_PREFIXES: dict[str, tuple[str, ...]] = {
    "genome": ("genome__", "genome_"),
    "transcriptome": ("transcriptome__", "transcriptome_", "transcript__", "transcript_"),
    "proteome": ("proteome__", "proteome_", "protein__", "protein_"),
}


@dataclass(frozen=True)
class FieldResolution:
    canonical_field: str
    source_column: str
    method: str
    present: bool


def _normal(value: Any) -> str:
    return str(value or "").strip().casefold()


def field_aliases(omics: str, field: str, metadata: dict[str, Any] | None = None) -> list[str]:
    """Return aliases in deterministic priority order.

    Registry snapshots produced by older releases do not always contain an
    explicit alias list.  When they do, it is added after the canonical name
    and before the maintained schema aliases.
    """
    metadata = metadata or {}
    raw_aliases = metadata.get("aliases") or metadata.get("source_aliases") or metadata.get("legacy_aliases") or []
    if isinstance(raw_aliases, str):
        raw_aliases = [raw_aliases]
    values = [str(field)]
    values.extend(str(value) for value in raw_aliases if str(value).strip())
    values.extend(SCHEMA_ALIASES.get(str(omics).lower(), {}).get(str(field), ()))
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normal(value)
        if key and key not in seen:
            result.append(value)
            seen.add(key)
    return result


def resolve_field(
    headers: Iterable[str],
    *,
    omics: str,
    field: str,
    metadata: dict[str, Any] | None = None,
    allow_unprefixed: bool = True,
) -> FieldResolution:
    """Resolve one canonical field against a header without fuzzy matching."""
    original = [str(header) for header in headers]
    by_lower: dict[str, str] = {}
    for header in original:
        by_lower.setdefault(_normal(header), header)

    aliases = field_aliases(omics, field, metadata)
    if allow_unprefixed:
        for index, alias in enumerate(aliases):
            found = by_lower.get(_normal(alias))
            if found:
                return FieldResolution(field, found, "canonical" if index == 0 else "schema_alias", True)

    for prefix in NAMESPACE_PREFIXES.get(str(omics).lower(), ()):
        for alias in aliases:
            found = by_lower.get(_normal(f"{prefix}{alias}"))
            if found:
                return FieldResolution(field, found, "namespaced", True)

    return FieldResolution(field, "", "unresolved", False)


def resolve_registry_fields(
    headers: Iterable[str],
    fields: Iterable[dict[str, Any]],
    *,
    omics: str,
    explicit: dict[str, str] | None = None,
) -> dict[str, FieldResolution]:
    """Resolve all registry fields using one shared alias contract."""
    original = [str(header) for header in headers]
    by_lower = {_normal(header): header for header in original}
    explicit = explicit or {}
    result: dict[str, FieldResolution] = {}
    for metadata in fields:
        field = str(metadata.get("field") or "")
        if not field:
            continue
        key = f"{omics}::{field}"
        configured = explicit.get(key) or explicit.get(field)
        if configured and _normal(configured) in by_lower:
            result[field] = FieldResolution(field, by_lower[_normal(configured)], "explicit_provenance", True)
            continue
        result[field] = resolve_field(
            original,
            omics=omics,
            field=field,
            metadata=metadata,
            allow_unprefixed=True,
        )
    return result


def canonical_context_column(omics: str, field: str) -> str:
    return f"{str(omics).lower()}__{field}"


def comparison_feature_key(omics: str, field: str) -> str:
    return f"{str(omics).lower()}::{field}"

