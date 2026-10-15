from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings

from backend.apps.stoichdb.models import OmicsDataset, SchemaRegistry
from .schemas import normalize_omics, normalize_scope


REGISTRY_VERSION = "stoich_ml_feature_registry_v1"
REGISTRY_PATH = Path(settings.BASE_DIR) / "shared" / "schemas" / "stoich_ml_feature_registry_v1.json"
DISPLAY_SCHEMA_PATH = Path(settings.BASE_DIR) / "shared" / "schemas" / "stoich_feature_display_schema.json"
FEATURE_DICTIONARY_PATH = Path(settings.BASE_DIR) / "backend" / "apps" / "stoichdb" / "resources" / "feature_dictionary.json"

IDENTIFIER_FIELDS = {
    "species_id", "gene_id", "source_gene_id", "protein_id", "transcript_id",
    "ensembl_gene_id", "ensembl_transcript_id", "ensembl_protein_id",
    "source_protein_id", "source_db", "raw_header", "seq_md5",
}
COORDINATE_FIELDS = {"seqid", "seq_region", "assembly", "start", "end", "start_1", "end_1", "strand"}
COUNT_RE = re.compile(r"(^n_|_n$|_count$|count_|_bp$|_nt$|_aa$|length|len)", re.I)
CODON_RE = re.compile(r"^codon_[ACGTU]{3}_(freq|count)$", re.I)
DINUC_RE = re.compile(r"^dinuc_[ACGTU]{2}_freq$", re.I)
AA_COMP_RE = re.compile(r"^(aa_[A-Z]_(freq|pct|count)|AA_[A-Z]_pct)$")
NT_FRAC_RE = re.compile(r"^frac_[ACGTU]$")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _column_name(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("name") or item.get("field") or "").strip()
    return ""


def _column_type(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("type") or item.get("dtype") or "").strip().lower()
    return ""


def _display_overlays() -> dict[str, dict[str, dict[str, Any]]]:
    display = _read_json(DISPLAY_SCHEMA_PATH).get("omics") or {}
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for omics, rows in display.items():
        out[str(omics)] = {}
        for row in rows or []:
            if isinstance(row, dict) and row.get("field"):
                out[str(omics)][str(row["field"])] = row
    dictionary = _read_json(FEATURE_DICTIONARY_PATH)
    for key, row in (dictionary.get("field_overrides") or {}).items():
        if "." in str(key) and isinstance(row, dict):
            omics, field = str(key).split(".", 1)
            out.setdefault(omics, {}).setdefault(field, {}).update(row)
    return out


def _is_metadata(field: str) -> bool:
    f = field.lower()
    return (
        f in IDENTIFIER_FIELDS
        or f in COORDINATE_FIELDS
        or "name" in f
        or "symbol" in f
        or "description" in f
        or f.endswith("_tag")
        or f.endswith("_source_id")
        or f.endswith("_reason")
        or f.endswith("_biotype")
        or f in {"omics", "element_rule", "transl_table_used", "biotype"}
        or "strategy" in f
    )


def _composition_group(field: str) -> str:
    if CODON_RE.match(field):
        return "codon_freq_64"
    if DINUC_RE.match(field):
        return "dinuc_freq_16"
    if NT_FRAC_RE.match(field):
        return "nt_frac_4"
    if field.startswith("aa_") and field.endswith("_freq"):
        return "aa_freq_20"
    if field.startswith("AA_") and field.endswith("_pct"):
        return "aa_pct_20"
    return ""


def _family(field: str, omics: str) -> str:
    f = field.lower()
    if _composition_group(field):
        return _composition_group(field).replace("_64", "").replace("_20", "").replace("_16", "").replace("_4", "")
    if "gc" in f or f in {"frac_a", "frac_c", "frac_g", "frac_u"}:
        return "gc_composition" if "gc" in f else "nucleotide_composition"
    if any(token in f for token in ["atoms", "_atom_", "c_n_ratio", "c_p_ratio", "n_p_ratio", "s_atoms", "se_atoms"]):
        return "element_density"
    if any(token in f for token in ["entropy", "skew", "complexity"]):
        return "sequence_complexity"
    if any(token in f for token in ["mw", "mass", "charge", "gravy", "aromaticity", "instability", "aliphatic", "pi"]):
        return "protein_property" if omics == "proteome" else "molecular_property"
    if COUNT_RE.search(field):
        return "length_count"
    if f in COORDINATE_FIELDS:
        return "coordinate"
    if any(token in f for token in ["valid", "quality", "respect_phase", "phase_trimmed", "has_stop"]):
        return "qc"
    return "metadata" if _is_metadata(field) else "other"


