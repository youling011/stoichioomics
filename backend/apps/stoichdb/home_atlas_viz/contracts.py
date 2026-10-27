from __future__ import annotations
import hashlib
import json
import math

VERSION = "home-atlas-v1"
OMICS = ("genome", "transcriptome", "proteome")
GROUPS = ("Bacteria", "Fungi", "Protists", "Plants", "Metazoa", "Vertebrates")
PATTERNS = ("100", "010", "001", "110", "101", "011", "111", "000")
FAMILIES = ("Sequence / annotation", "Base / sequence composition", "Dinucleotide patterns",
            "Codon usage", "Amino-acid composition", "Elemental / stoichiometric",
            "Protein descriptors", "Identifiers / metadata")


def digest(value):
    def stable(item):
        if isinstance(item, float) and not math.isfinite(item):
            return {"nonfinite_float": str(item)}
        if isinstance(item, dict):
            return {k: stable(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [stable(v) for v in item]
        return item
    return hashlib.sha256(json.dumps(stable(value), sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), default=str, allow_nan=False).encode()).hexdigest()


def group_name(value):
    text = str(value or "").strip()
    if text.lower() in {"", "unknown", "unclassified", "na", "n/a", "none"}:
        return "Unclassified"
    if text.lower() == "protist":
        return "Protists"
    return next((g for g in GROUPS if g.lower() == text.lower()), text)


def group_order(values):
    seen = {group_name(x) for x in values}
    return [g for g in GROUPS if g in seen] + sorted(seen.difference(GROUPS))


def number(value, name):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number.")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number.")
    return 0.0 if result == 0 else result


def normalize_filters(params, allowed_keys=None):
    result = {k: str(params.get(k) or "").strip() for k in ("query", "domain", "clade", "habitat")}
    if result["domain"]:
        result["domain"] = group_name(result["domain"])
    for k in ("genome_size_min", "genome_size_max"):
        result[k] = number(params.get(k), k)
    if (result["genome_size_min"] is not None and result["genome_size_max"] is not None
            and result["genome_size_min"] > result["genome_size_max"]):
        raise ValueError("Genome size minimum exceeds maximum.")
    raw = params.get("fingerprint_filters") or []
    try:
        raw = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid fingerprint_filters JSON.") from exc
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("fingerprint_filters must be an array of at most 100 bounds.")
    bounds = []
    for item in raw:
        if not isinstance(item, dict) or set(item).difference({"key", "min", "max"}):
            raise ValueError("Each fingerprint bound requires key and optional min/max.")
        key = str(item.get("key") or "").strip()
        if not key or (allowed_keys is not None and key not in allowed_keys):
            raise ValueError(f"Unsupported fingerprint key: {key}")
        low, high = number(item.get("min"), key), number(item.get("max"), key)
        if low is not None and high is not None and low > high:
            raise ValueError(f"{key} minimum exceeds maximum.")
        if low is not None or high is not None:
            bounds.append({"key": key, "min": low, "max": high})
    result["fingerprint_filters"] = sorted(bounds, key=lambda r: (r["key"], str(r["min"]), str(r["max"])))
    return result


def ignored_filters(params):
    return {k: str(params.get(k, "")) for k in
            ("omics", "has_all_omics", "page", "page_size", "sort_by", "sort_order", "view_mode")
            if k in params}


def family(field, omics, role):
    if role == "metadata":
        return FAMILIES[-1]
    if "dinuc" in field:
        return FAMILIES[2]
    if field.startswith("codon_"):
        return FAMILIES[3]
    if any(s in field for s in ("atoms", "ratio", "oxidation")) or field == "mw_rna_nmp_per_nt_Da":
        return FAMILIES[5]
    if field.startswith(("aa_", "AA_")) and field not in {
        "aa_len", "aa_hydrophobic_frac", "aa_polar_frac", "aa_pos_frac", "aa_neg_frac", "aa_aromatic_frac"
    }:
        return FAMILIES[4]
    if omics == "proteome" or field.startswith("protein_"):
        return FAMILIES[6]
    if any(s in field for s in ("gc", "entropy", "skew", "frac_", "_percent")):
        return FAMILIES[1]
    return FAMILIES[0]


def card(code, data, meta, unit, n_source, n_valid=None, method="", evidence="registered_metadata",
         status=None, warnings=None, complete=True):
    valid = n_source if n_valid is None else n_valid
    return {"chart_id": code, "status": status or ("ready" if n_source else "empty"),
            "scope_kind": meta["scope_kind"], "scope_id": meta["scope_id"],
            "source_revision": meta["source_revision"], "population_unit": unit,
            "n_source": n_source, "n_valid": valid, "n_excluded": n_source - valid,
            "complete_population": complete, "method": method, "evidence_level": evidence,
            "generated_at": meta["generated_at"], "warnings": warnings or [], "data": data}