def _semantic_type(field: str, dtype: str, omics: str, scope: str) -> str:
    f = field.lower()
    if _is_metadata(field):
        if f in {"strand", "transl_table_used", "source_db", "biotype"} or f.endswith("_biotype") or "strategy" in f:
            return "categorical_code"
        if f in COORDINATE_FIELDS:
            return "coordinate"
        return "identifier" if f.endswith("_id") or f == "species_id" else "metadata_text"
    if _composition_group(field):
        return "composition"
    if f.startswith("is_") or f.startswith("has_") or f.endswith("_valid") or dtype == "boolean":
        return "binary"
    if dtype in {"integer", "int"} or COUNT_RE.search(field):
        return "count"
    return "continuous"


def _ml_role(field: str, dtype: str, omics: str, scope: str) -> tuple[str, bool]:
    if scope == "full":
        return "exclude", False
    semantic = _semantic_type(field, dtype, omics, scope)
    if semantic in {"identifier", "metadata_text", "coordinate"}:
        return "exclude", False
    if semantic == "categorical_code" or _family(field, omics) == "qc":
        return "conditional", False
    return "eligible", True


def _applicability(field: str, omics: str) -> str:
    if omics == "genome" and (CODON_RE.match(field) or AA_COMP_RE.match(field) or field.startswith("aa_")):
        return "coding_only"
    if omics == "transcriptome" and (field.startswith("orf_") or field.startswith("aa_")):
        return "protein_proxy_only"
    return "all"


def _unit(field: str) -> str:
    f = field.lower()
    if f.endswith("_pct") or "percent" in f:
        return "%"
    if f.endswith("_frac") or f.startswith("frac_") or f.endswith("_freq"):
        return "fraction"
    if f.endswith("_bp"):
        return "bp"
    if f.endswith("_nt"):
        return "nt"
    if f.endswith("_aa") or "length_aa" in f:
        return "aa"
    if "mw" in f or "mass" in f:
        return "Da"
    if "atoms_per" in f:
        return "atoms/unit"
    return ""


def _redundancy_group(field: str) -> str:
    return {
        "length_nt_total": "transcript_length_identity_1",
        "length_nt_acgu": "transcript_length_identity_1",
        "P_atoms": "transcript_length_identity_1",
        "clean_rna_len": "transcript_length_identity_1",
        "orf_len_aa": "transcript_orf_aa_identity_1",
        "aa_len": "transcript_orf_aa_identity_1",
        "sulfur_aa_frac": "proteome_sulfur_density_1",
        "S_atoms_per_aa": "proteome_sulfur_density_1",
        "aromaticity": "proteome_aromaticity_relation_1",
        "aa_aromatic_frac": "proteome_aromaticity_relation_1",
    }.get(field, "")


def _fallback_header(omics: str, scope: str) -> list[str]:
    query = OmicsDataset.objects.filter(omics_type=omics)
    query = query.exclude(core_csv_path="" if scope == "core" else "___never___")
    ds = query.only("core_csv_path", "full_csv_path").first()
    if not ds:
        return []
    path = Path(ds.core_csv_path if scope == "core" else ds.full_csv_path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle), [])


@lru_cache(maxsize=4)
def load_registry() -> dict[str, Any]:
    overlays = _display_overlays()
    schemas: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    for schema in SchemaRegistry.objects.order_by("omics_type", "product_type"):
        omics = normalize_omics(schema.omics_type)
        scope = normalize_scope(schema.product_type)
        columns = schema.columns_json or _fallback_header(omics, scope)
        names = [_column_name(item) for item in columns]
        names = [name for name in names if name]
        schemas.append({
            "schema_id": schema.schema_id,
            "omics": omics,
            "scope": scope,
            "schema_version": schema.version,
            "status": schema.status,
            "column_count": len(names),
            "columns": names,
        })
        for index, item in enumerate(columns):
            field = _column_name(item)
            if not field:
                continue
            dtype = _column_type(item)
            overlay = overlays.get(omics, {}).get(field, {})
            semantic = _semantic_type(field, dtype, omics, scope)
            role, default = _ml_role(field, dtype, omics, scope)
            composition = _composition_group(field)
            applicability = _applicability(field, omics)
            fields.append({
                "field": field,
                "label": overlay.get("label") or field.replace("_", " "),
                "omics": omics,
                "scope": scope,
                "source_scope": scope,
                "schema_id": schema.schema_id,
                "schema_version": schema.version,
                "ordinal": index + 1,
                "dtype": dtype or "string",
                "semantic_type": semantic,
                "family": overlay.get("family") or _family(field, omics),
                "unit": overlay.get("unit") or _unit(field),
                "ml_role": role,
                "ml_default": bool(default),
                "applicability": applicability,
                "composition_group": composition,
                "zero_semantics": "structural_na" if applicability != "all" else "true_zero",
                "scaling_hint": "none" if semantic in {"identifier", "metadata_text", "categorical_code", "binary"} else ("model_dependent" if semantic == "composition" else "robust" if COUNT_RE.search(field) else "standard"),
                "transform_hint": "composition_transform" if semantic == "composition" else ("log1p" if COUNT_RE.search(field) else "none"),
                "redundancy_group": _redundancy_group(field),
                "description": overlay.get("description_short") or overlay.get("description") or ("Full-scope feature for browsing and download only." if scope == "full" else "Core hand-crafted molecular descriptor for browsing and ML dataset construction."),
                "formula": overlay.get("formula") or "",
                "formula_status": overlay.get("formula_status") or ("defined" if overlay.get("formula") else "heuristic"),
                "bounded_min": overlay.get("bounded_min"),
                "bounded_max": overlay.get("bounded_max"),
                "ml_status": "Browse/Download only" if scope == "full" else role,
            })
    return {
        "registry_version": REGISTRY_VERSION,
        "source": "SchemaRegistry + feature table headers + display dictionary overlay",
        "schemas": schemas,
        "fields": fields,
        "summary": {
            "schema_count": len(schemas),
            "field_rows": len(fields),
            "core_fields": sum(1 for row in fields if row["scope"] == "core"),
            "full_fields": sum(1 for row in fields if row["scope"] == "full"),
            "ml_eligible_core_fields": sum(1 for row in fields if row["scope"] == "core" and row["ml_role"] == "eligible"),
        },
        "rules": {
            "core_for_ml": True,
            "full_for_ml": False,
            "metadata_export": "Identifiers, annotations, positions, and categorical codes are exported separately from X by default.",
            "leakage_policy": "Scaler, imputer, PCA, target encoding, and supervised feature selection are emitted as recipe steps only and must be fit inside train folds.",
        },
    }


def catalog_payload(omics: str = "", scope: str = "", family: str = "", ml_role: str = "", search: str = "") -> dict[str, Any]:
    registry = load_registry()
    rows = registry["fields"]
    if omics:
        rows = [row for row in rows if row["omics"] == normalize_omics(omics)]
    if scope:
        rows = [row for row in rows if row["scope"] == normalize_scope(scope)]
    if family:
        rows = [row for row in rows if row["family"] == family]
    if ml_role:
        rows = [row for row in rows if row["ml_role"] == ml_role]
    if search:
        q = search.lower().strip()
        rows = [row for row in rows if q in row["field"].lower() or q in row["label"].lower() or q in row["description"].lower()]
    return {
        "registry_version": registry["registry_version"],
        "schemas": registry["schemas"],
        "items": rows,
        "summary": registry["summary"],
        "facets": {
            "omics": sorted({row["omics"] for row in registry["fields"]}),
            "scopes": sorted({row["scope"] for row in registry["fields"]}),
            "families": sorted({row["family"] for row in registry["fields"]}),
            "ml_roles": sorted({row["ml_role"] for row in registry["fields"]}),
        },
    }


def fields_for(omics: str, scope: str) -> list[dict[str, Any]]:
    return [row for row in load_registry()["fields"] if row["omics"] == normalize_omics(omics) and row["scope"] == normalize_scope(scope)]


def field_lookup(omics: str, scope: str) -> dict[str, dict[str, Any]]:
    return {row["field"]: row for row in fields_for(omics, scope)}


def write_registry_file() -> Path:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(load_registry(), ensure_ascii=False, indent=2), encoding="utf-8")
    return REGISTRY_PATH
