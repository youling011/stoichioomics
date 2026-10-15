from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db.models import Case, Count, IntegerField, Max, Min, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce

try:
    import numpy as np
except Exception:  # pragma: no cover - runtime fallback when numpy is unavailable
    np = None

umap = None


def _optional_umap():
    global umap
    if umap is not None:
        return umap
    try:
        import umap as umap_module
    except Exception:  # pragma: no cover - runtime fallback when umap is unavailable
        return None
    umap = umap_module
    return umap

from .models import (
    AnalysisArtifact,
    DataRelease,
    EntityRecord,
    FeatureFile,
    FunctionalAnnotationRelease,
    GeneIndex,
    OmicsDataset,
    PhylogenyRelease,
    PhylogenyTipMap,
    ProteinIndex,
    ReleaseSpecies,
    SchemaRegistry,
    Species,
    SpeciesFunctionalAnnotationStatus,
    TranscriptIndex,
)
from . import function_annotations
from . import phylogeny
from .complete_core.aggregates import (
    complete_core_field_summary,
    complete_core_scatter_payload,
    complete_core_summary_overlay,
)
from .complete_core.contracts import optional_full_fields_for_omics
from .complete_core.cross_omics import build_complete_cross_omics_payload


DATA_ROOT = Path(getattr(settings, 'STOICHDB_DATA_ROOT', settings.BASE_DIR / 'data' / 'stoichdb_demo'))
FEATURE_DISPLAY_SCHEMA_PATH = Path(settings.BASE_DIR) / 'shared' / 'schemas' / 'stoich_feature_display_schema.json'
FEATURE_DICTIONARY_PATH = Path(settings.BASE_DIR) / 'backend' / 'apps' / 'stoichdb' / 'resources' / 'feature_dictionary.json'
ID_MAPPING_DIR = Path(settings.BASE_DIR) / 'data' / 'id_mapping'


def _id_mapping_json(name: str, default: Any | None = None) -> Any:
    path = ID_MAPPING_DIR / name
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {} if default is None else default

OMICS_META_DEFAULT = {
    'genome': {
        'display_name': 'Genome',
        'entity_label': 'Gene',
        'primary_id': 'gene_id',
        'fallback_id': 'entity_id',
        'description': 'Genome stoichiometric feature tables derived from exon, promoter and locus-level elemental composition fields.',
        'analysis_modules': ['Profile', 'Core features', 'Strategy clusters', 'Outliers', 'Stoich islands', 'Coupling network'],
        'browse_columns': ['entity_id', 'gene_id', 'gene_name', 'biotype', 'seqid', 'start_1', 'end_1', 'strand', 'strategy_cluster', 'exon_gc_percent'],
        'feature_options': ['exon_gc_percent', 'promoter_gc_percent', 'gc_delta_promoter_minus_exon', 'promoter_exon_gc_delta', 'exon_atoms_N_per_base', 'stoich_island_score'],
    },
    'transcriptome': {
        'display_name': 'Transcript sequence',
        'entity_label': 'Transcript',
        'primary_id': 'transcript_id',
        'fallback_id': 'entity_id',
        'description': 'Transcript sequence feature tables derived from nucleotide composition, element-per-nt fields and ORF / coding proxy features; this is not RNA-seq expression abundance.',
        'analysis_modules': ['Profile', 'Core features', 'Strategy clusters', 'Outliers', 'RNA-ORF coupling', 'Motif themes'],
        'browse_columns': ['entity_id', 'transcript_id', 'gene_id', 'gene_symbol', 'transcript_biotype', 'seq_region', 'start', 'end', 'strand', 'strategy_cluster'],
        'feature_options': ['gc_percent_display', 'gc_content', 'nt_entropy', 'atoms_per_nt_N', 'coding_density_proxy', 'rna_orf_coupling_score', 'protein_gravy_proxy'],
    },
    'proteome': {
        'display_name': 'Proteome',
        'entity_label': 'Protein',
        'primary_id': 'protein_id',
        'fallback_id': 'entity_id',
        'description': 'Proteome feature tables derived from atom-per-aa, elemental ratio and physicochemical fields.',
        'analysis_modules': ['Profile', 'Core features', 'Strategy clusters', 'Outliers', 'Resource budgets', 'Trade-off front'],
        'browse_columns': ['entity_id', 'protein_id', 'ensembl_gene_id', 'gene_id', 'gene_symbol', 'description', 'length_aa', 'strategy_cluster', 'N_atoms_per_aa', 'S_atoms_per_aa'],
        'feature_options': ['length_aa', 'N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy', 'resource_budget_score', 'adaptation_score'],
    },
}

PROJECT_DEFAULT = {
    'name': 'Stoichioomics Platform',
    'species_count': 0,
    'omics_types': ['genome', 'transcriptome', 'proteome'],
    'modules': ['Gateway', 'Overview', 'Database', 'Visualization', 'Analysis', 'Compare', 'Release', 'Quality', 'Downloads', 'Docs', 'Workflows', 'Guide', 'Contact'],
}


# The registry stores screened protists explicitly as ``Protists``.  Older
# imports used ``Unknown`` for this subset, but the database release scope is
# now corrected at the data layer.
COVERAGE_GROUPS = (
    {'key': 'bacteria', 'label': 'Bacteria', 'domain': 'Bacteria'},
    {'key': 'fungi', 'label': 'Fungi', 'domain': 'Fungi'},
    {'key': 'metazoa', 'label': 'Metazoa', 'domain': 'Metazoa'},
    {'key': 'plants', 'label': 'Plants', 'domain': 'Plants'},
    {'key': 'protists', 'label': 'Protists', 'domain': 'Protists'},
    {'key': 'vertebrates', 'label': 'Vertebrates', 'domain': 'Vertebrates'},
)

CROSS_OMICS_MODULE_CONTRACTS = (
    ('X0', 'Cross-omics data foundation'),
    ('X1', 'DNA-RNA-Protein resource shift'),
    ('X2', 'Regulatory-to-transcript coupling'),
    ('X3', 'Codon-to-protein translation strategy'),
    ('X4', 'RNA-predicted protein vs observed proteome'),
    ('X5', 'Stoich island propagation'),
    ('X6', 'Cross-omics feature coupling network'),
    ('X7', 'Species-level cross-omics fingerprint'),
    ('X8', 'Candidate workbench and export'),
)


class NotFoundError(Exception):
    pass


@lru_cache(maxsize=1)
def db_mode() -> bool:
    storage_mode = str(os.environ.get('STOICHDB_STORAGE_MODE', '')).strip().lower()
    if storage_mode in {'file', 'json', 'registry'}:
        return False
    if storage_mode in {'db', 'database', 'postgres', 'postgresql'}:
        return True
    force_file = str(os.environ.get('STOICHDB_FORCE_FILE_MODE', '')).strip().lower()
    if force_file in {'1', 'true', 'yes', 'on'}:
        return False
    try:
        return Species.objects.exists()
    except Exception:
        return False


@lru_cache(maxsize=1)
def load_index() -> dict[str, Any]:
    path = DATA_ROOT / 'index.json'
    if not path.exists():
        return {'project': PROJECT_DEFAULT, 'species': [], 'omics_meta': OMICS_META_DEFAULT, 'compare_pairs': []}
    return json.loads(path.read_text(encoding='utf-8'))


@lru_cache(maxsize=128)
def load_json(relative_path: str) -> Any:
    path = DATA_ROOT / relative_path
    if not path.exists():
        raise NotFoundError(f'Missing dataset file: {relative_path}')
    return json.loads(path.read_text(encoding='utf-8'))


@lru_cache(maxsize=64)
def file_species_map() -> dict[str, dict[str, Any]]:
    idx = load_index()
    return {row['species_id']: row for row in idx.get('species', [])}


@lru_cache(maxsize=1)
def feature_display_schema() -> dict[str, Any]:
    if FEATURE_DISPLAY_SCHEMA_PATH.exists():
        try:
            payload = json.loads(FEATURE_DISPLAY_SCHEMA_PATH.read_text(encoding='utf-8'))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    fallback = {
        'version': 'fallback_v1',
        'notes': 'Auto-generated fallback feature display schema from OMICS_META defaults.',
        'omics': {},
    }
    for omics_key, meta in OMICS_META_DEFAULT.items():
        fallback['omics'][omics_key] = [
            {
                'field': field,
                'label': field.replace('_', ' '),
                'unit': '',
                'family': 'general',
                'value_type': 'numeric',
                'display_transform': 'none',
                'default_chart': 'histogram',
                'allowed_chart_types': ['histogram', 'boxplot', 'scatter', 'heatmap'],
                'allow_in_basic': True,
                'allow_pairwise': True,
                'is_derived': False,
                'evidence_level': 'raw',
                'description_short': '',
            }
            for field in (meta.get('feature_options') or [])
        ]
    return fallback


@lru_cache(maxsize=1)
def feature_dictionary_source() -> dict[str, Any]:
    if FEATURE_DICTIONARY_PATH.exists():
        try:
            payload = json.loads(FEATURE_DICTIONARY_PATH.read_text(encoding='utf-8'))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {
        'schema_version': 'feature_dictionary_fallback',
        'source': str(FEATURE_DICTIONARY_PATH),
        'normalization_policy': 'none',
        'missing_policy': 'missing fields are absent, null, or non-finite',
        'family_defaults': {},
        'field_overrides': {},
    }


def _dictionary_entry(omics: str, field: str, family: str, dictionary: dict[str, Any]) -> dict[str, Any]:
    family_defaults = dictionary.get('family_defaults') if isinstance(dictionary.get('family_defaults'), dict) else {}
    field_overrides = dictionary.get('field_overrides') if isinstance(dictionary.get('field_overrides'), dict) else {}
    fallback = family_defaults.get(family) or family_defaults.get('other') or {}
    override = field_overrides.get(f'{omics}.{field}') or field_overrides.get(field) or {}
    formula = override.get('formula') or fallback.get('formula') or 'Formula is pending registration for this field.'
    formula_status = override.get('formula_status') or fallback.get('formula_status') or 'pending'
    return {
        'formula': formula,
        'formula_status': formula_status,
        'normalization': override.get('normalization') or dictionary.get('normalization_policy') or 'none',
        'missing_rule': override.get('missing_rule') or dictionary.get('missing_policy') or 'Absent, null, or non-finite values are treated as missing.',
    }


@lru_cache(maxsize=1)
def _feature_dictionary_coverage(sample_size: int = 4000) -> dict[str, dict[str, dict[str, Any]]]:
    schema = feature_display_schema()
    fields_by_omics = {
        omics: [str(item.get('field')) for item in fields if isinstance(item, dict) and item.get('field')]
        for omics, fields in (schema.get('omics') or {}).items()
        if isinstance(fields, list)
    }
    coverage = {
        omics: {
            field: {'present_count': 0, 'sample_count': 0, 'coverage_ratio': 0.0, 'missing_rate': 1.0}
            for field in fields
        }
        for omics, fields in fields_by_omics.items()
    }
    if db_mode():
        for omics, fields in fields_by_omics.items():
            if not fields:
                continue
            datasets = OmicsDataset.objects.filter(omics_type=omics).only('summary_payload')
            total = datasets.count()
            present_counts = {field: 0 for field in fields}
            for ds in datasets[:200]:
                summary = ds.summary_payload or {}
                sources = [summary]
                if isinstance(summary.get('core'), dict):
                    sources.append(summary.get('core') or {})
                if isinstance(summary.get('full'), dict):
                    sources.append(summary.get('full') or {})
                registered_fields = set()
                for source in sources:
                    if not isinstance(source, dict):
                        continue
                    for container_key in ('feature_cards', 'distributions', 'field_meta'):
                        container = source.get(container_key)
                        if isinstance(container, dict):
                            registered_fields.update(str(key) for key in container.keys())
                        elif isinstance(container, list):
                            registered_fields.update(str(item.get('field')) for item in container if isinstance(item, dict) and item.get('field'))
                for field in fields:
                    if field in registered_fields:
                        present_counts[field] += 1
            for field in fields:
                ratio = _safe_div(present_counts[field], total)
                coverage[omics][field] = {
                    'present_count': int(present_counts[field]),
                    'sample_count': int(total),
                    'coverage_ratio': round(ratio, 6),
                    'missing_rate': round(1.0 - ratio, 6),
                }
    else:
        for omics, fields in fields_by_omics.items():
            rows = []
            for species_id in list_species_ids()[:10]:
                rows.extend(_file_rows_for_scope(species_id, omics, 'core')[:200])
            total = len(rows)
            present_counts = {field: 0 for field in fields}
            for row in rows:
                for field in fields:
                    if _safe_num(row.get(field)) is not None:
                        present_counts[field] += 1
            for field in fields:
                ratio = _safe_div(present_counts[field], total)
                coverage[omics][field] = {
                    'present_count': int(present_counts[field]),
                    'sample_count': int(total),
                    'coverage_ratio': round(ratio, 6),
                    'missing_rate': round(1.0 - ratio, 6),
                }
    return coverage


def omics_field_meta(omics: str) -> list[dict[str, Any]]:
    schema = feature_display_schema().get('omics') or {}
    rows = schema.get(omics) or []
    output: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if not item.get('field'):
            continue
        output.append(item)
    return output


PLANNED_VISUAL_REQUIREMENTS = {
    'genome': [
        {
            'module': 'Promoter/exon GC contrast',
            'required_fields': ['promoter_gc_percent', 'exon_gc_percent', 'promoter_exon_gc_delta'],
            'recommended_visual': 'bar + scatter + distribution',
            'purpose': 'Regulatory-coding composition contrast.',
        },
        {
            'module': 'GC1/GC2/GC3 and codon pressure',
            'required_fields': ['gc1_percent', 'gc2_percent', 'gc3_percent', 'codon_entropy_bits'],
            'recommended_visual': 'radar + codon-position bar',
            'purpose': 'Coding-region selection pressure and codon strategy.',
        },
        {
            'module': 'GC/AT skew coordinate profile',
            'required_fields': ['gc_skew', 'at_skew', 'seqid', 'start_1', 'end_1', 'strand'],
            'recommended_visual': 'coordinate profile + outlier plot',
            'purpose': 'Replication/strand bias and assembly anomaly checks.',
        },
        {
            'module': 'Dinucleotide genomic signature',
            'required_fields': ['dinuc_AA_freq', 'dinuc_AC_freq', 'dinuc_AG_freq', 'dinuc_AT_freq', 'dinuc_TT_freq'],
            'recommended_visual': '16-cell heatmap + fingerprint',
            'purpose': 'Species fingerprint, local heterogeneity, and candidate island screening.',
        },
        {
            'module': '64-codon usage matrix',
            'required_fields': ['codon_*_freq', 'codon_entropy_bits'],
            'recommended_visual': 'codon heatmap + entropy ranking',
            'purpose': 'Translation-efficiency proxy and ML feature vector.',
        },
    ],
    'transcriptome': [
        {
            'module': 'RNA elemental resource profile',
            'required_fields': ['atoms_per_nt_C', 'atoms_per_nt_H', 'atoms_per_nt_O', 'atoms_per_nt_N', 'atoms_per_nt_P', 'C_N_ratio', 'N_P_ratio', 'mw_rna_nmp_per_nt_Da'],
            'recommended_visual': 'resource bar + distribution',
            'purpose': 'RNA molecular resource cost and nutrient-limitation hypotheses.',
        },
        {
            'module': 'RNA GC and sequence complexity',
            'required_fields': ['gc_content', 'nt_entropy'],
            'recommended_visual': 'scatter + distributions',
            'purpose': 'Composition and sequence-complexity landscape.',
        },
        {
            'module': 'RNA stability proxy',
            'required_fields': ['dinuc_*_freq', 'max_run_any', 'avg_spacing_A', 'avg_spacing_U'],
            'recommended_visual': 'dinucleotide heatmap + homopolymer ranking',
            'purpose': 'Proxy for transcript structural tendency and stability screening.',
        },
        {
            'module': 'RNA-to-protein preview',
            'required_fields': ['orf_len_nt', 'orf_len_aa', 'codon_valid_codons', 'aa_*_freq', 'protein_gravy', 'protein_instability_index', 'protein_isoelectric_point'],
            'recommended_visual': 'ORF summary + protein-property proxy scatter',
            'purpose': 'Connect transcript features to predicted coding product properties.',
        },
    ],
    'proteome': [
        {
            'module': 'Protein elemental resource budget',
            'required_fields': ['N_atoms_per_aa', 'S_atoms_per_aa', 'C_N_ratio', 'N_S_ratio', 'sulfur_aa_frac', 'cys_count', 'met_count'],
            'recommended_visual': 'budget bar + N/S scatter',
            'purpose': 'Protein nitrogen/sulfur resource economy.',
        },
        {
            'module': 'Protein charge and hydropathy',
            'required_fields': ['pI', 'net_charge_pH7', 'gravy'],
            'recommended_visual': 'pI-GRAVY scatter + distribution',
            'purpose': 'Physicochemical regime, localization tendency, and solubility screening.',
        },
        {
            'module': 'Full physicochemical panel',
            'required_fields': ['instability_index', 'aromaticity', 'aliphatic_index', 'avg_oxidation_state_C'],
            'recommended_visual': 'multi-feature radar + ridge/distribution panel',
            'purpose': 'Stability, thermotolerance, aromaticity, and redox-property hypotheses.',
        },
        {
            'module': 'AA composition signature',
            'required_fields': ['aa_*_freq'],
            'recommended_visual': '20-AA heatmap + species fingerprint',
            'purpose': 'Composition-driven function and ML-ready protein language features.',
        },
    ],
}


REQUIREMENT_FIELD_EQUIVALENTS = {
    'genome': {
        'gc1_percent': ['gc12_percent_estimated'],
        'gc2_percent': ['gc12_percent_estimated'],
    },
    'transcriptome': {
        'atoms_per_nt_C': ['atoms_per_nt_C_estimated'],
        'atoms_per_nt_H': ['atoms_per_nt_H_estimated'],
        'atoms_per_nt_O': ['atoms_per_nt_O_estimated'],
        'C_N_ratio': ['C_N_ratio_estimated'],
        'mw_rna_nmp_per_nt_Da': ['mw_rna_nmp_per_nt_Da_estimated'],
    },
    'proteome': {
        'sulfur_aa_frac': ['sulfur_aa_frac_estimated'],
    },
}


@lru_cache(maxsize=4)
def _available_numeric_fields_by_omics(sample_size: int = 2000) -> dict[str, set[str]]:
    available = {key: set() for key in ('genome', 'transcriptome', 'proteome')}
    if db_mode():
        for omics_key in available:
            for ds in OmicsDataset.objects.filter(omics_type=omics_key).only('summary_payload')[:20]:
                summary = ds.summary_payload or {}
                summary_candidates = [summary]
                if isinstance(summary.get('core'), dict):
                    summary_candidates.append(summary.get('core') or {})
                if isinstance(summary.get('full'), dict):
                    summary_candidates.append(summary.get('full') or {})
                for candidate in summary_candidates:
                    for container_key in ('feature_cards', 'distributions'):
                        container = candidate.get(container_key) if isinstance(candidate, dict) else {}
                        if isinstance(container, dict):
                            available[omics_key].update(str(field) for field in container.keys())
                            if omics_key == 'genome' and 'exon_gc_percent' in container and 'gc3_percent' in container:
                                available[omics_key].add('gc12_percent_estimated')
            qs = (
                EntityRecord.objects
                .filter(omics_type=omics_key)
                .only('numeric_summary', 'payload_json')[:sample_size]
            )
            for record in qs.iterator(chunk_size=1000):
                for source in (record.numeric_summary or {}, record.payload_json or {}):
                    for field, value in source.items():
                        if _safe_num(value) is not None:
                            available[omics_key].add(str(field))
                numeric = record.numeric_summary or {}
                payload = record.payload_json or {}
                for field in DERIVED_OMICS_FIELDS.get(omics_key, []):
                    if _feature_value_from_sources(numeric, payload, field) is not None:
                        available[omics_key].add(field)
            if omics_key == 'genome' and {'exon_gc_percent', 'gc3_percent'}.issubset(available[omics_key]):
                available[omics_key].add('gc12_percent_estimated')
    else:
        for species_id in list_species_ids()[:10]:
            for omics_key in available:
                for row in _file_rows_for_scope(species_id, omics_key, 'core')[:200]:
                    for field, value in row.items():
                        if _safe_num(value) is not None:
                            available[omics_key].add(str(field))
    return available


def _requirement_status(required_fields: list[str], available_fields: set[str], omics: str = '') -> dict[str, Any]:
    available_required = []
    missing_required = []
    equivalents = REQUIREMENT_FIELD_EQUIVALENTS.get(omics, {})
    for field in required_fields:
        if '*' in field:
            prefix = field.split('*', 1)[0]
            matched = sorted(name for name in available_fields if name.startswith(prefix))
            if matched:
                available_required.append({'field': field, 'matched_fields': matched[:12], 'match_count': len(matched)})
            else:
                missing_required.append(field)
        elif field in available_fields:
            available_required.append({'field': field, 'matched_fields': [field], 'match_count': 1})
        elif any(candidate in available_fields for candidate in equivalents.get(field, [])):
            matched = [candidate for candidate in equivalents.get(field, []) if candidate in available_fields]
            available_required.append({'field': field, 'matched_fields': matched, 'match_count': len(matched), 'computed_equivalent': True})
        else:
            missing_required.append(field)
    total = len(required_fields) or 1
    return {
        'available_required_fields': available_required,
        'missing_required_fields': missing_required,
        'coverage_ratio': round((total - len(missing_required)) / total, 6),
        'implementation_status': 'implemented' if not missing_required else ('partial' if available_required else 'missing'),
    }


@lru_cache(maxsize=1)
def feature_catalog_payload() -> dict[str, Any]:
    schema = feature_display_schema()
    dictionary = feature_dictionary_source()
    omics_schema = schema.get('omics') or {}
    omics_labels = omics_meta()
    rows: list[dict[str, Any]] = []
    families: set[str] = set()
    available_fields = _available_numeric_fields_by_omics()
    coverage = _feature_dictionary_coverage()

    for omics_key, fields in omics_schema.items():
        if not isinstance(fields, list):
            continue
        for item in fields:
            if not isinstance(item, dict) or not item.get('field'):
                continue
            family = item.get('family') or 'other'
            families.add(str(family))
            recommended = item.get('default_chart') or ''
            allowed = item.get('allowed_chart_types') or []
            if not recommended and allowed:
                recommended = allowed[0]
            field = str(item.get('field'))
            dictionary_entry = _dictionary_entry(omics_key, field, str(family), dictionary)
            coverage_entry = coverage.get(omics_key, {}).get(field, {
                'present_count': 0,
                'sample_count': 0,
                'coverage_ratio': 0.0,
                'missing_rate': 1.0,
            })
            rows.append({
                'omics': omics_key,
                'omics_label': omics_labels.get(omics_key, {}).get('display_name', omics_key),
                'field': field,
                'label': item.get('label') or field.replace('_', ' '),
                'family': family,
                'unit': item.get('unit') or '',
                'scope': 'core' if item.get('allow_in_basic', True) else 'full',
                'available_scopes': item.get('available_scopes') or ['core', 'full'],
                'recommended_chart': recommended or 'histogram',
                'allowed_chart_types': allowed,
                'scientific_meaning': item.get('description_short') or item.get('description') or '',
                'value_type': item.get('value_type') or 'numeric',
                'evidence_level': item.get('evidence_level') or ('computed' if item.get('is_derived') else 'raw'),
                'is_derived': bool(item.get('is_derived')),
                'allow_pairwise': bool(item.get('allow_pairwise', False)),
                'formula': dictionary_entry['formula'],
                'formula_status': dictionary_entry['formula_status'],
                'normalization': dictionary_entry['normalization'],
                'missing_rule': dictionary_entry['missing_rule'],
                'coverage_ratio': coverage_entry['coverage_ratio'],
                'missing_rate': coverage_entry['missing_rate'],
                'present_count': coverage_entry['present_count'],
                'sample_count': coverage_entry['sample_count'],
            })

    rows.sort(key=lambda row: (str(row['omics']), str(row['family']), str(row['field'])))
    planned_modules = []
    for omics_key, modules in PLANNED_VISUAL_REQUIREMENTS.items():
        for module in modules:
            status = _requirement_status(module.get('required_fields') or [], available_fields.get(omics_key, set()), omics_key)
            planned_modules.append({
                'omics': omics_key,
                'omics_label': omics_labels.get(omics_key, {}).get('display_name', omics_key),
                **module,
                **status,
            })

    return {
        'version': schema.get('version') or 'unknown',
        'schema_version': dictionary.get('schema_version') or schema.get('version') or 'unknown',
        'notes': schema.get('notes') or '',
        'dictionary_source': dictionary.get('source') or str(FEATURE_DICTIONARY_PATH),
        'normalization_policy': dictionary.get('normalization_policy') or 'none',
        'missing_policy': dictionary.get('missing_policy') or 'absent, null, or non-finite values are treated as missing',
        'families': sorted(families),
        'items': rows,
        'coverage_summary': {
            'field_count': len(rows),
            'defined_formula_count': sum(1 for row in rows if row.get('formula_status') == 'defined'),
            'pending_formula_count': sum(1 for row in rows if row.get('formula_status') == 'pending'),
            'sample_size_per_omics_max': 4000,
        },
        'module_groups': [
            {
                'family': family,
                'field_count': sum(1 for row in rows if row.get('family') == family),
                'omics': sorted({row.get('omics') for row in rows if row.get('family') == family}),
            }
            for family in sorted(families)
        ],
        'planned_visual_modules': planned_modules,
        'method_metadata': {
            'source': 'shared/schemas/stoich_feature_display_schema.json + backend/apps/stoichdb/resources/feature_dictionary.json',
            'schema_version': dictionary.get('schema_version') or schema.get('version') or 'unknown',
            'normalization': 'none',
            'missing_policy': 'planned modules are marked implemented/partial/missing from sampled numeric fields in the current release',
            'is_exploratory': False,
        },
    }


def clear_runtime_caches() -> None:
    load_index.cache_clear()
    load_json.cache_clear()
    file_species_map.cache_clear()
    feature_display_schema.cache_clear()
    feature_dictionary_source.cache_clear()
    db_mode.cache_clear()
    _available_numeric_fields_by_omics.cache_clear()
    _feature_dictionary_coverage.cache_clear()
    _model_species_priority_info.cache_clear()
    feature_catalog_payload.cache_clear()
    current_release.cache_clear()
    taxonomy_reference_manifest.cache_clear()
    home_payload.cache_clear()
    list_species.cache_clear()
    species_detail.cache_clear()
    cross_omics_mapping_summary.cache_clear()
    get_cross_omics.cache_clear()
    get_omics_bundle.cache_clear()
    get_summary.cache_clear()
    get_analysis.cache_clear()
    row_listing.cache_clear()
    field_summary.cache_clear()
    scatter_payload.cache_clear()
    analysis_hub_payload.cache_clear()
    species_facets.cache_clear()
    release_overview.cache_clear()
    _db_strategy_clusters.cache_clear()
    _file_strategy_clusters.cache_clear()
    species_enhanced_visuals.cache_clear()
    quality_overview.cache_clear()
    coverage_overview.cache_clear()
    downloads_manifest.cache_clear()


def _download_file_url(file_id: str) -> str:
    return f'/api/stoichdb/downloads/files/{file_id}/'


def _download_artifact_url(artifact_id: str) -> str:
    return f'/api/stoichdb/downloads/artifacts/{artifact_id}/'


def _download_page_route(species_id: str = '', omics: str = '') -> str:
    query = []
    if species_id:
        query.append(f'species={species_id}')
    if omics:
        query.append(f'omics={omics}')
    suffix = f"?{'&'.join(query)}" if query else ''
    return f'/downloads{suffix}'


def _release_payload_from_record(record: DataRelease | None) -> dict[str, Any]:
    if not record:
        return {
            'release_id': '',
            'label': 'Unregistered working release',
            'description': 'The PostgreSQL registry is active, but no formal release record is registered yet.',
            'database_engine': 'postgresql',
            'species_count': Species.objects.count() if db_mode() else 0,
            'dataset_count': OmicsDataset.objects.count() if db_mode() else 0,
            'entity_row_count': EntityRecord.objects.count() if db_mode() else 0,
            'artifact_count': AnalysisArtifact.objects.count() if db_mode() else 0,
            'feature_file_count': FeatureFile.objects.count() if db_mode() else 0,
            'source_root': '',
            'pipeline_root': '',
            'platform_registry_path': str(DATA_ROOT),
            'is_active': True,
            'created_at': '',
            'updated_at': '',
            'metadata': {},
            'manifest': {},
        }
    return {
        'release_id': record.release_id,
        'label': record.label,
        'description': record.description,
        'database_engine': record.database_engine,
        'species_count': record.species_count,
        'dataset_count': record.dataset_count,
        'entity_row_count': record.entity_row_count,
        'artifact_count': record.artifact_count,
        'feature_file_count': record.feature_file_count,
        'source_root': record.source_root,
        'pipeline_root': record.pipeline_root,
        'platform_registry_path': record.platform_registry_path,
        'is_active': record.is_active,
        'created_at': record.created_at.isoformat(),
        'updated_at': record.updated_at.isoformat(),
        'metadata': record.metadata_json or {},
        'manifest': record.manifest_json or {},
    }


@lru_cache(maxsize=1)
def current_release() -> dict[str, Any]:
    if db_mode():
        record = DataRelease.objects.filter(is_active=True).order_by('-created_at').first()
        if not record:
            record = DataRelease.objects.order_by('-created_at').first()
        return _release_payload_from_record(record)
    idx = load_index()
    return {
        'release_id': 'file_registry_fallback',
        'label': idx.get('project', {}).get('name', 'Stoichioomics fallback registry'),
        'description': idx.get('project', {}).get('description', 'File-backed fallback registry payload.'),
        'database_engine': 'file_registry',
        'species_count': idx.get('project', {}).get('species_count', len(idx.get('species', []))),
        'dataset_count': sum(len(row.get('omics', {})) for row in idx.get('species', [])),
        'entity_row_count': sum(int(payload.get('row_count', 0)) for row in idx.get('species', []) for payload in row.get('omics', {}).values()),
        'artifact_count': 0,
        'feature_file_count': 0,
        'source_root': '',
        'pipeline_root': '',
        'platform_registry_path': str(DATA_ROOT),
        'is_active': True,
        'created_at': '',
        'updated_at': '',
        'metadata': {},
        'manifest': {},
    }


def _release_species_source_database(release_id: str) -> str:
    if str(release_id or '').startswith('model_organisms_'):
        return f'model_organism_release:{release_id}'
    return ''


@lru_cache(maxsize=1)
def taxonomy_reference_manifest() -> dict[str, Any]:
    """Return the checked-in six-group taxonomy manifest, if available.

    This is intentionally kept separate from the database release metadata:
    the current release record has empty metadata/manifest fields, while the
    taxonomy pipeline has its own generated manifest that is useful for
    reconciliation and QA.
    """
    path = Path(settings.BASE_DIR) / 'data' / 'metadata' / 'taxonomy' / 'taxonomy_metadata_manifest.json'
    if not path.exists():
        return {'status': 'missing', 'path': str(path), 'manifest': {}}
    try:
        return {'status': 'available', 'path': str(path), 'manifest': json.loads(path.read_text(encoding='utf-8'))}
    except Exception as exc:
        return {'status': 'invalid', 'path': str(path), 'manifest': {}, 'error': str(exc)}


def _resolve_existing_path(path_value: str) -> Path | None:
    raw = str(path_value or '').strip()
    if not raw:
        return None
    candidates = [Path(raw)]
    if not Path(raw).is_absolute():
        candidates.extend([
            Path(settings.BASE_DIR) / raw,
            DATA_ROOT / raw,
        ])
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _file_checksum(path: Path | None) -> tuple[str, str]:
    if path is None:
        return '', 'missing'
    try:
        if path.stat().st_size > 64 * 1024 * 1024:
            return '', 'deferred_large_file'
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest(), 'sha256'
    except Exception:
        return '', 'unavailable'


def _file_generated_at(path: Path | None) -> str:
    if path is None:
        return ''
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except Exception:
        return ''


def _file_payload(record: FeatureFile, *, check_exists: bool = True) -> dict[str, Any]:
    resolved = _resolve_existing_path(record.path) if check_exists else None
    filename = resolved.name if resolved else Path(record.path or '').name
    checksum, checksum_status = _file_checksum(resolved) if check_exists else ('', 'not_checked_list_view')
    generated_at = _file_generated_at(resolved) if check_exists else ''
    dataset = getattr(record._state, 'fields_cache', {}).get('dataset')
    return {
        'file_id': record.file_id,
        'file_type': record.file_type,
        'path': record.path,
        'size_bytes': record.size_bytes,
        'filename': filename,
        'download_url': _download_file_url(record.file_id),
        'available': bool(resolved) if check_exists else True,
        'checksum': checksum,
        'checksum_status': checksum_status,
        'checksum_algorithm': 'sha256',
        'schema_version': getattr(dataset, 'schema_version', '') if dataset is not None else '',
        'release_id': current_release().get('release_id', ''),
        'source': 'FeatureFile.path',
        'generated_at': generated_at,
    }


def _artifact_payload(record: AnalysisArtifact, *, check_exists: bool = True, release_id: str = '', include_payload_metadata: bool = True) -> dict[str, Any]:
    resolved = _resolve_existing_path(record.path) if check_exists else None
    filename = resolved.name if resolved else Path(record.path or '').name
    checksum, checksum_status = _file_checksum(resolved) if check_exists else ('', 'not_checked_list_view')
    payload = record.payload_json or {} if include_payload_metadata else {}
    metadata = payload.get('method_metadata') if isinstance(payload, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    analysis_metadata = {
        'analysis_id': record.artifact_id,
        'species_id': record.species.species_id,
        'omics_type': record.omics_type,
        'release_id': release_id,
        'feature_set': metadata.get('feature_set') or payload.get('feature_set') if isinstance(payload, dict) else '',
        'features_used': metadata.get('features_used') or payload.get('features_used') if isinstance(payload, dict) else [],
        'normalization': metadata.get('normalization') or metadata.get('scale') or '',
        'missing_policy': metadata.get('missing_policy') or '',
        'method': metadata.get('method') or record.artifact_type,
        'n_entities': metadata.get('n_entities') or payload.get('n_entities') if isinstance(payload, dict) else '',
        'n_features': metadata.get('n_features') or payload.get('n_features') if isinstance(payload, dict) else '',
        'n_missing': metadata.get('n_missing') or payload.get('n_missing') if isinstance(payload, dict) else '',
        'thresholds': metadata.get('thresholds') or {},
        'is_exploratory': bool(metadata.get('is_exploratory', True)),
    }
    return {
        'artifact_id': record.artifact_id,
        'species_id': record.species.species_id,
        'species_name': record.species.display_name,
        'omics': record.omics_type,
        'artifact_type': record.artifact_type,
        'path': record.path,
        'filename': filename,
        'version': record.version,
        'created_at': record.created_at.isoformat(),
        'generated_at': record.created_at.isoformat(),
        'download_url': _download_artifact_url(record.artifact_id),
        'available': bool(resolved) if check_exists else True,
        'checksum': checksum,
        'checksum_status': checksum_status,
        'checksum_algorithm': 'sha256',
        'schema_version': record.version,
        'release_id': release_id,
        'source': 'AnalysisArtifact.path',
        'route': f"/species/{record.species.species_id}?panel={record.omics_type or 'overview'}",
        'analysis_metadata': analysis_metadata,
    }


@lru_cache(maxsize=1)
def omics_meta() -> dict[str, Any]:
    base = {key: dict(value) for key, value in OMICS_META_DEFAULT.items()}
    for omics_key in base:
        base[omics_key].setdefault('field_meta', omics_field_meta(omics_key))
        base[omics_key].setdefault('available_scopes', ['core'])
    if db_mode():
        meta = base
        for omics_key in list(base.keys()):
            ds = (
                OmicsDataset.objects
                .filter(omics_type=omics_key)
                .only('omics_type', 'browse_meta', 'core_csv_path', 'full_csv_path')
                .order_by('-row_count_core', 'dataset_id')
                .first()
            )
            if not ds:
                continue
            payload = meta.get(ds.omics_type, {}).copy()
            payload.update(ds.browse_meta or {})
            payload.setdefault('field_meta', omics_field_meta(ds.omics_type))
            payload.setdefault('available_scopes', _available_scopes_db_mode(ds))
            meta[ds.omics_type] = payload
        return meta
    merged = load_index().get('omics_meta') or base
    for omics_key, payload in merged.items():
        if not isinstance(payload, dict):
            continue
        payload.setdefault('field_meta', omics_field_meta(omics_key))
        payload.setdefault('available_scopes', _available_scopes_file_mode(next(iter(file_species_map().keys()), ''), omics_key) if file_species_map() else ['core'])
    return merged


def validate_omics(omics: str) -> None:
    if omics not in omics_meta():
        raise NotFoundError(f'Unknown omics type: {omics}')


def _safe_num(value: Any) -> float | None:
    try:
        if value is None:
            return None
        num = float(value)
        if not math.isfinite(num):
            return None
        return num
    except Exception:
        return None


def _safe_int(value: Any, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    if minimum is not None:
        parsed = max(parsed, int(minimum))
    if maximum is not None:
        parsed = min(parsed, int(maximum))
    return parsed


def _normalize_scope(scope: str) -> str:
    token = str(scope or '').strip().lower()
    if token in {'full', 'all'}:
        return 'full'
    return 'core'


def _normalize_compute_mode(compute: str = '') -> str:
    token = str(compute or '').strip().lower()
    if token in {'complete_core', 'complete-core', 'core_complete', 'core-complete', 'full_core', 'full-core', 'exact_core', 'exact-core'}:
        return 'complete_core'
    if token in {'full', 'all', 'exact', 'complete'}:
        return 'full'
    return 'stored'


def _interactive_umap_enabled() -> bool:
    token = str(os.environ.get('STOICHDB_ENABLE_INTERACTIVE_UMAP', '')).strip().lower()
    return token in {'1', 'true', 'yes', 'on'}


def _safe_div(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return float(numerator) / float(denominator)


def _percentile(sorted_values: list[float], ratio: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    ratio = max(0.0, min(1.0, ratio))
    index = ratio * (len(sorted_values) - 1)
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return float(sorted_values[low])
    weight = index - low
    return float(sorted_values[low] * (1 - weight) + sorted_values[high] * weight)


def _fisher_pvalue_from_r(r: float, n: int) -> float:
    if n < 4:
        return 1.0
    bounded = max(min(float(r), 0.999999), -0.999999)
    z = 0.5 * math.log((1.0 + bounded) / (1.0 - bounded)) * math.sqrt(max(1.0, n - 3.0))
    return float(math.erfc(abs(z) / math.sqrt(2.0)))


def _benjamini_hochberg_fdr(pvalues: list[float]) -> list[float]:
    if not pvalues:
        return []
    m = len(pvalues)
    ranked = sorted(enumerate(pvalues), key=lambda item: item[1])
    adjusted = [1.0] * m
    prev = 1.0
    for reverse_rank, (idx, pval) in enumerate(reversed(ranked), start=1):
        rank = m - reverse_rank + 1
        value = min(prev, (float(pval) * m) / max(1, rank))
        adjusted[idx] = value
        prev = value
    return [min(1.0, max(0.0, float(item))) for item in adjusted]


def _distribution_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {'min': 0.0, 'p25': 0.0, 'p50': 0.0, 'p75': 0.0, 'max': 0.0, 'mean': 0.0}
    ordered = sorted(float(v) for v in values)
    return {
        'min': round(ordered[0], 6),
        'p25': round(_percentile(ordered, 0.25), 6),
        'p50': round(_percentile(ordered, 0.50), 6),
        'p75': round(_percentile(ordered, 0.75), 6),
        'max': round(ordered[-1], 6),
        'mean': round(sum(ordered) / len(ordered), 6),
    }


def _median_abs_deviation(values: list[float]) -> tuple[float | None, float | None]:
    clean = sorted(float(v) for v in values if _safe_num(v) is not None)
    if not clean:
        return None, None
    median = _percentile(clean, 0.5)
    deviations = sorted(abs(v - median) for v in clean)
    mad = _percentile(deviations, 0.5) if deviations else 0.0
    return float(median), float(mad)


def _robust_z(value: Any, median: float | None, mad: float | None) -> float | None:
    num = _safe_num(value)
    if num is None or median is None or mad is None or abs(float(mad)) < 1e-12:
        return None
    return 0.67448975 * (float(num) - float(median)) / float(mad)


def _attach_standardized_resource_shifts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach dimensionless robust-z resource-shift metrics to matched cross-omics rows."""
    reference_fields = ['genome_n_per_base', 'transcript_n_per_nt', 'proteome_n_per_aa']
    stats: dict[str, dict[str, float | None]] = {}
    reference_n: dict[str, int] = {}
    for field in reference_fields:
        vals = [float(v) for v in (_safe_num(row.get(field)) for row in rows) if v is not None]
        med, mad = _median_abs_deviation(vals)
        stats[field] = {'median': med, 'mad': mad}
        reference_n[field] = len(vals)
    complete_reference_n = min(reference_n.values() or [0])
    usable = complete_reference_n >= 10 and all((stats[field].get('mad') or 0) > 0 for field in reference_fields)
    for row in rows:
        dna_raw = _safe_num(row.get('dna_to_rna_n_shift'))
        protein_raw = _safe_num(row.get('rna_to_protein_n_shift'))
        existing_dna_std = _safe_num(row.get('dna_to_rna_n_shift_std'))
        existing_protein_std = _safe_num(row.get('rna_to_protein_n_shift_std'))
        row['dna_to_rna_n_shift_legacy_proxy'] = round(float(dna_raw), 6) if dna_raw is not None else row.get('dna_to_rna_n_shift_legacy_proxy')
        row['rna_to_protein_n_shift_legacy_proxy'] = round(float(protein_raw), 6) if protein_raw is not None else row.get('rna_to_protein_n_shift_legacy_proxy')
        row['resource_shift_reference_n'] = int(complete_reference_n)
        row['resource_shift_method_version'] = 'resource_shift_robust_z_v2_2026_08_09'
        row['resource_shift_units'] = 'dimensionless robust-z delta' if usable or existing_dna_std is not None or existing_protein_std is not None else 'raw legacy proxy only; insufficient reference variation'
        if not usable:
            row['dna_to_rna_n_shift_std'] = round(float(existing_dna_std), 6) if existing_dna_std is not None else None
            row['rna_to_protein_n_shift_std'] = round(float(existing_protein_std), 6) if existing_protein_std is not None else None
            row['resource_shift_score_std'] = round(abs(float(existing_dna_std or 0.0)) + abs(float(existing_protein_std or 0.0)), 6) if existing_dna_std is not None or existing_protein_std is not None else None
            continue
        genome_z = _robust_z(row.get('genome_n_per_base'), stats['genome_n_per_base']['median'], stats['genome_n_per_base']['mad'])
        transcript_z = _robust_z(row.get('transcript_n_per_nt'), stats['transcript_n_per_nt']['median'], stats['transcript_n_per_nt']['mad'])
        proteome_z = _robust_z(row.get('proteome_n_per_aa'), stats['proteome_n_per_aa']['median'], stats['proteome_n_per_aa']['mad'])
        dna_std = (transcript_z - genome_z) if transcript_z is not None and genome_z is not None else None
        protein_std = (proteome_z - transcript_z) if proteome_z is not None and transcript_z is not None else None
        row['dna_to_rna_n_shift_std'] = round(float(dna_std), 6) if dna_std is not None else None
        row['rna_to_protein_n_shift_std'] = round(float(protein_std), 6) if protein_std is not None else None
        row['resource_shift_score_std'] = round(abs(float(dna_std or 0.0)) + abs(float(protein_std or 0.0)), 6) if dna_std is not None or protein_std is not None else None
    return {
        'method': 'robust_z_delta',
        'method_version': 'resource_shift_robust_z_v2_2026_08_09',
        'reference_n': int(complete_reference_n),
        'usable': bool(usable),
        'units': 'dimensionless robust-z delta',
        'legacy_proxy_fields': ['dna_to_rna_n_shift_legacy_proxy', 'rna_to_protein_n_shift_legacy_proxy'],
        'reference': stats,
    }


def _value_from_row_payload(row: dict[str, Any], key: str) -> float | None:
    numeric_summary = row.get('numeric_summary') or {}
    payload_json = row.get('payload_json') or {}
    if key in numeric_summary:
        return _safe_num(numeric_summary.get(key))
    return _safe_num(payload_json.get(key))


def _binned_profile(points: list[tuple[float, float]], bins: int = 40) -> dict[str, Any]:
    if not points:
        return {
            'centers': [],
            'counts': [],
            'bin_n': [],
            'bin_start': [],
            'bin_end': [],
            'n': 0,
            'display_mode': 'continuous_profile',
            'aggregation': 'mean_by_coordinate_bin',
            'missing_policy': 'empty bins are null, never zero-filled',
        }
    xs = [float(item[0]) for item in points]
    min_x = min(xs)
    max_x = max(xs)
    if min_x == max_x:
        return {
            'centers': [round(min_x, 6)],
            'counts': [round(sum(float(item[1]) for item in points) / len(points), 6)],
            'bin_n': [len(points)],
            'bin_start': [round(min_x, 6)],
            'bin_end': [round(max_x, 6)],
            'n': len(points),
            'display_mode': 'continuous_profile',
            'aggregation': 'mean_by_coordinate_bin',
            'missing_policy': 'empty bins are null, never zero-filled',
        }
    bins = max(10, min(120, int(bins)))
    width = (max_x - min_x) / bins
    sums = [0.0] * bins
    counts = [0] * bins
    for x, y in points:
        idx = int((float(x) - min_x) / width)
        idx = max(0, min(bins - 1, idx))
        sums[idx] += float(y)
        counts[idx] += 1
    centers = []
    values = []
    starts = []
    ends = []
    for idx in range(bins):
        start = min_x + width * idx
        end = min_x + width * (idx + 1)
        center = min_x + width * (idx + 0.5)
        starts.append(round(start, 6))
        ends.append(round(end, 6))
        centers.append(round(center, 6))
        if counts[idx]:
            values.append(round(sums[idx] / counts[idx], 6))
        else:
            values.append(None)
    return {
        'centers': centers,
        'counts': values,
        'bin_n': counts,
        'bin_start': starts,
        'bin_end': ends,
        'n': len(points),
        'display_mode': 'continuous_profile',
        'aggregation': 'mean_by_coordinate_bin',
        'missing_policy': 'empty bins are null, never zero-filled',
    }


def _histogram_payload(values: list[float], bins: int = 36) -> dict[str, Any]:
    if not values:
        return {'centers': [], 'counts': [], 'n': 0}
    ordered = [float(v) for v in values]
    lo = min(ordered)
    hi = max(ordered)
    if lo == hi:
        return {'centers': [round(lo, 6)], 'counts': [len(ordered)], 'n': len(ordered)}
    bins = max(10, min(120, int(bins)))
    width = (hi - lo) / bins
    counts = [0] * bins
    for value in ordered:
        idx = int((value - lo) / width)
        idx = max(0, min(bins - 1, idx))
        counts[idx] += 1
    centers = [round(lo + width * (idx + 0.5), 6) for idx in range(bins)]
    return {'centers': centers, 'counts': counts, 'n': len(ordered)}


def _clean_meta_value(value: Any) -> str:
    text = str(value or '').strip()
    if text.lower() in {'unknown', 'unclassified', 'not provided', 'nan', 'none'}:
        return ''
    return text


def _species_context_label(row: Species | dict[str, Any]) -> str:
    parts = []
    if isinstance(row, dict):
        candidates = [row.get('source_database'), row.get('assembly_version')]
    else:
        candidates = [row.source_database, row.assembly_version]
    for value in candidates:
        cleaned = _clean_meta_value(value)
        if cleaned:
            parts.append(cleaned)
    return ' / '.join(parts)


def _external_source_url(row: Species | dict[str, Any]) -> str:
    if isinstance(row, dict):
        source_db = _clean_meta_value(row.get('source_database'))
        source_species_id = row.get('source_species_id') or row.get('species_id')
    else:
        source_db = _clean_meta_value(row.source_database)
        source_species_id = row.source_species_id or row.species_id
    if source_db and 'ensembl' in source_db.lower():
        token = str(source_species_id or '').replace(' ', '_')
        if token:
            return f'https://www.ensembl.org/Multi/Search/Results?q={token}'
    return ''


COMPARE_DEFAULT_SPECIES_LIMIT = 12
COMPARE_MAX_SPECIES = 24


QC_GRADE_RULES = [
    {'grade': 'A', 'meaning': 'Default comparison eligible', 'rule': 'Ready dataset, core rows present, schema_version registered, and full rows are not smaller than core rows.'},
    {'grade': 'B', 'meaning': 'Display with limitations and default comparison eligible', 'rule': 'Core rows present and schema_version registered, but one readiness signal is incomplete.'},
    {'grade': 'C', 'meaning': 'Browse only', 'rule': 'Rows are present, but status/schema/readiness is insufficient for default comparison.'},
    {'grade': 'Fail', 'meaning': 'Excluded from default comparison', 'rule': 'No usable rows or invalid row-count relationship.'},
]


def _qc_grade_from_dataset_values(
    *,
    row_count_core: Any = 0,
    row_count_full: Any = 0,
    status: str = '',
    schema_version: str = '',
    feature_file_count: int | None = None,
) -> dict[str, Any]:
    core = int(row_count_core or 0)
    full = int(row_count_full or 0)
    usable_rows = full or core
    ready = str(status or '').lower() in {'ready', 'active', 'ok', 'complete', 'completed', 'loaded'}
    schema_ok = bool(str(schema_version or '').strip())
    row_relation_ok = not (full and core and full < core)
    files_ok = feature_file_count is None or int(feature_file_count or 0) > 0
    if usable_rows <= 0 or not row_relation_ok:
        grade = 'Fail'
        reason = 'No usable rows or invalid full/core row-count relationship.'
    elif ready and schema_ok and files_ok:
        grade = 'A'
        reason = 'Ready dataset with usable rows, schema version, and registered source files.'
    elif schema_ok and core > 0:
        grade = 'B'
        reason = 'Usable core rows and schema version are present, but one readiness signal is incomplete.'
    else:
        grade = 'C'
        reason = 'Rows are present, but status/schema/readiness is insufficient for default comparison.'
    return {
        'qc_grade': grade,
        'qc_reason': reason,
        'default_compare_eligible': grade in {'A', 'B'},
    }


def _combine_qc_grades(grades: list[str]) -> str:
    if not grades:
        return 'Fail'
    order = {'A': 0, 'B': 1, 'C': 2, 'Fail': 3}
    return max(grades, key=lambda value: order.get(value, 3))


def _dataset_chart_ready(ds: OmicsDataset) -> bool:
    return (
        int(ds.row_count_core or 0) > 0
        and bool(str(ds.core_csv_path or '').strip())
        and str(ds.status or '').lower() in {'ready', 'complete', 'ok'}
    )


@lru_cache(maxsize=1)
def _model_species_priority_info() -> dict[str, dict[str, Any]]:
    memberships = list(
        ReleaseSpecies.objects
        .filter(inclusion_status='included', is_model_organism=True, species__isnull=False)
        .select_related('species')
        .only(
            'species_id_text',
            'source_division',
            'expected_model_group',
            'qc_status',
            'species__id',
            'species__species_id',
            'species__display_name',
        )
    )
    if not memberships:
        return {}

    info: dict[str, dict[str, Any]] = {}
    public_ids = []
    for membership in memberships:
        species = membership.species
        if not species:
            continue
        public_id = species.species_id
        public_ids.append(public_id)
        info[public_id] = {
            'species_id': public_id,
            'display_name': species.display_name,
            'source_division': membership.source_division,
            'expected_model_group': membership.expected_model_group,
            'qc_status': membership.qc_status,
            'is_model_organism': True,
            'profiled_omics_count': 0,
            'ready_omics_count': 0,
            'chart_payload_count': 0,
            'cross_artifact_count': 0,
            'overall_completeness_pct': 0.0,
            'minimum_omics_completeness_pct': 0.0,
            'all_three_profiled': False,
        }

    datasets = list(
        OmicsDataset.objects
        .filter(species__species_id__in=public_ids, omics_type__in=ATLAS_OMICS_KEYS)
        .select_related('species')
        .only(
            'id',
            'species__species_id',
            'omics_type',
            'row_count_core',
            'core_csv_path',
            'status',
        )
    )
    dataset_ids = {dataset.id for dataset in datasets}
    chart_payload_dataset_ids: set[int] = set()
    if dataset_ids:
        chart_payload_dataset_ids = set(
            OmicsDataset.objects
            .filter(id__in=dataset_ids)
            .exclude(summary_payload={})
            .exclude(analysis_payload={})
            .values_list('id', flat=True)
        )
    completeness_pct_by_dataset: dict[int, float] = {}
    if dataset_ids:
        for row in (
            AnalysisArtifact.objects
            .filter(artifact_type=ATLAS_COMPLETENESS_ARTIFACT, dataset_id__in=dataset_ids)
            .values('dataset_id', 'payload_json__completeness_pct')
        ):
            pct = _safe_num(row.get('payload_json__completeness_pct'))
            if pct is not None:
                completeness_pct_by_dataset[int(row['dataset_id'])] = float(pct)
    pct_by_species: dict[str, list[float]] = defaultdict(list)
    for dataset in datasets:
        public_id = dataset.species.species_id
        item = info.get(public_id)
        if not item:
            continue
        if _dataset_chart_ready(dataset):
            item['ready_omics_count'] += 1
        if int(dataset.id) in chart_payload_dataset_ids:
            item['chart_payload_count'] += 1
        pct = completeness_pct_by_dataset.get(int(dataset.id))
        if pct is None:
            continue
        item['profiled_omics_count'] += 1
        pct_by_species[public_id].append(pct)

    for row in (
        AnalysisArtifact.objects
        .filter(species__species_id__in=public_ids)
        .filter(Q(artifact_type='cross_omics') | Q(omics_type__in=['all', 'cross_omics']))
        .values('species__species_id')
        .annotate(count=Count('id'))
    ):
        public_id = str(row.get('species__species_id') or '')
        if public_id in info:
            info[public_id]['cross_artifact_count'] = int(row.get('count') or 0)

    for public_id, item in info.items():
        pcts = pct_by_species.get(public_id, [])
        item['all_three_profiled'] = len(pcts) == len(ATLAS_OMICS_KEYS)
        if pcts:
            item['overall_completeness_pct'] = round(sum(pcts) / len(pcts), 4)
            item['minimum_omics_completeness_pct'] = round(min(pcts), 4)
        item['chart_completeness_score'] = round(
            (1000 if item['all_three_profiled'] else 0)
            + float(item['overall_completeness_pct'])
            + (float(item['minimum_omics_completeness_pct']) * 0.1)
            + (item['ready_omics_count'] * 10)
            + (item['chart_payload_count'] * 5)
            + min(item['cross_artifact_count'], 5),
            4,
        )

    ordered = sorted(
        info.values(),
        key=lambda item: (
            not item['all_three_profiled'],
            -float(item['overall_completeness_pct']),
            -float(item['minimum_omics_completeness_pct']),
            -int(item['profiled_omics_count']),
            -int(item['ready_omics_count']),
            -int(item['chart_payload_count']),
            str(item['display_name']).lower(),
            str(item['species_id']),
        ),
    )
    for rank, item in enumerate(ordered):
        item['model_priority_rank'] = rank
    return info


def _species_model_priority_payload(species_id: str) -> dict[str, Any]:
    item = _model_species_priority_info().get(species_id)
    if not item:
        return {
            'is_model_organism': False,
            'model_priority_rank': None,
            'chart_completeness_score': 0,
            'chart_completeness': None,
        }
    return {
        'is_model_organism': True,
        'model_priority_rank': item.get('model_priority_rank'),
        'chart_completeness_score': item.get('chart_completeness_score', 0),
        'chart_completeness': {
            'overall_pct': item.get('overall_completeness_pct', 0),
            'minimum_omics_pct': item.get('minimum_omics_completeness_pct', 0),
            'profiled_omics_count': item.get('profiled_omics_count', 0),
            'ready_omics_count': item.get('ready_omics_count', 0),
            'chart_payload_count': item.get('chart_payload_count', 0),
            'cross_artifact_count': item.get('cross_artifact_count', 0),
            'all_three_profiled': bool(item.get('all_three_profiled')),
            'source': 'species_atlas_core_completeness_artifacts',
        },
    }


def _species_to_summary(row: Species, *, include_model_priority: bool = True) -> dict[str, Any]:
    datasets = {ds.omics_type: ds for ds in row.datasets.all()}
    omics_payload = {}
    dataset_grades = []
    for omics, ds in datasets.items():
        summary = ds.summary_payload or {}
        qc = _qc_grade_from_dataset_values(
            row_count_core=ds.row_count_core,
            row_count_full=ds.row_count_full,
            status=ds.status,
            schema_version=ds.schema_version,
        )
        dataset_grades.append(qc['qc_grade'])
        omics_payload[omics] = {
            'row_count': ds.row_count_full or ds.row_count_core,
            'kpis': summary.get('kpis', [])[:6],
            **qc,
        }
    species_grade = _combine_qc_grades(dataset_grades)
    payload = {
        'species_id': row.species_id,
        'display_name': row.display_name,
        'short_name': row.short_name,
        'source_species_id': row.source_species_id,
        'domain': _clean_meta_value(row.domain),
        'clade': _clean_meta_value(row.clade),
        'habitat': _clean_meta_value(row.habitat),
        'source_database': _clean_meta_value(row.source_database),
        'assembly_version': _clean_meta_value(row.assembly_version),
        'source_context': _species_context_label(row),
        'external_source_url': _external_source_url(row),
        'genome_size_mb': row.genome_size_mb,
        'has_genome': row.has_genome,
        'has_transcriptome': row.has_transcriptome,
        'has_proteome': row.has_proteome,
        'fingerprint': row.fingerprint or {},
        'omics': omics_payload,
        'qc_grade': species_grade,
        'default_compare_eligible': species_grade in {'A', 'B'},
    }
    if include_model_priority:
        payload.update(_species_model_priority_payload(row.species_id))
    return payload


def _species_to_light_summary(row: Species, *, include_model_priority: bool = True) -> dict[str, Any]:
    omics_payload = {}
    dataset_grades = []
    omics_flags = {
        'genome': bool(row.has_genome),
        'transcriptome': bool(row.has_transcriptome),
        'proteome': bool(row.has_proteome),
    }
    for omics, present in omics_flags.items():
        if not present:
            continue
        qc = _qc_grade_from_dataset_values(row_count_core=1, row_count_full=1, status='ready', schema_version='species_flag')
        dataset_grades.append(qc['qc_grade'])
        omics_payload[omics] = {'row_count': None, 'kpis': [], **qc}
    species_grade = _combine_qc_grades(dataset_grades)
    payload = {
        'species_id': row.species_id,
        'display_name': row.display_name,
        'short_name': row.short_name,
        'source_species_id': row.source_species_id,
        'domain': _clean_meta_value(row.domain),
        'clade': _clean_meta_value(row.clade),
        'habitat': _clean_meta_value(row.habitat),
        'source_database': _clean_meta_value(row.source_database),
        'assembly_version': _clean_meta_value(row.assembly_version),
        'source_context': _species_context_label(row),
        'external_source_url': _external_source_url(row),
        'genome_size_mb': row.genome_size_mb,
        'has_genome': row.has_genome,
        'has_transcriptome': row.has_transcriptome,
        'has_proteome': row.has_proteome,
        'fingerprint': row.fingerprint or {},
        'omics': omics_payload,
        'qc_grade': species_grade,
        'default_compare_eligible': species_grade in {'A', 'B'},
        'display_mode': 'lightweight_collection_row',
    }
    if include_model_priority:
        payload.update(_species_model_priority_payload(row.species_id))
    return payload


def _dataset_summary_prefetch() -> Prefetch:
    dataset_qs = OmicsDataset.objects.only(
        'id',
        'species_id',
        'dataset_id',
        'omics_type',
        'schema_version',
        'row_count_core',
        'row_count_full',
        'core_csv_path',
        'full_csv_path',
        'status',
        'summary_payload',
    )
    return Prefetch('datasets', queryset=dataset_qs)


def _species_summary_queryset():
    return Species.objects.only(
        'id',
        'species_id',
        'display_name',
        'short_name',
        'source_species_id',
        'domain',
        'clade',
        'habitat',
        'source_database',
        'assembly_version',
        'genome_size_mb',
        'has_genome',
        'has_transcriptome',
        'has_proteome',
        'fingerprint',
    ).prefetch_related(_dataset_summary_prefetch())


def _species_light_queryset():
    return Species.objects.only(
        'id',
        'species_id',
        'display_name',
        'short_name',
        'source_species_id',
        'domain',
        'clade',
        'habitat',
        'source_database',
        'assembly_version',
        'genome_size_mb',
        'has_genome',
        'has_transcriptome',
        'has_proteome',
        'fingerprint',
    )


def _dataset_total_rows() -> int:
    totals = OmicsDataset.objects.aggregate(core=Sum('row_count_core'), full=Sum('row_count_full'))
    return int((totals.get('full') or 0) + (totals.get('core') or 0))


HOME_CLADE_GROUPS = (
    {'key': 'vertebrates', 'label': 'Vertebrates', 'color': '#18A8D8', 'aliases': {'vertebrates', 'vertebrate'}},
    {'key': 'plants', 'label': 'Plants', 'color': '#39B96C', 'aliases': {'plants', 'plant', 'viridiplantae'}},
    {'key': 'fungi', 'label': 'Fungi', 'color': '#E48A23', 'aliases': {'fungi', 'fungus'}},
    {'key': 'metazoa', 'label': 'Metazoa', 'color': '#1769E0', 'aliases': {'metazoa', 'animalia', 'animals'}},
    {'key': 'protists', 'label': 'Protists', 'color': '#7448C8', 'aliases': {'protists', 'protist'}},
    {'key': 'bacteria', 'label': 'Bacteria', 'color': '#D95467', 'aliases': {'bacteria', 'bacterium'}},
)

HOME_FEATURE_FAMILIES = (
    'Sequence Composition',
    'Amino-acid Properties',
    'Codon Usage',
    'Elemental Stoichiometry',
    'Physicochemical/QC',
    'Module Score',
)

HOME_REPRESENTATIVE_SPECIES = (
    {
        'label': 'Escherichia coli',
        'preferred_ids': (
            'escherichia_coli_str_k_12_substr_mg1655_gca_000005845',
            'escherichia_coli_k_12_gca_004919995',
        ),
        'queries': ('Escherichia coli str k 12', 'Escherichia coli k 12', 'Escherichia coli'),
    },
    {
        'label': 'Saccharomyces cerevisiae',
        'preferred_ids': ('saccharomyces_cerevisiae',),
        'queries': ('Saccharomyces cerevisiae',),
    },
    {
        'label': 'Bacillus subtilis',
        'preferred_ids': ('bacillus_subtilis_gca_004328845', 'bacillus_subtilis_best7613_gca_000328745'),
        'queries': ('Bacillus subtilis',),
    },
    {
        'label': 'Oryza sativa',
        'preferred_ids': ('oryza_sativa',),
        'queries': ('Oryza sativa',),
    },
    {
        'label': 'Arabidopsis thaliana',
        'preferred_ids': ('arabidopsis_thaliana',),
        'queries': ('Arabidopsis thaliana',),
    },
    {
        'label': 'Mus musculus',
        'preferred_ids': ('mus_musculus', 'mus_musculus_casteij'),
        'queries': ('Mus musculus',),
    },
    {
        'label': 'Danio rerio',
        'preferred_ids': ('danio_rerio',),
        'queries': ('Danio rerio',),
    },
    {
        'label': 'Drosophila melanogaster',
        'preferred_ids': ('drosophila_melanogaster',),
        'queries': ('Drosophila melanogaster',),
    },
)

HOME_READINESS_FAMILY_GROUPS = {
    'Sequence Composition': {'gc_composition', 'nucleotide_composition', 'nt_frac', 'dinuc_freq', 'aa_freq', 'aa_pct'},
    'Amino-acid Properties': {'aa_freq', 'aa_pct', 'protein_property', 'physicochemical'},
    'Codon Usage': {'codon_freq'},
    'Elemental Stoichiometry': {'element_density'},
    'Physicochemical/QC': {'physicochemical', 'protein_property', 'molecular_property', 'qc'},
    'Module Score': {'sequence_complexity', 'other'},
}


def compact_count(value: int | None) -> dict[str, Any]:
    raw = int(value or 0)
    if raw >= 1_000_000_000:
        label = f'{raw / 1_000_000_000:.1f}B+'
    elif raw >= 1_000_000:
        label = f'{raw / 1_000_000:.1f}M+'
    elif raw >= 1_000:
        label = f'{raw / 1_000:.1f}K+'
    else:
        label = str(raw)
    return {'raw': raw, 'label': label}


def _active_release_record() -> DataRelease | None:
    record = DataRelease.objects.filter(is_active=True).order_by('-created_at', '-id').first()
    return record or DataRelease.objects.order_by('-created_at', '-id').first()


def _home_display_release_record() -> DataRelease | None:
    """Homepage scope prefers the largest published release over model-only active subsets."""
    full_record = (
        DataRelease.objects
        .filter(status='published')
        .order_by('-species_count', '-dataset_count', '-created_at', '-id')
        .first()
    )
    return full_record or _active_release_record()


def _home_release_has_memberships(release: DataRelease | None) -> bool:
    return bool(release and ReleaseSpecies.objects.filter(release=release, inclusion_status='included').exists())


def _home_scope_memberships(release: DataRelease | None) -> list[ReleaseSpecies]:
    if not release:
        return []
    rows = list(
        ReleaseSpecies.objects.filter(release=release, inclusion_status='included')
        .select_related('species')
        .only(
            'species_id_text',
            'source_division',
            'is_model_organism',
            'qc_status',
            'expected_model_group',
            'species__species_id',
            'species__display_name',
            'species__short_name',
            'species__domain',
            'species__clade',
            'species__has_genome',
            'species__has_transcriptome',
            'species__has_proteome',
            'species__fingerprint',
        )
    )
    return rows


def _home_scope_species_queryset(release: DataRelease | None):
    if _home_release_has_memberships(release):
        ids = ReleaseSpecies.objects.filter(
            release=release,
            inclusion_status='included',
        ).values_list('species_id_text', flat=True)
        return Species.objects.filter(species_id__in=ids)
    return Species.objects.all()


def _home_clade_key(value: str) -> str:
    normalized = str(value or '').strip().lower().replace('_', ' ').replace('-', ' ')
    for group in HOME_CLADE_GROUPS:
        if normalized in group['aliases']:
            return group['key']
    return 'protists'


def _home_clade_label_for_key(key: str) -> str:
    for group in HOME_CLADE_GROUPS:
        if group['key'] == key:
            return group['label']
    return 'Protists'


def _home_feature_registry_counts() -> dict[str, Any]:
    try:
        from .feature_hub.registry import load_registry
        registry = load_registry()
        summary = registry.get('summary') or {}
        return {
            'core_fields': int(summary.get('core_fields') or 0),
            'full_fields': int(summary.get('full_fields') or 0),
            'ml_eligible_core_fields': int(summary.get('ml_eligible_core_fields') or 0),
            'registry_version': registry.get('registry_version', ''),
            'source': registry.get('source', ''),
        }
    except Exception as exc:
        rows = SchemaRegistry.objects.all()
        core = 0
        full = 0
        for schema in rows:
            count = len(schema.columns_json or [])
            if str(schema.product_type).lower() == 'core':
                core += count
            elif str(schema.product_type).lower() == 'full':
                full += count
        return {
            'core_fields': core,
            'full_fields': full,
            'ml_eligible_core_fields': 0,
            'registry_version': '',
            'source': 'SchemaRegistry fallback',
            'warning': str(exc),
        }


def _home_case_stage() -> dict[str, Any]:
    model8_root = Path(settings.BASE_DIR) / 'data' / 'case_studies' / 'model8'
    case_dirs = [path for path in model8_root.iterdir() if path.is_dir() and path.name.startswith('case')] if model8_root.exists() else []
    stage = 'Stage 6' if case_dirs else 'N/A'
    return {
        'label': stage,
        'case_count': len(case_dirs),
        'source': str(model8_root),
    }


def _home_kpis(display_release: DataRelease | None, species_count: int) -> dict[str, Any]:
    registry_counts = _home_feature_registry_counts()
    indexed_entities = int(display_release.entity_row_count or 0) if display_release else 0
    indexed_source = 'display DataRelease.entity_row_count'
    if not indexed_entities:
        indexed_entities = int(DataRelease.objects.aggregate(value=Max('entity_row_count')).get('value') or 0)
        indexed_source = 'largest registered DataRelease.entity_row_count fallback'
    case_stage = _home_case_stage()
    return {
        'species': compact_count(species_count),
        'omics_layers': len(OmicsDataset.OmicsType.choices),
        'core_fields': registry_counts['core_fields'],
        'full_fields': registry_counts['full_fields'],
        'indexed_entities': compact_count(indexed_entities),
        'case_stage': case_stage['label'],
        'case_count': case_stage['case_count'],
        'registry': registry_counts,
        'scope': 'release_membership' if _home_release_has_memberships(display_release) else 'species_table_full_registry',
        'indexed_entities_source': indexed_source,
    }


def _home_membership_group_map(memberships: list[ReleaseSpecies]) -> dict[str, str]:
    group_map: dict[str, str] = {}
    for row in memberships:
        species = row.species
        source_value = row.source_division or (species.domain if species else '')
        group_map[row.species_id_text] = _home_clade_key(source_value)
    return group_map


def _home_clade_distribution(display_release: DataRelease | None, scope_species_count: int) -> list[dict[str, Any]]:
    memberships = _home_scope_memberships(display_release)
    counts = {group['key']: 0 for group in HOME_CLADE_GROUPS}
    if memberships:
        for row in memberships:
            key = _home_clade_key(row.source_division or (row.species.domain if row.species else ''))
            if key in counts:
                counts[key] += 1
    else:
        for row in Species.objects.values('domain').annotate(species_count=Count('id')):
            key = _home_clade_key(row.get('domain', ''))
            if key in counts:
                counts[key] += int(row.get('species_count') or 0)
    total = max(1, scope_species_count)
    rows = []
    for group in HOME_CLADE_GROUPS:
        count = counts[group['key']]
        rows.append({
            'key': group['key'],
            'label': group['label'],
            'species_count': count,
            'percentage': round(count * 100 / total, 1),
            'color': group['color'],
        })
    rows.sort(key=lambda item: item['species_count'], reverse=True)
    return rows


def _home_omics_coverage(display_release: DataRelease | None) -> list[dict[str, Any]]:
    memberships = _home_scope_memberships(display_release)
    group_map = _home_membership_group_map(memberships)
    species_ids = set(group_map.keys())
    group_counts = {group['key']: 0 for group in HOME_CLADE_GROUPS}
    for key in group_map.values():
        if key in group_counts:
            group_counts[key] += 1
    coverage = {group['key']: {'genome': 0, 'transcriptome': 0, 'proteome': 0} for group in HOME_CLADE_GROUPS}
    if not species_ids:
        for row in Species.objects.values('domain').annotate(species_count=Count('id')):
            key = _home_clade_key(row.get('domain', ''))
            if key in group_counts:
                group_counts[key] += int(row.get('species_count') or 0)
        for row in (
            OmicsDataset.objects
            .values('species__domain', 'omics_type')
            .annotate(species_count=Count('species_id', distinct=True))
        ):
            key = _home_clade_key(row.get('species__domain', ''))
            omics = row.get('omics_type')
            if key in coverage and omics in coverage[key]:
                coverage[key][omics] += int(row.get('species_count') or 0)
        return [
            {
                'key': group['key'],
                'label': group['label'],
                'species_count': group_counts.get(group['key'], 0),
                'genome': coverage[group['key']]['genome'],
                'transcriptome': coverage[group['key']]['transcriptome'],
                'proteome': coverage[group['key']]['proteome'],
            }
            for group in HOME_CLADE_GROUPS
        ]
    query = OmicsDataset.objects.filter(species__species_id__in=species_ids).values('species__species_id', 'omics_type')
    seen: set[tuple[str, str]] = set()
    for row in query:
        species_id = row.get('species__species_id')
        omics = row.get('omics_type')
        key = group_map.get(species_id)
        if not key:
            species = Species.objects.filter(species_id=species_id).only('domain').first()
            key = _home_clade_key(species.domain if species else '')
        if key not in coverage or omics not in coverage[key]:
            continue
        marker = (str(species_id), str(omics))
        if marker in seen:
            continue
        seen.add(marker)
        coverage[key][omics] += 1
    return [
        {
            'key': group['key'],
            'label': group['label'],
            'species_count': group_counts.get(group['key'], 0),
            'genome': coverage[group['key']]['genome'],
            'transcriptome': coverage[group['key']]['transcriptome'],
            'proteome': coverage[group['key']]['proteome'],
        }
        for group in HOME_CLADE_GROUPS
    ]


def _home_species_payload(species: Species, membership: ReleaseSpecies | None = None) -> dict[str, Any]:
    fingerprint = species.fingerprint or {}
    return {
        'species_id': species.species_id,
        'display_name': species.display_name,
        'short_name': species.short_name,
        'source_context': _species_context_label(species),
        'source_division': membership.source_division if membership else species.domain,
        'domain': species.domain,
        'clade': species.clade,
        'is_model_organism': bool(membership.is_model_organism) if membership else bool(species.is_featured),
        'published': True,
        'genome_gc': fingerprint.get('genome_gc'),
        'proteome_pi': fingerprint.get('proteome_pi'),
        'omics': {
            'genome': bool(species.has_genome),
            'transcriptome': bool(species.has_transcriptome),
            'proteome': bool(species.has_proteome),
        },
    }


def _preferred_home_representatives() -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in HOME_REPRESENTATIVE_SPECIES:
        row = None
        for preferred_id in spec['preferred_ids']:
            row = Species.objects.filter(species_id=preferred_id).first()
            if row is not None:
                break
        if row is None:
            query_filter = Q()
            for query in spec['queries']:
                query_filter |= Q(display_name__icontains=query) | Q(species_id__icontains=query.lower().replace(' ', '_'))
            row = Species.objects.filter(query_filter).order_by('display_name', 'species_id').first()
        if row is not None and row.species_id not in seen:
            payload = _home_species_payload(row)
            payload['preferred_display_name'] = spec['label']
            selected.append(payload)
            seen.add(row.species_id)
    return selected


def _home_representative_species(display_release: DataRelease | None) -> list[dict[str, Any]]:
    preferred = _preferred_home_representatives()
    if len(preferred) == len(HOME_REPRESENTATIVE_SPECIES):
        return preferred

    memberships = _home_scope_memberships(display_release)
    selected = [row for row in memberships if row.is_model_organism and row.species][:8]
    if selected:
        seen = {item['species_id'] for item in preferred}
        preferred.extend(_home_species_payload(row.species, row) for row in selected if row.species_id_text not in seen)
        return preferred[:8]
    selected = list(
        ReleaseSpecies.objects
        .filter(inclusion_status='included', is_model_organism=True, species__isnull=False)
        .select_related('species')
        .only(
            'species_id_text',
            'source_division',
            'is_model_organism',
            'species__species_id',
            'species__display_name',
            'species__short_name',
            'species__domain',
            'species__clade',
            'species__has_genome',
            'species__has_transcriptome',
            'species__has_proteome',
            'species__fingerprint',
        )
        .order_by('species__display_name')[:8]
    )
    if selected:
        return [_home_species_payload(row.species, row) for row in selected]
    rows = Species.objects.filter(is_featured=True).order_by('display_name')[:8]
    if rows:
        return [_home_species_payload(row) for row in rows]
    return [_home_species_payload(row) for row in Species.objects.order_by('display_name')[:8]]


def _home_core_header(species_id: str, omics: str) -> set[str]:
    try:
        from .feature_hub.sources import DatasetSourceResolver, read_header
        source = DatasetSourceResolver().resolve(species_id, omics, 'core')
        return set(read_header(source))
    except Exception:
        return set()


def _home_core_registry_fields() -> dict[str, list[dict[str, Any]]]:
    try:
        from .feature_hub.registry import load_registry
        rows = load_registry().get('fields') or []
    except Exception:
        return {}
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get('scope') != 'core':
            continue
        if row.get('ml_role') == 'exclude':
            continue
        out[str(row.get('omics') or '')].append(row)
    return out


def _home_readiness_values(species_row: dict[str, Any], registry_fields: dict[str, list[dict[str, Any]]]) -> tuple[list[float | None], list[dict[str, Any]]]:
    values: list[float | None] = []
    details: list[dict[str, Any]] = []
    species_id = species_row['species_id']
    headers = {
        omics: _home_core_header(species_id, omics)
        for omics in ('genome', 'transcriptome', 'proteome')
        if species_row.get('omics', {}).get(omics)
    }
    for label in HOME_FEATURE_FAMILIES:
        family_keys = HOME_READINESS_FAMILY_GROUPS.get(label, set())
        expected = 0
        present = 0
        for omics, header in headers.items():
            candidates = [row for row in registry_fields.get(omics, []) if row.get('family') in family_keys]
            expected += len(candidates)
            present += sum(1 for row in candidates if row.get('field') in header)
        value = round(present * 100 / expected, 1) if expected else None
        values.append(value)
        details.append({
            'family': label,
            'present_fields': present,
            'expected_fields': expected,
            'readiness': value,
        })
    return values, details


def _home_readiness_heatmap(active_release: DataRelease | None) -> dict[str, Any]:
    species_rows = _home_representative_species(active_release)
    registry_fields = _home_core_registry_fields()
    rows = []
    for item in species_rows:
        values, details = _home_readiness_values(item, registry_fields)
        rows.append({
            'species_id': item['species_id'],
            'label': item.get('preferred_display_name') or item['short_name'] or item['display_name'],
            'values': values,
            'details': details,
            'status': 'profiled' if any(value is not None for value in values) else 'not_available',
        })
    return {
        'columns': list(HOME_FEATURE_FAMILIES),
        'rows': rows,
        'scale': {'min': 0, 'max': 100},
        'method': 'Readiness is computed from registered Core feature schemas and the actual CSV headers for each representative species across genome, transcriptome, and proteome datasets.',
    }


def _home_profiled_feature_rows(species_id: str, omics: str, scope: str, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from .feature_hub.profiling import field_profile
    except Exception:
        return fields
    out = []
    for row in fields:
        enriched = dict(row)
        try:
            profile = field_profile(species_id, omics, scope, row.get('field') or '')
            p25 = profile.get('summary', {}).get('p25')
            p75 = profile.get('summary', {}).get('p75')
            enriched['missingness'] = round(float(profile.get('missing_rate') or 0) * 100, 2)
            enriched['iqr'] = round(float(p75) - float(p25), 6) if p25 is not None and p75 is not None else None
            enriched['notes'] = f"{int(profile.get('numeric_n') or 0):,} numeric / {int(profile.get('n_rows') or 0):,} rows"
        except Exception:
            enriched.setdefault('missingness', None)
            enriched.setdefault('iqr', None)
        out.append(enriched)
    return out


def _home_spotlight_qc(species_id: str, omics: str, fields: list[str], fallback_fields: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from .feature_hub.qc import qc_report
        report = qc_report(species_id, omics, fields)
        missing = report.get('missingness') or {}
        return {
            'profile_status': 'profiled_preview_fields',
            'missing_gt_20_count': sum(1 for item in missing.values() if float(item.get('missing_rate') or 0) > 0.2),
            'constant_count': len(report.get('constant') or []),
            'high_corr_pair_count': len(report.get('high_correlation_pairs') or []),
            'compositional_group_count': len(report.get('composition_groups') or {}),
            'message': f"Computed from {int(report.get('selected_features') or len(fields)):,} preview Core fields across {int(report.get('n_rows') or 0):,} {omics} rows.",
        }
    except Exception:
        return {
            'profile_status': 'not_profiled',
            'missing_gt_20_count': None,
            'constant_count': None,
            'high_corr_pair_count': None,
            'compositional_group_count': len({row.get('composition_group') for row in fallback_fields if row.get('composition_group')}),
            'message': 'No cached homepage QC profile was found; open Feature Hub QC for an on-demand report.',
        }


def _home_feature_hub_spotlight(active_release: DataRelease | None) -> dict[str, Any]:
    try:
        from .feature_hub.registry import catalog_payload
        candidates = _home_representative_species(active_release)
        default_species = next((item for item in candidates if item['omics'].get('proteome')), candidates[0] if candidates else None)
        catalog = catalog_payload(omics='proteome', scope='core')
        fields = catalog.get('items') or []
        preview_rows = []
        selected_fields = [
            row for row in fields
            if row.get('ml_role') == 'eligible'
            and row.get('semantic_type') not in {'identifier', 'metadata_text', 'categorical_code', 'coordinate'}
        ][:6]
        for row in selected_fields:
            preview_rows.append({
                'field': row.get('field'),
                'label': row.get('label'),
                'family': row.get('family'),
                'module': row.get('semantic_type') or row.get('ml_role'),
                'dtype': row.get('dtype'),
                'ml_role': row.get('ml_role'),
                'missingness': None,
                'iqr': None,
                'notes': row.get('description') or '',
            })
        dataset = None
        if default_species:
            dataset = OmicsDataset.objects.filter(
                species__species_id=default_species['species_id'],
                omics_type='proteome',
            ).only('row_count_core', 'row_count_full', 'dataset_id', 'status').first()
        if default_species:
            try:
                from .feature_hub.homepage_cache import homepage_preview
                cached = homepage_preview(default_species['species_id'], 'proteome', 'core')
                cached['species'] = default_species
                return cached
            except Exception:
                preview_rows = _home_profiled_feature_rows(default_species['species_id'], 'proteome', 'core', preview_rows)
        return {
            'status': 'ready',
            'species': default_species,
            'omics': 'proteome',
            'table_level': 'core',
            'field_count': int(catalog.get('summary', {}).get('core_fields') or len(fields)),
            'entity_count': int(dataset.row_count_core if dataset else 0),
            'feature_rows': preview_rows,
            'summary': catalog.get('summary') or {},
            'facets': catalog.get('facets') or {},
            'qc': _home_spotlight_qc(
                default_species['species_id'],
                'proteome',
                [row.get('field') for row in preview_rows if row.get('field')],
                selected_fields,
            ) if default_species else {'profile_status': 'unavailable'},
        }
    except Exception as exc:
        return {
            'status': 'unavailable',
            'message': str(exc),
            'feature_rows': [],
            'qc': {'profile_status': 'unavailable'},
        }


@lru_cache(maxsize=1)
def home_payload() -> dict[str, Any]:
    if db_mode():
        active_release_record = _active_release_record()
        display_release_record = _home_display_release_record()
        scope_qs = _home_scope_species_queryset(display_release_record)
        species_count = scope_qs.count()
        total_rows = _dataset_total_rows()
        omics_counts = list(OmicsDataset.objects.values('omics_type').annotate(count=Count('id')).order_by('omics_type'))
        display_release = _release_payload_from_record(display_release_record)
        runtime_active_release = _release_payload_from_record(active_release_record)
        kpis = _home_kpis(display_release_record, species_count)
        representative_species = _home_representative_species(display_release_record)
        return {
            'homepage_schema_version': '2.0',
            'project': {
                **PROJECT_DEFAULT,
                'species_count': species_count,
                'data_mode': 'postgresql_or_orm',
            },
            'platform_scope': {
                'registry_target_species': 30000,
                'registry_source': 'PostgreSQL-backed stoichiometric feature registry',
                'demo_species_loaded': species_count,
                'loaded_species_count': species_count,
                'storage_mode': 'PostgreSQL metadata + JSONB row payloads + file-path manifest for reproducible artifacts',
                'upload_support': [
                    'Genome / transcriptome / proteome feature-table ingestion into PostgreSQL',
                    'Open academic platform mode (no user accounts required)',
                    'HVG-oriented uploaded data workflow',
                ],
            },
            'homepage_data_scope': {
                'display_release_id': display_release.get('release_id', ''),
                'runtime_active_release_id': runtime_active_release.get('release_id', ''),
                'scope': kpis['scope'],
                'species_count_source': 'ReleaseSpecies membership' if _home_release_has_memberships(display_release_record) else 'Species table full registry',
                'dataset_count_source': 'OmicsDataset table',
                'reason': 'Homepage prefers the largest published release so the full coexistence registry is shown even when the runtime active release is a model-organism subset.',
            },
            'stats': [
                {'label': 'Published species', 'value': compact_count(species_count)['label'], 'raw': species_count},
                {'label': 'Loaded omics datasets', 'value': compact_count(OmicsDataset.objects.count())['label'], 'raw': OmicsDataset.objects.count()},
                {'label': 'Registered feature rows', 'value': compact_count(total_rows)['label'], 'raw': total_rows},
                {'label': 'Indexed entities', 'value': kpis['indexed_entities']['label'], 'raw': kpis['indexed_entities']['raw']},
            ],
            'omics_breakdown': [{'omics': r['omics_type'], 'count': r['count']} for r in omics_counts],
            'active_release': display_release,
            'runtime_active_release': runtime_active_release,
            'kpis': kpis,
            'clade_distribution': _home_clade_distribution(display_release_record, species_count),
            'omics_coverage': _home_omics_coverage(display_release_record),
            'readiness_heatmap': _home_readiness_heatmap(display_release_record),
            'representative_species': representative_species,
            'featured_species': representative_species[:4],
            'feature_hub_spotlight': _home_feature_hub_spotlight(display_release_record),
            'module_availability': {
                'database': True,
                'feature_hub': True,
                'entity_explorer': True,
                'compare': True,
                'workflows': True,
                'release_qc': True,
                'docs': True,
            },
            'analysis_tracks': [
                {
                    'title': 'Advanced registry search',
                    'description': 'Species-level filtering, entity-level discovery, and database-backed table queries using PostgreSQL-backed metadata and indexed row payloads.',
                },
                {
                    'title': 'Foundational visualization',
                    'description': 'Feature-table driven distributions, composition summaries, landscapes, and cross-omics previews anchored to imported stoichiometric schemas.',
                },
                {
                    'title': 'Deep stoichiometric analysis',
                    'description': 'Strategy typing, outlier mining, trade-off fronts, coupling networks, and omics-specific artifacts such as stoich islands and resource budgets.',
                },
                {
                    'title': 'Open workflows',
                    'description': 'The platform remains open and account-free; HVG-Stoich jobs stay available for user-run analysis without a login system.',
                },
            ],
            'site_sections': PROJECT_DEFAULT['modules'],
        }
    idx = load_index()
    species = idx.get('species', [])
    total_rows = 0
    omics_counts: dict[str, int] = {}
    for item in species:
        for omics_key, omics_payload in item['omics'].items():
            omics_counts[omics_key] = omics_counts.get(omics_key, 0) + 1
            total_rows += int(omics_payload['row_count'])
    featured = []
    for item in species[:4]:
        featured.append({
            'species_id': item['species_id'],
            'display_name': item['display_name'],
            'source_context': _species_context_label(item),
            'genome_gc': item['fingerprint']['genome_gc'],
            'proteome_pi': item['fingerprint']['proteome_pi'],
        })
    return {
        'project': idx.get('project', PROJECT_DEFAULT),
        'platform_scope': {
            'registry_target_species': 30000,
            'registry_source': 'Ensembl-derived multi-clade stoichiometric feature registry',
            'demo_species_loaded': idx.get('project', {}).get('species_count', len(species)),
            'loaded_species_count': idx.get('project', {}).get('species_count', len(species)),
            'upload_support': ['Genome / transcriptome / proteome sequence-derived feature tables', 'HVG-oriented uploaded data workflow', 'User-owned sequence bundles for private job execution'],
        },
        'stats': [
            {'label': 'Design target species', 'value': '30,000+'},
            {'label': 'Loaded species', 'value': idx.get('project', {}).get('species_count', len(species))},
            {'label': 'Loaded omics tables', 'value': len(species) * len(idx.get('project', {}).get('omics_types', ['genome', 'transcriptome', 'proteome']))},
            {'label': 'Indexed feature rows', 'value': total_rows},
        ],
        'omics_breakdown': [{'omics': k, 'count': v} for k, v in omics_counts.items()],
        'active_release': current_release(),
        'featured_species': featured,
        'analysis_tracks': [
            {
                'title': 'Screen and browse',
                'description': 'Species registry search, omics-specific filtering, fingerprint comparison and row-level exploration for genes, transcripts and proteins.',
            },
            {
                'title': 'Foundational visualization',
                'description': 'Feature-table driven distributions, cross-feature landscapes, composition summaries and cross-omics previews anchored to real stoichiometric schemas.',
            },
            {
                'title': 'Deep stoichiometric analysis',
                'description': 'Strategy typing, outlier mining, trade-off fronts, coupling networks and omics-specific artifacts such as stoich islands, RNA-ORF coupling and protein resource budgets.',
            },
            {
                'title': 'Integrated user workflows',
                'description': 'The original HVG-Stoich jobs system remains available as a dedicated branch for user-uploaded data and reproducible analysis tasks.',
            },
        ],
        'site_sections': idx.get('project', {}).get('modules', PROJECT_DEFAULT['modules']),
    }


def _paginate_payload(rows: list[dict[str, Any]], page: Any = '', page_size: Any = '', default_size: int = 24, aggregate: dict[str, Any] | None = None) -> dict[str, Any] | list[dict[str, Any]]:
    if page in (None, '') and page_size in (None, ''):
        return rows
    try:
        page_num = max(1, int(page or 1))
    except Exception:
        page_num = 1
    try:
        size = max(1, min(500, int(page_size or default_size)))
    except Exception:
        size = default_size
    total = len(rows)
    total_pages = max(1, math.ceil(total / size)) if total else 1
    page_num = min(page_num, total_pages)
    start = (page_num - 1) * size
    end = start + size
    payload = {
        'items': rows[start:end],
        'page': page_num,
        'page_size': size,
        'total': total,
        'total_pages': total_pages,
        'has_next': page_num < total_pages,
        'has_previous': page_num > 1,
    }
    if aggregate is not None:
        payload['aggregate'] = aggregate
    return payload


def _species_queryset_aggregate(qs: Any) -> dict[str, Any]:
    omics_keys = ['genome', 'transcriptome', 'proteome']
    # Build aggregate from a lightweight Species-only queryset. The incoming
    # queryset may carry prefetch/order clauses for row rendering; those are
    # intentionally removed here to keep the registry page responsive.
    base = qs.order_by()
    total = int(base.count())
    omics_counts = {
        'genome': int(base.filter(has_genome=True).count()),
        'transcriptome': int(base.filter(has_transcriptome=True).count()),
        'proteome': int(base.filter(has_proteome=True).count()),
    }
    all_three_count = int(base.filter(has_genome=True, has_transcriptome=True, has_proteome=True).count())
    domain_rows = list(base.values('domain').annotate(count=Count('id')).order_by('-count', 'domain'))
    clade_rows = list(base.values('clade').annotate(count=Count('id')).order_by('-count', 'clade')[:20])
    domain_counts: dict[str, int] = defaultdict(int)
    for row in domain_rows:
        domain_counts[_atlas_domain_label(row.get('domain'))] += int(row.get('count') or 0)
    clade_counts = {(_clean_meta_value(row.get('clade')) or 'Unclassified'): int(row.get('count') or 0) for row in clade_rows}
    domains = [item[0] for item in sorted(domain_counts.items(), key=lambda item: (-item[1], item[0]))[:12]]
    domain_omics_matrix = []
    for y_idx, domain in enumerate(domains):
        domain_filter = _atlas_domain_query(domain)
        domain_qs = base.filter(domain_filter)
        counts = {
            'genome': int(domain_qs.filter(has_genome=True).count()),
            'transcriptome': int(domain_qs.filter(has_transcriptome=True).count()),
            'proteome': int(domain_qs.filter(has_proteome=True).count()),
        }
        for x_idx, omics in enumerate(omics_keys):
            domain_omics_matrix.append([x_idx, y_idx, counts.get(omics, 0)])
    gstats = base.aggregate(min_value=Min('genome_size_mb'), max_value=Max('genome_size_mb'), sum_value=Sum('genome_size_mb'), n_value=Count('genome_size_mb'))
    n_g = int(gstats.get('n_value') or 0)
    g_min = _safe_num(gstats.get('min_value'))
    g_max = _safe_num(gstats.get('max_value'))
    g_sum = _safe_num(gstats.get('sum_value'))
    genome_size_stats = {
        'min': round(float(g_min), 6) if g_min is not None else 0.0,
        'p25': None,
        'p50': None,
        'p75': None,
        'max': round(float(g_max), 6) if g_max is not None else 0.0,
        'mean': round(_safe_div(float(g_sum or 0.0), max(1, n_g)), 6) if n_g else 0.0,
    }
    return {
        'schema_version': 'species_collection_aggregate.v1',
        'display_mode': 'filtered_collection_aggregate',
        'total_count': total,
        'displayed_domain_count': len(domains),
        'display_note': 'domain_omics_matrix is limited to the top 12 domains for responsive registry rendering',
        'omics_counts': omics_counts,
        'domain_counts': domain_counts,
        'clade_counts': clade_counts,
        'all_three_count': all_three_count,
        'all_three_ratio': round(_safe_div(all_three_count, max(1, total)), 6),
        'genome_size_mb_stats': genome_size_stats,
        'domain_omics_matrix': {
            'x_labels': omics_keys,
            'y_labels': domains,
            'values': domain_omics_matrix,
            'scale_type': 'coverage',
            'aggregation': 'filtered_species_count_top_domains',
        },
    }


def _species_collection_aggregate(rows: Any) -> dict[str, Any]:
    summaries = list(rows or [])
    omics_keys = ['genome', 'transcriptome', 'proteome']
    omics_counts = {key: 0 for key in omics_keys}
    domain_counts: dict[str, int] = defaultdict(int)
    clade_counts: dict[str, int] = defaultdict(int)
    completeness_rows = []
    genome_sizes = []
    for row in summaries:
        omics_values = set(row.get('omics') or [])
        if not omics_values:
            for key in omics_keys:
                if row.get(f'has_{key}'):
                    omics_values.add(key)
        for key in omics_keys:
            if key in omics_values:
                omics_counts[key] += 1
        domain = _atlas_domain_label(row.get('domain'))
        clade = _clean_meta_value(row.get('clade')) or 'Unclassified'
        domain_counts[domain] += 1
        clade_counts[clade] += 1
        gsize = _safe_num(row.get('genome_size_mb'))
        if gsize is not None:
            genome_sizes.append(float(gsize))
        present = sum(1 for key in omics_keys if key in omics_values)
        completeness_rows.append({
            'species_id': row.get('species_id'),
            'display_name': row.get('display_name'),
            'omics_present_count': present,
            'all_three': present == 3,
        })
    total = len(summaries)
    domain_omics_matrix = []
    domains = sorted(domain_counts)
    for y_idx, domain in enumerate(domains):
        domain_rows = [row for row in summaries if _atlas_domain_label(row.get('domain')) == domain]
        for x_idx, omics in enumerate(omics_keys):
            value = sum(1 for row in domain_rows if omics in set(row.get('omics') or []) or row.get(f'has_{omics}'))
            domain_omics_matrix.append([x_idx, y_idx, value])
    return {
        'schema_version': 'species_collection_aggregate.v1',
        'display_mode': 'filtered_collection_aggregate',
        'total_count': total,
        'omics_counts': omics_counts,
        'domain_counts': dict(sorted(domain_counts.items(), key=lambda item: (-item[1], item[0]))),
        'clade_counts': dict(sorted(clade_counts.items(), key=lambda item: (-item[1], item[0]))[:20]),
        'all_three_count': sum(1 for item in completeness_rows if item['all_three']),
        'all_three_ratio': round(_safe_div(sum(1 for item in completeness_rows if item['all_three']), max(1, total)), 6),
        'genome_size_mb_stats': _distribution_stats(genome_sizes) if genome_sizes else {},
        'domain_omics_matrix': {
            'x_labels': omics_keys,
            'y_labels': domains,
            'values': domain_omics_matrix,
            'scale_type': 'coverage',
            'aggregation': 'filtered_species_count',
        },
    }


def _page_params(page: Any = '', page_size: Any = '', default_size: int = 24) -> tuple[int, int]:
    try:
        page_num = max(1, int(page or 1))
    except Exception:
        page_num = 1
    try:
        size = max(1, min(500, int(page_size or default_size)))
    except Exception:
        size = default_size
    return page_num, size


def _should_use_model_priority_sort(sort_by: str, sort_order: str) -> bool:
    return str(sort_by or 'display_name') == 'display_name' and str(sort_order or 'asc').lower() == 'asc'


def _apply_model_priority_ordering(qs: Any) -> Any:
    priority = _model_species_priority_info()
    if not priority:
        return qs.order_by('display_name', 'species_id')
    whens = [
        When(species_id=species_id, then=Value(int(item.get('model_priority_rank') or 0)))
        for species_id, item in priority.items()
    ]
    return (
        qs
        .annotate(
            _model_priority_rank=Case(
                *whens,
                default=Value(1_000_000),
                output_field=IntegerField(),
            )
        )
        .order_by('_model_priority_rank', 'display_name', 'species_id')
    )


def _model_priority_sort_key(row: Species) -> tuple[Any, ...]:
    item = _model_species_priority_info().get(row.species_id)
    if item:
        return (
            0,
            int(item.get('model_priority_rank') or 0),
            str(row.display_name or '').lower(),
            str(row.species_id),
        )
    return (1, 1_000_000, str(row.display_name or '').lower(), str(row.species_id))


@lru_cache(maxsize=128)
def list_species(query: str = '', domain: str = '', omics: str = '', clade: str = '', habitat: str = '', has_all_omics: str = '', genome_size_min: Any = '', genome_size_max: Any = '', fingerprint_filters: str = '', sort_by: str = 'display_name', sort_order: str = 'asc', page: Any = '', page_size: Any = '', compare_default: Any = '', include_aggregate: Any = 'true') -> dict[str, Any] | list[dict[str, Any]]:
    if db_mode():
        compare_default_mode = str(compare_default).lower() in {'1', 'true', 'yes'}
        aggregate_enabled = str(include_aggregate).lower() not in {'0', 'false', 'no'}
        qs = _species_light_queryset() if compare_default_mode or not aggregate_enabled else _species_summary_queryset()
        if compare_default_mode:
            qs = qs.filter(has_genome=True, has_transcriptome=True, has_proteome=True)
        gmin = _safe_num(genome_size_min)
        gmax = _safe_num(genome_size_max)
        qs = _filtered_species_queryset(
            query=query,
            domain=domain,
            clade=clade,
            habitat=habitat,
            include_omics_filter=True,
            omics=omics,
            has_all_omics=has_all_omics,
            base_queryset=qs,
        )
        wants_page = page not in (None, '') or page_size not in (None, '')
        if compare_default_mode and not aggregate_enabled and wants_page and not fingerprint_filters and gmin is None and gmax is None:
            page_num, size = _page_params(page=page, page_size=page_size)
            start = (page_num - 1) * size
            page_rows = list(qs.order_by('id')[start:start + size + 1])
            has_next = len(page_rows) > size
            items = [_species_to_light_summary(r) for r in page_rows[:size]]
            return {
                'items': items,
                'page': page_num,
                'page_size': size,
                'total': None,
                'total_pages': None,
                'has_next': has_next,
                'has_previous': page_num > 1,
                'display_mode': 'compare_default_fast_page',
            }
        if compare_default_mode and not sort_by:
            sort_by = 'display_name'
        db_sort_fields = {'display_name', 'domain', 'clade', 'genome_size_mb'}
        if wants_page and not fingerprint_filters and gmin is None and gmax is None and sort_by in db_sort_fields:
            if _should_use_model_priority_sort(sort_by, sort_order):
                qs = _apply_model_priority_ordering(qs)
            else:
                order_field = sort_by
                if sort_order != 'asc':
                    order_field = f'-{order_field}'
                qs = qs.order_by(order_field, 'species_id')
            page_num, size = _page_params(page=page, page_size=page_size)
            total = qs.count()
            total_pages = max(1, math.ceil(total / size)) if total else 1
            page_num = min(page_num, total_pages)
            start = (page_num - 1) * size
            items = [_species_to_light_summary(r) for r in qs[start:start + size]]
            aggregate = _species_queryset_aggregate(qs) if aggregate_enabled else None
            payload = {
                'items': items,
                'page': page_num,
                'page_size': size,
                'total': total,
                'total_pages': total_pages,
                'has_next': page_num < total_pages,
                'has_previous': page_num > 1,
            }
            if aggregate is not None:
                payload['aggregate'] = aggregate
            return payload
        rows = list(qs)
        if gmin is not None:
            rows = [r for r in rows if (r.genome_size_mb or 0) >= gmin]
        if gmax is not None:
            rows = [r for r in rows if (r.genome_size_mb or 0) <= gmax]
        rows = _apply_fingerprint_filters(rows, fingerprint_filters)
        if _should_use_model_priority_sort(sort_by, sort_order):
            rows = sorted(rows, key=_model_priority_sort_key)
        else:
            rows = sorted(rows, key=lambda r: _species_sort_key(r, sort_by), reverse=(sort_order != 'asc'))
        summaries = [_species_to_summary(r) for r in rows]
        return _paginate_payload(summaries, page=page, page_size=page_size, aggregate=_species_collection_aggregate(summaries) if aggregate_enabled else None)

    rows = list(file_species_map().values())
    if query:
        q = query.lower().strip()
        rows = [r for r in rows if q in r['display_name'].lower() or q in r['species_id'].lower() or q in r['clade'].lower()]
    if domain:
        rows = [r for r in rows if r['domain'].lower() == domain.lower()]
    if omics:
        validate_omics(omics)
        rows = [r for r in rows if omics in r['omics']]
    return _paginate_payload(rows, page=page, page_size=page_size, aggregate=_species_collection_aggregate(rows) if str(include_aggregate).lower() not in {'0', 'false', 'no'} else None)


def _species_sort_key(row: Species, sort_by: str) -> Any:
    fp = row.fingerprint or {}
    if sort_by == 'genome_size_mb':
        return row.genome_size_mb or 0
    if sort_by in {'display_name', 'domain', 'clade'}:
        return getattr(row, sort_by, '') or ''
    return fp.get(sort_by, '') or ''


def _apply_fingerprint_filters(rows: list[Species], fingerprint_filters: str) -> list[Species]:
    if not fingerprint_filters:
        return rows
    try:
        parsed = json.loads(fingerprint_filters)
    except Exception:
        return rows
    if isinstance(parsed, dict):
        parsed = [parsed]
    filtered = rows
    for item in parsed:
        key = item.get('key')
        if not key:
            continue
        min_v = _safe_num(item.get('min'))
        max_v = _safe_num(item.get('max'))
        if min_v is None and max_v is None:
            continue
        next_rows = []
        for row in filtered:
            value = _safe_num((row.fingerprint or {}).get(key))
            if value is None:
                continue
            if min_v is not None and value < min_v:
                continue
            if max_v is not None and value > max_v:
                continue
            next_rows.append(row)
        filtered = next_rows
    return filtered


ATLAS_DOMAIN_ORDER = ('Bacteria', 'Fungi', 'Metazoa', 'Plants', 'Protists', 'Vertebrates')
ATLAS_OMICS_KEYS = ('genome', 'transcriptome', 'proteome')
ATLAS_COMPLETENESS_ARTIFACT = 'species_atlas_core_completeness'


def _atlas_domain_query(domain: Any) -> Q:
    label = _atlas_domain_label(domain)
    if label == 'Protists':
        return (
            Q(domain__iexact='Protists') |
            Q(domain__iexact='Protist')
        )
    return Q(domain__iexact=label)


def _filtered_species_queryset(
    query: str = '',
    domain: str = '',
    clade: str = '',
    habitat: str = '',
    genome_size_min: Any = '',
    genome_size_max: Any = '',
    fingerprint_filters: str = '',
    *,
    include_omics_filter: bool = False,
    omics: str = '',
    has_all_omics: str = '',
    base_queryset: Any = None,
) -> Any:
    qs = base_queryset if base_queryset is not None else _species_summary_queryset()
    if query:
        q = query.strip()
        qs = qs.filter(
            Q(display_name__icontains=q) |
            Q(species_id__icontains=q) |
            Q(clade__icontains=q) |
            Q(habitat__icontains=q) |
            Q(searchable_text__icontains=q)
        )
    if domain:
        qs = qs.filter(_atlas_domain_query(domain))
    if clade:
        qs = qs.filter(clade__icontains=clade)
    if habitat:
        qs = qs.filter(habitat__icontains=habitat)
    if include_omics_filter and omics:
        validate_omics(omics)
        qs = qs.filter(datasets__omics_type=omics).distinct()
    if include_omics_filter and str(has_all_omics).lower() in {'1', 'true', 'yes'}:
        qs = qs.filter(has_genome=True, has_transcriptome=True, has_proteome=True)
    gmin = _safe_num(genome_size_min)
    gmax = _safe_num(genome_size_max)
    if gmin is not None:
        qs = qs.filter(genome_size_mb__gte=gmin)
    if gmax is not None:
        qs = qs.filter(genome_size_mb__lte=gmax)
    if fingerprint_filters:
        rows = _apply_fingerprint_filters(list(qs), fingerprint_filters)
        ids = [row.pk for row in rows]
        qs = Species.objects.filter(pk__in=ids)
    return qs


def _atlas_domain_label(value: Any) -> str:
    label = _clean_meta_value(value)
    if not label or label.lower() in {'unknown', 'unclassified', 'na', 'n/a', 'none'}:
        return 'Unclassified'
    for domain in ATLAS_DOMAIN_ORDER:
        if label.lower() == domain.lower():
            return domain
    return label


def _atlas_domain_order(labels: list[str]) -> list[str]:
    seen = {_atlas_domain_label(label) for label in labels if _atlas_domain_label(label)}
    ordered = [domain for domain in ATLAS_DOMAIN_ORDER if domain in seen]
    extra = sorted(label for label in seen if label not in ATLAS_DOMAIN_ORDER)
    return ordered + extra


def _atlas_core_field_counts() -> dict[str, int]:
    try:
        from .feature_hub.registry import fields_for
        return {
            omics: sum(
                1 for row in fields_for(omics, 'core')
                if row.get('ml_role') in {'eligible', 'conditional'} and row.get('semantic_type') not in {'identifier', 'metadata_text', 'coordinate'}
            )
            for omics in ATLAS_OMICS_KEYS
        }
    except Exception:
        counts: dict[str, int] = {}
        for omics in ATLAS_OMICS_KEYS:
            total = 0
            for schema in SchemaRegistry.objects.filter(omics_type=omics, product_type='core'):
                total += len(schema.columns_json or [])
            counts[omics] = total
        return counts


def _atlas_ready_dataset_filter(prefix: str = 'datasets') -> Q:
    return (
        Q(**{f'{prefix}__row_count_core__gt': 0}) &
        ~Q(**{f'{prefix}__core_csv_path': ''}) &
        Q(**{f'{prefix}__status__in': ['ready', 'complete', 'ok']})
    )


def _atlas_percentile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = (len(sorted_values) - 1) * fraction
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return float(sorted_values[low])
    return float(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low))


def _atlas_kde(log_values: list[float], bins: int = 40) -> list[dict[str, float]]:
    if len(log_values) < 3:
        return []
    lo = min(log_values)
    hi = max(log_values)
    if lo == hi:
        return [{'x': round(10 ** lo, 6), 'density': 1.0}]
    n = len(log_values)
    mean = sum(log_values) / n
    variance = sum((value - mean) ** 2 for value in log_values) / max(1, n - 1)
    std = math.sqrt(max(variance, 1e-8))
    bandwidth = max(0.05, 1.06 * std * (n ** -0.2))
    points = []
    max_density = 0.0
    for idx in range(bins):
        x_log = lo + ((hi - lo) * idx / max(1, bins - 1))
        density = sum(math.exp(-0.5 * ((x_log - value) / bandwidth) ** 2) for value in log_values) / (n * bandwidth * math.sqrt(2 * math.pi))
        max_density = max(max_density, density)
        points.append({'x_log': x_log, 'x': 10 ** x_log, 'density': density})
    if max_density:
        for point in points:
            point['density'] = point['density'] / max_density
    return [{'x': round(point['x'], 6), 'density': round(point['density'], 6)} for point in points]


def _atlas_genome_distribution(base_qs: Any, domain_order: list[str]) -> list[dict[str, Any]]:
    output = []
    for domain in domain_order:
        domain_filter = _atlas_domain_query(domain)
        rows = list(
            base_qs.filter(domain_filter)
            .values_list('genome_size_mb', flat=True)
            .order_by('genome_size_mb')
        )
        valid = sorted(float(value) for value in rows if _safe_num(value) is not None and float(value) > 0)
        excluded = len(rows) - len(valid)
        if not valid:
            output.append({'domain': domain, 'n': 0, 'excluded_count': excluded, 'outliers': [], 'violin': []})
            continue
        q1 = _atlas_percentile(valid, 0.25)
        median_value = _atlas_percentile(valid, 0.5)
        q3 = _atlas_percentile(valid, 0.75)
        iqr = float((q3 or 0) - (q1 or 0))
        low_bound = float((q1 or 0) - (1.5 * iqr))
        high_bound = float((q3 or 0) + (1.5 * iqr))
        inside = [value for value in valid if value >= low_bound and value <= high_bound]
        whisker_low = min(inside) if inside else min(valid)
        whisker_high = max(inside) if inside else max(valid)
        outliers = [value for value in valid if value < whisker_low or value > whisker_high]
        if len(outliers) > 300:
            sample_step = max(1, math.ceil(len(outliers) / 300))
            outliers = outliers[::sample_step]
        log_values = [math.log10(value) for value in valid if value > 0]
        output.append({
            'domain': domain,
            'n': len(valid),
            'excluded_count': excluded,
            'min': round(min(valid), 6),
            'q1': round(float(q1 or 0), 6),
            'median': round(float(median_value or 0), 6),
            'q3': round(float(q3 or 0), 6),
            'max': round(max(valid), 6),
            'whisker_low': round(float(whisker_low), 6),
            'whisker_high': round(float(whisker_high), 6),
            'outliers': [round(float(value), 6) for value in outliers],
            'violin': _atlas_kde(log_values),
        })
    return output


def _atlas_completeness_by_dataset(dataset_ids: set[int] | None = None) -> dict[int, dict[str, Any]]:
    qs = AnalysisArtifact.objects.filter(artifact_type=ATLAS_COMPLETENESS_ARTIFACT, dataset__isnull=False)
    if dataset_ids is not None:
        qs = qs.filter(dataset_id__in=dataset_ids)
    out: dict[int, dict[str, Any]] = {}
    for artifact in qs.only('dataset_id', 'payload_json').iterator(chunk_size=5000):
        payload = artifact.payload_json or {}
        out[int(artifact.dataset_id)] = payload
    return out


def _atlas_model_species_completeness_payload() -> list[dict[str, Any]]:
    representatives = _preferred_home_representatives()
    if len(representatives) < len(HOME_REPRESENTATIVE_SPECIES):
        representatives = _home_representative_species(_home_display_release_record())
    representatives = representatives[:len(HOME_REPRESENTATIVE_SPECIES)]
    species_ids = [row['species_id'] for row in representatives if row.get('species_id')]
    if not species_ids:
        return []

    species_by_public_id = {
        row.species_id: row
        for row in Species.objects.filter(species_id__in=species_ids).only('id', 'species_id', 'display_name', 'domain')
    }
    datasets = list(
        OmicsDataset.objects
        .filter(species__species_id__in=species_ids, omics_type__in=ATLAS_OMICS_KEYS)
        .select_related('species')
        .only('id', 'species_id', 'species__species_id', 'species__display_name', 'species__domain', 'omics_type')
    )
    artifacts = _atlas_completeness_by_dataset({dataset.id for dataset in datasets})
    rows_by_species: dict[str, dict[str, Any]] = {}
    for dataset in datasets:
        public_id = dataset.species.species_id
        row = rows_by_species.setdefault(public_id, {
            'species_id': public_id,
            'display_name': dataset.species.display_name,
            'domain': _atlas_domain_label(dataset.species.domain),
            'genome_pct': None,
            'transcriptome_pct': None,
            'proteome_pct': None,
        })
        payload = artifacts.get(dataset.id)
        if not payload:
            continue
        pct = _safe_num(payload.get('completeness_pct'))
        if pct is None:
            continue
        row[f'{dataset.omics_type}_pct'] = round(float(pct), 4)

    ordered_rows: list[dict[str, Any]] = []
    for representative in representatives:
        public_id = representative.get('species_id')
        species = species_by_public_id.get(public_id)
        row = rows_by_species.get(public_id, {
            'species_id': public_id,
            'display_name': species.display_name if species else representative.get('display_name') or representative.get('preferred_display_name') or public_id,
            'domain': _atlas_domain_label(species.domain if species else representative.get('domain')),
            'genome_pct': None,
            'transcriptome_pct': None,
            'proteome_pct': None,
        })
        row = dict(row)
        row['display_name'] = representative.get('preferred_display_name') or row.get('display_name') or public_id
        values = [row.get(f'{omics}_pct') for omics in ATLAS_OMICS_KEYS]
        row['overall_pct'] = round(sum(float(value) for value in values) / 3.0, 4) if all(value is not None for value in values) else None
        row['all_three_profiled'] = all(value is not None for value in values)
        ordered_rows.append(row)
    return ordered_rows


def _atlas_completeness_payload(base_qs: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    species_ids = set(base_qs.values_list('id', flat=True))
    datasets = list(
        OmicsDataset.objects
        .filter(species_id__in=species_ids, omics_type__in=ATLAS_OMICS_KEYS)
        .select_related('species')
        .only('id', 'species_id', 'species__species_id', 'species__display_name', 'species__domain', 'omics_type')
    )
    artifacts = _atlas_completeness_by_dataset({dataset.id for dataset in datasets})
    weighted = {omics: {'valid_cells': 0, 'applicable_cells': 0, 'datasets': 0, 'field_count': 0} for omics in ATLAS_OMICS_KEYS}
    species_scores: dict[int, dict[str, Any]] = {}
    core_field_counts = _atlas_core_field_counts()
    for omics in ATLAS_OMICS_KEYS:
        weighted[omics]['field_count'] = int(core_field_counts.get(omics) or 0)
    for dataset in datasets:
        payload = artifacts.get(dataset.id)
        if not payload:
            continue
        omics = dataset.omics_type
        applicable = int(payload.get('applicable_cells') or 0)
        valid = int(payload.get('valid_cells') or 0)
        pct = _safe_num(payload.get('completeness_pct'))
        if applicable <= 0 or pct is None:
            continue
        weighted[omics]['valid_cells'] += valid
        weighted[omics]['applicable_cells'] += applicable
        weighted[omics]['datasets'] += 1
        species_row = species_scores.setdefault(dataset.species_id, {
            'species_id': dataset.species.species_id,
            'display_name': dataset.species.display_name,
            'domain': _atlas_domain_label(dataset.species.domain),
            'genome_pct': None,
            'transcriptome_pct': None,
            'proteome_pct': None,
        })
        species_row[f'{omics}_pct'] = round(float(pct), 4)
    summary = {}
    for omics in ATLAS_OMICS_KEYS:
        applicable = weighted[omics]['applicable_cells']
        valid = weighted[omics]['valid_cells']
        summary[omics] = {
            **weighted[omics],
            'pct': round(_safe_div(valid * 100.0, applicable), 4) if applicable else None,
            'artifact_count': weighted[omics]['datasets'],
        }
    top_rows = []
    for row in species_scores.values():
        values = [row.get(f'{omics}_pct') for omics in ATLAS_OMICS_KEYS]
        if any(value is None for value in values):
            continue
        overall = sum(float(value) for value in values) / 3.0
        row['overall_pct'] = round(overall, 4)
        row['_min_pct'] = min(float(value) for value in values)
        top_rows.append(row)
    top_rows.sort(key=lambda row: (-row['overall_pct'], -row['_min_pct'], row['display_name']))
    for row in top_rows:
        row.pop('_min_pct', None)
    return summary, _atlas_model_species_completeness_payload()


@lru_cache(maxsize=128)
def species_atlas_summary(
    query: str = '',
    domain: str = '',
    clade: str = '',
    habitat: str = '',
    genome_size_min: Any = '',
    genome_size_max: Any = '',
    fingerprint_filters: str = '',
) -> dict[str, Any]:
    if not db_mode():
        rows = list(file_species_map().values())
        aggregate = _species_collection_aggregate(rows)
        now = datetime.now(timezone.utc).isoformat()
        return {
            'meta': {
                'release_id': current_release().get('release_id', 'file_registry_fallback'),
                'generated_at': now,
                'species_total': len(rows),
                'scope': 'atlas_context',
                'domain_order': list(aggregate.get('domain_counts', {}).keys()),
                'data_mode': 'file_registry',
            },
            'domain_omics_coverage': {'rows': [], 'all_domains': {}},
            'genome_size_distribution': [],
            'omics_availability': {},
            'core_feature_completeness': {},
            'top_species_completeness': [],
        }
    base_qs = _filtered_species_queryset(
        query=query,
        domain=domain,
        clade=clade,
        habitat=habitat,
        genome_size_min=genome_size_min,
        genome_size_max=genome_size_max,
        fingerprint_filters=fingerprint_filters,
        include_omics_filter=False,
        base_queryset=Species.objects.all(),
    ).order_by()
    species_total = int(base_qs.count())
    domain_count_rows = list(base_qs.values('domain').annotate(count=Count('id')).order_by('domain'))
    domain_order = _atlas_domain_order([row.get('domain') for row in domain_count_rows])
    species_ids = base_qs.values('id')
    ready_counts: dict[str, set[int]] = {omics: set() for omics in ATLAS_OMICS_KEYS}
    for row in (
        OmicsDataset.objects
        .filter(species_id__in=species_ids, omics_type__in=ATLAS_OMICS_KEYS, row_count_core__gt=0)
        .exclude(core_csv_path='')
        .filter(status__in=['ready', 'complete', 'ok'])
        .values('species_id', 'omics_type')
        .distinct()
    ):
        ready_counts[str(row['omics_type'])].add(int(row['species_id']))
    species_domain = {
        int(row['id']): _atlas_domain_label(row.get('domain'))
        for row in base_qs.values('id', 'domain').iterator(chunk_size=5000)
    }
    domain_totals = {domain: 0 for domain in domain_order}
    for label in species_domain.values():
        domain_totals[label] = domain_totals.get(label, 0) + 1
    core_field_counts = _atlas_core_field_counts()
    coverage_rows = []
    all_species_ids = set(species_domain)
    all_three_ids = set.intersection(*(ready_counts[omics] for omics in ATLAS_OMICS_KEYS)) if all_species_ids else set()
    for domain_label in domain_order:
        ids = {sid for sid, label in species_domain.items() if label == domain_label}
        total = len(ids)
        row = {'domain': domain_label, 'species_count': total}
        for omics in ATLAS_OMICS_KEYS:
            available = len(ids & ready_counts[omics])
            row[omics] = {
                'available': available,
                'coverage_pct': round(_safe_div(available * 100.0, total), 4) if total else None,
                'core_feature_count': int(core_field_counts.get(omics) or 0),
            }
        all_three = len(ids & all_three_ids)
        row['all_three'] = {
            'available': all_three,
            'coverage_pct': round(_safe_div(all_three * 100.0, total), 4) if total else None,
        }
        coverage_rows.append(row)
    all_domains = {'domain': 'All Domains', 'species_count': species_total}
    for omics in ATLAS_OMICS_KEYS:
        available = len(all_species_ids & ready_counts[omics])
        all_domains[omics] = {
            'available': available,
            'coverage_pct': round(_safe_div(available * 100.0, species_total), 4) if species_total else None,
            'core_feature_count': int(core_field_counts.get(omics) or 0),
        }
    all_domains['all_three'] = {
        'available': len(all_species_ids & all_three_ids),
        'coverage_pct': round(_safe_div(len(all_species_ids & all_three_ids) * 100.0, species_total), 4) if species_total else None,
    }
    availability = {'all_3': 0, 'two_omics': 0, 'one_omics': 0, 'no_omics': 0}
    for species_id in all_species_ids:
        count = sum(1 for omics in ATLAS_OMICS_KEYS if species_id in ready_counts[omics])
        if count == 3:
            availability['all_3'] += 1
        elif count == 2:
            availability['two_omics'] += 1
        elif count == 1:
            availability['one_omics'] += 1
        else:
            availability['no_omics'] += 1
    completeness, top_species = _atlas_completeness_payload(base_qs)
    release = _home_display_release_record() or _active_release_record()
    return {
        'meta': {
            'release_id': release.release_id if release else '',
            'runtime_active_release_id': (_active_release_record().release_id if _active_release_record() else ''),
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'species_total': species_total,
            'scope': 'atlas_context',
            'domain_order': domain_order,
            'data_mode': 'postgresql',
            'notes': [
                'Coverage and availability ignore omics/has_all_omics filters to avoid self-conditioned 100% coverage.',
                'Core completeness reads AnalysisArtifact species_atlas_core_completeness records generated from Core files.',
            ],
        },
        'domain_omics_coverage': {
            'rows': coverage_rows,
            'all_domains': all_domains,
        },
        'genome_size_distribution': _atlas_genome_distribution(base_qs, domain_order),
        'omics_availability': availability,
        'core_feature_completeness': completeness,
        'top_species_completeness': top_species,
    }


def _species_module_coverage(row: Species, ds_map: dict[str, OmicsDataset], *, allow_cross_payload_lookup: bool = True) -> dict[str, Any]:
    """Explain per-species readiness for the modules that can otherwise look blank."""
    species_id = row.species_id
    artifact_counts: dict[str, int] = defaultdict(int)
    for item in (
        AnalysisArtifact.objects
        .filter(species__species_id=species_id)
        .values('omics_type', 'artifact_type')
        .annotate(count=Count('id'))
    ):
        artifact_key = 'cross_omics' if item.get('artifact_type') == 'cross_omics' or item.get('omics_type') in {'all', 'cross_omics'} else item.get('omics_type')
        artifact_counts[artifact_key or 'other'] += int(item.get('count') or 0)
    cross_payload = (row.cross_omics_payload or {}) if allow_cross_payload_lookup else {}
    cross_payload_ready = bool(cross_payload)
    cross_payload_usable = bool(
        isinstance(cross_payload.get('top_transformations'), list) and cross_payload.get('top_transformations')
    )
    cross_suite = cross_payload.get('cross_omics_module_suite') if isinstance(cross_payload.get('cross_omics_module_suite'), dict) else {}
    if not cross_payload_usable and int(cross_suite.get('row_count') or 0) > 0:
        cross_payload_usable = True
    if not cross_payload_usable and int((cross_payload.get('join_summary') or {}).get('matched_all_three') or 0) > 0:
        cross_payload_usable = True
    cross_artifact_count = int(artifact_counts.get('cross_omics', 0))
    entity_index_ready = EntityRecord.objects.filter(species__species_id=species_id).exists()
    annotation = SpeciesFunctionalAnnotationStatus.objects.filter(species_id_text=species_id).first()
    active_phylogeny = PhylogenyRelease.objects.filter(is_active=True).order_by('-created_at', '-id').first()
    phylogeny_tip_ready = bool(
        active_phylogeny and PhylogenyTipMap.objects.filter(
            release=active_phylogeny,
            species_id_text=species_id,
        ).exists()
    )

    modules: list[dict[str, Any]] = []

    def registered_file_ready(path_value: Any, *, min_size: int = 4096) -> bool:
        path_text = str(path_value or '').strip()
        if not path_text:
            return False
        try:
            path = Path(path_text)
            return path.exists() and path.is_file() and path.stat().st_size >= min_size
        except Exception:
            return False

    def core_feature_ready(ds: OmicsDataset | None) -> bool:
        if ds is None:
            return False
        return int(ds.row_count_core or 0) > 0 and registered_file_ready(ds.core_csv_path, min_size=256)

    def add_module(key: str, label: str, state: str, reason: str, **details: Any) -> None:
        modules.append({
            'key': key,
            'label': label,
            'state': state,
            'reason': reason,
            'details': details,
        })

    for omics_key, meta in OMICS_META_DEFAULT.items():
        ds = ds_map.get(omics_key)
        display_name = meta['display_name']
        if ds is None:
            add_module(
                f'{omics_key}.basic', f'{display_name} basic data', 'missing',
                'No dataset is registered for this species and omics type.',
            )
            add_module(
                f'{omics_key}.full', f'{display_name} full scope', 'missing',
                'The basic dataset is absent, so the full-scope view cannot be opened.',
            )
            add_module(
                f'{omics_key}.deep', f'{display_name} deep analysis', 'missing',
                'The basic dataset is absent, so no downstream analysis can be materialized.',
                artifact_count=0,
            )
            continue

        core_rows = int(ds.row_count_core or 0)
        full_rows = int(ds.row_count_full or 0)
        core_file_ready = registered_file_ready(ds.core_csv_path, min_size=256)
        full_file_ready = registered_file_ready(ds.full_csv_path, min_size=4096)
        summary_payload_ready = bool(ds.summary_payload)
        derived_deep_ready = core_rows > 0 and core_file_ready
        if core_rows > 0 and str(ds.status or '').lower() in {'ready', 'complete', 'ok'}:
            add_module(
                f'{omics_key}.basic', f'{display_name} basic data', 'ready',
                'Core feature rows are registered and the dataset is marked ready.',
                dataset_id=ds.dataset_id,
                core_rows=core_rows,
                core_csv_path=ds.core_csv_path,
            )
        elif core_rows > 0:
            add_module(
                f'{omics_key}.basic', f'{display_name} basic data', 'limited',
                'Core rows exist, but the dataset readiness status is not complete.',
                dataset_id=ds.dataset_id,
                core_rows=core_rows,
                dataset_status=ds.status,
                core_csv_path=ds.core_csv_path,
            )
        else:
            add_module(
                f'{omics_key}.basic', f'{display_name} basic data', 'missing',
                'The dataset is registered but has no core rows recorded.',
                dataset_id=ds.dataset_id,
                dataset_status=ds.status,
            )

        if full_rows > 0 or full_file_ready:
            add_module(
                f'{omics_key}.full', f'{display_name} full scope', 'ready',
                'Full-scope source file is available for this dataset; row count may be read from the file when the manifest did not store row_count_full.',
                full_rows=full_rows,
                full_csv_path=ds.full_csv_path,
                file_backed=full_rows <= 0 and full_file_ready,
            )
        elif ds.full_csv_path:
            add_module(
                f'{omics_key}.full', f'{display_name} full scope', 'limited',
                'A full-scope file path is registered, but the file is empty, very small, or unavailable; the full view can be incomplete until the source file is refreshed.',
                full_csv_path=ds.full_csv_path,
                full_rows=0,
            )
        else:
            add_module(
                f'{omics_key}.full', f'{display_name} full scope', 'missing',
                'No full-scope file path or row count is registered for this dataset.',
                full_rows=0,
            )

        artifact_count = int(artifact_counts.get(omics_key, 0))
        if artifact_count > 0:
            add_module(
                f'{omics_key}.deep', f'{display_name} deep analysis', 'ready',
                'At least one registered analysis artifact is available for this species.',
                artifact_count=artifact_count,
            )
        elif derived_deep_ready:
            add_module(
                f'{omics_key}.deep', f'{display_name} deep analysis', 'ready',
                'Deep-analysis charts are generated on demand from the registered core feature table; no separate AnalysisArtifact is required.',
                artifact_count=0,
                data_source='core_csv_on_demand_module_suite',
                core_rows=core_rows,
                summary_payload_ready=summary_payload_ready,
            )
        else:
            add_module(
                f'{omics_key}.deep', f'{display_name} deep analysis', 'missing',
                'The base dataset exists, but no usable core feature rows/file are available for on-demand deep-analysis charts.',
                artifact_count=0,
                core_rows=core_rows,
                core_csv_path=ds.core_csv_path,
            )

    all_three_core_ready = all(core_feature_ready(ds_map.get(key)) for key in ('genome', 'transcriptome', 'proteome'))
    if cross_payload_usable or all_three_core_ready:
        add_module(
            'cross_omics.payload', 'Cross-omics overview',
            'ready',
            'Cross-omics payload has usable matched rows.' if cross_payload_usable else 'Cross-omics X0-X8 charts are generated on demand from the three registered core feature tables.',
            artifact_count=cross_artifact_count,
            data_source='stored_payload' if cross_payload_usable else 'core_csv_gene_join_on_demand',
            all_three_core_ready=all_three_core_ready,
        )
    elif cross_payload_ready:
        add_module(
            'cross_omics.payload', 'Cross-omics overview', 'limited',
            'A cross-omics payload object is registered, but it has no usable matched rows and this species lacks at least one core feature table for on-demand derivation.',
            artifact_count=cross_artifact_count,
            all_three_core_ready=False,
        )
    else:
        add_module(
            'cross_omics.payload', 'Cross-omics overview', 'missing',
            'No cross-omics payload is registered and the species lacks at least one usable genome/transcriptome/proteome core feature table for on-demand derivation.',
            artifact_count=cross_artifact_count,
            all_three_core_ready=False,
        )

    add_module(
        'entity_index', 'Entity explorer index',
        'ready' if entity_index_ready else ('limited' if any(core_feature_ready(ds_map.get(key)) for key in ('genome', 'transcriptome', 'proteome')) else 'missing'),
        'Indexed entity rows are available.' if entity_index_ready else 'EntityRecord index rows are not materialized, but row browsing and row-level panels use the registered core CSV fallback. Indexed full-text entity search remains limited.',
        csv_fallback_ready=any(core_feature_ready(ds_map.get(key)) for key in ('genome', 'transcriptome', 'proteome')),
    )

    if annotation is None:
        add_module(
            'functional_annotations', 'GO / KEGG annotations', 'missing',
            'No functional-annotation status row is registered for this species; the current annotation release is a subset rather than a six-group full release.',
        )
    else:
        go_rows = int(annotation.go_rows or 0)
        kegg_rows = int(annotation.kegg_joined_rows or annotation.kegg_gene_rows or 0)
        annotation_state = 'ready' if go_rows or kegg_rows else 'limited'
        add_module(
            'functional_annotations', 'GO / KEGG annotations', annotation_state,
            'Functional-annotation status is registered for this species.' if annotation_state == 'ready' else 'A status row exists, but no GO/KEGG annotation rows are recorded.',
            go_rows=go_rows,
            kegg_rows=kegg_rows,
        )

    if active_phylogeny is None:
        add_module(
            'phylogeny', 'Phylogeny / PGLS', 'limited',
            'Phylogeny/PGLS is outside the current six-group data optimization scope and is not required for species-detail charts.',
            intentionally_out_of_scope=True,
        )
    elif not phylogeny_tip_ready:
        add_module(
            'phylogeny', 'Phylogeny / PGLS', 'limited',
            f'This species is not mapped to the active {active_phylogeny.scope} phylogeny release; phylogeny/PGLS is intentionally not part of the current six-group optimization.',
            release_id=active_phylogeny.release_id,
            analysis_eligible=active_phylogeny.analysis_eligible,
            intentionally_out_of_scope=True,
        )
    elif active_phylogeny.analysis_eligible:
        add_module(
            'phylogeny', 'Phylogeny / PGLS', 'ready',
            'The species is mapped to an analysis-eligible active phylogeny release.',
            release_id=active_phylogeny.release_id,
        )
    else:
        add_module(
            'phylogeny', 'Phylogeny / PGLS', 'limited',
            'The species is mapped to the active topology, but the release is not analysis-eligible (for example, branch lengths are unavailable).',
            release_id=active_phylogeny.release_id,
            analysis_eligible=False,
        )

    state_counts = {state: sum(1 for item in modules if item['state'] == state) for state in ('ready', 'limited', 'missing')}
    return {
        'summary': {
            'total': len(modules),
            'ready': state_counts['ready'],
            'limited': state_counts['limited'],
            'missing': state_counts['missing'],
        },
        'modules': modules,
        'notes': [
            'A limited state means the module has a source or partial payload but one downstream registration/eligibility signal is incomplete.',
            'A missing state means the module has no usable source for this species, not that the page is still loading.',
        ],
    }


@lru_cache(maxsize=256)
def species_detail(species_id: str, lightweight: bool = False) -> dict[str, Any]:
    if db_mode():
        fields = [
            'id',
            'species_id',
            'display_name',
            'short_name',
            'source_species_id',
            'domain',
            'clade',
            'habitat',
            'source_database',
            'assembly_version',
            'genome_size_mb',
            'has_genome',
            'has_transcriptome',
            'has_proteome',
            'fingerprint',
        ]
        if not lightweight:
            fields.append('cross_omics_payload')
        try:
            row = _species_summary_queryset().only(*fields).get(species_id=species_id)
        except Species.DoesNotExist as exc:
            raise NotFoundError(f'Unknown species_id: {species_id}') from exc
        meta = omics_meta()
        omics_cards = []
        ds_map = {ds.omics_type: ds for ds in row.datasets.all()}
        for omics, ds in ds_map.items():
            summary = ds.summary_payload or {}
            feature_files = [_file_payload(item, check_exists=False) for item in ds.feature_files.all()]
            artifacts = [
                _artifact_payload(item, check_exists=False, include_payload_metadata=False)
                for item in (
                    AnalysisArtifact.objects
                    .select_related('species')
                    .only(
                        'artifact_id',
                        'species__species_id',
                        'species__display_name',
                        'omics_type',
                        'artifact_type',
                        'path',
                        'version',
                        'created_at',
                    )
                    .filter(dataset=ds)
                    .order_by('artifact_type', 'artifact_id')[:12]
                )
            ]
            omics_cards.append({
                'omics': omics,
                'display_name': meta[omics]['display_name'],
                'description': meta[omics]['description'],
                'row_count': ds.row_count_full or ds.row_count_core,
                'row_count_core': ds.row_count_core,
                'row_count_full': ds.row_count_full,
                'kpis': summary.get('kpis', []),
                'analysis_modules': meta[omics]['analysis_modules'],
                'dataset_id': ds.dataset_id,
                'schema_version': ds.schema_version,
                'status': ds.status,
                'core_csv_path': ds.core_csv_path,
                'full_csv_path': ds.full_csv_path,
                'feature_files': feature_files,
                'artifacts': artifacts,
                'full_scope_state': 'ready' if ds.row_count_full else ('not_registered' if ds.full_csv_path else 'missing'),
                'artifact_state': 'ready' if artifacts else 'missing',
                'downloads_route': _download_page_route(row.species_id, omics),
                'source_page_route': _download_page_route(row.species_id, omics),
            })
        cross = {} if lightweight else (row.cross_omics_payload or {})
        return {
            **_species_to_summary(row, include_model_priority=False),
            'omics_cards': omics_cards,
            'cross_omics_preview': (cross.get('top_transformations') or [])[:8],
            'cross_omics_deferred': bool(lightweight),
            'downloads_route': _download_page_route(row.species_id),
            'release': current_release(),
            'module_coverage': _species_module_coverage(row, ds_map, allow_cross_payload_lookup=not lightweight),
            'enhanced_visuals': {} if lightweight else species_enhanced_visuals(row.species_id),
            'enhanced_visuals_deferred': bool(lightweight),
        }

    row = file_species_map().get(species_id)
    if not row:
        raise NotFoundError(f'Unknown species_id: {species_id}')
    meta = omics_meta()
    omics_cards = []
    for omics, payload in row['omics'].items():
        omics_cards.append({
            'omics': omics,
            'display_name': meta[omics]['display_name'],
            'description': meta[omics]['description'],
            'row_count': payload['row_count'],
            'kpis': payload['kpis'],
            'analysis_modules': meta[omics]['analysis_modules'],
            'feature_files': [],
            'artifacts': [],
            'full_scope_state': 'ready',
            'artifact_state': 'missing',
            'downloads_route': _download_page_route(row['species_id'], omics),
            'source_page_route': _download_page_route(row['species_id'], omics),
        })
    return {
        **row,
        'source_context': _species_context_label(row),
        'external_source_url': _external_source_url(row),
        'omics_cards': omics_cards,
        'cross_omics_preview': [] if lightweight else get_cross_omics(species_id)['top_transformations'][:8],
        'cross_omics_deferred': bool(lightweight),
        'downloads_route': _download_page_route(row['species_id']),
        'release': current_release(),
        'module_coverage': {
            'summary': {'total': len(omics_cards), 'ready': len(omics_cards), 'limited': 0, 'missing': 0},
            'modules': [],
            'notes': ['File-backed fallback mode does not expose PostgreSQL registry-level module coverage.'],
        },
        'enhanced_visuals': {} if lightweight else species_enhanced_visuals(row['species_id']),
        'enhanced_visuals_deferred': bool(lightweight),
    }


def _legacy_get_summary(species_id: str, omics: str) -> dict[str, Any]:
    validate_omics(omics)
    if db_mode():
        try:
            ds = OmicsDataset.objects.select_related('species').get(species__species_id=species_id, omics_type=omics)
        except OmicsDataset.DoesNotExist as exc:
            raise NotFoundError(f'Unknown dataset: {species_id}/{omics}') from exc
        return ds.summary_payload or {}
    return load_json(f'{species_id}/{omics}/summary.json')


def _legacy_get_analysis(species_id: str, omics: str) -> dict[str, Any]:
    validate_omics(omics)
    if db_mode():
        try:
            ds = OmicsDataset.objects.select_related('species').get(species__species_id=species_id, omics_type=omics)
        except OmicsDataset.DoesNotExist as exc:
            raise NotFoundError(f'Unknown dataset: {species_id}/{omics}') from exc
        return ds.analysis_payload or {}
    return load_json(f'{species_id}/{omics}/analysis.json')


def _pareto_front_ranks(points: list[dict[str, Any]]) -> dict[int, int]:
    def dominates(a_idx: int, b_idx: int) -> bool:
        a = points[a_idx]
        b = points[b_idx]
        a_cost = _safe_num(a.get('cost_axis'))
        a_adapt = _safe_num(a.get('adapt_axis'))
        b_cost = _safe_num(b.get('cost_axis'))
        b_adapt = _safe_num(b.get('adapt_axis'))
        if None in {a_cost, a_adapt, b_cost, b_adapt}:
            return False
        return (a_cost <= b_cost and a_adapt >= b_adapt) and (a_cost < b_cost or a_adapt > b_adapt)

    remaining = set(range(len(points)))
    ranks: dict[int, int] = {}
    rank = 1
    while remaining:
        front: list[int] = []
        for idx in remaining:
            if not any(dominates(other, idx) for other in remaining if other != idx):
                front.append(idx)
        if not front:
            break
        for idx in front:
            ranks[idx] = rank
        remaining -= set(front)
        rank += 1
    return ranks


def _enhance_analysis_payload(payload: Any, omics: str) -> dict[str, Any]:
    data = dict(payload or {}) if isinstance(payload, dict) else {}
    data.setdefault('evidence_level', 'exploratory')
    data.setdefault('result_type', 'hypothesis_generating')
    data.setdefault('display_labels', {
        'outliers': 'Candidate outliers',
        'tradeoff_front': 'Trade-off landscape',
        'coupling_edges': 'Feature coupling network',
        'strategy_breakdown': 'Exploratory strategy groups',
    })
    if omics == 'genome':
        data['display_labels'].setdefault('stoich_islands', 'Stoichiometric island candidates')
    elif omics == 'transcriptome':
        data['display_labels'].setdefault('motif_themes', 'Compositional themes')
    elif omics == 'proteome':
        data['display_labels'].setdefault('resource_budget', 'Sequence-intrinsic resource profile')

    method_metadata = data.get('method_metadata')
    if not isinstance(method_metadata, dict):
        method_metadata = {}
    method_metadata.setdefault('outliers', {
        'method': 'score_quantile_extremes',
        'scale': 'project_strategy_score',
        'evidence_level': 'exploratory',
        'missing_policy': 'pairwise_complete',
    })
    method_metadata.setdefault('tradeoff_front', {
        'method': 'non_dominated_sorting',
        'axes': {'cost_axis': 'minimize', 'adapt_axis': 'maximize'},
        'formula': {
            'cost_axis': 'payload cost_axis field, usually sequence-intrinsic resource burden proxy',
            'adapt_axis': 'payload adapt_axis field, usually adaptive or physicochemical benefit proxy',
            'front_score': 'non-dominated sorting rank; lower front_rank indicates stronger Pareto candidate',
        },
        'evidence_level': 'exploratory',
    })
    method_metadata.setdefault('coupling_network', {
        'method': 'spearman_association',
        'multiple_testing': 'benjamini_hochberg_fdr',
        'evidence_level': 'exploratory',
    })
    data['method_metadata'] = method_metadata

    outliers = data.get('outliers')
    if isinstance(outliers, dict):
        for side in ['high', 'low']:
            rows = outliers.get(side)
            if not isinstance(rows, list):
                continue
            for idx, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    continue
                row.setdefault('outlier_rank', idx)
                row.setdefault('outlier_label', 'candidate')

    tradeoff = data.get('tradeoff_front')
    if isinstance(tradeoff, list) and tradeoff:
        ranks = _pareto_front_ranks([row if isinstance(row, dict) else {} for row in tradeoff])
        for idx, row in enumerate(tradeoff):
            if not isinstance(row, dict):
                continue
            row.setdefault('front_rank', ranks.get(idx, 0))

    if omics == 'transcriptome' and 'composition_themes' not in data and isinstance(data.get('motif_themes'), list):
        data['composition_themes'] = data.get('motif_themes')
    if omics == 'proteome' and 'sequence_intrinsic_resource_profile' not in data and isinstance(data.get('resource_budget'), list):
        data['sequence_intrinsic_resource_profile'] = data.get('resource_budget')
    return _attach_known_chart_metadata(data)


def _analysis_rows_for_scope(species_id: str, omics: str, scope: str) -> list[dict[str, Any]]:
    if db_mode():
        if _normalize_scope(scope) == 'full':
            return _csv_rows_for_db_scope(species_id, omics, 'full')
        rows: list[dict[str, Any]] = []
        for record in (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type=omics)
            .only('entity_id', 'canonical_gene_id', 'gene_name', 'strategy_cluster', 'payload_json')
        ):
            payload = dict(record.payload_json or {})
            payload.setdefault('entity_id', record.entity_id)
            if record.canonical_gene_id:
                payload.setdefault('gene_id', record.canonical_gene_id)
            if record.gene_name:
                payload.setdefault('gene_name', record.gene_name)
            if record.strategy_cluster:
                payload.setdefault('strategy_cluster', record.strategy_cluster)
            rows.append(payload)
        return rows if rows else _csv_rows_for_db_scope(species_id, omics, 'core')
    try:
        rows = _file_rows_for_scope(species_id, omics, scope)
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def _robust_outliers_from_rows(rows: list[dict[str, Any]], omics: str) -> dict[str, Any] | None:
    if not rows:
        return None
    meta = omics_meta().get(omics, {})
    preferred_cols = {
        'genome': ['strategy_score', 'gc_delta_promoter_minus_exon', 'exon_atoms_N_per_base', 'promoter_gc_percent', 'exon_gc_percent', 'stoich_island_score'],
        'transcriptome': ['strategy_score', 'rna_orf_coupling_score', 'nt_entropy', 'atoms_per_nt_N', 'gc_percent_display', 'gc_content'],
        'proteome': ['strategy_score', 'resource_budget_score', 'N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy'],
    }

    def _is_valid_feature(col: str) -> bool:
        lower = str(col or '').strip().lower()
        if not lower:
            return False
        blocked_tokens = ['_id', 'start', 'end', 'seq', 'chrom', 'contig', 'strand', 'position']
        return not any(token in lower for token in blocked_tokens)

    candidate_cols: list[str] = []
    for key in preferred_cols.get(omics, ['strategy_score']):
        if key not in candidate_cols:
            candidate_cols.append(key)
    for key in (meta.get('feature_options') or []):
        if not _is_valid_feature(str(key)):
            continue
        if key not in candidate_cols:
            candidate_cols.append(str(key))

    score_col = ''
    values: list[float] = []
    for col in candidate_cols:
        clean = [_safe_num(row.get(col)) for row in rows]
        numeric = [float(item) for item in clean if item is not None]
        if len(numeric) >= 8:
            score_col = col
            values = numeric
            break
    if not score_col or not values:
        return None

    ordered = sorted(values)
    median = float(_percentile(ordered, 0.5))
    abs_dev = sorted(abs(value - median) for value in values)
    mad = float(_percentile(abs_dev, 0.5))
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / max(len(values), 1)
    std = math.sqrt(max(variance, 0.0))
    scale = (1.4826 * mad) if mad > 0 else (std if std > 0 else 1.0)

    scored = []
    for row in rows:
        value = _safe_num(row.get(score_col))
        if value is None:
            continue
        robust_z = (float(value) - median) / (scale or 1.0)
        item = {}
        for key in ['entity_id', 'gene_id', 'ensembl_gene_id', 'transcript_id', 'protein_id', 'gene_name', 'gene_symbol', 'strategy_cluster']:
            if key in row:
                item[key] = row.get(key)
        item[score_col] = round(float(value), 6)
        item['robust_z'] = round(float(robust_z), 6)
        item['outlier_score'] = round(abs(float(robust_z)), 6)
        scored.append(item)
    if len(scored) < 8:
        return None

    high = [item for item in scored if float(item.get('robust_z', 0.0)) >= 2.5]
    low = [item for item in scored if float(item.get('robust_z', 0.0)) <= -2.5]
    if not high and not low:
        sorted_scored = sorted(scored, key=lambda item: float(item.get('robust_z', 0.0)))
        low = sorted_scored[:12]
        high = list(reversed(sorted_scored[-12:]))
    else:
        high.sort(key=lambda item: float(item.get('robust_z', 0.0)), reverse=True)
        low.sort(key=lambda item: float(item.get('robust_z', 0.0)))

    for idx, row in enumerate(high, start=1):
        row['outlier_rank'] = idx
        row['outlier_label'] = 'candidate'
    for idx, row in enumerate(low, start=1):
        row['outlier_rank'] = idx
        row['outlier_label'] = 'candidate'

    return {
        'score_col': score_col,
        'n_entities': len(scored),
        'center': round(median, 6),
        'scale': round(scale, 6),
        'high': high[:24],
        'low': low[:24],
    }


def _apply_robust_outliers(species_id: str, omics: str, scope: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    # Model-organism payloads are already computed from the registered real
    # feature rows.  Re-scanning a remote full CSV on every API request was
    # the main reason Results & Analysis Hub cards appeared blank or timed
    # out.  Keep the stored robust result and only use the legacy scan for
    # releases that do not carry this marker.
    if data.get('precomputed_from_real_rows'):
        return data
    robust = _robust_outliers_from_rows(_analysis_rows_for_scope(species_id, omics, scope), omics)
    if not robust:
        return data
    outliers = data.get('outliers') if isinstance(data.get('outliers'), dict) else {}
    outliers['high'] = robust['high']
    outliers['low'] = robust['low']
    outliers.setdefault('multivariate', [])
    outliers.setdefault('feature_contributions', {})
    data['outliers'] = outliers

    method_metadata = data.get('method_metadata') if isinstance(data.get('method_metadata'), dict) else {}
    method_metadata['outliers'] = {
        'method': 'robust_zscore_mad',
        'score_col': robust['score_col'],
        'thresholds': {'high': 2.5, 'low': -2.5},
        'center': 'median',
        'scale': '1.4826_mad_fallback_std',
        'n_entities': robust['n_entities'],
        'evidence_level': 'exploratory',
    }
    data['method_metadata'] = method_metadata
    return data


def _outlier_gene_id_set(species_id: str, omics: str) -> set[str]:
    try:
        analysis = get_analysis(species_id, omics, scope='core')
    except Exception:
        return set()
    outliers = analysis.get('outliers') if isinstance(analysis, dict) else {}
    if not isinstance(outliers, dict):
        return set()
    candidate_rows: list[dict[str, Any]] = []
    for side in ['high', 'low']:
        rows = outliers.get(side)
        if isinstance(rows, list):
            candidate_rows.extend([row for row in rows if isinstance(row, dict)])
    if not candidate_rows:
        return set()

    direct = {
        str(row.get('gene_id') or row.get('ensembl_gene_id') or '').strip()
        for row in candidate_rows
        if str(row.get('gene_id') or row.get('ensembl_gene_id') or '').strip()
    }
    if direct:
        return direct

    entity_ids = {
        str(
            row.get('entity_id')
            or row.get('transcript_id')
            or row.get('protein_id')
            or row.get(omics_meta().get(omics, {}).get('primary_id', ''))
            or ''
        ).strip()
        for row in candidate_rows
    }
    entity_ids = {item for item in entity_ids if item}
    if not entity_ids:
        return set()

    if db_mode():
        mapped = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type=omics, entity_id__in=list(entity_ids))
            .exclude(canonical_gene_id='')
            .values_list('canonical_gene_id', flat=True)
        )
        return {str(item).strip() for item in mapped if str(item).strip()}

    try:
        rows = _file_rows_for_scope(species_id, omics, 'core')
    except Exception:
        return set()
    mapped = set()
    primary = omics_meta().get(omics, {}).get('primary_id', '')
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = str(row.get('entity_id') or row.get(primary) or '').strip()
        if entity not in entity_ids:
            continue
        gene = str(row.get('gene_id') or row.get('ensembl_gene_id') or '').strip()
        if gene:
            mapped.add(gene)
    return mapped


def _cross_join_summary(species_id: str) -> dict[str, Any]:
    if db_mode():
        genome_rows = EntityRecord.objects.filter(species__species_id=species_id, omics_type='genome').count()
        transcript_rows = EntityRecord.objects.filter(species__species_id=species_id, omics_type='transcriptome').count()
        proteome_rows = EntityRecord.objects.filter(species__species_id=species_id, omics_type='proteome').count()
        genome_set = set(
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type='genome')
            .exclude(canonical_gene_id='')
            .values_list('canonical_gene_id', flat=True)
        )
        transcript_set = set(
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type='transcriptome')
            .exclude(canonical_gene_id='')
            .values_list('canonical_gene_id', flat=True)
        )
        proteome_set = set(
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type='proteome')
            .exclude(canonical_gene_id='')
            .values_list('canonical_gene_id', flat=True)
        )
    else:
        genome_rows_data = _file_rows_for_scope(species_id, 'genome', 'core')
        transcript_rows_data = _file_rows_for_scope(species_id, 'transcriptome', 'core')
        proteome_rows_data = _file_rows_for_scope(species_id, 'proteome', 'core')
        genome_rows = len(genome_rows_data)
        transcript_rows = len(transcript_rows_data)
        proteome_rows = len(proteome_rows_data)
        genome_set = {str(row.get('gene_id') or '').strip() for row in genome_rows_data if str(row.get('gene_id') or '').strip()}
        transcript_set = {str(row.get('gene_id') or '').strip() for row in transcript_rows_data if str(row.get('gene_id') or '').strip()}
        proteome_set = {
            str(row.get('ensembl_gene_id') or row.get('gene_id') or '').strip()
            for row in proteome_rows_data
            if str(row.get('ensembl_gene_id') or row.get('gene_id') or '').strip()
        }

    matched_gt = len(genome_set & transcript_set)
    matched_tp = len(transcript_set & proteome_set)
    matched_all = len(genome_set & transcript_set & proteome_set)
    base = max(1, min(len(genome_set) or 0, len(transcript_set) or 0, len(proteome_set) or 0))
    return {
        'genome_rows': int(genome_rows),
        'transcriptome_rows': int(transcript_rows),
        'proteome_rows': int(proteome_rows),
        'matched_genome_transcriptome': int(matched_gt),
        'matched_transcriptome_proteome': int(matched_tp),
        'matched_all_three': int(matched_all),
        'match_rate_genome_transcriptome': round(_safe_div(matched_gt, max(1, min(len(genome_set), len(transcript_set)))), 6) if genome_set and transcript_set else 0.0,
        'match_rate_transcriptome_proteome': round(_safe_div(matched_tp, max(1, min(len(transcript_set), len(proteome_set)))), 6) if transcript_set and proteome_set else 0.0,
        'match_rate_all_three': round(_safe_div(matched_all, base), 6),
    }


def _build_transformations_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dna_to_rna = _safe_num(row.get('dna_to_rna_n_shift_std'))
        rna_to_protein = _safe_num(row.get('rna_to_protein_n_shift_std'))
        if dna_to_rna is None and rna_to_protein is None:
            continue
        delta_sum = abs(dna_to_rna or 0.0) + abs(rna_to_protein or 0.0)
        discordance = delta_sum + abs((dna_to_rna or 0.0) - (rna_to_protein or 0.0))
        driver = 'balanced'
        if abs(dna_to_rna or 0.0) > abs(rna_to_protein or 0.0):
            driver = 'DNA_to_RNA_shift'
        elif abs(rna_to_protein or 0.0) > abs(dna_to_rna or 0.0):
            driver = 'RNA_to_protein_shift'
        output.append({
            'entity_id': row.get('entity_id') or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id'),
            'gene_id': row.get('gene_id'),
            'gene_name': row.get('gene_name') or row.get('gene_symbol'),
            'dna_to_rna_n_delta': round(float(dna_to_rna or 0.0), 6),
            'rna_to_protein_n_delta': round(float(rna_to_protein or 0.0), 6),
            'dna_to_rna_n_shift_std': row.get('dna_to_rna_n_shift_std'),
            'rna_to_protein_n_shift_std': row.get('rna_to_protein_n_shift_std'),
            'dna_to_rna_n_shift_legacy_proxy': row.get('dna_to_rna_n_shift_legacy_proxy') or row.get('dna_to_rna_n_shift'),
            'rna_to_protein_n_shift_legacy_proxy': row.get('rna_to_protein_n_shift_legacy_proxy') or row.get('rna_to_protein_n_shift'),
            'resource_shift_method_version': row.get('resource_shift_method_version'),
            'discordance_score': round(float(discordance), 6),
            'main_driver': driver,
        })
    output.sort(key=lambda item: item.get('discordance_score', 0.0), reverse=True)
    return output


def _build_shared_outliers(species_id: str) -> dict[str, Any]:
    genome = _outlier_gene_id_set(species_id, 'genome')
    transcriptome = _outlier_gene_id_set(species_id, 'transcriptome')
    proteome = _outlier_gene_id_set(species_id, 'proteome')
    all_shared = sorted(genome & transcriptome & proteome)
    return {
        'genome_only': sorted(genome - transcriptome - proteome)[:200],
        'transcriptome_only': sorted(transcriptome - genome - proteome)[:200],
        'proteome_only': sorted(proteome - genome - transcriptome)[:200],
        'shared_all_three': all_shared[:200],
        'counts': {
            'genome_only': len(genome - transcriptome - proteome),
            'transcriptome_only': len(transcriptome - genome - proteome),
            'proteome_only': len(proteome - genome - transcriptome),
            'shared_all_three': len(all_shared),
        },
    }


def _cross_module_status(required: list[str], available: set[str]) -> str:
    present = 0
    for field in required:
        if field in available:
            present += 1
    if required and present == len(required):
        return 'implemented'
    if present:
        return 'partial'
    return 'not_available'


def _shift_direction_class(dna_to_rna: float | None, rna_to_protein: float | None) -> str:
    if dna_to_rna is None or rna_to_protein is None:
        return 'incomplete'
    if dna_to_rna >= 0 and rna_to_protein >= 0:
        return 'conserved-high resource shift'
    if dna_to_rna < 0 and rna_to_protein < 0:
        return 'conserved-low resource shift'
    if dna_to_rna >= 0 and rna_to_protein < 0:
        return 'RNA-buffered / protein-lean'
    return 'protein-amplified discordance'


def _feature_omics_hint(feature: str) -> str:
    name = str(feature or '').lower()
    if any(token in name for token in ('genome', 'exon', 'promoter', 'codon', 'gc3', 'dna')):
        return 'genome'
    if any(token in name for token in ('transcript', 'rna', 'nt_', 'nmp')):
        return 'transcriptome'
    if any(token in name for token in ('protein', 'proteome', 'aa', 'pi', 'gravy', 'instability')):
        return 'proteome'
    return 'cross_omics'


def _cross_rows_from_transformations(data: dict[str, Any]) -> list[dict[str, Any]]:
    source = data.get('top_transformations') if isinstance(data.get('top_transformations'), list) else []
    if not source:
        source = data.get('transformations') if isinstance(data.get('transformations'), list) else []
    rows = []
    for item in source:
        if not isinstance(item, dict):
            continue
        dna = _safe_num(item.get('dna_to_rna_n_shift_std'))
        protein = _safe_num(item.get('rna_to_protein_n_shift_std'))
        legacy_dna = _safe_num(item.get('dna_to_rna_n_delta') if item.get('dna_to_rna_n_delta') is not None else item.get('dna_to_rna_n_shift'))
        legacy_protein = _safe_num(item.get('rna_to_protein_n_delta') if item.get('rna_to_protein_n_delta') is not None else item.get('rna_to_protein_n_shift'))
        row = dict(item)
        if legacy_dna is not None:
            row['dna_to_rna_n_shift_legacy_proxy'] = round(float(legacy_dna), 6)
        if legacy_protein is not None:
            row['rna_to_protein_n_shift_legacy_proxy'] = round(float(legacy_protein), 6)
        if dna is not None:
            row['dna_to_rna_n_shift_std'] = round(float(dna), 6)
        if protein is not None:
            row['rna_to_protein_n_shift_std'] = round(float(protein), 6)
        row.setdefault('data_scope', 'top_transformations')
        row.setdefault('source_modules', ['legacy_top_transformations'])
        row.setdefault('direction_class', _shift_direction_class(dna, protein))
        if row.get('discordance_score') is None:
            row['discordance_score'] = round(abs(dna or 0.0) + abs(protein or 0.0) + abs((dna or 0.0) - (protein or 0.0)), 6)
        row.setdefault('candidate_score', row.get('discordance_score'))
        row.setdefault('canonical_gene_id', row.get('gene_id') or row.get('entity_id'))
        rows.append(row)
    return sorted(rows, key=lambda item: float(item.get('candidate_score') or item.get('discordance_score') or 0), reverse=True)


def _cross_quadrant_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = {
        'RNA up / protein up': 0,
        'RNA up / protein down': 0,
        'RNA down / protein up': 0,
        'RNA down / protein down': 0,
    }
    for row in rows:
        dna = _safe_num(row.get('dna_to_rna_n_shift_std'))
        protein = _safe_num(row.get('rna_to_protein_n_shift_std'))
        if dna is None or protein is None:
            continue
        if dna >= 0 and protein >= 0:
            counts['RNA up / protein up'] += 1
        elif dna >= 0 and protein < 0:
            counts['RNA up / protein down'] += 1
        elif dna < 0 and protein >= 0:
            counts['RNA down / protein up'] += 1
        else:
            counts['RNA down / protein down'] += 1
    return [{'name': key, 'value': value} for key, value in counts.items()]


def _cross_scatter(rows: list[dict[str, Any]], x_field: str, y_field: str, limit: int = 1200) -> list[dict[str, Any]]:
    points = []
    for row in rows:
        x = _safe_num(row.get(x_field))
        y = _safe_num(row.get(y_field))
        if x is None or y is None:
            continue
        points.append({
            'entity_id': row.get('canonical_gene_id') or row.get('gene_id') or row.get('entity_id'),
            'gene_id': row.get('gene_id') or row.get('canonical_gene_id'),
            'gene_name': row.get('gene_name') or '',
            x_field: round(float(x), 6),
            y_field: round(float(y), 6),
            'direction_class': row.get('direction_class') or '',
        })
    if len(points) > limit:
        stride = max(1, len(points) // limit)
        points = points[::stride][:limit]
    return points


def _cross_core_gene_key(row: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = str(row.get(field) or '').strip()
        if value:
            return value
    return ''


def _cross_feature_path(species_id: str, omics: str) -> Path | None:
    if not db_mode():
        return None
    try:
        dataset = (
            OmicsDataset.objects
            .filter(species__species_id=species_id, omics_type=omics)
            .only('core_csv_path', 'full_csv_path')
            .first()
        )
    except Exception:
        return None
    if not dataset:
        return None
    for raw_path in (dataset.core_csv_path, dataset.full_csv_path):
        path_text = str(raw_path or '').strip()
        if not path_text:
            continue
        path = Path(path_text)
        if path.exists() and path.is_file():
            return path
    return None


def _cross_read_gene_index(
    path: Path | None,
    gene_fields: tuple[str, ...],
    keep_fields: tuple[str, ...],
    *,
    max_rows: int = 150_000,
) -> tuple[dict[str, dict[str, Any]], int, set[str]]:
    if path is None:
        return {}, 0, set()
    index: dict[str, dict[str, Any]] = {}
    seen_fields: set[str] = set()
    read_rows = 0
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            seen_fields = set(reader.fieldnames or [])
            for row in reader:
                read_rows += 1
                gene = _cross_core_gene_key(row, *gene_fields)
                if gene and gene not in index:
                    selected = {field: row.get(field) for field in keep_fields if field in row}
                    selected['gene_id'] = gene
                    index[gene] = selected
                if read_rows >= max_rows:
                    break
    except Exception:
        return {}, read_rows, seen_fields
    return index, read_rows, seen_fields


def _cross_first_num(row: dict[str, Any], *fields: str) -> float | None:
    for field in fields:
        value = _safe_num(row.get(field))
        if value is not None:
            return float(value)
    return None


def _cross_text(row: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = str(row.get(field) or '').strip()
        if value:
            return value
    return ''


def _cross_gc_percent(value: float | None) -> float | None:
    if value is None:
        return None
    if -1.0 <= value <= 1.0:
        return round(float(value) * 100.0, 6)
    return round(float(value), 6)


def _cross_row_correlation_matrix(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, dict[str, float]]:
    matrix: dict[str, dict[str, float]] = {field: {} for field in fields}
    for field_a in fields:
        for field_b in fields:
            if field_a == field_b:
                matrix[field_a][field_b] = 1.0
                continue
            xs: list[float] = []
            ys: list[float] = []
            for row in rows:
                x = _safe_num(row.get(field_a))
                y = _safe_num(row.get(field_b))
                if x is None or y is None:
                    continue
                xs.append(float(x))
                ys.append(float(y))
            value = _pearson_from_values(xs, ys) if len(xs) >= 3 else None
            matrix[field_a][field_b] = round(float(value), 6) if value is not None else 0.0
    return matrix


@lru_cache(maxsize=256)
def _derive_cross_payload_from_core_features(species_id: str) -> dict[str, Any]:
    """Build chart-ready cross-omics rows on demand from imported core feature CSV files.

    This is intentionally bounded and read-only.  It avoids materialising EntityRecord
    for 18k species while still allowing species-detail modules to render from the
    real feature tables already registered in OmicsDataset.
    """
    genome_path = _cross_feature_path(species_id, 'genome')
    transcript_path = _cross_feature_path(species_id, 'transcriptome')
    proteome_path = _cross_feature_path(species_id, 'proteome')
    genome_keep = (
        'gene_id', 'source_gene_id', 'gene_name', 'locus_tag', 'biotype', 'seqid',
        'exon_gc_percent', 'cds_gc_percent', 'locus_gc_percent', 'promoter_gc_percent',
        'exon_atoms_N_per_base', 'promoter_atoms_N_per_base', 'gc3_percent',
        'codon_entropy_bits', 'aa_entropy_bits', 'exon_length_bp', 'cds_length_bp',
    )
    transcript_keep = (
        'gene_id', 'transcript_id', 'gene_symbol', 'gc_content', 'atoms_per_nt_N',
        'C_N_ratio', 'length_nt_acgu', 'orf_len_nt', 'orf_len_aa',
        'protein_isoelectric_point', 'protein_gravy', 'protein_instability_index',
        'aa_len', 'nt_entropy',
    )
    proteome_keep = (
        'gene_id', 'ensembl_gene_id', 'protein_id', 'transcript_id', 'gene_symbol',
        'description', 'length_aa', 'N_atoms_per_aa', 'S_atoms_per_aa', 'pI',
        'gravy', 'instability_index', 'avg_oxidation_state_C', 'sulfur_aa_frac',
        'aa_entropy_bits', 'net_charge_pH7',
    )
    genome, genome_rows, _ = _cross_read_gene_index(genome_path, ('gene_id', 'ensembl_gene_id'), genome_keep)
    transcriptome, transcript_rows, _ = _cross_read_gene_index(transcript_path, ('gene_id', 'ensembl_gene_id'), transcript_keep)
    proteome, proteome_rows, _ = _cross_read_gene_index(proteome_path, ('ensembl_gene_id', 'gene_id'), proteome_keep)
    common = sorted(set(genome) & set(transcriptome) & set(proteome))
    if not common:
        return {}

    rows: list[dict[str, Any]] = []
    max_join_rows = 80_000
    for gene in common[:max_join_rows]:
        g_row = genome[gene]
        t_row = transcriptome[gene]
        p_row = proteome[gene]
        exon_gc = _cross_gc_percent(_cross_first_num(g_row, 'exon_gc_percent', 'cds_gc_percent', 'locus_gc_percent'))
        transcript_gc = _cross_gc_percent(_cross_first_num(t_row, 'gc_content'))
        promoter_gc = _cross_gc_percent(_cross_first_num(g_row, 'promoter_gc_percent'))
        genome_n = _cross_first_num(g_row, 'exon_atoms_N_per_base')
        transcript_n = _cross_first_num(t_row, 'atoms_per_nt_N')
        proteome_n = _cross_first_num(p_row, 'N_atoms_per_aa')
        proteome_s = _cross_first_num(p_row, 'S_atoms_per_aa')
        dna_to_rna = (transcript_n - genome_n) if transcript_n is not None and genome_n is not None else None
        rna_to_protein = (proteome_n - transcript_n) if proteome_n is not None and transcript_n is not None else None
        dna_to_rna_gc = (transcript_gc - exon_gc) if transcript_gc is not None and exon_gc is not None else None
        promoter_delta = (promoter_gc - exon_gc) if promoter_gc is not None and exon_gc is not None else None
        predicted_pi = _cross_first_num(t_row, 'protein_isoelectric_point')
        observed_pi = _cross_first_num(p_row, 'pI')
        predicted_gravy = _cross_first_num(t_row, 'protein_gravy')
        observed_gravy = _cross_first_num(p_row, 'gravy')
        predicted_instability = _cross_first_num(t_row, 'protein_instability_index')
        observed_instability = _cross_first_num(p_row, 'instability_index')
        pi_residual = (observed_pi - predicted_pi) if observed_pi is not None and predicted_pi is not None else None
        gravy_residual = (observed_gravy - predicted_gravy) if observed_gravy is not None and predicted_gravy is not None else None
        instability_residual = (
            observed_instability - predicted_instability
            if observed_instability is not None and predicted_instability is not None else None
        )
        resource_shift_score = abs(dna_to_rna or 0.0) + abs(rna_to_protein or 0.0)
        residual_score = abs(pi_residual or 0.0) + abs(gravy_residual or 0.0) + abs((instability_residual or 0.0) / 40.0)
        gc_score = abs((dna_to_rna_gc or 0.0) / 10.0)
        discordance = resource_shift_score + residual_score + gc_score
        driver = 'balanced'
        driver_values = {
            'DNA_to_RNA_shift': abs(dna_to_rna or 0.0),
            'RNA_to_protein_shift': abs(rna_to_protein or 0.0),
            'predicted_observed_residual': residual_score,
            'GC_shift': gc_score,
        }
        if driver_values:
            driver = max(driver_values.items(), key=lambda item: item[1])[0]
        row = {
            'entity_id': gene,
            'canonical_gene_id': gene,
            'gene_id': gene,
            'gene_name': _cross_text(g_row, 'gene_name', 'locus_tag') or _cross_text(t_row, 'gene_symbol') or _cross_text(p_row, 'gene_symbol'),
            'transcript_id': _cross_text(t_row, 'transcript_id') or _cross_text(p_row, 'transcript_id'),
            'protein_id': _cross_text(p_row, 'protein_id'),
            'exon_gc_percent': exon_gc,
            'promoter_gc_percent': promoter_gc,
            'transcript_gc': transcript_gc,
            'dna_to_rna_gc_delta': round(float(dna_to_rna_gc), 6) if dna_to_rna_gc is not None else None,
            'exon_rna_gc_delta': round(float(dna_to_rna_gc), 6) if dna_to_rna_gc is not None else None,
            'promoter_exon_gc_delta': round(float(promoter_delta), 6) if promoter_delta is not None else None,
            'genome_n_per_base': round(float(genome_n), 6) if genome_n is not None else None,
            'transcript_n_per_nt': round(float(transcript_n), 6) if transcript_n is not None else None,
            'proteome_n_per_aa': round(float(proteome_n), 6) if proteome_n is not None else None,
            'proteome_s_per_aa': round(float(proteome_s), 6) if proteome_s is not None else None,
            'N_atoms_per_aa': round(float(proteome_n), 6) if proteome_n is not None else None,
            'S_atoms_per_aa': round(float(proteome_s), 6) if proteome_s is not None else None,
            'dna_to_rna_n_shift': round(float(dna_to_rna), 6) if dna_to_rna is not None else None,
            'rna_to_protein_n_shift': round(float(rna_to_protein), 6) if rna_to_protein is not None else None,
            'dna_to_rna_n_delta': round(float(dna_to_rna), 6) if dna_to_rna is not None else None,
            'rna_to_protein_n_delta': round(float(rna_to_protein), 6) if rna_to_protein is not None else None,
            'pI': round(float(observed_pi), 6) if observed_pi is not None else None,
            'gravy': round(float(observed_gravy), 6) if observed_gravy is not None else None,
            'instability_index': round(float(observed_instability), 6) if observed_instability is not None else None,
            'transcript_protein_pi': round(float(predicted_pi), 6) if predicted_pi is not None else None,
            'transcript_protein_gravy': round(float(predicted_gravy), 6) if predicted_gravy is not None else None,
            'transcript_protein_instability_index': round(float(predicted_instability), 6) if predicted_instability is not None else None,
            'protein_pi_residual': round(float(pi_residual), 6) if pi_residual is not None else None,
            'protein_gravy_residual': round(float(gravy_residual), 6) if gravy_residual is not None else None,
            'protein_instability_residual': round(float(instability_residual), 6) if instability_residual is not None else None,
            'discordance_score': round(float(discordance), 6),
            'candidate_score': round(float(discordance), 6),
            'resource_shift_score': round(float(resource_shift_score), 6),
            'main_driver': driver,
            'direction_class': _shift_direction_class(dna_to_rna, rna_to_protein),
            'data_scope': 'on_demand_core_csv_gene_join',
            'source_modules': ['X1', 'X2', 'X3', 'X4', 'X8'],
            'evidence_level': 'sequence-derived descriptive',
        }
        if dna_to_rna is not None or rna_to_protein is not None or transcript_gc is not None or proteome_n is not None:
            rows.append(row)
    if not rows:
        return {}
    resource_shift_reference = _attach_standardized_resource_shifts(rows)
    for row in rows:
        raw_resource_shift_score = row.get('resource_shift_score')
        std_score = _safe_num(row.get('resource_shift_score_std'))
        if std_score is not None:
            row['resource_shift_score_raw_legacy_proxy'] = raw_resource_shift_score
            row['resource_shift_score'] = round(float(std_score), 6)
            residual_score = abs(float(row.get('protein_pi_residual') or 0.0)) + abs(float(row.get('protein_gravy_residual') or 0.0)) + abs(float(row.get('protein_instability_residual') or 0.0) / 40.0)
            gc_score = abs(float(row.get('dna_to_rna_gc_delta') or 0.0) / 10.0)
            row['candidate_score'] = round(float(std_score) + residual_score + gc_score, 6)
            row['discordance_score'] = row['candidate_score']
            row['direction_class'] = _shift_direction_class(row.get('dna_to_rna_n_shift_std'), row.get('rna_to_protein_n_shift_std'))
    rows.sort(key=lambda item: float(item.get('candidate_score') or 0.0), reverse=True)
    exported_rows = rows[:600]
    corr_fields = [
        field for field in [
            'exon_gc_percent', 'transcript_gc', 'proteome_n_per_aa', 'pI', 'gravy',
            'dna_to_rna_n_shift_std', 'rna_to_protein_n_shift_std', 'protein_pi_residual',
        ]
        if any(_safe_num(row.get(field)) is not None for row in exported_rows)
    ]
    corr_matrix = _cross_row_correlation_matrix(exported_rows, corr_fields) if len(corr_fields) >= 2 else {}
    top_genome = sorted(
        exported_rows,
        key=lambda item: abs(float(item.get('promoter_exon_gc_delta') or item.get('dna_to_rna_gc_delta') or 0.0)),
        reverse=True,
    )[:60]
    top_transcript = sorted(exported_rows, key=lambda item: abs(float(item.get('dna_to_rna_n_shift_std') or 0.0)), reverse=True)[:60]
    top_proteome = sorted(exported_rows, key=lambda item: abs(float(item.get('rna_to_protein_n_shift_std') or 0.0)), reverse=True)[:60]
    top_shared = exported_rows[:60]
    shared_outliers = {
        'genome_only': [row['gene_id'] for row in top_genome],
        'transcriptome_only': [row['gene_id'] for row in top_transcript],
        'proteome_only': [row['gene_id'] for row in top_proteome],
        'shared_all_three': [row['gene_id'] for row in top_shared],
        'counts': {
            'genome_only': len(top_genome),
            'transcriptome_only': len(top_transcript),
            'proteome_only': len(top_proteome),
            'shared_all_three': len(top_shared),
        },
    }
    join_base = max(1, min(len(genome), len(transcriptome), len(proteome)))
    join_summary = {
        'genome_rows': int(genome_rows or len(genome)),
        'transcriptome_rows': int(transcript_rows or len(transcriptome)),
        'proteome_rows': int(proteome_rows or len(proteome)),
        'matched_genome_transcriptome': int(len(set(genome) & set(transcriptome))),
        'matched_transcriptome_proteome': int(len(set(transcriptome) & set(proteome))),
        'matched_all_three': int(len(common)),
        'match_rate_genome_transcriptome': round(_safe_div(len(set(genome) & set(transcriptome)), max(1, min(len(genome), len(transcriptome)))), 6),
        'match_rate_transcriptome_proteome': round(_safe_div(len(set(transcriptome) & set(proteome)), max(1, min(len(transcriptome), len(proteome)))), 6),
        'match_rate_all_three': round(_safe_div(len(common), join_base), 6),
        'source': 'on_demand_core_csv_gene_join',
    }
    mapping_summary = {
        'species_id': species_id,
        'entity_key': '',
        'row_counts': {
            'genome': int(genome_rows or len(genome)),
            'transcriptome': int(transcript_rows or len(transcriptome)),
            'proteome': int(proteome_rows or len(proteome)),
        },
        'coverage': {
            'all_three': join_summary['match_rate_all_three'],
            'genome_transcriptome': join_summary['match_rate_genome_transcriptome'],
            'transcriptome_proteome': join_summary['match_rate_transcriptome_proteome'],
        },
        'matched_all_three': int(len(common)),
        'conflict_count': 0,
        'multi_mapping': {'multi_transcript_gene_count': 0, 'multi_protein_gene_count': 0},
        'method': 'on-demand gene_id join over OmicsDataset core_csv_path files',
    }
    return {
        'species_id': species_id,
        'join_summary': join_summary,
        'mapping_summary': mapping_summary,
        'top_transformations': exported_rows,
        'transformations': _build_transformations_from_rows(exported_rows),
        'shared_outliers': shared_outliers,
        'correlation_matrices': {'pearson': corr_matrix} if corr_matrix else {},
        'correlation_matrix': corr_matrix,
        'cross_points': _cross_scatter(exported_rows, 'dna_to_rna_n_shift_std', 'rna_to_protein_n_shift_std'),
        'precomputed_from_real_rows': True,
        'on_demand_derived': True,
        'source_files': {
            'genome_core': str(genome_path) if genome_path else '',
            'transcriptome_core': str(transcript_path) if transcript_path else '',
            'proteome_core': str(proteome_path) if proteome_path else '',
        },
        'method_metadata': {
            'join_panel': {'method': 'gene_id intersection over imported core feature CSV files', 'evidence_level': 'sequence-derived descriptive'},
            'transformations': {'method': 'robust-z standardized deltas across genome/transcriptome/proteome stoichiometric nitrogen features; raw cross-unit deltas retained only as legacy_proxy fields', 'resource_shift_reference': resource_shift_reference},
            'correlation': {'method': 'pearson over derived matched rows', 'missing_policy': 'pairwise_complete'},
            'missing_policy': 'fallback generated only when all three core feature tables and gene_id overlap are available',
        },
    }


SCATTER_FIELD_MAP: dict[str, tuple[str, str, str]] = {
    'promoter_vs_exon_gc': ('exon_gc_percent', 'promoter_gc_percent', 'identity'),
    'promoter_exon_scatter': ('exon_gc_percent', 'promoter_gc_percent', 'identity'),
    'gc3_vs_n': ('gc3_percent', 'exon_atoms_N_per_base', 'density'),
    'gc3_vs_n_scatter': ('gc3_percent', 'exon_atoms_N_per_base', 'density'),
    'gc12_vs_gc3': ('gc12_percent_estimated', 'gc3_percent', 'identity'),
    'promoter_delta_vs_n': ('promoter_exon_gc_delta', 'exon_atoms_N_per_base', 'quadrant'),
    'delta_vs_n_scatter': ('promoter_exon_gc_delta', 'promoter_exon_N_delta', 'quadrant'),
    'skew_scatter': ('locus_gc_percent', 'locus_gc_skew', 'density'),
    'length_vs_gc_scatter': ('gene_length_bp', 'exon_gc_percent', 'log_scatter'),
    'length_vs_island_scatter': ('gene_length_bp', 'stoich_island_score', 'log_scatter'),
    'gc_vs_entropy': ('gc_content', 'nt_entropy', 'density'),
    'gc_vs_rna_mw': ('gc_content', 'mw_rna_nmp_per_nt_Da_estimated', 'formula_card'),
    'rna_n_vs_cn_ratio': ('atoms_per_nt_N', 'C_N_ratio_estimated', 'formula_card'),
    'coupling_vs_gravy': ('rna_orf_coupling_score', 'protein_gravy_proxy', 'proxy_scatter'),
    'resource_n_vs_coding_density': ('atoms_per_nt_N', 'coding_density_proxy', 'density'),
    'orf_vs_transcript_scatter': ('length_nt_acgu', 'orf_len_nt', 'identity'),
    'n_vs_pi': ('N_atoms_per_aa', 'pI', 'density'),
    'pi_vs_gravy': ('pI', 'gravy', 'quadrant'),
    'n_vs_s_resource': ('N_atoms_per_aa', 'S_atoms_per_aa', 'density'),
    'ns_tradeoff_scatter': ('N_atoms_per_aa', 'S_atoms_per_aa', 'density'),
    'n_vs_ns_ratio': ('N_atoms_per_aa', 'N_S_ratio', 'formula_card'),
    'sulfur_frac_vs_gravy': ('sulfur_aa_frac_estimated', 'gravy', 'density'),
    'length_vs_resource_budget': ('length_aa', 'resource_budget_score', 'log_scatter'),
    'instability_gravy_scatter': ('gravy', 'instability_index', 'threshold_scatter'),
    'flex_access_scatter': ('flex_mean', 'surface_access_em_mean', 'quadrant'),
    'redox_gravy_scatter': ('avg_oxidation_state_C', 'gravy', 'threshold_scatter'),
    'shift_scatter': ('dna_to_rna_n_shift_std', 'rna_to_protein_n_shift_std', 'quadrant'),
    'exon_transcript_gc_scatter': ('exon_gc_percent', 'transcript_gc', 'identity'),
    'gc_protein_n_scatter': ('transcript_gc', 'proteome_n_per_aa', 'small_n_scatter'),
    'gc_pi_scatter': ('transcript_gc', 'pI', 'small_n_scatter'),
    'gc_gravy_scatter': ('transcript_gc', 'gravy', 'small_n_scatter'),
    'available_proxy_scatter': ('pI', 'gravy', 'matched_subset_scatter'),
}

ORDINATION_KEYS = {
    'pca', 'contrast_pca', 'promoter_signature_pca', 'cross_species_dinuc_pca',
    'codon_strategy_pca', 'species_pca', 'resource_projection', 'dinuc_projection',
    'codon_projection', 'protein_projection', 'aa_projection', 'property_projection',
    'structure_projection', 'redox_projection', 'ordination',
}

FORMULA_REPLACEMENTS = {
    'gc_vs_rna_mw': {
        'title': 'RNA GC 与平均 NMP 分子量为公式关系',
        'formula': 'MW/nt ≈ f(GC content)',
        'reason': '平均 RNA NMP 质量由 GC 含量按固定碱基组成假设估算，默认散点会制造冗余相关。',
        'recommended_view': 'formula_card',
    },
    'rna_n_vs_cn_ratio': {
        'title': 'RNA N/nt 与 C/N ratio 为数学反比关系',
        'formula': 'C/N ≈ C_atoms_per_nt / N_atoms_per_nt',
        'reason': 'C/N ratio 直接由 N/nt 参与计算，默认散点不应被解释为独立生物耦合。',
        'recommended_view': 'formula_card',
    },
    'n_vs_ns_ratio': {
        'title': 'Protein N/aa 与 N/S ratio 存在数学耦合',
        'formula': 'N/S = N_atoms_per_aa / S_atoms_per_aa',
        'reason': 'N/S ratio 直接由 N 与 S 计算，应优先展示 N/aa vs S/aa 与 ratio 分布。',
        'recommended_view': 'formula_card',
    },
}


def _scatter_median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def _rank_values(values: list[float]) -> list[float]:
    indexed = sorted((value, idx) for idx, value in enumerate(values))
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][0] == indexed[i][0]:
            j += 1
        rank = (i + j + 1) / 2.0
        for k in range(i, j):
            ranks[indexed[k][1]] = rank
        i = j
    return ranks


def _xy_pairs(points: list[dict[str, Any]], x_field: str, y_field: str) -> list[tuple[float, float, dict[str, Any]]]:
    pairs = []
    for row in points or []:
        x = _safe_num(row.get(x_field))
        y = _safe_num(row.get(y_field))
        if x is None or y is None:
            continue
        pairs.append((float(x), float(y), row))
    return pairs


def _pearson_from_values(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    den_x = math.sqrt(sum((value - mean_x) ** 2 for value in xs))
    den_y = math.sqrt(sum((value - mean_y) ** 2 for value in ys))
    if den_x <= 0 or den_y <= 0:
        return None
    return float(sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / (den_x * den_y))


def _scatter_stats(points: list[dict[str, Any]], x_field: str, y_field: str) -> dict[str, Any]:
    pairs = _xy_pairs(points, x_field, y_field)
    xs = [item[0] for item in pairs]
    ys = [item[1] for item in pairs]
    pearson = _pearson_from_values(xs, ys)
    spearman = _pearson_from_values(_rank_values(xs), _rank_values(ys)) if len(xs) >= 3 else None
    return {
        'n': len(pairs),
        'x_field': x_field,
        'y_field': y_field,
        'x_min': round(min(xs), 6) if xs else None,
        'x_max': round(max(xs), 6) if xs else None,
        'y_min': round(min(ys), 6) if ys else None,
        'y_max': round(max(ys), 6) if ys else None,
        'x_median': round(_scatter_median(xs), 6) if xs else None,
        'y_median': round(_scatter_median(ys), 6) if ys else None,
        'pearson_r': round(float(pearson), 6) if pearson is not None else None,
        'spearman_r': round(float(spearman), 6) if spearman is not None else None,
        'missing_policy': 'points with missing x or y are omitted before sampling/rendering',
        'sampling_policy': 'deterministic stride sampling when points exceed the payload limit',
    }


def _scatter_reference_lines(kind: str, x_field: str = '', y_field: str = '') -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    if kind in {'quadrant', 'threshold_scatter'}:
        lines.extend([{'kind': 'x', 'value': 0, 'label': 'x=0'}, {'kind': 'y', 'value': 0, 'label': 'y=0'}])
    if kind == 'identity':
        lines.append({'kind': 'identity', 'label': 'y=x'})
    if y_field == 'instability_index':
        lines.append({'kind': 'y', 'value': 40, 'label': 'instability=40'})
    if x_field == 'gravy' or y_field == 'gravy':
        axis = 'x' if x_field == 'gravy' else 'y'
        lines.append({'kind': axis, 'value': 0, 'label': 'GRAVY=0'})
    return lines


def _scatter_candidates(points: list[dict[str, Any]], x_field: str, y_field: str, kind: str, limit: int = 12) -> list[dict[str, Any]]:
    pairs = _xy_pairs(points, x_field, y_field)
    if not pairs:
        return []
    candidates = []
    if kind == 'identity':
        for x, y, row in pairs:
            candidates.append((abs(y - x), row, {'residual': round(y - x, 6)}))
    elif kind == 'quadrant':
        for x, y, row in pairs:
            candidates.append((abs(x) + abs(y), row, {'quadrant_score': round(abs(x) + abs(y), 6)}))
    else:
        xs = [item[0] for item in pairs]
        ys = [item[1] for item in pairs]
        mx = _scatter_median(xs) or 0.0
        my = _scatter_median(ys) or 0.0
        for x, y, row in pairs:
            candidates.append((abs(x - mx) + abs(y - my), row, {'outlier_score': round(abs(x - mx) + abs(y - my), 6)}))
    output = []
    for _, row, extra in sorted(candidates, key=lambda item: item[0], reverse=True)[:limit]:
        output.append({
            'entity_id': row.get('entity_id') or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id') or row.get('species_id'),
            'gene_id': row.get('gene_id') or '',
            'transcript_id': row.get('transcript_id') or '',
            'protein_id': row.get('protein_id') or '',
            'gene_name': row.get('gene_name') or row.get('gene_symbol') or '',
            x_field: row.get(x_field),
            y_field: row.get(y_field),
            **extra,
        })
    return output


def _scatter_meta(points: list[dict[str, Any]], x_field: str, y_field: str, kind: str = 'density', title: str = '') -> dict[str, Any]:
    stats = _scatter_stats(points, x_field, y_field)
    replacement = FORMULA_REPLACEMENTS.get(title) or FORMULA_REPLACEMENTS.get(kind)
    return {
        'stats': stats,
        'semantic_type': kind,
        'recommended_view': FORMULA_REPLACEMENTS.get(title, {}).get('recommended_view') or kind,
        'reference_lines': _scatter_reference_lines(kind, x_field, y_field),
        'candidates': _scatter_candidates(points, x_field, y_field, kind),
        'explanation': {
            'ordinary_scatter': 'Read trend, density, stratification and outlier candidates; do not infer causality from scatter alone.',
            'quadrant': 'Read x/y direction combinations using zero lines and quadrant counts.',
            'identity': 'Read agreement with y=x; large residuals are candidate mismatches or biologically divergent entities.',
            'formula_card': 'This relation is mathematically coupled and should be shown as formula/distribution rather than a default scatter.',
        }.get(kind, 'Read density, trend and outlier candidates.'),
        'replacement_payload': replacement,
        'evidence_level': 'descriptive / hypothesis-generating',
    }


def _nearest_neighbors(points: list[dict[str, Any]], x_field: str, y_field: str, current_species_id: str, limit: int = 3) -> list[dict[str, Any]]:
    pairs = _xy_pairs(points, x_field, y_field)
    target = None
    for x, y, row in pairs:
        if str(row.get('species_id') or '') == current_species_id:
            target = (x, y)
            break
    if target is None:
        return []
    neighbors = []
    for x, y, row in pairs:
        sid = str(row.get('species_id') or '')
        if sid == current_species_id:
            continue
        dist = math.sqrt((x - target[0]) ** 2 + (y - target[1]) ** 2)
        neighbors.append({'species_id': sid, 'display_name': row.get('display_name') or sid, 'distance': round(dist, 6)})
    return sorted(neighbors, key=lambda item: item['distance'])[:limit]


def _attach_ordination_meta(payload: dict[str, Any], current_species_id: str = '') -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    points = payload.get('umap_points') or ((payload.get('umap') or {}).get('points') if isinstance(payload.get('umap'), dict) else None) or payload.get('points') or []
    x_field = 'umap1' if payload.get('umap_points') else ('x' if points and 'x' in points[0] else 'pc1')
    y_field = 'umap2' if payload.get('umap_points') else ('y' if points and 'y' in points[0] else 'pc2')
    payload.setdefault('ordination_meta', {
        'input_features': payload.get('input_features') or payload.get('metrics') or [],
        'standardization': payload.get('standardization') or 'robust z-score or centered species fingerprint, depending on source payload',
        'method': 'UMAP' if payload.get('umap_points') else payload.get('method', 'pca_svd'),
        'explained_variance_ratio': payload.get('explained_variance_ratio') or [0.0, 0.0],
        'umap_params': payload.get('umap_params') or ((payload.get('umap') or {}).get('params') if isinstance(payload.get('umap'), dict) else {}) or {},
        'nearest_neighbors': _nearest_neighbors(points, x_field, y_field, current_species_id) if current_species_id else [],
        'interpretation_boundary': 'Projected distances are descriptive feature-space distances and are not phylogenetic distances.',
        'color_fields': ['strategy_cluster', 'stoich_island_score', 'gene_length_bp', 'biotype', 'resource_budget_score'],
    })
    return payload


def _attach_known_chart_metadata(payload: Any, current_species_id: str = '') -> Any:
    if isinstance(payload, list):
        for item in payload:
            _attach_known_chart_metadata(item, current_species_id)
        return payload
    if not isinstance(payload, dict):
        return payload

    scatter = payload.get('scatter')
    if isinstance(scatter, dict):
        scatter_meta = payload.setdefault('scatter_meta', {})
        for key, points in scatter.items():
            if isinstance(points, list) and key in SCATTER_FIELD_MAP:
                x_field, y_field, kind = SCATTER_FIELD_MAP[key]
                scatter_meta[key] = _scatter_meta(points, x_field, y_field, kind, title=key)

    for key, value in list(payload.items()):
        if key in SCATTER_FIELD_MAP and isinstance(value, list):
            x_field, y_field, kind = SCATTER_FIELD_MAP[key]
            payload.setdefault(f'{key}_meta', _scatter_meta(value, x_field, y_field, kind, title=key))
        elif key in ORDINATION_KEYS and isinstance(value, dict):
            _attach_ordination_meta(value, current_species_id)
        elif isinstance(value, (dict, list)):
            _attach_known_chart_metadata(value, current_species_id)
    return payload


def _cross_correlation_heatmap(data: dict[str, Any]) -> dict[str, Any]:
    matrices = data.get('correlation_matrices') if isinstance(data.get('correlation_matrices'), dict) else {}
    method = 'spearman' if 'spearman' in matrices else next(iter(matrices.keys()), '')
    matrix = matrices.get(method) if method else None
    if not isinstance(matrix, dict):
        matrix = data.get('correlation_matrix') if isinstance(data.get('correlation_matrix'), dict) else {}
        method = method or 'spearman'
    labels = list(matrix.keys())
    values = []
    for y_idx, y_key in enumerate(labels):
        row = matrix.get(y_key) if isinstance(matrix.get(y_key), dict) else {}
        for x_idx, x_key in enumerate(labels):
            values.append([x_idx, y_idx, round(float(_safe_num(row.get(x_key)) or 0.0), 6)])
    return {'x_labels': labels, 'y_labels': labels, 'values': values, 'method': method, 'details': data.get('correlation_details') or []}


def _cross_edge_rows(data: dict[str, Any], min_abs: float = 0.25) -> list[dict[str, Any]]:
    edges = []
    for item in data.get('correlation_details') or []:
        if not isinstance(item, dict):
            continue
        r = _safe_num(item.get('r'))
        if r is None or abs(float(r)) < min_abs:
            continue
        a = item.get('feature_a')
        b = item.get('feature_b')
        pair = 'cross_or_within'
        if a and b:
            a_layer = str(a).split('_')[0]
            b_layer = str(b).split('_')[0]
            pair = f'{a_layer}-{b_layer}' if a_layer != b_layer else f'within-{a_layer}'
        edges.append({
            'source': a,
            'target': b,
            'omics_pair': pair,
            'r': round(float(r), 6),
            'p_value': item.get('p_value'),
            'fdr': item.get('fdr'),
            'n': item.get('n'),
            'method': item.get('method') or 'spearman',
        })
    return sorted(edges, key=lambda row: abs(float(row.get('r') or 0)), reverse=True)[:60]


def _species_cross_fingerprint_rows(current_species_id: str, limit: int = 80) -> list[dict[str, Any]]:
    rows = []
    if db_mode():
        species_rows = list(
            Species.objects
            .only('species_id', 'display_name', 'fingerprint', 'cross_omics_payload', 'has_genome', 'has_transcriptome', 'has_proteome')
            .order_by('display_name')[:limit]
        )
        for species in species_rows:
            cross_payload = species.cross_omics_payload or {}
            top = cross_payload.get('top_transformations') if isinstance(cross_payload.get('top_transformations'), list) else []
            dna_shifts = [_safe_num(row.get('dna_to_rna_n_shift_std')) for row in top if isinstance(row, dict)]
            protein_shifts = [_safe_num(row.get('rna_to_protein_n_shift_std')) for row in top if isinstance(row, dict)]
            dna_clean = [float(v) for v in dna_shifts if v is not None]
            protein_clean = [float(v) for v in protein_shifts if v is not None]
            join = cross_payload.get('join_summary') if isinstance(cross_payload.get('join_summary'), dict) else {}
            fp = species.fingerprint or {}
            rows.append({
                'species_id': species.species_id,
                'display_name': species.display_name,
                'match_rate_all_three': _safe_num(join.get('match_rate_all_three')) or 0.0,
                'dna_to_rna_n_shift_mean': _mean(dna_clean) if dna_clean else 0.0,
                'rna_to_protein_n_shift_mean': _mean(protein_clean) if protein_clean else 0.0,
                'cross_shift_abs_mean': _mean([abs(v) for v in dna_clean + protein_clean]) if dna_clean or protein_clean else 0.0,
                'genome_gc': _safe_num(fp.get('genome_gc')) or 0.0,
                'transcript_gc': _safe_num(fp.get('transcript_gc')) or _safe_num(fp.get('transcript_coupling')) or 0.0,
                'proteome_n_per_aa': _safe_num(fp.get('proteome_n_per_aa')) or 0.0,
                'proteome_pi': _safe_num(fp.get('proteome_pi')) or 0.0,
            })
    else:
        for species_id, meta in list(file_species_map().items())[:limit]:
            try:
                cross_payload = load_json(f'{species_id}/cross_omics.json')
            except Exception:
                cross_payload = {}
            top = cross_payload.get('top_transformations') if isinstance(cross_payload.get('top_transformations'), list) else []
            dna_clean = [float(v) for v in (_safe_num(row.get('dna_to_rna_n_shift_std')) for row in top if isinstance(row, dict)) if v is not None]
            protein_clean = [float(v) for v in (_safe_num(row.get('rna_to_protein_n_shift_std')) for row in top if isinstance(row, dict)) if v is not None]
            rows.append({
                'species_id': species_id,
                'display_name': meta.get('display_name') or species_id,
                'match_rate_all_three': _safe_num((cross_payload.get('join_summary') or {}).get('match_rate_all_three')) or 0.0,
                'dna_to_rna_n_shift_mean': _mean(dna_clean) if dna_clean else 0.0,
                'rna_to_protein_n_shift_mean': _mean(protein_clean) if protein_clean else 0.0,
                'cross_shift_abs_mean': _mean([abs(v) for v in dna_clean + protein_clean]) if dna_clean or protein_clean else 0.0,
            })
    if rows and not any(row.get('species_id') == current_species_id for row in rows):
        rows = rows[: max(0, limit - 1)]
    return rows


def _species_rows_for_response(rows: list[dict[str, Any]], current_species_id: str, limit: int = 180) -> list[dict[str, Any]]:
    """Return a deterministic UI-sized species subset while keeping the selected species visible."""
    if not rows or len(rows) <= limit:
        return rows
    current_rows = [row for row in rows if str(row.get('species_id') or '') == current_species_id]
    current_ids = {str(row.get('species_id') or '') for row in current_rows}
    other_rows = [row for row in rows if str(row.get('species_id') or '') not in current_ids]
    remaining = max(0, limit - len(current_rows))
    if remaining and len(other_rows) > remaining:
        stride = max(1, math.ceil(len(other_rows) / remaining))
        other_rows = other_rows[::stride][:remaining]
    else:
        other_rows = other_rows[:remaining]
    return (current_rows + other_rows)[:limit]


def _cross_omics_module_suite(species_id: str, data: dict[str, Any]) -> dict[str, Any]:
    rows = _cross_rows_from_transformations(data)
    resource_shift_reference = _attach_standardized_resource_shifts(rows) if rows else {'usable': False, 'reference_n': 0, 'method_version': 'resource_shift_robust_z_v2_2026_08_09'}
    join = data.get('join_summary') if isinstance(data.get('join_summary'), dict) else {}
    available = set()
    for row in rows[:2000]:
        for key, value in row.items():
            if value not in (None, ''):
                available.add(str(key))
    if join:
        available.update(str(key) for key, value in join.items() if value not in (None, ''))
    if data.get('correlation_matrix') or data.get('correlation_matrices'):
        available.add('correlation_matrix')
    if data.get('shared_outliers'):
        available.add('shared_outliers')

    dna_shift_values = [float(v) for v in (_safe_num(row.get('dna_to_rna_n_shift_std')) for row in rows) if v is not None]
    protein_shift_values = [float(v) for v in (_safe_num(row.get('rna_to_protein_n_shift_std')) for row in rows) if v is not None]
    legacy_dna_shift_values = [float(v) for v in (_safe_num(row.get('dna_to_rna_n_shift_legacy_proxy')) for row in rows) if v is not None]
    legacy_protein_shift_values = [float(v) for v in (_safe_num(row.get('rna_to_protein_n_shift_legacy_proxy')) for row in rows) if v is not None]
    x6_heatmap = _cross_correlation_heatmap(data)
    species_rows = _species_cross_fingerprint_rows(species_id)
    species_metrics = [
        'match_rate_all_three',
        'dna_to_rna_n_shift_mean',
        'rna_to_protein_n_shift_mean',
        'cross_shift_abs_mean',
        'genome_gc',
        'transcript_gc',
        'proteome_n_per_aa',
        'proteome_pi',
    ]
    species_metrics = [metric for metric in species_metrics if any(_safe_num(row.get(metric)) is not None for row in species_rows)]
    current_fingerprint = next((row for row in species_rows if row.get('species_id') == species_id), {})
    species_response_rows = _species_rows_for_response(species_rows, species_id)
    shared_outliers = data.get('shared_outliers') if isinstance(data.get('shared_outliers'), dict) else {}
    shared_rows = []
    for label, genes in (shared_outliers.items() if isinstance(shared_outliers, dict) else []):
        if label == 'counts' or not isinstance(genes, list):
            continue
        for gene_id in genes[:40]:
            shared_rows.append({
                'canonical_gene_id': gene_id,
                'gene_id': gene_id,
                'candidate_class': label,
                'candidate_score': 1.0 if label == 'shared_all_three' else 0.5,
                'data_scope': 'shared_outlier_overlap',
                'source_modules': ['X5', 'shared_outliers'],
                'top_contributing_features': label,
                'evidence_level': 'shared_outlier_overlap',
            })
    x8_rows = []
    for row in rows[:80]:
        x8_rows.append({
            'canonical_gene_id': row.get('canonical_gene_id') or row.get('gene_id'),
            'gene_id': row.get('gene_id') or row.get('canonical_gene_id'),
            'gene_name': row.get('gene_name') or '',
            'candidate_score': row.get('candidate_score') or row.get('discordance_score'),
            'resource_shift_score': row.get('resource_shift_score_std') if row.get('resource_shift_score_std') is not None else None,
            'discordance_score': row.get('discordance_score'),
            'direction_class': row.get('direction_class') or '',
            'data_scope': row.get('data_scope') or 'top_transformations',
            'source_modules': row.get('source_modules') or ['X1', 'legacy_top_transformations'],
            'score_components': {
                'resource_shift_score': row.get('resource_shift_score_std') if row.get('resource_shift_score_std') is not None else None,
                'discordance_score': row.get('discordance_score'),
            },
            'top_contributing_features': row.get('main_driver') or 'resource shift',
            'evidence_level': 'sequence-derived descriptive',
        })
    x8_rows = sorted(x8_rows + shared_rows, key=lambda item: float(item.get('candidate_score') or 0), reverse=True)[:120]

    modules = [
        {
            'id': 'X0',
            'name': 'Cross-omics data foundation',
            'status': _cross_module_status(['genome_rows', 'transcriptome_rows', 'proteome_rows', 'matched_all_three'], available),
            'cards': join,
            'match_coverage_rows': [
                {'name': 'Genome rows', 'value': join.get('genome_rows') or 0},
                {'name': 'Transcriptome rows', 'value': join.get('transcriptome_rows') or 0},
                {'name': 'Proteome rows', 'value': join.get('proteome_rows') or 0},
                {'name': 'Matched all three', 'value': join.get('matched_all_three') or 0},
            ],
            'match_rate_rows': [
                {'name': 'G-T', 'value': join.get('match_rate_genome_transcriptome') or 0},
                {'name': 'T-P', 'value': join.get('match_rate_transcriptome_proteome') or 0},
                {'name': 'G-T-P', 'value': join.get('match_rate_all_three') or 0},
            ],
            'method': 'canonical gene-level matching using gene_id / canonical_gene_id / ensembl_gene_id where available; coverage is reported before all downstream interpretation.',
            'missing_fields': ['isoform_policy metadata', 'canonical_cross_omics_index artifact', 'quality_flags table'],
        },
        {
            'id': 'X1',
            'name': 'DNA-RNA-Protein resource shift',
            'status': _cross_module_status(['dna_to_rna_n_shift_std', 'rna_to_protein_n_shift_std'], available),
            'shift_histograms': {
                'dna_to_rna_n_std': _histogram_payload(dna_shift_values, bins=42),
                'rna_to_protein_n_std': _histogram_payload(protein_shift_values, bins=42),
            },
            'shift_stats': {
                'dna_to_rna_n_std': _distribution_stats(dna_shift_values),
                'rna_to_protein_n_std': _distribution_stats(protein_shift_values),
            },
            'shift_scatter': _cross_scatter(rows, 'dna_to_rna_n_shift_std', 'rna_to_protein_n_shift_std'),
            'legacy_shift_histograms': {
                'dna_to_rna_n_legacy_proxy': _histogram_payload(legacy_dna_shift_values, bins=42),
                'rna_to_protein_n_legacy_proxy': _histogram_payload(legacy_protein_shift_values, bins=42),
            },
            'legacy_shift_stats': {
                'dna_to_rna_n_legacy_proxy': _distribution_stats(legacy_dna_shift_values),
                'rna_to_protein_n_legacy_proxy': _distribution_stats(legacy_protein_shift_values),
            },
            'resource_shift_reference': resource_shift_reference,
            'quadrants': _cross_quadrant_rows(rows),
            'candidate_table': rows[:40],
            'method': 'Primary X1 metric is dimensionless robust-z delta: DNA_to_RNA_N_shift_std=z(transcriptome N/nt)-z(genome exon N/base); RNA_to_Protein_N_shift_std=z(proteome N/aa)-z(transcriptome N/nt). Raw cross-denominator differences are retained only as legacy_proxy fields.',
            'method_version': 'resource_shift_robust_z_v2_2026_08_09',
            'units': 'dimensionless robust-z delta',
            'missing_fields': ['resource_concordance_score from full matched matrix', 'C/P/S shift fields for all matched entities'],
        },
        {
            'id': 'X2',
            'name': 'Regulatory-to-transcript coupling',
            'status': _cross_module_status(['exon_gc_percent', 'transcript_gc'], available),
            'exon_transcript_gc_scatter': _cross_scatter(rows, 'exon_gc_percent', 'transcript_gc'),
            'residual_candidates': sorted(
                [
                    {**row, 'exon_rna_gc_delta': round((float(row.get('transcript_gc') or 0) * 100.0) - float(row.get('exon_gc_percent') or 0), 6)}
                    for row in rows
                    if _safe_num(row.get('transcript_gc')) is not None and _safe_num(row.get('exon_gc_percent')) is not None
                ],
                key=lambda item: abs(float(item.get('exon_rna_gc_delta') or 0)),
                reverse=True,
            )[:40],
            'method': 'Exon_RNA_GC_delta=transcript_gc*100-exon_gc_percent. Promoter residual models require promoter_gc_percent and promoter_exon_gc_delta in matched rows.',
            'missing_fields': ['promoter_gc_percent in cross payload', 'promoter_exon_gc_delta in cross payload', 'coordinate profile overlay artifact'],
        },
        {
            'id': 'X3',
            'name': 'Codon-to-protein translation strategy',
            'status': _cross_module_status(['transcript_gc', 'proteome_n_per_aa', 'pI', 'gravy'], available),
            'gc_protein_n_scatter': _cross_scatter(rows, 'transcript_gc', 'proteome_n_per_aa'),
            'gc_pi_scatter': _cross_scatter(rows, 'transcript_gc', 'pI'),
            'gc_gravy_scatter': _cross_scatter(rows, 'transcript_gc', 'gravy'),
            'discordance_candidates': rows[:40],
            'method': 'Current implementation uses available transcript GC and observed proteome pI/GRAVY/N per aa as a translation-strategy proxy. Full codon-vector distances require codon_* matched artifacts.',
            'missing_fields': ['genome codon_*_freq matched matrix', 'transcript codon_*_freq matched matrix', 'codon-protein FDR matrix'],
        },
        {
            'id': 'X4',
            'name': 'RNA-predicted protein vs observed proteome',
            'status': _cross_module_status(['protein_isoelectric_point', 'protein_gravy', 'protein_instability_index', 'pI', 'gravy', 'instability_index'], available),
            'available_proxy_scatter': _cross_scatter(rows, 'pI', 'gravy'),
            'candidate_table': [],
            'method': 'Requires transcript-derived protein-like properties from Transcriptome T7 matched to observed proteome properties. Existing cross payload does not yet include these paired residual fields.',
            'missing_fields': ['transcript protein_isoelectric_point', 'transcript protein_gravy', 'transcript protein_instability_index', 'matched transcript AA frequency vector'],
        },
        {
            'id': 'X5',
            'name': 'Stoich island propagation',
            'status': _cross_module_status(['stoich_island_score', 'transcript_resource_outlier_score', 'proteome_resource_outlier_score'], available),
            'shared_outlier_counts': [{'name': key, 'value': value} for key, value in (shared_outliers.get('counts') or {}).items()] if isinstance(shared_outliers.get('counts'), dict) else [],
            'candidate_table': shared_rows[:60],
            'method': 'Current fallback exposes shared single-omics outlier overlap. Full propagation_score requires matched stoich_island_score plus transcript/proteome resource outlier scores and genome coordinate bins.',
            'missing_fields': ['stoich_island_score in matched cross payload', 'transcript resource_outlier_score', 'proteome resource_outlier_score', 'window propagation artifact'],
        },
        {
            'id': 'X6',
            'name': 'Cross-omics feature coupling network',
            'status': _cross_module_status(['correlation_matrix'], available),
            'correlation_heatmap': x6_heatmap,
            'edge_ranking': _cross_edge_rows(data),
            'method': 'Spearman/Pearson correlation over matched cross-omics features with Benjamini-Hochberg FDR where p-values can be estimated.',
            'missing_fields': ['stable FDR artifact with full matched matrix', 'network community detection artifact'],
        },
        {
            'id': 'X7',
            'name': 'Species-level cross-omics fingerprint',
            'status': 'implemented' if species_rows and species_metrics else 'partial',
            'fingerprint': {key: value for key, value in current_fingerprint.items() if key not in {'species_id', 'display_name'}},
            'species_fingerprint_rows': species_response_rows,
            'species_fingerprint_meta': {
                'source_species_count': len(species_rows),
                'returned_species_count': len(species_response_rows),
                'downsampled': len(species_rows) > len(species_response_rows),
                'policy': 'current_species_plus_even_species_sample',
            },
            'species_pca': _species_pca_payload(species_response_rows, species_metrics) if species_metrics else {'points': [], 'umap_points': []},
            'distance_matrix': _species_distance_heatmap(species_response_rows, species_metrics) if species_metrics else {'x_labels': [], 'y_labels': [], 'values': []},
            'feature_ranking': _fingerprint_feature_rank(species_rows),
            'method': 'Species-level cross-omics fingerprint aggregates match rates, mean shifts and selected species fingerprint fields, then applies robust species-level ordination/distance routines.',
            'missing_fields': ['resource_concordance_score across all matched genes', 'codon_protein_coupling_strength artifact'],
        },
        {
            'id': 'X8',
            'name': 'Candidate workbench and export',
            'status': 'implemented' if x8_rows else 'partial',
            'candidate_table': x8_rows,
            'score_components': [
                {'name': 'resource_shift_score', 'value': _mean([float(row.get('resource_shift_score') or 0) for row in x8_rows]) if x8_rows else 0},
                {'name': 'discordance_score', 'value': _mean([float(row.get('discordance_score') or 0) for row in x8_rows if _safe_num(row.get('discordance_score')) is not None]) if x8_rows else 0},
            ],
            'method': 'Candidate score defaults to existing discordance/resource-shift ranking plus shared outlier overlap fallback. Weights are descriptive and not causal.',
            'missing_fields': ['interactive weight presets', 'entity detail drawer', 'export package with field dictionary and generated_at metadata'],
        },
    ]
    edge_rows = modules[6].get('edge_ranking') or []
    coupling_edges_export = []
    for idx, edge in enumerate(edge_rows):
        feature_a = str(edge.get('feature_a') or edge.get('source_feature') or '')
        feature_b = str(edge.get('feature_b') or edge.get('target_feature') or '')
        coupling_edges_export.append({
            'edge_id': f'cross_edge_{idx + 1}',
            'source_feature': feature_a,
            'source_omics': _feature_omics_hint(feature_a),
            'target_feature': feature_b,
            'target_omics': _feature_omics_hint(feature_b),
            'r': edge.get('r'),
            'abs_r': edge.get('abs_r') or abs(float(edge.get('r') or 0.0)),
            'p_value': edge.get('p_value'),
            'fdr': edge.get('fdr'),
            'n': edge.get('n'),
            'method': edge.get('method') or (x6_heatmap.get('method') if isinstance(x6_heatmap, dict) else ''),
        })
    resource_shift_export = [
        {
            'canonical_gene_id': row.get('canonical_gene_id') or row.get('gene_id'),
            'gene_id': row.get('gene_id') or row.get('canonical_gene_id'),
            'gene_name': row.get('gene_name') or '',
            'dna_to_rna_n_shift_std': row.get('dna_to_rna_n_shift_std'),
            'rna_to_protein_n_shift_std': row.get('rna_to_protein_n_shift_std'),
            'dna_to_rna_n_shift_legacy_proxy': row.get('dna_to_rna_n_shift_legacy_proxy'),
            'rna_to_protein_n_shift_legacy_proxy': row.get('rna_to_protein_n_shift_legacy_proxy'),
            'resource_shift_method_version': row.get('resource_shift_method_version'),
            'direction_class': row.get('direction_class'),
            'main_driver': row.get('main_driver'),
            'discordance_score': row.get('discordance_score'),
            'data_scope': row.get('data_scope') or 'top_transformations',
        }
        for row in rows
    ]
    fingerprint_export = [
        {
            'species_id': row.get('species_id'),
            'display_name': row.get('display_name'),
            **{key: value for key, value in row.items() if key not in {'species_id', 'display_name'}},
        }
        for row in species_response_rows
    ]
    missing_count = sum(len(module.get('missing_fields') or []) for module in modules)
    quality_flags = {
        'data_scope': 'top_transformations_adapter' if rows else 'no_matched_transformations',
        'top_transformations_only': True,
        'matched_all_three': join.get('matched_all_three') or 0,
        'match_rate_all_three': join.get('match_rate_all_three') or 0.0,
        'missing_field_count': missing_count,
        'evidence_level': 'sequence-derived descriptive / hypothesis-generating',
    }
    return {
        'schema_version': 'cross_omics_module_suite.v2',
        'module_suite_version': 'integrated_x0_x8_2026_05',
        'scope': 'cross_omics_payload_plus_species_fingerprint',
        'row_count': len(rows),
        'matched_all_three': join.get('matched_all_three') or 0,
        'modules': modules,
        'quality_flags': quality_flags,
        'export_tables': {
            'cross_omics_resource_shift.csv': resource_shift_export,
            'cross_omics_coupling_edges.csv': coupling_edges_export,
            'cross_omics_species_fingerprint_matrix.csv': fingerprint_export,
            'cross_omics_candidate_workbench.csv': x8_rows,
        },
        'artifact_recommendations': [
            'cross_omics_match_index.json',
            'cross_omics_resource_shift.json',
            'cross_omics_regulatory_transcript.json',
            'cross_omics_translation_strategy.json',
            'cross_omics_island_propagation.json',
            'cross_omics_coupling_network.json',
            'cross_omics_species_fingerprint.json',
            'cross_omics_candidate_workbench.csv',
        ],
        'method_metadata': {
            'method': 'cross-omics X0-X8 module suite built from existing cross_omics_payload, matched-gene transformations, correlation details, shared outliers and species fingerprints',
            'join_policy': 'canonical gene-level join from imported cross payload / EntityRecord canonical IDs',
            'normalization': 'X1 primary visuals use dimensionless robust-z deltas; raw cross-denominator differences are retained only as legacy_proxy export/context fields',
            'missing_policy': 'available matched fields are used; modules requiring codon vectors, predicted-observed residuals, FDR artifacts or external abundance are marked partial',
            'evidence_level': 'sequence-derived descriptive / hypothesis-generating',
        },
    }


def _precomputed_cross_module_suite(species_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Fast X0-X8 adapter backed by the persisted cross-omics payload."""
    join = data.get('join_summary') if isinstance(data.get('join_summary'), dict) else {}
    rows = _cross_rows_from_transformations(data)
    resource_shift_reference = _attach_standardized_resource_shifts(rows) if rows else {'usable': False, 'reference_n': 0, 'method_version': 'resource_shift_robust_z_v2_2026_08_09'}
    shifts_a = [float(value) for value in (_safe_num(row.get('dna_to_rna_n_shift_std')) for row in rows) if value is not None]
    shifts_b = [float(value) for value in (_safe_num(row.get('rna_to_protein_n_shift_std')) for row in rows) if value is not None]
    legacy_shifts_a = [float(value) for value in (_safe_num(row.get('dna_to_rna_n_shift_legacy_proxy')) for row in rows) if value is not None]
    legacy_shifts_b = [float(value) for value in (_safe_num(row.get('rna_to_protein_n_shift_legacy_proxy')) for row in rows) if value is not None]
    shared = data.get('shared_outliers') if isinstance(data.get('shared_outliers'), dict) else {}
    shared_rows = []
    for label, values in shared.items():
        if label == 'counts' or not isinstance(values, list):
            continue
        shared_rows.extend([
            {'canonical_gene_id': value, 'gene_id': value, 'candidate_class': label, 'candidate_score': 1.0 if label == 'shared_all_three' else 0.5, 'data_scope': 'shared_outlier_overlap', 'source_modules': ['X5']}
            for value in values[:40]
        ])

    species_rows = []
    try:
        for species in Species.objects.only('species_id', 'display_name', 'fingerprint').iterator(chunk_size=500):
            fingerprint = species.fingerprint or {}
            species_rows.append({'species_id': species.species_id, 'display_name': species.display_name, **fingerprint})
    except Exception:
        species_rows = []
    current_fingerprint = next((row for row in species_rows if row.get('species_id') == species_id), {})
    species_response_rows = _species_rows_for_response(species_rows, species_id)
    species_metrics = [key for key in ['genome_gc', 'transcript_gc', 'proteome_n_per_aa', 'proteome_pi', 'transcript_coupling'] if any(_safe_num(row.get(key)) is not None for row in species_rows)]

    def cheap_species_projection(metrics: list[str]) -> dict[str, Any]:
        if len(metrics) < 2:
            return {'points': [], 'umap_points': [], 'explained_variance_ratio': [0.0, 0.0], 'method': 'precomputed_species_fingerprint'}
        points = []
        for row in species_response_rows:
            x = _safe_num(row.get(metrics[0]))
            y = _safe_num(row.get(metrics[1]))
            if x is None or y is None:
                continue
            points.append({'species_id': row.get('species_id'), 'display_name': row.get('display_name'), 'pc1': float(x), 'pc2': float(y)})
        return {'points': points, 'umap_points': [], 'explained_variance_ratio': [0.5, 0.5], 'method': 'precomputed_species_fingerprint', 'meta': {'source_species_count': len(species_rows), 'returned_species_count': len(points), 'downsampled': len(species_rows) > len(species_response_rows)}}
    x6_heatmap = _cross_correlation_heatmap(data)
    x8_rows = [
        {
            'canonical_gene_id': row.get('gene_id') or row.get('canonical_gene_id'),
            'gene_id': row.get('gene_id') or row.get('canonical_gene_id'),
            'gene_name': row.get('gene_name') or '',
            'candidate_score': row.get('discordance_score') or 0.0,
            'resource_shift_score': row.get('resource_shift_score_std') if row.get('resource_shift_score_std') is not None else None,
            'discordance_score': row.get('discordance_score'),
            'direction_class': row.get('main_driver') or '',
            'data_scope': 'precomputed_top_transformations',
            'source_modules': ['X1', 'X8'],
            'evidence_level': 'sequence-derived descriptive',
        }
        for row in rows[:80]
    ]
    x8_rows = sorted(x8_rows + shared_rows, key=lambda item: float(item.get('candidate_score') or 0), reverse=True)[:120]
    x4_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        residual_values = [
            _safe_num(row.get('protein_pi_residual')),
            _safe_num(row.get('protein_gravy_residual')),
            _safe_num(row.get('protein_instability_residual')),
        ]
        if not any(value is not None for value in residual_values):
            continue
        x4_rows.append({
            'canonical_gene_id': row.get('gene_id') or row.get('canonical_gene_id'),
            'gene_id': row.get('gene_id') or row.get('canonical_gene_id'),
            'gene_name': row.get('gene_name') or '',
            'transcript_id': row.get('transcript_id') or '',
            'protein_id': row.get('protein_id') or '',
            'transcript_protein_pi': row.get('transcript_protein_pi'),
            'observed_protein_pi': row.get('pI'),
            'protein_pi_residual': row.get('protein_pi_residual'),
            'transcript_protein_gravy': row.get('transcript_protein_gravy'),
            'observed_protein_gravy': row.get('gravy'),
            'protein_gravy_residual': row.get('protein_gravy_residual'),
            'transcript_protein_instability_index': row.get('transcript_protein_instability_index'),
            'observed_protein_instability_index': row.get('instability_index'),
            'protein_instability_residual': row.get('protein_instability_residual'),
            'candidate_score': round(
                abs(float(row.get('protein_pi_residual') or 0.0))
                + abs(float(row.get('protein_gravy_residual') or 0.0))
                + abs(float(row.get('protein_instability_residual') or 0.0) / 40.0),
                6,
            ),
            'data_scope': row.get('data_scope') or 'matched_predicted_observed_protein_properties',
            'source_modules': ['X4', 'X8'],
            'evidence_level': 'sequence-derived descriptive',
        })
    x4_rows = sorted(x4_rows, key=lambda item: float(item.get('candidate_score') or 0.0), reverse=True)[:80]

    def module(module_id: str, name: str, status: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        result = {'id': module_id, 'name': name, 'status': status, 'method': 'Precomputed from matched real feature rows; source limitations are explicit.'}
        if extra:
            result.update(extra)
        return result

    modules = [
        module('X0', 'Cross-omics data foundation', 'implemented' if int(join.get('matched_all_three') or 0) > 0 else 'partial', {
            'cards': join,
            'match_coverage_rows': [{'name': 'Genome rows', 'value': join.get('genome_rows') or 0}, {'name': 'Transcriptome rows', 'value': join.get('transcriptome_rows') or 0}, {'name': 'Proteome rows', 'value': join.get('proteome_rows') or 0}, {'name': 'Matched all three', 'value': join.get('matched_all_three') or 0}],
            'match_rate_rows': [{'name': 'G-T', 'value': join.get('match_rate_genome_transcriptome') or 0}, {'name': 'T-P', 'value': join.get('match_rate_transcriptome_proteome') or 0}, {'name': 'G-T-P', 'value': join.get('match_rate_all_three') or 0}],
        }),
        module('X1', 'DNA-RNA-Protein resource shift', 'implemented' if shifts_a and shifts_b else 'partial', {'shift_histograms': {'dna_to_rna_n_std': _histogram_payload(shifts_a, bins=42), 'rna_to_protein_n_std': _histogram_payload(shifts_b, bins=42)}, 'shift_stats': {'dna_to_rna_n_std': _distribution_stats(shifts_a), 'rna_to_protein_n_std': _distribution_stats(shifts_b)}, 'shift_scatter': _cross_scatter(rows, 'dna_to_rna_n_shift_std', 'rna_to_protein_n_shift_std'), 'legacy_shift_histograms': {'dna_to_rna_n_legacy_proxy': _histogram_payload(legacy_shifts_a, bins=42), 'rna_to_protein_n_legacy_proxy': _histogram_payload(legacy_shifts_b, bins=42)}, 'legacy_shift_stats': {'dna_to_rna_n_legacy_proxy': _distribution_stats(legacy_shifts_a), 'rna_to_protein_n_legacy_proxy': _distribution_stats(legacy_shifts_b)}, 'resource_shift_reference': resource_shift_reference, 'method': 'Primary X1 metric is dimensionless robust-z delta; raw cross-denominator differences are retained only as legacy_proxy fields.', 'method_version': 'resource_shift_robust_z_v2_2026_08_09', 'units': 'dimensionless robust-z delta', 'quadrants': _cross_quadrant_rows(rows), 'candidate_table': rows[:40]}),
        module('X2', 'Regulatory-to-transcript coupling', 'implemented' if _cross_scatter(rows, 'exon_gc_percent', 'transcript_gc') else 'partial', {'exon_transcript_gc_scatter': _cross_scatter(rows, 'exon_gc_percent', 'transcript_gc'), 'exon_transcript_gc_scatter_meta': {'source': 'precomputed matched transformations'}, 'residual_candidates': rows[:40]}),
        module('X3', 'Codon-to-protein translation strategy', 'implemented' if _cross_scatter(rows, 'transcript_gc', 'proteome_n_per_aa') else 'partial', {'gc_protein_n_scatter': _cross_scatter(rows, 'transcript_gc', 'proteome_n_per_aa'), 'gc_pi_scatter': _cross_scatter(rows, 'transcript_gc', 'pI'), 'gc_gravy_scatter': _cross_scatter(rows, 'transcript_gc', 'gravy'), 'discordance_candidates': rows[:40]}),
        module('X4', 'RNA-predicted protein vs observed proteome', 'implemented' if x4_rows else 'partial', {
            'candidate_table': x4_rows,
            'residual_scatter': _cross_scatter(rows, 'transcript_protein_pi', 'pI'),
            'gravy_residual_scatter': _cross_scatter(rows, 'transcript_protein_gravy', 'gravy'),
            'instability_residual_scatter': _cross_scatter(rows, 'transcript_protein_instability_index', 'instability_index'),
            'missing_fields': [] if x4_rows else ['transcript predicted protein property fields or observed proteome property fields are absent'],
        }),
        module('X5', 'Stoich island propagation', 'implemented' if shared_rows else 'partial', {'shared_outlier_counts': [{'name': key, 'value': value} for key, value in (shared.get('counts') or {}).items()] if isinstance(shared.get('counts'), dict) else [], 'candidate_table': shared_rows[:60]}),
        module('X6', 'Cross-omics feature coupling network', 'implemented' if x6_heatmap else 'partial', {'correlation_heatmap': x6_heatmap, 'edge_ranking': _cross_edge_rows(data)}),
        module('X7', 'Species-level cross-omics fingerprint', 'implemented' if species_rows and species_metrics else 'partial', {'fingerprint': {key: value for key, value in current_fingerprint.items() if key not in {'species_id', 'display_name'}}, 'species_fingerprint_rows': species_response_rows, 'species_fingerprint_meta': {'source_species_count': len(species_rows), 'returned_species_count': len(species_response_rows), 'downsampled': len(species_rows) > len(species_response_rows), 'policy': 'current_species_plus_even_species_sample'}, 'species_pca': cheap_species_projection(species_metrics), 'distance_matrix': _species_distance_heatmap(species_response_rows, species_metrics) if species_metrics else {'x_labels': [], 'y_labels': [], 'values': []}, 'feature_ranking': _fingerprint_feature_rank(species_rows)}),
        module('X8', 'Candidate workbench and export', 'implemented' if x8_rows else 'partial', {'candidate_table': x8_rows, 'score_components': [{'name': 'resource_shift_score', 'value': _mean([float(row.get('resource_shift_score') or 0) for row in x8_rows]) if x8_rows else 0.0}]}),
    ]
    return {
        'schema_version': 'cross_omics_module_suite.v2',
        'module_suite_version': 'integrated_x0_x8_precomputed_real_rows_v1',
        'scope': 'cross_omics_payload_plus_species_fingerprint',
        'row_count': len(rows),
        'matched_all_three': int(join.get('matched_all_three') or 0),
        'modules': modules,
        'quality_flags': {'data_scope': 'precomputed_top_transformations', 'top_transformations_only': True, 'matched_all_three': int(join.get('matched_all_three') or 0), 'evidence_level': 'sequence-derived descriptive / hypothesis-generating'},
        'export_tables': {
            'cross_omics_resource_shift.csv': rows,
            'cross_omics_predicted_observed_residuals.csv': x4_rows,
            'cross_omics_candidate_workbench.csv': x8_rows,
        },
        'method_metadata': {'method': 'cross-omics X0-X8 suite assembled from persisted real-row matched transformations, correlation matrix, shared outliers and species fingerprints', 'normalization': 'X1 primary visuals use dimensionless robust-z deltas; legacy raw cross-unit deltas are export-only context fields', 'resource_shift_reference': resource_shift_reference, 'missing_policy': 'fields not present in source tables remain partial/not implemented', 'evidence_level': 'sequence-derived descriptive / hypothesis-generating'},
    }


def _mapping_grade_from_layers(layer_count: int, conflict_count: int = 0) -> tuple[str, str]:
    if layer_count >= 3 and conflict_count == 0:
        return 'A', 'complete genome-transcript-protein evidence chain'
    if layer_count >= 3:
        return 'B', 'complete chain with mapping caveats'
    if layer_count == 2:
        return 'C', 'two-layer evidence chain'
    if layer_count == 1:
        return 'D', 'single-layer evidence only'
    return 'Fail', 'no mapped omics layer'


@lru_cache(maxsize=512)
def cross_omics_mapping_summary(species_id: str, entity_key: str = '') -> dict[str, Any]:
    join = {}
    try:
        payload = Species.objects.only('cross_omics_payload').get(species_id=species_id).cross_omics_payload or {}
        join = payload.get('join_summary') if isinstance(payload.get('join_summary'), dict) else {}
    except Exception:
        join = {}
    if not db_mode():
        try:
            payload = load_json(f'{species_id}/cross_omics.json')
            join = payload.get('join_summary') if isinstance(payload.get('join_summary'), dict) else join
        except Exception:
            pass
    if not db_mode() or not entity_key:
        return {
            'species_id': species_id,
            'entity_key': entity_key,
            'row_counts': {
                'genome': int(join.get('genome_rows') or 0),
                'transcriptome': int(join.get('transcriptome_rows') or 0),
                'proteome': int(join.get('proteome_rows') or 0),
            },
            'coverage': {
                'all_three': float(join.get('match_rate_all_three') or 0.0),
                'genome_transcriptome': float(join.get('match_rate_genome_transcriptome') or 0.0),
                'transcriptome_proteome': float(join.get('match_rate_transcriptome_proteome') or 0.0),
            },
            'matched_all_three': int(join.get('matched_all_three') or 0),
            'conflict_count': 0,
            'multi_mapping': {'multi_transcript_gene_count': 0, 'multi_protein_gene_count': 0},
            'method': 'join_summary fallback; entity-level conflict scan runs only inside Entity Report',
        }

    target_text = str(entity_key or '').strip()
    qs = (
        EntityRecord.objects
        .filter(species__species_id=species_id)
        .filter(
            Q(entity_id__iexact=target_text)
            | Q(canonical_gene_id__iexact=target_text)
            | Q(secondary_id__iexact=target_text)
            | Q(searchable_text__icontains=target_text)
        )
        .only('omics_type', 'entity_id', 'canonical_gene_id', 'secondary_id', 'payload_json')
    )
    omics_order = ('genome', 'transcriptome', 'proteome')
    per_gene: dict[str, dict[str, set[str]]] = defaultdict(lambda: {omics: set() for omics in omics_order})
    row_counts = {omics: 0 for omics in omics_order}
    conflict_count = 0
    target = target_text.lower()
    target_layers: set[str] = set()
    for rec in qs.iterator(chunk_size=5000):
        if rec.omics_type not in row_counts:
            continue
        row_counts[rec.omics_type] += 1
        payload = rec.payload_json or {}
        gene = str(rec.canonical_gene_id or payload.get('gene_id') or payload.get('ensembl_gene_id') or '').strip()
        if not gene:
            conflict_count += 1
            continue
        per_gene[gene][rec.omics_type].add(str(rec.entity_id or '').strip())
        aliases = {
            gene.lower(),
            str(rec.entity_id or '').strip().lower(),
            str(rec.secondary_id or '').strip().lower(),
            str(payload.get('gene_id') or '').strip().lower(),
            str(payload.get('ensembl_gene_id') or '').strip().lower(),
            str(payload.get('transcript_id') or '').strip().lower(),
            str(payload.get('protein_id') or '').strip().lower(),
        }
        if target and target in aliases:
            target_layers.add(rec.omics_type)
        payload_gene_values = {
            str(payload.get('gene_id') or '').strip(),
            str(payload.get('ensembl_gene_id') or '').strip(),
        }
        payload_gene_values = {value for value in payload_gene_values if value}
        if len({gene, *payload_gene_values}) > 1:
            conflict_count += 1

    genes_with_gt = sum(1 for layers in per_gene.values() if layers['genome'] and layers['transcriptome'])
    genes_with_tp = sum(1 for layers in per_gene.values() if layers['transcriptome'] and layers['proteome'])
    genes_with_all = sum(1 for layers in per_gene.values() if layers['genome'] and layers['transcriptome'] and layers['proteome'])
    gene_total = len(per_gene)
    multi_transcript = sum(1 for layers in per_gene.values() if len(layers['transcriptome']) > 1)
    multi_protein = sum(1 for layers in per_gene.values() if len(layers['proteome']) > 1)
    entity_grade, grade_reason = _mapping_grade_from_layers(len(target_layers), conflict_count=0)
    return {
        'species_id': species_id,
        'entity_key': entity_key,
        'row_counts': row_counts,
        'gene_count': gene_total,
        'matched_all_three': genes_with_all or int(join.get('matched_all_three') or 0),
        'coverage': {
            'all_three': float(join.get('match_rate_all_three') or (round(genes_with_all / gene_total, 6) if gene_total else 0.0)),
            'genome_transcriptome': float(join.get('match_rate_genome_transcriptome') or (round(genes_with_gt / gene_total, 6) if gene_total else 0.0)),
            'transcriptome_proteome': float(join.get('match_rate_transcriptome_proteome') or (round(genes_with_tp / gene_total, 6) if gene_total else 0.0)),
        },
        'conflict_count': int(conflict_count),
        'multi_mapping': {
            'multi_transcript_gene_count': int(multi_transcript),
            'multi_protein_gene_count': int(multi_protein),
        },
        'entity_layers': sorted(target_layers),
        'entity_evidence_grade': entity_grade,
        'entity_evidence_reason': grade_reason,
        'method': 'EntityReport-scoped EntityRecord canonical_gene_id join with payload gene_id / ensembl_gene_id consistency checks; species coverage comes from join_summary',
    }


def _light_cross_payload(species_id: str, payload: Any) -> dict[str, Any]:
    data = dict(payload or {}) if isinstance(payload, dict) else {}
    data.setdefault('species_id', species_id)
    data.setdefault('evidence_level', 'exploratory')
    top_rows = data.get('top_transformations') if isinstance(data.get('top_transformations'), list) else []
    if top_rows:
        light_top = [dict(row) for row in top_rows[:40] if isinstance(row, dict)]
        _attach_standardized_resource_shifts(light_top)
        data['top_transformations'] = light_top
        data['transformations'] = _build_transformations_from_rows(light_top[:24])
    else:
        data['top_transformations'] = []
        data['transformations'] = []
    if not isinstance(data.get('join_summary'), dict):
        data['join_summary'] = {}
    if not isinstance(data.get('mapping_summary'), dict):
        data['mapping_summary'] = {}
    data['compare_detail_mode'] = 'light'
    data['compare_detail_note'] = 'Compare light mode does not derive missing cross-omics modules, shared outliers or full module suite payloads.'
    return data


def _enhance_cross_payload(species_id: str, payload: Any) -> dict[str, Any]:
    data = dict(payload or {}) if isinstance(payload, dict) else {}
    data.setdefault('species_id', species_id)
    data.setdefault('evidence_level', 'exploratory')
    derived_payload: dict[str, Any] = {}
    existing_top = data.get('top_transformations') if isinstance(data.get('top_transformations'), list) else []
    existing_suite = data.get('cross_omics_module_suite') if isinstance(data.get('cross_omics_module_suite'), dict) else {}
    existing_suite_empty = not existing_suite or int(existing_suite.get('row_count') or 0) <= 0
    needs_predicted_observed = not any(
        isinstance(row, dict) and (
            _safe_num(row.get('transcript_protein_pi')) is not None
            or _safe_num(row.get('protein_pi_residual')) is not None
        )
        for row in existing_top[:25]
    )
    if not existing_top or existing_suite_empty or needs_predicted_observed:
        try:
            derived_payload = _derive_cross_payload_from_core_features(species_id)
        except Exception:
            derived_payload = {}
        if derived_payload.get('top_transformations'):
            for key, value in derived_payload.items():
                current = data.get(key)
                if key == 'precomputed_from_real_rows':
                    data[key] = bool(value)
                    continue
                if key == 'method_metadata' and isinstance(value, dict):
                    merged = dict(value)
                    if isinstance(current, dict):
                        merged.update(current)
                    data[key] = merged
                    continue
                if key == 'join_summary' and isinstance(value, dict):
                    if (
                        not isinstance(current, dict)
                        or not current
                        or int(current.get('matched_all_three') or 0) <= 0
                    ):
                        data[key] = value
                    continue
                if key == 'mapping_summary' and isinstance(value, dict):
                    current_matched = (
                        current.get('matched_all_three')
                        if isinstance(current, dict)
                        else 0
                    )
                    if not isinstance(current, dict) or not current or int(current_matched or 0) <= 0:
                        data[key] = value
                    continue
                if key in {'top_transformations', 'transformations'} and needs_predicted_observed:
                    data[key] = value
                    continue
                if current in (None, '', [], {}):
                    data[key] = value
            if existing_suite_empty or needs_predicted_observed:
                data.pop('cross_omics_module_suite', None)
    if 'join_summary' not in data:
        try:
            data['join_summary'] = _cross_join_summary(species_id)
        except Exception:
            data['join_summary'] = {}
    if 'mapping_summary' not in data:
        try:
            data['mapping_summary'] = cross_omics_mapping_summary(species_id)
        except Exception:
            data['mapping_summary'] = {
                'species_id': species_id,
                'conflict_count': 0,
                'coverage': {'all_three': (data.get('join_summary') or {}).get('match_rate_all_three') or 0.0},
                'method': 'mapping summary unavailable; using join_summary fallback',
            }

    if 'transformations' not in data:
        top_rows = data.get('top_transformations') or []
        data['transformations'] = _build_transformations_from_rows(top_rows if isinstance(top_rows, list) else [])
    if not isinstance(data.get('top_transformations'), list):
        data['top_transformations'] = []
    if not data['top_transformations'] and isinstance(data.get('transformations'), list):
        data['top_transformations'] = list(data['transformations'])[:24]

    if 'shared_outliers' not in data:
        try:
            data['shared_outliers'] = _build_shared_outliers(species_id)
        except Exception:
            data['shared_outliers'] = {
                'genome_only': [],
                'transcriptome_only': [],
                'proteome_only': [],
                'shared_all_three': [],
                'counts': {'genome_only': 0, 'transcriptome_only': 0, 'proteome_only': 0, 'shared_all_three': 0},
            }

    corr_matrices = data.get('correlation_matrices') if isinstance(data.get('correlation_matrices'), dict) else {}
    default_method = 'spearman' if 'spearman' in corr_matrices else (next(iter(corr_matrices.keys()), 'spearman'))
    corr_matrix = corr_matrices.get(default_method) if isinstance(corr_matrices.get(default_method), dict) else (data.get('correlation_matrix') or {})
    details = []
    keys = list(corr_matrix.keys()) if isinstance(corr_matrix, dict) else []
    n_matched = int((data.get('join_summary') or {}).get('matched_all_three') or 0)
    pvalues: list[float] = []
    for i, src in enumerate(keys):
        row = corr_matrix.get(src) if isinstance(corr_matrix.get(src), dict) else {}
        for dst in keys[i + 1:]:
            weight = _safe_num(row.get(dst))
            if weight is None:
                continue
            pval = _fisher_pvalue_from_r(float(weight), n_matched)
            pvalues.append(float(pval))
            details.append({
                'method': default_method,
                'feature_a': src,
                'feature_b': dst,
                'r': round(float(weight), 6),
                'n': n_matched,
                'p_value': round(float(pval), 8),
                'fdr': None,
            })
    fdr_values = _benjamini_hochberg_fdr(pvalues)
    for idx, fdr in enumerate(fdr_values):
        if idx < len(details):
            details[idx]['fdr'] = round(float(fdr), 8)
    existing_details = data.get('correlation_details')
    should_replace_details = (
        not isinstance(existing_details, list)
        or not existing_details
        or any(isinstance(item, dict) and item.get('p_value') is None for item in existing_details)
    )
    if should_replace_details:
        data['correlation_details'] = details
    method_meta = data.get('method_metadata')
    if not isinstance(method_meta, dict):
        method_meta = {}
    method_meta.setdefault('join_panel', {'method': 'gene_level_id_mapping', 'evidence_level': 'exploratory'})
    method_meta.setdefault('correlation', {'method': default_method, 'multiple_testing': 'benjamini_hochberg_fdr'})
    method_meta.setdefault('transformations', {'method': 'explicit_delta_and_discordance', 'direction': 'DNA_to_RNA_to_Protein'})
    method_meta.setdefault('shared_outliers', {'method': 'set_overlap_from_candidate_outliers'})
    method_meta.setdefault('statistical_caveats', {
        'sample_size': n_matched,
        'annotation_quality': 'depends on canonical gene_id / transcript_id / protein_id availability',
        'missingness': 'pairwise complete rows are used for correlations and module-specific plots',
        'phylogenetic_correlation': 'cross-species panels are descriptive unless stratified or adjusted upstream',
        'group_source': 'species metadata / uploaded labels when present',
    })
    data['method_metadata'] = method_meta
    if 'cross_omics_module_suite' not in data:
        try:
            data['cross_omics_module_suite'] = (
                _precomputed_cross_module_suite(species_id, data)
                if data.get('precomputed_from_real_rows')
                else _cross_omics_module_suite(species_id, data)
            )
        except Exception as exc:
            data['cross_omics_module_suite'] = {
                'scope': 'cross_omics_payload_plus_species_fingerprint',
                'row_count': 0,
                'matched_all_three': (data.get('join_summary') or {}).get('matched_all_three', 0),
                'modules': [],
                'error': str(exc),
                'method_metadata': {
                    'evidence_level': 'sequence-derived descriptive / hypothesis-generating',
                    'missing_policy': 'cross-omics suite could not be assembled for this payload',
                },
            }
    return data


@lru_cache(maxsize=256)
def get_cross_omics(species_id: str, compute: str = 'stored') -> dict[str, Any]:
    if db_mode():
        try:
            payload = Species.objects.only('cross_omics_payload').get(species_id=species_id).cross_omics_payload or {}
        except Species.DoesNotExist as exc:
            raise NotFoundError(f'Unknown species_id: {species_id}') from exc
        enhanced = _enhance_cross_payload(species_id, payload)
        if _normalize_compute_mode(compute) == 'complete_core':
            enhanced = build_complete_cross_omics_payload(species_id, enhanced)
        return _attach_known_chart_metadata(enhanced, species_id)
    if species_id not in file_species_map():
        raise NotFoundError(f'Unknown species_id: {species_id}')
    enhanced = _enhance_cross_payload(species_id, load_json(f'{species_id}/cross_omics.json'))
    if _normalize_compute_mode(compute) == 'complete_core':
        enhanced = build_complete_cross_omics_payload(species_id, enhanced)
    return _attach_known_chart_metadata(enhanced, species_id)


@lru_cache(maxsize=256)
def species_enhanced_visuals(species_id: str, compute: str = 'stored') -> dict[str, Any]:
    compute_mode = _normalize_compute_mode(compute)
    if not db_mode():
        cross = get_cross_omics(species_id, compute=compute_mode)
        shifts_a = [
            _safe_num(item.get('dna_to_rna_n_shift_std'))
            for item in (cross.get('top_transformations') or [])
            if _safe_num(item.get('dna_to_rna_n_shift_std')) is not None
        ]
        shifts_b = [
            _safe_num(item.get('rna_to_protein_n_shift_std'))
            for item in (cross.get('top_transformations') or [])
            if _safe_num(item.get('rna_to_protein_n_shift_std')) is not None
        ]
        return {
            'coordinate_profiles': {},
            'shift_histograms': {
                'dna_to_rna_n_std': _histogram_payload([float(v) for v in shifts_a]),
                'rna_to_protein_n_std': _histogram_payload([float(v) for v in shifts_b]),
            },
            'cluster_transition_links': [],
            'resource_budget_breakdown': [],
            'global_feature_rank': [],
        }

    if not Species.objects.filter(species_id=species_id).exists():
        raise NotFoundError(f'Unknown species_id: {species_id}')

    if compute_mode == 'complete_core':
        return _species_enhanced_visuals_complete_core(species_id)

    try:
        stored_cross = Species.objects.only('cross_omics_payload', 'fingerprint').get(species_id=species_id)
        stored_visuals = (stored_cross.cross_omics_payload or {}).get('enhanced_visuals')
    except Species.DoesNotExist:
        stored_cross = None
        stored_visuals = None
    if isinstance(stored_visuals, dict):
        data = dict(stored_visuals)
        coordinate_profiles = data.setdefault('coordinate_profiles', {})
        if not isinstance(coordinate_profiles, dict):
            coordinate_profiles = {}
            data['coordinate_profiles'] = coordinate_profiles
        try:
            genome_summary = get_summary(species_id, 'genome', scope='core')
            modules = (genome_summary.get('genome_module_suite') or {}).get('modules') or []
            module_map = {module.get('id'): module for module in modules if isinstance(module, dict)}
            g6_profile = (module_map.get('G6') or {}).get('coordinate_profile') or {}
            current_island = coordinate_profiles.get('genome_stoich_island') or {}
            if g6_profile.get('centers') and len(g6_profile.get('centers') or []) > len(current_island.get('centers') or []):
                coordinate_profiles['genome_stoich_island'] = g6_profile
            if not (coordinate_profiles.get('genome_gc_delta') or {}).get('centers'):
                delta_rows = _sample_feature_rows_from_csv(
                    species_id,
                    'genome',
                    ('start_1', 'promoter_exon_gc_delta', 'gc_delta_promoter_minus_exon'),
                    limit=1200,
                )
                delta_points = []
                for idx, row in enumerate(delta_rows):
                    x = _safe_num(row.get('start_1'))
                    y = _safe_num(row.get('promoter_exon_gc_delta'))
                    if y is None:
                        y = _safe_num(row.get('gc_delta_promoter_minus_exon'))
                    if y is not None:
                        delta_points.append((float(x if x is not None else idx), float(y)))
                if delta_points:
                    coordinate_profiles['genome_gc_delta'] = _binned_profile(delta_points, bins=48)
        except Exception:
            pass
        shift_histograms = data.setdefault('shift_histograms', {})
        if not isinstance(shift_histograms, dict):
            shift_histograms = {}
            data['shift_histograms'] = shift_histograms
        if not (shift_histograms.get('dna_to_rna_n_std') or {}).get('centers') or not (shift_histograms.get('rna_to_protein_n_std') or {}).get('centers'):
            try:
                cross = get_cross_omics(species_id)
                x1 = next(
                    (
                        module for module in ((cross.get('cross_omics_module_suite') or {}).get('modules') or [])
                        if isinstance(module, dict) and module.get('id') == 'X1'
                    ),
                    {},
                )
                module_histograms = x1.get('shift_histograms') if isinstance(x1.get('shift_histograms'), dict) else {}
                if module_histograms.get('dna_to_rna_n_std', {}).get('centers'):
                    shift_histograms['dna_to_rna_n_std'] = module_histograms['dna_to_rna_n_std']
                if module_histograms.get('rna_to_protein_n_std', {}).get('centers'):
                    shift_histograms['rna_to_protein_n_std'] = module_histograms['rna_to_protein_n_std']
            except Exception:
                pass
        current_fingerprint = stored_cross.fingerprint or {}
        rank_rows = []
        all_species = list(Species.objects.only('species_id', 'fingerprint'))
        for feature_key, feature_label in [
            ('genome_gc', 'Genome GC'),
            ('transcript_coupling', 'Transcript coupling'),
            ('proteome_n_per_aa', 'Proteome N/aa'),
            ('proteome_pi', 'Proteome pI'),
        ]:
            current_value = _safe_num(current_fingerprint.get(feature_key))
            if current_value is None:
                continue
            values = [(row.species_id, _safe_num((row.fingerprint or {}).get(feature_key))) for row in all_species]
            values = [(sid, value) for sid, value in values if value is not None]
            values.sort(key=lambda item: item[1], reverse=True)
            if not values:
                continue
            rank = next((idx + 1 for idx, item in enumerate(values) if item[0] == species_id), len(values))
            rank_rows.append({'feature': feature_key, 'label': feature_label, 'value': round(float(current_value), 6), 'rank': rank, 'total': len(values), 'percentile': round((len(values) - rank + 1) / len(values) * 100.0, 2)})
        data['global_feature_rank'] = rank_rows
        return data

    # Sample cap keeps response stable while still showing meaningful structure.
    sample_cap = 120000
    gene_map: dict[str, dict[str, Any]] = {}
    genome_profile_island: list[tuple[float, float]] = []
    genome_profile_delta: list[tuple[float, float]] = []

    def _scan_omics(omics_type: str) -> None:
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type=omics_type)
            .exclude(canonical_gene_id='')
            .values('canonical_gene_id', 'strategy_cluster', 'start_pos', 'numeric_summary', 'payload_json')[:sample_cap]
        )
        for row in qs.iterator(chunk_size=5000):
            gene_id = str(row.get('canonical_gene_id') or '').strip()
            if not gene_id:
                continue
            entry = gene_map.setdefault(gene_id, {})
            cluster_value = str(row.get('strategy_cluster') or '').strip()
            if omics_type == 'genome':
                if cluster_value:
                    entry['g_cluster'] = cluster_value
                n_value = _value_from_row_payload(row, 'exon_atoms_N_per_base')
                if n_value is not None:
                    entry['g_n'] = n_value
                start_value = _safe_num(row.get('start_pos'))
                if start_value is None:
                    start_value = _value_from_row_payload(row, 'start_1')
                island_score = _value_from_row_payload(row, 'stoich_island_score')
                delta_score = _value_from_row_payload(row, 'gc_delta_promoter_minus_exon')
                if delta_score is None:
                    delta_score = _value_from_row_payload(row, 'promoter_exon_gc_delta')
                if start_value is not None and island_score is not None:
                    genome_profile_island.append((start_value, island_score))
                if start_value is not None and delta_score is not None:
                    genome_profile_delta.append((start_value, delta_score))
            elif omics_type == 'transcriptome':
                if cluster_value:
                    entry['t_cluster'] = cluster_value
                n_value = _value_from_row_payload(row, 'atoms_per_nt_N')
                if n_value is not None:
                    entry['t_n'] = n_value
            elif omics_type == 'proteome':
                if cluster_value:
                    entry['p_cluster'] = cluster_value
                n_value = _value_from_row_payload(row, 'N_atoms_per_aa')
                if n_value is not None:
                    entry['p_n'] = n_value

    _scan_omics('genome')
    _scan_omics('transcriptome')
    _scan_omics('proteome')

    # The model-organism release deliberately keeps the large feature tables
    # as registered CSV sources instead of duplicating every row into
    # EntityRecord.  Use the precomputed payloads as the authoritative
    # fallback for overview visuals when the optional entity index is empty.
    if not gene_map:
        cross = get_cross_omics(species_id)
        transformations = [item for item in (cross.get('top_transformations') or cross.get('transformations') or []) if isinstance(item, dict)]
        shift_dna_rna = [
            float(value) for value in (_safe_num(item.get('dna_to_rna_n_shift_std')) for item in transformations)
            if value is not None
        ]
        shift_rna_protein = [
            float(value) for value in (_safe_num(item.get('rna_to_protein_n_shift_std')) for item in transformations)
            if value is not None
        ]

        coordinate_island: list[tuple[float, float]] = []
        coordinate_delta: list[tuple[float, float]] = []
        try:
            genome_analysis = get_analysis(species_id, 'genome', scope='core')
            for item in genome_analysis.get('stoich_islands') or []:
                start = _safe_num(item.get('start'))
                score = _safe_num(item.get('mean_island_score'))
                if start is not None and score is not None:
                    coordinate_island.append((float(start), float(score)))
            genome_summary = get_summary(species_id, 'genome', scope='core')
            for points in (genome_summary.get('scatter') or {}).values():
                for item in points if isinstance(points, list) else []:
                    exon = _safe_num(item.get('exon_gc_percent'))
                    promoter = _safe_num(item.get('promoter_gc_percent'))
                    if exon is not None and promoter is not None:
                        coordinate_delta.append((float(len(coordinate_delta)), float(promoter - exon)))
        except Exception:
            coordinate_island = []
            coordinate_delta = []

        try:
            resource_budget = list((get_analysis(species_id, 'proteome', scope='core').get('resource_budget') or []))
        except Exception:
            resource_budget = []
        if not resource_budget:
            resource_budget = [
                {'feature': 'shift_dna_to_rna_n_std', 'mean': _distribution_stats(shift_dna_rna).get('mean', 0.0)},
                {'feature': 'shift_rna_to_protein_n_std', 'mean': _distribution_stats(shift_rna_protein).get('mean', 0.0)},
            ]

        species_obj = Species.objects.only('species_id', 'fingerprint').get(species_id=species_id)
        all_species = list(Species.objects.only('species_id', 'fingerprint'))
        global_rank_rows = []
        for feature_key, feature_label in [
            ('genome_gc', 'Genome GC'),
            ('transcript_coupling', 'Transcript coupling'),
            ('proteome_n_per_aa', 'Proteome N/aa'),
            ('proteome_pi', 'Proteome pI'),
        ]:
            current_value = _safe_num((species_obj.fingerprint or {}).get(feature_key))
            if current_value is None:
                continue
            values = [
                (row.species_id, _safe_num((row.fingerprint or {}).get(feature_key)))
                for row in all_species
            ]
            values = [(sid, value) for sid, value in values if value is not None]
            values.sort(key=lambda item: item[1], reverse=True)
            if not values:
                continue
            rank = next((idx + 1 for idx, item in enumerate(values) if item[0] == species_id), len(values))
            global_rank_rows.append({
                'feature': feature_key,
                'label': feature_label,
                'value': round(float(current_value), 6),
                'rank': rank,
                'total': len(values),
                'percentile': round((len(values) - rank + 1) / len(values) * 100.0, 2),
            })

        return {
            'coordinate_profiles': {
                'genome_stoich_island': _binned_profile(coordinate_island, bins=48),
                'genome_gc_delta': _binned_profile(coordinate_delta, bins=48),
            },
            'shift_histograms': {
                'dna_to_rna_n_std': _histogram_payload(shift_dna_rna, bins=42),
                'rna_to_protein_n_std': _histogram_payload(shift_rna_protein, bins=42),
            },
            'shift_stats': {
                'dna_to_rna_n_std': _distribution_stats(shift_dna_rna),
                'rna_to_protein_n_std': _distribution_stats(shift_rna_protein),
            },
            'cluster_transition_links': list(cross.get('cluster_transition_links') or []),
            'resource_budget_breakdown': resource_budget,
            'global_feature_rank': global_rank_rows,
            'paired_gene_count': int((cross.get('join_summary') or {}).get('matched_all_three') or 0),
            'data_source': 'precomputed_real_feature_payloads',
            'entity_index_fallback': True,
        }

    resource_rows = []
    for gene_id, values in gene_map.items():
        resource_rows.append({
            'gene_id': gene_id,
            'genome_n_per_base': values.get('g_n'),
            'transcript_n_per_nt': values.get('t_n'),
            'proteome_n_per_aa': values.get('p_n'),
            'dna_to_rna_n_shift': (values.get('t_n') - values.get('g_n')) if _safe_num(values.get('g_n')) is not None and _safe_num(values.get('t_n')) is not None else None,
            'rna_to_protein_n_shift': (values.get('p_n') - values.get('t_n')) if _safe_num(values.get('t_n')) is not None and _safe_num(values.get('p_n')) is not None else None,
        })
    resource_shift_reference = _attach_standardized_resource_shifts(resource_rows) if resource_rows else {'usable': False, 'reference_n': 0}
    resource_by_gene = {row.get('gene_id'): row for row in resource_rows}
    shift_dna_rna: list[float] = [float(v) for v in (_safe_num(row.get('dna_to_rna_n_shift_std')) for row in resource_rows) if v is not None]
    shift_rna_protein: list[float] = [float(v) for v in (_safe_num(row.get('rna_to_protein_n_shift_std')) for row in resource_rows) if v is not None]
    transition_g_t: defaultdict[tuple[str, str], int] = defaultdict(int)
    transition_t_p: defaultdict[tuple[str, str], int] = defaultdict(int)
    for gene_id, values in gene_map.items():
        g_cluster = str(values.get('g_cluster') or '').strip()
        t_cluster = str(values.get('t_cluster') or '').strip()
        p_cluster = str(values.get('p_cluster') or '').strip()
        if g_cluster and t_cluster:
            transition_g_t[(g_cluster, t_cluster)] += 1
        if t_cluster and p_cluster:
            transition_t_p[(t_cluster, p_cluster)] += 1

    transition_links = []
    for (source, target), count in sorted(transition_g_t.items(), key=lambda item: item[1], reverse=True)[:20]:
        transition_links.append({
            'source': f'Genome:{source}',
            'target': f'Transcriptome:{target}',
            'value': int(count),
            'transition': 'genome_to_transcriptome',
        })
    for (source, target), count in sorted(transition_t_p.items(), key=lambda item: item[1], reverse=True)[:20]:
        transition_links.append({
            'source': f'Transcriptome:{source}',
            'target': f'Proteome:{target}',
            'value': int(count),
            'transition': 'transcriptome_to_proteome',
        })

    resource_budget = []
    try:
        proteome_analysis = get_analysis(species_id, 'proteome')
        resource_budget = list(proteome_analysis.get('resource_budget') or [])
    except Exception:
        resource_budget = []
    if not resource_budget:
        resource_budget = [
            {'feature': 'N_atoms_per_aa', 'mean': _distribution_stats([v for v in (values.get('p_n') for values in gene_map.values()) if _safe_num(v) is not None]).get('mean', 0.0)},
            {'feature': 'shift_dna_to_rna_n_std', 'mean': _distribution_stats(shift_dna_rna).get('mean', 0.0)},
            {'feature': 'shift_rna_to_protein_n_std', 'mean': _distribution_stats(shift_rna_protein).get('mean', 0.0)},
        ]

    global_rank_rows = []
    rank_features = [
        ('genome_gc', 'Genome GC'),
        ('transcript_coupling', 'Transcript coupling'),
        ('proteome_n_per_aa', 'Proteome N/aa'),
        ('proteome_pi', 'Proteome pI'),
    ]
    species_obj = Species.objects.only('species_id', 'fingerprint').get(species_id=species_id)
    all_species = list(Species.objects.only('species_id', 'fingerprint'))
    for feature_key, feature_label in rank_features:
        current_value = _safe_num((species_obj.fingerprint or {}).get(feature_key))
        if current_value is None:
            continue
        values = [
            (row.species_id, _safe_num((row.fingerprint or {}).get(feature_key)))
            for row in all_species
        ]
        values = [(sid, val) for sid, val in values if val is not None]
        values.sort(key=lambda item: item[1], reverse=True)
        if not values:
            continue
        rank = next((idx + 1 for idx, item in enumerate(values) if item[0] == species_id), len(values))
        global_rank_rows.append({
            'feature': feature_key,
            'label': feature_label,
            'value': round(current_value, 6),
            'rank': rank,
            'total': len(values),
            'percentile': round((len(values) - rank + 1) / len(values) * 100.0, 2),
        })

    return {
        'coordinate_profiles': {
            'genome_stoich_island': _binned_profile(genome_profile_island, bins=48),
            'genome_gc_delta': _binned_profile(genome_profile_delta, bins=48),
        },
        'shift_histograms': {
            'dna_to_rna_n_std': _histogram_payload(shift_dna_rna, bins=42),
            'rna_to_protein_n_std': _histogram_payload(shift_rna_protein, bins=42),
        },
        'shift_stats': {
            'dna_to_rna_n_std': _distribution_stats(shift_dna_rna),
            'rna_to_protein_n_std': _distribution_stats(shift_rna_protein),
        },
        'cluster_transition_links': transition_links,
        'resource_budget_breakdown': resource_budget,
        'global_feature_rank': global_rank_rows,
        'paired_gene_count': len(gene_map),
        'resource_shift_reference': resource_shift_reference,
    }


def _species_enhanced_visuals_complete_core(species_id: str) -> dict[str, Any]:
    cross = get_cross_omics(species_id, compute='complete_core')
    cross_modules = {
        module.get('id'): module
        for module in ((cross.get('cross_omics_module_suite') or {}).get('modules') or [])
        if isinstance(module, dict) and module.get('id')
    }
    x1 = cross_modules.get('X1') or {}
    shift_histograms = x1.get('shift_histograms') if isinstance(x1.get('shift_histograms'), dict) else {}

    coordinate_profiles: dict[str, Any] = {}
    try:
        genome_summary = get_summary(species_id, 'genome', scope='core', compute='complete_core')
        genome_modules = {
            module.get('id'): module
            for module in ((genome_summary.get('genome_module_suite') or {}).get('modules') or [])
            if isinstance(module, dict) and module.get('id')
        }
        g6_profile = (genome_modules.get('G6') or {}).get('coordinate_profile') or {}
        g2_profile = (genome_modules.get('G2') or {}).get('coordinate_profile') or {}
        if g6_profile.get('centers'):
            coordinate_profiles['genome_stoich_island'] = g6_profile
        if g2_profile.get('centers'):
            coordinate_profiles['genome_gc_delta'] = g2_profile
    except Exception:
        coordinate_profiles = {}

    resource_budget = []
    try:
        resource_budget = list(get_analysis(species_id, 'proteome', scope='core', compute='complete_core').get('resource_budget') or [])
    except Exception:
        resource_budget = []

    x7 = cross_modules.get('X7') or {}
    feature_rank = x7.get('feature_ranking') if isinstance(x7.get('feature_ranking'), list) else []
    global_feature_rank = []
    for row in feature_rank:
        if not isinstance(row, dict) or _safe_num(row.get('value')) is None:
            continue
        feature = str(row.get('feature') or row.get('key') or '').strip()
        global_feature_rank.append({
            'feature': feature,
            'label': feature.replace('_', ' ').title(),
            'value': row.get('value'),
            'rank': None,
            'total': None,
            'percentile': None,
            'scope': 'current_species_complete_core',
        })

    return {
        'coordinate_profiles': coordinate_profiles,
        'shift_histograms': {
            'dna_to_rna_n_std': shift_histograms.get('dna_to_rna_n_std') or {'centers': [], 'counts': []},
            'rna_to_protein_n_std': shift_histograms.get('rna_to_protein_n_std') or {'centers': [], 'counts': []},
        },
        'cluster_transition_links': list(cross.get('cluster_transition_links') or []),
        'resource_budget_breakdown': resource_budget,
        'global_feature_rank': global_feature_rank,
        'paired_gene_count': int((cross.get('join_summary') or {}).get('matched_all_three') or 0),
        'data_source': 'complete_core_csv_pipeline',
        'compute_mode': 'complete_core',
        'result_view': 'complete_core',
        'method_metadata': {
            'source': 'complete_core_csv_pipeline',
            'cross_source': (cross.get('method_metadata') or {}).get('complete_core_v2') or {},
            'fallback_policy': 'stored enhanced_visuals are not used in complete_core mode',
        },
    }


def _record_to_row(record: EntityRecord) -> dict[str, Any]:
    payload = dict(record.payload_json or {})
    payload.setdefault('entity_id', record.entity_id)
    return payload


def _legacy_row_listing(species_id: str, omics: str, *, query: str = '', strategy_cluster: str = '', sort_by: str = '', sort_order: str = 'desc', page: int = 1, page_size: int = 25, feature_filters: str = '') -> dict[str, Any]:
    validate_omics(omics)
    meta = omics_meta()[omics]
    if db_mode():
        qs = EntityRecord.objects.select_related('dataset', 'species').filter(species__species_id=species_id, omics_type=omics)
        if query:
            q = query.strip()
            qs = qs.filter(
                Q(entity_id__icontains=q) |
                Q(canonical_gene_id__icontains=q) |
                Q(gene_name__icontains=q) |
                Q(description__icontains=q) |
                Q(searchable_text__icontains=q)
            )
        if strategy_cluster:
            qs = qs.filter(strategy_cluster__iexact=strategy_cluster)
        records = list(qs)
        records = _apply_row_feature_filters(records, feature_filters)
        if sort_by:
            records.sort(key=lambda r: _sort_record_value(r, sort_by), reverse=(sort_order != 'asc'))
        total = len(records)
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 5000)
        start = (page - 1) * page_size
        end = start + page_size
        rows = [_record_to_row(r) for r in records[start:end]]
        clusters = sorted({r.strategy_cluster for r in EntityRecord.objects.filter(species__species_id=species_id, omics_type=omics) if r.strategy_cluster})
        feature_options = list(dict.fromkeys((meta.get('feature_options') or [])))
        return {
            'page': page,
            'page_size': page_size,
            'total': total,
            'columns': meta.get('browse_columns') or [],
            'rows': rows,
            'strategy_clusters': clusters,
            'feature_options': feature_options,
        }

    rows = list(load_json(f'{species_id}/{omics}/rows.json'))
    id_col = meta['primary_id']
    if query:
        q = query.lower().strip()
        rows = [
            r for r in rows
            if q in str(r.get(id_col, '')).lower()
            or q in str(r.get('gene_name', '')).lower()
            or q in str(r.get('description', '')).lower()
        ]
    if strategy_cluster:
        rows = [r for r in rows if str(r.get('strategy_cluster', '')).lower() == strategy_cluster.lower()]
    if sort_by:
        rows.sort(key=lambda r: (r.get(sort_by) is None, r.get(sort_by)), reverse=(sort_order != 'asc'))
    total = len(rows)
    page = max(int(page), 1)
    page_size = min(max(int(page_size), 1), 5000)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        'page': page,
        'page_size': page_size,
        'total': total,
        'columns': meta.get('browse_columns') or [],
        'rows': rows[start:end],
        'strategy_clusters': sorted({r.get('strategy_cluster') for r in load_json(f'{species_id}/{omics}/rows.json') if r.get('strategy_cluster')}),
        'feature_options': meta.get('feature_options') or [],
    }


def _apply_row_feature_filters(records: list[EntityRecord], feature_filters: str) -> list[EntityRecord]:
    if not feature_filters:
        return records
    try:
        parsed = json.loads(feature_filters)
    except Exception:
        return records
    if isinstance(parsed, dict):
        parsed = [parsed]
    output = records
    for item in parsed:
        key = item.get('key')
        if not key:
            continue
        min_v = _safe_num(item.get('min'))
        max_v = _safe_num(item.get('max'))
        text_v = str(item.get('value', '')).strip()
        next_records = []
        for rec in output:
            value = rec.payload_json.get(key)
            num = _safe_num(value)
            if text_v:
                if text_v.lower() not in str(value).lower():
                    continue
            if min_v is not None and (num is None or num < min_v):
                continue
            if max_v is not None and (num is None or num > max_v):
                continue
            next_records.append(rec)
        output = next_records
    return output


def _sort_record_value(record: EntityRecord, key: str) -> Any:
    payload = record.payload_json or {}
    value = payload.get(key)
    num = _safe_num(value)
    return num if num is not None else str(value or '')


def row_detail(species_id: str, omics: str, entity_id: str, scope: str = 'core') -> dict[str, Any]:
    active_scope = _normalize_scope(scope)
    validate_omics(omics)
    meta = omics_meta()[omics]
    if db_mode():
        try:
            rec = EntityRecord.objects.get(species__species_id=species_id, omics_type=omics, entity_id=entity_id)
        except EntityRecord.DoesNotExist:
            rec = EntityRecord.objects.filter(species__species_id=species_id, omics_type=omics, canonical_gene_id=entity_id).first()
            if not rec:
                rows = _csv_rows_for_db_scope(species_id, omics, active_scope)
                id_col = meta['primary_id']
                row = next((r for r in rows if str(r.get(id_col)) == entity_id or str(r.get('entity_id')) == entity_id), None)
                if not row:
                    raise NotFoundError(f'Unknown entity for {omics}: {entity_id}')
                return {'species_id': species_id, 'omics': omics, 'scope': active_scope, 'row': row, 'linked_entities': {}}
        gene_id = rec.canonical_gene_id or (rec.payload_json or {}).get('gene_id') or (rec.payload_json or {}).get('ensembl_gene_id')
        linked = {}
        if gene_id:
            for other in EntityRecord.objects.filter(species__species_id=species_id, canonical_gene_id=gene_id).exclude(omics_type=omics):
                linked[other.omics_type] = {
                    'entity_id': other.entity_id,
                    'gene_name': other.gene_name,
                }
        return {'species_id': species_id, 'omics': omics, 'scope': active_scope, 'row': _record_to_row(rec), 'linked_entities': linked}

    rows = _file_rows_for_scope(species_id, omics, active_scope)
    id_col = meta['primary_id']
    row = next((r for r in rows if str(r.get(id_col)) == entity_id or str(r.get('entity_id')) == entity_id), None)
    if not row:
        raise NotFoundError(f'Unknown entity for {omics}: {entity_id}')
    gene_id = row.get('gene_id') or row.get('ensembl_gene_id')
    linked = {}
    if gene_id:
        for other_omics in omics_meta().keys():
            other_rows = _file_rows_for_scope(species_id, other_omics, active_scope)
            other_match = next((r for r in other_rows if r.get('gene_id') == gene_id or r.get('ensembl_gene_id') == gene_id), None)
            if other_match:
                linked[other_omics] = {'entity_id': other_match.get(omics_meta()[other_omics]['primary_id']) or other_match.get('entity_id'), 'gene_name': other_match.get('gene_name')}
    return {'species_id': species_id, 'omics': omics, 'scope': active_scope, 'row': row, 'linked_entities': linked}


def _metric_panel_for_omics(omics: str = '') -> list[str]:
    mapping = {
        'genome': ['genome_gc', 'promoter_gc', 'genome_n_per_base'],
        'transcriptome': ['transcript_gc', 'transcript_entropy', 'transcript_coupling'],
        'proteome': ['proteome_n_per_aa', 'proteome_s_per_aa', 'proteome_pi', 'proteome_gravy'],
    }
    if omics in mapping:
        return mapping[omics]
    return [
        'genome_gc',
        'promoter_gc',
        'genome_n_per_base',
        'transcript_gc',
        'transcript_entropy',
        'transcript_coupling',
        'proteome_n_per_aa',
        'proteome_s_per_aa',
        'proteome_pi',
        'proteome_gravy',
    ]


def _extract_compare_metrics(rows: list[dict[str, Any]], omics: str = '') -> list[str]:
    candidate_metrics = _metric_panel_for_omics(omics)
    metrics = [
        metric
        for metric in candidate_metrics
        if any(_safe_num(row.get(metric)) is not None for row in rows)
    ]
    if metrics:
        return metrics
    return sorted({
        key
        for row in rows
        for key, value in row.items()
        if key not in {'species_id', 'display_name', 'source_context', 'domain', 'clade', 'habitat'} and _safe_num(value) is not None
    })


def _normalize_fingerprints(rows: list[dict[str, Any]], metrics: list[str], mode: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mode = str(mode or 'raw').strip().lower()
    if mode not in {'raw', 'zscore', 'robust_zscore'}:
        mode = 'raw'

    stats: dict[str, dict[str, float]] = {}
    for metric in metrics:
        values = [_safe_num(row.get(metric)) for row in rows]
        clean = [float(v) for v in values if v is not None]
        if not clean:
            stats[metric] = {'center': 0.0, 'scale': 1.0, 'mean': 0.0, 'std': 1.0, 'median': 0.0, 'mad': 1.0}
            continue
        mean = float(sum(clean) / len(clean))
        variance = float(sum((value - mean) ** 2 for value in clean) / max(1, len(clean)))
        std = float(math.sqrt(max(variance, 0.0)))
        ordered = sorted(clean)
        median = float(_percentile(ordered, 0.5))
        abs_dev = sorted([abs(value - median) for value in clean])
        mad = float(_percentile(abs_dev, 0.5))
        scale = 1.0
        center = 0.0
        if mode == 'raw':
            center = 0.0
            scale = 1.0
        elif mode == 'zscore':
            center = mean
            scale = std if std > 0 else 1.0
        else:
            center = median
            robust_scale = 1.4826 * mad
            scale = robust_scale if robust_scale > 0 else (std if std > 0 else 1.0)
        stats[metric] = {
            'center': float(center),
            'scale': float(scale),
            'mean': mean,
            'std': std if std > 0 else 1.0,
            'median': median,
            'mad': mad if mad > 0 else 1.0,
        }

    normalized: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for metric in metrics:
            raw = _safe_num(row.get(metric))
            if raw is None:
                item[metric] = None
                continue
            center = stats.get(metric, {}).get('center', 0.0)
            scale = stats.get(metric, {}).get('scale', 1.0) or 1.0
            item[metric] = round((float(raw) - float(center)) / float(scale), 6) if mode != 'raw' else round(float(raw), 6)
        normalized.append(item)
    return normalized, {
        'mode': mode,
        'stats': stats,
        'notes': 'raw values are preserved separately; chart and distance payloads follow selected normalization mode.',
    }


def _vector_distance(a: list[float], b: list[float], method: str) -> float:
    if not a or not b:
        return 0.0
    method = str(method or 'euclidean').strip().lower()
    if method not in {'euclidean', 'cosine', 'correlation'}:
        method = 'euclidean'
    if method == 'euclidean':
        return float(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))))
    if method == 'cosine':
        dot = float(sum(x * y for x, y in zip(a, b)))
        norm_a = float(math.sqrt(sum(x * x for x in a)))
        norm_b = float(math.sqrt(sum(y * y for y in b)))
        if norm_a <= 0 or norm_b <= 0:
            return 0.0
        cosine = dot / (norm_a * norm_b)
        return float(max(0.0, min(2.0, 1.0 - cosine)))
    # correlation distance
    if len(a) < 2:
        return 0.0
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    den_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
    den_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))
    if den_a <= 0 or den_b <= 0:
        return 0.0
    corr = num / (den_a * den_b)
    return float(max(0.0, min(2.0, 1.0 - corr)))


def _pairwise_distances(rows: list[dict[str, Any]], metrics: list[str], method: str) -> list[dict[str, Any]]:
    output = []
    for idx, src in enumerate(rows):
        for dst in rows[idx + 1:]:
            shared = []
            for metric in metrics:
                a = _safe_num(src.get(metric))
                b = _safe_num(dst.get(metric))
                if a is None or b is None:
                    continue
                shared.append((float(a), float(b)))
            if not shared:
                value = 0.0
                n_used = 0
            else:
                left = [x for x, _ in shared]
                right = [y for _, y in shared]
                value = _vector_distance(left, right, method)
                n_used = len(shared)
            output.append({
                'source': str(src.get('species_id', '')),
                'target': str(dst.get('species_id', '')),
                'distance': round(float(value), 6),
                'n_features': n_used,
                'method': method,
            })
    return output


def _ordination_payload(rows: list[dict[str, Any]], metrics: list[str], group_by: str = '', include_umap: bool = True) -> dict[str, Any]:
    if not rows or not metrics:
        return {
            'method': 'pca_svd',
            'points': [],
            'explained_variance_ratio': [0.0, 0.0],
            'umap': {'method': 'umap', 'points': [], 'params': {}, 'available': False, 'fallback_reason': 'no_rows_or_metrics'},
        }
    matrix = []
    for row in rows:
        vector = []
        for metric in metrics:
            value = _safe_num(row.get(metric))
            vector.append(float(value) if value is not None else 0.0)
        matrix.append(vector)
    if np is None or len(rows) < 2:
        points = []
        x_metric = metrics[0]
        y_metric = metrics[1] if len(metrics) > 1 else metrics[0]
        for row in rows:
            points.append({
                'species_id': row.get('species_id'),
                'display_name': row.get('display_name'),
                'x': _safe_num(row.get(x_metric)) or 0.0,
                'y': _safe_num(row.get(y_metric)) or 0.0,
                'group': row.get(group_by) if group_by else '',
            })
        return {
            'method': 'metric_projection',
            'x_metric': x_metric,
            'y_metric': y_metric,
            'points': points,
            'explained_variance_ratio': [0.0, 0.0],
            'umap': {'method': 'umap', 'points': [], 'params': {}, 'available': False, 'fallback_reason': 'numpy_unavailable_or_too_few_rows'},
        }

    arr = np.asarray(matrix, dtype=float)
    arr = arr - np.mean(arr, axis=0, keepdims=True)
    umap_payload = _umap_payload(
        arr,
        rows,
        x_key='x',
        y_key='y',
        row_keys=('species_id', 'display_name'),
        extra_keys=[group_by] if group_by else [],
    ) if include_umap and _interactive_umap_enabled() else {'method': 'umap', 'points': [], 'params': {}, 'available': False, 'fallback_reason': 'interactive_umap_disabled_by_default' if include_umap else 'disabled_for_compare_light_mode'}
    try:
        u, s, _ = np.linalg.svd(arr, full_matrices=False)
    except Exception:
        return {'method': 'pca_svd', 'points': [], 'explained_variance_ratio': [0.0, 0.0], 'umap': umap_payload}

    coords = u[:, :2] * s[:2]
    var = (s ** 2)
    total = float(np.sum(var)) if len(var) else 0.0
    explained = [float(var[i] / total) if total > 0 and i < len(var) else 0.0 for i in range(2)]
    points = []
    for idx, row in enumerate(rows):
        points.append({
            'species_id': row.get('species_id'),
            'display_name': row.get('display_name'),
            'x': round(float(coords[idx, 0]), 6) if coords.shape[1] >= 1 else 0.0,
            'y': round(float(coords[idx, 1]), 6) if coords.shape[1] >= 2 else 0.0,
            'group': row.get(group_by) if group_by else '',
        })
    return {'method': 'pca_svd', 'points': points, 'explained_variance_ratio': explained, 'umap': umap_payload}


def _umap_payload(
    matrix: Any,
    rows: list[dict[str, Any]],
    x_key: str,
    y_key: str,
    row_keys: tuple[str, ...],
    extra_keys: list[str] | None = None,
) -> dict[str, Any]:
    extra_keys = extra_keys or []
    params = {
        'n_components': 2,
        'metric': 'euclidean',
        'random_state': 42,
        'min_dist': 0.15,
        'init': 'random',
    }
    umap_module = _optional_umap()
    if umap_module is None or np is None:
        return {'method': 'umap', 'points': [], 'params': params, 'available': False, 'fallback_reason': 'umap_dependency_unavailable'}
    try:
        arr = np.asarray(matrix, dtype=float)
    except Exception:
        return {'method': 'umap', 'points': [], 'params': params, 'available': False, 'fallback_reason': 'matrix_cast_failed'}
    if arr.ndim != 2 or arr.shape[0] < 3 or arr.shape[1] < 2:
        return {'method': 'umap', 'points': [], 'params': params, 'available': False, 'fallback_reason': 'insufficient_rows_or_features'}
    params['n_neighbors'] = max(2, min(15, arr.shape[0] - 1))
    try:
        reducer = umap_module.UMAP(
            n_components=2,
            n_neighbors=params['n_neighbors'],
            min_dist=params['min_dist'],
            metric=params['metric'],
            random_state=params['random_state'],
            init=params['init'],
            n_jobs=1,
            low_memory=True,
        )
        coords = reducer.fit_transform(arr)
    except Exception as exc:
        return {'method': 'umap', 'points': [], 'params': params, 'available': False, 'fallback_reason': str(exc)}

    points = []
    for idx, row in enumerate(rows):
        payload = {
            x_key: round(float(coords[idx, 0]), 6),
            y_key: round(float(coords[idx, 1]), 6),
        }
        for key in row_keys:
            payload[key] = row.get(key)
        for key in extra_keys:
            if key:
                payload[key] = row.get(key)
        points.append(payload)
    return {'method': 'umap', 'points': points, 'params': params, 'available': True}


def _kmeans_cluster_labels(rows: list[dict[str, Any]], metrics: list[str], k: int = 3) -> list[dict[str, Any]]:
    if not rows or not metrics:
        return []
    vectors: list[list[float]] = []
    for row in rows:
        vectors.append([float(_safe_num(row.get(metric)) or 0.0) for metric in metrics])
    n = len(vectors)
    if n == 0:
        return []
    k = max(1, min(int(k or 1), n))
    if k == 1:
        return [{
            'species_id': row.get('species_id'),
            'display_name': row.get('display_name'),
            'cluster': 'cluster_1',
        } for row in rows]

    # Deterministic seeds: evenly spaced rows.
    seed_indices = [int(round(i * (n - 1) / max(1, k - 1))) for i in range(k)]
    centroids = [vectors[idx][:] for idx in seed_indices]
    labels = [0] * n

    for _ in range(12):
        updated = False
        for i, vec in enumerate(vectors):
            best_j = 0
            best_dist = None
            for j, center in enumerate(centroids):
                dist = sum((a - b) ** 2 for a, b in zip(vec, center))
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_j = j
            if labels[i] != best_j:
                labels[i] = best_j
                updated = True

        next_centroids: list[list[float]] = []
        for j in range(k):
            member_indices = [idx for idx, label in enumerate(labels) if label == j]
            if not member_indices:
                next_centroids.append(centroids[j])
                continue
            cols = len(metrics)
            center = []
            for col_idx in range(cols):
                values = [vectors[idx][col_idx] for idx in member_indices]
                center.append(sum(values) / len(values))
            next_centroids.append(center)
        centroids = next_centroids
        if not updated:
            break

    return [{
        'species_id': rows[idx].get('species_id'),
        'display_name': rows[idx].get('display_name'),
        'cluster': f'cluster_{labels[idx] + 1}',
    } for idx in range(n)]


def _group_summary(rows_raw: list[dict[str, Any]], metrics: list[str], group_by: str = '') -> list[dict[str, Any]]:
    group_key = str(group_by or '').strip().lower()
    if group_key not in {'domain', 'clade', 'habitat'}:
        return []
    buckets: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows_raw:
        label = str(row.get(group_key) or 'unknown').strip() or 'unknown'
        buckets[label].append(row)

    output = []
    for label, members in sorted(buckets.items(), key=lambda item: len(item[1]), reverse=True):
        row = {'group': label, 'count': len(members)}
        for metric in metrics[:6]:
            values = [_safe_num(item.get(metric)) for item in members]
            values = [float(v) for v in values if v is not None]
            row[metric] = round(sum(values) / len(values), 6) if values else None
        output.append(row)
    return output


def _cross_concordance_ranking(payload_map: dict[str, dict[str, Any]], species_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranking = []
    for row in species_rows:
        species_id = str(row.get('species_id') or '')
        cross = payload_map.get(species_id) or {}
        transformations = cross.get('transformations')
        score = None
        n_items = 0
        if isinstance(transformations, list) and transformations:
            values = [_safe_num(item.get('discordance_score')) for item in transformations if isinstance(item, dict)]
            values = [float(v) for v in values if v is not None]
            if values:
                score = -float(sum(values) / len(values))
                n_items = len(values)
        if score is None:
            top_rows = cross.get('top_transformations') if isinstance(cross.get('top_transformations'), list) else []
            signs = []
            mags = []
            for item in top_rows:
                if not isinstance(item, dict):
                    continue
                a = _safe_num(item.get('dna_to_rna_n_shift_std'))
                b = _safe_num(item.get('rna_to_protein_n_shift_std'))
                if a is None or b is None:
                    continue
                signs.append(1 if a * b >= 0 else -1)
                mags.append(abs(a) + abs(b))
            if signs:
                score = float(sum(signs) / len(signs)) - float(sum(mags) / max(1, len(mags)))
                n_items = len(signs)
        if score is None:
            score = 0.0
        ranking.append({
            'species_id': species_id,
            'display_name': row.get('display_name') or species_id,
            'concordance_score': round(float(score), 6),
            'n_items': int(n_items),
        })
    ranking.sort(key=lambda item: item['concordance_score'], reverse=True)
    return ranking


def _cross_match_quality_rows(payload_map: dict[str, dict[str, Any]], species_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in species_rows:
        species_id = str(row.get('species_id') or '')
        cross = payload_map.get(species_id) or {}
        join = cross.get('join_summary') if isinstance(cross.get('join_summary'), dict) else {}
        mapping = cross.get('mapping_summary') if isinstance(cross.get('mapping_summary'), dict) else {}
        suite = cross.get('cross_omics_module_suite') if isinstance(cross.get('cross_omics_module_suite'), dict) else {}
        quality = suite.get('quality_flags') if isinstance(suite.get('quality_flags'), dict) else {}
        missing_count = quality.get('missing_field_count')
        if missing_count is None and isinstance(suite.get('modules'), list):
            missing_count = sum(len(module.get('missing_fields') or []) for module in suite.get('modules') if isinstance(module, dict))
        rows.append({
            'species_id': species_id,
            'display_name': row.get('display_name') or species_id,
            'genome_rows': join.get('genome_rows') or 0,
            'transcriptome_rows': join.get('transcriptome_rows') or 0,
            'proteome_rows': join.get('proteome_rows') or 0,
            'matched_all_three': join.get('matched_all_three') or 0,
            'match_rate_all_three': join.get('match_rate_all_three') or 0.0,
            'mapping_conflict_count': int(mapping.get('conflict_count') or 0),
            'multi_transcript_gene_count': int((mapping.get('multi_mapping') or {}).get('multi_transcript_gene_count') or 0),
            'multi_protein_gene_count': int((mapping.get('multi_mapping') or {}).get('multi_protein_gene_count') or 0),
            'missing_field_count': int(missing_count or 0),
            'data_scope': quality.get('data_scope') or 'cross_omics_payload',
            'evidence_level': quality.get('evidence_level') or cross.get('evidence_level') or 'exploratory',
        })
    return rows


def _build_compare_atlas(
    rows_raw: list[dict[str, Any]],
    rows_scaled: list[dict[str, Any]],
    distances: list[dict[str, Any]],
    *,
    omics: str = '',
    normalization: str = 'raw',
    adjustment: str = 'none',
    distance_method: str = 'euclidean',
    group_by: str = '',
    detail: str = 'light',
    concordance_ranking: list[dict[str, Any]] | None = None,
    match_quality_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not rows_raw:
        return {
            'metrics': [],
            'species_labels': [],
            'species_ids': [],
            'fingerprint_heatmap': {'values': [], 'x_labels': [], 'y_labels': []},
            'distance_heatmap': {'values': [], 'x_labels': [], 'y_labels': []},
            'rankings': [],
            'metric_distributions': [],
            'group_summary': [],
            'ordination': {'method': 'pca_svd', 'points': [], 'explained_variance_ratio': [0.0, 0.0]},
            'clusters': [],
            'concordance_ranking': [],
            'match_quality': [],
            'normalization_info': {'mode': normalization},
            'adjustment_info': {'mode': adjustment},
            'distance_info': {'method': distance_method},
        }

    metrics = _extract_compare_metrics(rows_raw, omics=omics)
    metric_stats = {}
    for metric in metrics:
        values = [_safe_num(row.get(metric)) for row in rows_raw]
        values = [float(v) for v in values if v is not None]
        if not values:
            continue
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / max(len(values), 1)
        metric_stats[metric] = {
            'mean': mean,
            'std': math.sqrt(variance) if variance > 0 else 1.0,
            'min': min(values),
            'max': max(values),
            'distribution': _distribution_stats(values),
        }

    def _species_score(row: dict[str, Any], rows: list[dict[str, Any]]) -> float:
        score = 0.0
        for metric in metrics:
            value = _safe_num(row.get(metric))
            stats = metric_stats.get(metric)
            if value is None or not stats:
                continue
            if rows is rows_scaled:
                score += value
            else:
                score += (value - stats['mean']) / (stats['std'] or 1.0)
        return score

    ordered_scaled = sorted(rows_scaled, key=lambda row: _species_score(row, rows_scaled), reverse=True)
    ordered_raw_map = {str(row.get('species_id', '')): row for row in rows_raw}
    ordered_raw = [ordered_raw_map.get(str(row.get('species_id', '')), {}) for row in ordered_scaled]
    species_ids = [str(row.get('species_id', '')) for row in ordered_scaled]
    species_labels = [str(row.get('display_name') or row.get('species_id') or '') for row in ordered_scaled]

    fingerprint_heat_values = []
    for y_index, row in enumerate(ordered_scaled):
        for x_index, metric in enumerate(metrics):
            value = _safe_num(row.get(metric))
            fingerprint_heat_values.append([x_index, y_index, round(value, 6) if value is not None else 0.0])

    distance_map: dict[str, dict[str, float]] = {
        species_id: {other_id: 0.0 for other_id in species_ids}
        for species_id in species_ids
    }
    collected = []
    for item in distances:
        src = str(item.get('source'))
        dst = str(item.get('target'))
        value = _safe_num(item.get('distance'))
        if src not in distance_map or dst not in distance_map or value is None:
            continue
        distance_map[src][dst] = float(value)
        distance_map[dst][src] = float(value)
        collected.append(float(value))
    default_distance = (sum(collected) / len(collected)) if collected else 0.0
    distance_heat_values = []
    for y_index, src in enumerate(species_ids):
        for x_index, dst in enumerate(species_ids):
            value = distance_map[src].get(dst, default_distance)
            distance_heat_values.append([x_index, y_index, round(value, 6)])

    rankings = []
    scaled_map = {str(row.get('species_id', '')): row for row in ordered_scaled}
    for metric in metrics:
        ranked = [
            {
                'species_id': str(row.get('species_id')),
                'display_name': str(row.get('display_name') or row.get('species_id')),
                'value': round(_safe_num(row.get(metric)) or 0.0, 6),
                'scaled_value': (
                    round(_safe_num((scaled_map.get(str(row.get('species_id') or ''), {}) or {}).get(metric)) or 0.0, 6)
                    if str(row.get('species_id') or '') in scaled_map
                    else None
                ),
            }
            for row in ordered_raw
            if _safe_num(row.get(metric)) is not None
        ]
        ranked.sort(key=lambda item: item['value'], reverse=True)
        rankings.append({
            'feature': metric,
            'top': ranked[:10],
            'bottom': list(reversed(ranked[-10:])) if len(ranked) > 10 else ranked[:],
        })

    return {
        'metrics': metrics,
        'species_labels': species_labels,
        'species_ids': species_ids,
        'fingerprint_heatmap': {
            'x_labels': metrics,
            'y_labels': species_labels,
            'values': fingerprint_heat_values,
        },
        'distance_heatmap': {
            'x_labels': species_labels,
            'y_labels': species_labels,
            'values': distance_heat_values,
        },
        'rankings': rankings,
        'metric_distributions': [
            {'feature': metric, **(metric_stats.get(metric, {}).get('distribution') or {})}
            for metric in metrics
            if metric in metric_stats
        ],
        'group_summary': _group_summary(ordered_raw, metrics, group_by=group_by),
        'ordination': _ordination_payload(ordered_scaled, metrics, group_by=group_by, include_umap=(detail == 'full')),
        'clusters': _kmeans_cluster_labels(ordered_scaled, metrics, k=min(4, max(2, int(math.sqrt(len(ordered_scaled)))))),
        'concordance_ranking': concordance_ranking or [],
        'match_quality': match_quality_rows or [],
        'normalization_info': {'mode': normalization},
        'adjustment_info': {
            'mode': adjustment,
            'supported_modes': ['none', 'length_gc_adjusted', 'taxonomy_stratified'],
            'caveat': 'Adjustment changes descriptive distance interpretation and does not remove all phylogenetic or annotation confounding.',
        },
        'distance_info': {'method': distance_method},
        'selection_policy': {
            'selected_count': len(species_ids),
            'max_species_per_request': COMPARE_MAX_SPECIES,
            'default_species_limit': COMPARE_DEFAULT_SPECIES_LIMIT,
            'matrix_complexity': 'O(n^2) pairwise distances; keep selected species small and batch large comparisons.',
            'detail_mode': detail,
            'umap_policy': 'UMAP is skipped in light mode to avoid heavy interactive requests.',
        },
    }


def _adjust_compare_fingerprints(rows: list[dict[str, Any]], metrics: list[str], adjustment: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mode = str(adjustment or 'none').strip().lower()
    if mode in {'', 'raw'}:
        mode = 'none'
    if mode not in {'none', 'length_gc_adjusted', 'taxonomy_stratified'}:
        mode = 'none'
    info = {
        'mode': mode,
        'supported_modes': ['none', 'length_gc_adjusted', 'taxonomy_stratified'],
        'method': 'no covariate adjustment',
        'covariates': [],
        'caveat': 'Distances are descriptive and should not be treated as phylogenetic distances or causal contrasts.',
    }
    if mode == 'none':
        return rows, info
    adjusted = [dict(row) for row in rows]
    if mode == 'length_gc_adjusted':
        covariate_candidates = ['genome_size_mb', 'genome_length_mb', 'genome_length_bp', 'genome_gc', 'gc_percent']
        covariates = [key for key in covariate_candidates if any(_safe_num(row.get(key)) is not None for row in rows)]
        for metric in metrics:
            if metric in covariates:
                continue
            values = [_safe_num(row.get(metric)) for row in rows]
            finite = [float(v) for v in values if v is not None]
            if not finite:
                continue
            mean_value = _mean(finite)
            for row in adjusted:
                value = _safe_num(row.get(metric))
                if value is not None:
                    row[metric] = round(float(value) - mean_value, 6)
        info.update({
            'method': 'global mean centering for selected fingerprint metrics after exposing length/GC adjustment intent',
            'covariates': covariates,
            'caveat': 'Length/GC covariates are sparse in the registry, so this mode should be read as conservative descriptive centering rather than full residual modeling.',
        })
        return adjusted, info
    strata_key = 'domain' if any(row.get('domain') for row in rows) else ('clade' if any(row.get('clade') for row in rows) else '')
    if not strata_key:
        info.update({
            'method': 'taxonomy stratification requested but no domain/clade metadata was available',
            'caveat': 'No taxonomy strata were available; unstratified values were returned.',
        })
        return adjusted, info
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in adjusted:
        by_group[str(row.get(strata_key) or 'unclassified')].append(row)
    for group_rows in by_group.values():
        for metric in metrics:
            finite = [float(v) for v in (_safe_num(row.get(metric)) for row in group_rows) if v is not None]
            if not finite:
                continue
            mean_value = _mean(finite)
            for row in group_rows:
                value = _safe_num(row.get(metric))
                if value is not None:
                    row[metric] = round(float(value) - mean_value, 6)
    info.update({
        'method': f'within-{strata_key} mean centering for selected fingerprint metrics',
        'covariates': [strata_key],
        'caveat': 'Taxonomy-stratified centering reduces coarse group offsets only; it is not a phylogenetic comparative model.',
    })
    return adjusted, info


def compare_species(
    species_ids: list[str],
    omics: str = '',
    normalization: str = 'robust_zscore',
    adjustment: str = 'none',
    distance: str = 'euclidean',
    group_by: str = '',
    detail: str = 'light',
) -> dict[str, Any]:
    if omics:
        validate_omics(omics)
    normalization_mode = str(normalization or 'robust_zscore').strip().lower()
    if normalization_mode not in {'raw', 'zscore', 'robust_zscore'}:
        normalization_mode = 'robust_zscore'
    distance_method = str(distance or 'euclidean').strip().lower()
    if distance_method not in {'euclidean', 'cosine', 'correlation'}:
        distance_method = 'euclidean'
    adjustment_mode = str(adjustment or 'none').strip().lower()
    if adjustment_mode in {'', 'raw'}:
        adjustment_mode = 'none'
    if adjustment_mode not in {'none', 'length_gc_adjusted', 'taxonomy_stratified'}:
        adjustment_mode = 'none'
    group_key = str(group_by or '').strip().lower()
    if group_key not in {'domain', 'clade', 'habitat'}:
        group_key = ''
    detail_mode = str(detail or 'light').strip().lower()
    if detail_mode not in {'light', 'full'}:
        detail_mode = 'light'

    selected_ids = [str(item).strip() for item in (species_ids or []) if str(item).strip()]
    if len(selected_ids) > COMPARE_MAX_SPECIES:
        raise ValueError(f'Compare supports at most {COMPARE_MAX_SPECIES} selected species per request. Narrow the selection or run multiple batches.')

    if db_mode():
        qs = Species.objects.all()
        if selected_ids:
            qs = qs.filter(species_id__in=selected_ids)
        else:
            qs = qs.filter(has_genome=True, has_transcriptome=True, has_proteome=True).order_by('display_name', 'species_id')[:COMPARE_DEFAULT_SPECIES_LIMIT]
        rows = list(qs)
        selected = [_species_to_light_summary(r) for r in rows]
        fingerprints_raw = [{
            'species_id': r.species_id,
            'display_name': r.display_name,
            'source_context': _species_context_label(r),
            'domain': r.domain,
            'clade': r.clade,
            'habitat': r.habitat,
            **(r.fingerprint or {}),
        } for r in rows]
        metrics = _extract_compare_metrics(fingerprints_raw, omics=omics)
        fingerprints_adjusted, adjustment_info = _adjust_compare_fingerprints(fingerprints_raw, metrics, adjustment_mode)
        fingerprints_scaled, normalization_info = _normalize_fingerprints(fingerprints_adjusted, metrics, normalization_mode)
        distances = _pairwise_distances(fingerprints_scaled, metrics, distance_method)
        cross_builder = _enhance_cross_payload if detail_mode == 'full' else _light_cross_payload
        cross_map = {str(r.species_id): cross_builder(str(r.species_id), r.cross_omics_payload or {}) for r in rows}
        concordance = _cross_concordance_ranking(
            cross_map,
            fingerprints_raw,
        )
        match_quality = _cross_match_quality_rows(cross_map, fingerprints_raw)
        return {
            'species': selected,
            'fingerprints': fingerprints_scaled,
            'fingerprints_raw': fingerprints_raw,
            'distances': distances,
            'omics_focus': omics or 'all',
            'normalization': normalization_mode,
            'adjustment': adjustment_mode,
            'distance_method': distance_method,
            'group_by': group_key or 'none',
            'detail': detail_mode,
            'atlas': _build_compare_atlas(
                fingerprints_raw,
                fingerprints_scaled,
                distances,
                omics=omics,
                normalization=normalization_mode,
                adjustment=adjustment_mode,
                distance_method=distance_method,
                group_by=group_key,
                detail=detail_mode,
                concordance_ranking=concordance,
                match_quality_rows=match_quality,
            ),
            'normalization_info': normalization_info,
            'adjustment_info': adjustment_info,
            'distance_info': {'method': distance_method},
        }

    idx = load_index()
    selected_ids = selected_ids or [row['species_id'] for row in idx.get('species', [])[:COMPARE_DEFAULT_SPECIES_LIMIT]]
    if len(selected_ids) > COMPARE_MAX_SPECIES:
        raise ValueError(f'Compare supports at most {COMPARE_MAX_SPECIES} selected species per request. Narrow the selection or run multiple batches.')
    selected = [file_species_map()[sid] for sid in selected_ids if sid in file_species_map()]
    features_raw = [{
        'species_id': row['species_id'],
        'display_name': row['display_name'],
        'source_context': _species_context_label(row),
        'domain': row.get('domain', ''),
        'clade': row.get('clade', ''),
        'habitat': row.get('habitat', ''),
        **row['fingerprint'],
    } for row in selected]
    metrics = _extract_compare_metrics(features_raw, omics=omics)
    features_adjusted, adjustment_info = _adjust_compare_fingerprints(features_raw, metrics, adjustment_mode)
    features_scaled, normalization_info = _normalize_fingerprints(features_adjusted, metrics, normalization_mode)
    pairs = _pairwise_distances(features_scaled, metrics, distance_method)
    cross_map: dict[str, dict[str, Any]] = {}
    for row in selected:
        sid = str(row.get('species_id'))
        try:
            payload = load_json(f'{sid}/cross_omics.json')
            cross_map[sid] = (_enhance_cross_payload if detail_mode == 'full' else _light_cross_payload)(sid, payload)
        except Exception:
            cross_map[sid] = {}
    concordance = _cross_concordance_ranking(cross_map, features_raw)
    match_quality = _cross_match_quality_rows(cross_map, features_raw)
    return {
        'species': selected,
        'fingerprints': features_scaled,
        'fingerprints_raw': features_raw,
        'distances': pairs,
        'omics_focus': omics or 'all',
        'normalization': normalization_mode,
        'adjustment': adjustment_mode,
        'distance_method': distance_method,
        'group_by': group_key or 'none',
        'detail': detail_mode,
        'atlas': _build_compare_atlas(
            features_raw,
            features_scaled,
            pairs,
            omics=omics,
            normalization=normalization_mode,
            adjustment=adjustment_mode,
            distance_method=distance_method,
            group_by=group_key,
            detail=detail_mode,
            concordance_ranking=concordance,
            match_quality_rows=match_quality,
        ),
        'normalization_info': normalization_info,
        'adjustment_info': adjustment_info,
        'distance_info': {'method': distance_method},
    }


def _fingerprint_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    keys = sorted(set(a.keys()) & set(b.keys()))
    nums = []
    for key in keys:
        av = _safe_num(a.get(key))
        bv = _safe_num(b.get(key))
        if av is None or bv is None:
            continue
        nums.append((av - bv) ** 2)
    if not nums:
        return 0.0
    return round(math.sqrt(sum(nums)), 4)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    avg = _mean(values)
    variance = sum((value - avg) ** 2 for value in values) / len(values)
    return float(math.sqrt(max(variance, 0.0)))


def _effect_size(high_values: list[float], low_values: list[float]) -> float:
    if not high_values or not low_values:
        return 0.0
    mean_high = _mean(high_values)
    mean_low = _mean(low_values)
    std_high = _std(high_values)
    std_low = _std(low_values)
    pooled = math.sqrt(((std_high ** 2) + (std_low ** 2)) / 2.0) if (std_high or std_low) else 0.0
    if pooled == 0:
        return 0.0
    return (mean_high - mean_low) / pooled


def _omics_internal_payload() -> dict[str, Any]:
    output: dict[str, Any] = {}
    for omics in ['genome', 'transcriptome', 'proteome']:
        dataset_total = OmicsDataset.objects.filter(omics_type=omics).count()
        datasets = list(
            OmicsDataset.objects
            .filter(omics_type=omics)
            .only('dataset_id', 'species__species_id', 'summary_payload', 'analysis_payload')
            .select_related('species')
            .order_by('species__display_name')[:1000]
        )
        strategy_counts: defaultdict[str, int] = defaultdict(int)
        feature_values: defaultdict[str, list[float]] = defaultdict(list)
        outlier_counts: list[float] = []
        tradeoff_scores: list[float] = []

        genome_island_scores: list[float] = []
        transcript_motif_counts: defaultdict[str, int] = defaultdict(int)
        proteome_budget_values: defaultdict[str, list[float]] = defaultdict(list)

        for ds in datasets:
            summary = ds.summary_payload or {}
            analysis = ds.analysis_payload or {}
            for row in summary.get('strategy_breakdown') or []:
                cluster = str(row.get('cluster') or '').strip()
                count = int(_safe_num(row.get('count')) or 0)
                if cluster:
                    strategy_counts[cluster] += count
            for key, card in (summary.get('feature_cards') or {}).items():
                mean_value = _safe_num((card or {}).get('mean'))
                if mean_value is not None:
                    feature_values[str(key)].append(float(mean_value))

            outliers = analysis.get('outliers') or {}
            high_count = len(outliers.get('high') or [])
            low_count = len(outliers.get('low') or [])
            outlier_counts.append(float(high_count + low_count))

            for row in analysis.get('tradeoff_front') or []:
                score = _safe_num(row.get('front_score'))
                if score is not None:
                    tradeoff_scores.append(float(score))

            if omics == 'genome':
                for row in analysis.get('stoich_islands') or []:
                    score = _safe_num(row.get('mean_island_score'))
                    if score is not None:
                        genome_island_scores.append(float(score))
            elif omics == 'transcriptome':
                for row in analysis.get('motif_themes') or []:
                    theme = str(row.get('theme') or '').strip()
                    count = int(_safe_num(row.get('count')) or 0)
                    if theme:
                        transcript_motif_counts[theme] += count
            elif omics == 'proteome':
                for row in analysis.get('resource_budget') or []:
                    feature = str(row.get('feature') or '').strip()
                    value = _safe_num(row.get('mean'))
                    if feature and value is not None:
                        proteome_budget_values[feature].append(float(value))

        feature_rank = []
        for feature, values in feature_values.items():
            feature_rank.append({
                'feature': feature,
                'mean': round(_mean(values), 6),
                'p50': round(_distribution_stats(values).get('p50', 0.0), 6),
                'p75': round(_distribution_stats(values).get('p75', 0.0), 6),
            })
        feature_rank.sort(key=lambda row: row['mean'], reverse=True)

        specific_payload: dict[str, Any]
        if omics == 'genome':
            specific_payload = {
                'kind': 'genome_island',
                'distribution': _histogram_payload(genome_island_scores, bins=36),
                'stats': _distribution_stats(genome_island_scores),
            }
        elif omics == 'transcriptome':
            motif_rows = [
                {'name': key, 'value': value}
                for key, value in sorted(transcript_motif_counts.items(), key=lambda item: item[1], reverse=True)[:12]
            ]
            specific_payload = {
                'kind': 'transcript_motif',
                'composition': motif_rows,
            }
        else:
            budget_rows = [
                {'name': key, 'value': round(_mean(values), 6)}
                for key, values in proteome_budget_values.items()
            ]
            budget_rows.sort(key=lambda row: row['value'], reverse=True)
            specific_payload = {
                'kind': 'proteome_budget',
                'budget': budget_rows[:16],
            }

        output[omics] = {
            'dataset_count': len(datasets),
            'dataset_total': dataset_total,
            'sampled': dataset_total > len(datasets),
            'sample_policy': 'first_1000_species_by_display_name_for_analysis_hub_overview',
            'strategy_composition': [
                {'name': key, 'value': value}
                for key, value in sorted(strategy_counts.items(), key=lambda item: item[1], reverse=True)
            ],
            'feature_rank': feature_rank[:20],
            'outlier_distribution': _histogram_payload(outlier_counts, bins=24),
            'tradeoff_distribution': _histogram_payload(tradeoff_scores, bins=28),
            'specific': specific_payload,
        }
    return output


def _cross_omics_real_payload() -> dict[str, Any]:
    source_species_count = Species.objects.count()
    species_rows = list(Species.objects.only('species_id', 'display_name', 'cross_omics_payload', 'has_genome', 'has_transcriptome', 'has_proteome').order_by('display_name')[:2000])
    dna_to_rna: list[float] = []
    rna_to_protein: list[float] = []
    shift_pairs: list[dict[str, Any]] = []
    concordance = {'both_up': 0, 'both_down': 0, 'opposite': 0}
    conserved_shift = {'conserved': 0, 'shifted': 0}
    species_event_counts = []
    threshold = 0.05

    for row in species_rows:
        top_rows = (row.cross_omics_payload or {}).get('top_transformations') or []
        event_count = 0
        for item in top_rows:
            shift_a = _safe_num(item.get('dna_to_rna_n_shift_std'))
            shift_b = _safe_num(item.get('rna_to_protein_n_shift_std'))
            if shift_a is None or shift_b is None:
                continue
            shift_a = float(shift_a)
            shift_b = float(shift_b)
            dna_to_rna.append(shift_a)
            rna_to_protein.append(shift_b)
            event_count += 1
            shift_pairs.append({
                'species_id': row.species_id,
                'species_name': row.display_name,
                'dna_to_rna_n_shift_std': round(shift_a, 6),
                'rna_to_protein_n_shift_std': round(shift_b, 6),
            })
            if shift_a >= 0 and shift_b >= 0:
                concordance['both_up'] += 1
            elif shift_a < 0 and shift_b < 0:
                concordance['both_down'] += 1
            else:
                concordance['opposite'] += 1
            if abs(shift_a) + abs(shift_b) <= threshold:
                conserved_shift['conserved'] += 1
            else:
                conserved_shift['shifted'] += 1
        species_event_counts.append({
            'species_id': row.species_id,
            'display_name': row.display_name,
            'events': event_count,
        })
    species_event_counts.sort(key=lambda item: item['events'], reverse=True)

    join_coverage = {
        'all_species': len(species_rows),
        'genome_loaded': Species.objects.filter(has_genome=True).count(),
        'genome_transcriptome_loaded': Species.objects.filter(has_genome=True, has_transcriptome=True).count(),
        'all_omics_loaded': Species.objects.filter(has_genome=True, has_transcriptome=True, has_proteome=True).count(),
    }

    return {
        'source_species_count': source_species_count,
        'sampled_species_count': len(species_rows),
        'sampled': source_species_count > len(species_rows),
        'sample_policy': 'first_2000_species_by_display_name_for_analysis_hub_overview',
        'pair_count': len(shift_pairs),
        'shift_pairs': shift_pairs[:2000],
        'dna_to_rna_distribution_std': _histogram_payload(dna_to_rna, bins=40),
        'rna_to_protein_distribution_std': _histogram_payload(rna_to_protein, bins=40),
        'shift_stats': {
            'dna_to_rna': _distribution_stats(dna_to_rna),
            'rna_to_protein': _distribution_stats(rna_to_protein),
        },
        'concordance': [{'name': key, 'value': value} for key, value in concordance.items()],
        'conserved_vs_shifted': [{'name': key, 'value': value} for key, value in conserved_shift.items()],
        'species_event_rank': species_event_counts[:20],
        'join_coverage': join_coverage,
    }


def _cross_species_real_payload() -> dict[str, Any]:
    source_species_count = Species.objects.count()
    species_rows = list(Species.objects.only('species_id', 'display_name', 'fingerprint').order_by('display_name')[:800])
    fingerprints = []
    for row in species_rows:
        payload = row.fingerprint or {}
        if not payload:
            continue
        fingerprints.append({'species_id': row.species_id, 'display_name': row.display_name, **payload})
    metrics = _metric_panel_for_omics('')
    effect_rows = []
    discriminative_rows = []
    for metric in metrics:
        values = [(_safe_num(row.get(metric)), row) for row in fingerprints]
        values = [(float(v), row) for v, row in values if v is not None]
        if len(values) < 8:
            continue
        values.sort(key=lambda item: item[0])
        q = max(3, len(values) // 4)
        low = [item[0] for item in values[:q]]
        high = [item[0] for item in values[-q:]]
        effect = _effect_size(high, low)
        all_values = [item[0] for item in values]
        discriminative_rows.append({
            'feature': metric,
            'std': round(_std(all_values), 6),
            'cv': round(_safe_div(_std(all_values), abs(_mean(all_values)) or 1.0), 6),
        })
        effect_rows.append({
            'feature': metric,
            'effect_size': round(effect, 6),
            'high_mean': round(_mean(high), 6),
            'low_mean': round(_mean(low), 6),
        })
    effect_rows.sort(key=lambda row: abs(row['effect_size']), reverse=True)
    discriminative_rows.sort(key=lambda row: abs(row['std']), reverse=True)

    distances = []
    for i, src in enumerate(species_rows):
        for dst in species_rows[i + 1:]:
            distance = _fingerprint_distance(src.fingerprint or {}, dst.fingerprint or {})
            distances.append(float(distance))

    return {
        'source_species_count': source_species_count,
        'sampled_species_count': len(species_rows),
        'sampled': source_species_count > len(species_rows),
        'sample_policy': 'first_800_species_by_display_name_for_analysis_hub_distance_overview',
        'effect_sizes': effect_rows[:20],
        'discriminative_features': discriminative_rows[:20],
        'distance_distribution': _histogram_payload(distances, bins=36),
        'distance_stats': _distribution_stats(distances),
        'species_count': len(species_rows),
    }


def _exploratory_payload() -> dict[str, Any]:
    source_species_count = Species.objects.count()
    species_rows = list(Species.objects.only('species_id', 'display_name', 'fingerprint').order_by('display_name')[:2000])
    metrics = _metric_panel_for_omics('')
    numeric_rows = []
    missing_total = 0
    for row in species_rows:
        fingerprint = row.fingerprint or {}
        values = {metric: _safe_num(fingerprint.get(metric)) for metric in metrics}
        if sum(1 for value in values.values() if value is not None) < 4:
            continue
        missing_total += sum(1 for value in values.values() if value is None)
        numeric_rows.append({
            'species_id': row.species_id,
            'display_name': row.display_name,
            'values': values,
        })
    if not numeric_rows:
        return {
            'disclaimer': 'Exploratory analyses require at least four populated fingerprint metrics per species and should be interpreted as hypothesis-generating views.',
            'method': 'pca_svd',
            'method_metadata': {
                'normalization': 'robust_zscore',
                'missing_policy': 'species with fewer than four populated metrics removed',
                'n_entities': 0,
                'n_features': len(metrics),
                'n_missing': 0,
                'is_exploratory': True,
            },
            'embedding': [],
            'anomaly_candidates': [],
            'communities': [],
            'feature_loadings': [],
            'explained_variance_ratio': [],
        }

    stats = {}
    for metric in metrics:
        vals = sorted(float(item['values'][metric]) for item in numeric_rows if item['values'][metric] is not None)
        median = _percentile(vals, 0.50) if vals else 0.0
        q25 = _percentile(vals, 0.25) if vals else 0.0
        q75 = _percentile(vals, 0.75) if vals else 0.0
        scale = q75 - q25
        if not scale:
            scale = _std(vals) or 1.0
        stats[metric] = {'median': median, 'scale': scale}

    matrix = []
    for item in numeric_rows:
        matrix.append([
            (float(item['values'][metric]) - stats[metric]['median']) / stats[metric]['scale']
            if item['values'][metric] is not None else 0.0
            for metric in metrics
        ])

    if np is None or len(matrix) < 2:
        embedding = []
        groups = defaultdict(list)
        for item, vector in zip(numeric_rows, matrix):
            axis1 = float(sum(vector[:3]))
            axis2 = float(sum(vector[3:6]) - sum(vector[6:8]))
            anomaly_score = math.sqrt(axis1 ** 2 + axis2 ** 2)
            community = 'heuristic_high_high' if axis1 >= 0 and axis2 >= 0 else 'heuristic_mixed'
            groups[community].append(item['species_id'])
            embedding.append({
                'species_id': item['species_id'],
                'display_name': item['display_name'],
                'axis1': round(axis1, 6),
                'axis2': round(axis2, 6),
                'anomaly_score': round(anomaly_score, 6),
                'community': community,
            })
        embedding.sort(key=lambda row: row['anomaly_score'], reverse=True)
        return {
            'disclaimer': 'Exploratory analyses are heuristic because PCA dependencies or sample size are insufficient; interpret as hypothesis-generating only.',
            'method': 'heuristic_axis',
            'method_metadata': {
                'normalization': 'robust_zscore',
                'missing_policy': 'feature median imputation after species with fewer than four populated metrics removed',
                'n_entities': len(numeric_rows),
                'n_features': len(metrics),
                'n_missing': missing_total,
                'is_exploratory': True,
            },
            'embedding': embedding[:400],
            'anomaly_candidates': embedding[:20],
            'communities': [{'name': key, 'value': len(values), 'members': values[:12]} for key, values in groups.items()],
            'feature_loadings': [
                {'feature': 'genome and transcript robust-z summary', 'axis': 'axis1'},
                {'feature': 'transcript and proteome robust-z contrast', 'axis': 'axis2'},
            ],
            'explained_variance_ratio': [],
        }

    x = np.asarray(matrix, dtype=float)
    x = x - np.nanmean(x, axis=0)
    try:
        u, singular_values, vt = np.linalg.svd(x, full_matrices=False)
    except Exception:
        singular_values = np.asarray([], dtype=float)
        u = np.zeros((len(numeric_rows), 0))
        vt = np.zeros((0, len(metrics)))

    if singular_values.size:
        variances = singular_values ** 2
        total_variance = float(np.sum(variances)) or 1.0
        explained = [round(float(value / total_variance), 6) for value in variances[:2]]
        coords = u[:, :2] * singular_values[:2]
    else:
        explained = []
        coords = np.zeros((len(numeric_rows), 2))
    if coords.shape[1] < 2:
        coords = np.column_stack([coords[:, 0] if coords.shape[1] else np.zeros(len(numeric_rows)), np.zeros(len(numeric_rows))])

    embedding = []
    groups = defaultdict(list)
    for idx, item in enumerate(numeric_rows):
        axis1 = float(coords[idx, 0])
        axis2 = float(coords[idx, 1])
        anomaly_score = math.sqrt(axis1 ** 2 + axis2 ** 2)
        if axis1 >= 0 and axis2 >= 0:
            community = 'PC1+ / PC2+'
        elif axis1 >= 0 and axis2 < 0:
            community = 'PC1+ / PC2-'
        elif axis1 < 0 and axis2 >= 0:
            community = 'PC1- / PC2+'
        else:
            community = 'PC1- / PC2-'
        groups[community].append(item['species_id'])
        embedding.append({
            'species_id': item['species_id'],
            'display_name': item['display_name'],
            'axis1': round(axis1, 6),
            'axis2': round(axis2, 6),
            'anomaly_score': round(anomaly_score, 6),
            'community': community,
        })

    embedding.sort(key=lambda row: row['anomaly_score'], reverse=True)
    communities = [
        {'name': key, 'value': len(values), 'members': values[:12]}
        for key, values in sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)
    ]

    feature_loadings = []
    for axis_idx, axis_name in enumerate(['PC1', 'PC2']):
        if axis_idx >= vt.shape[0]:
            continue
        loading_pairs = sorted(
            zip(metrics, vt[axis_idx].tolist()),
            key=lambda item: abs(float(item[1])),
            reverse=True,
        )[:5]
        feature_loadings.append({
            'axis': axis_name,
            'feature': ' + '.join(f"{metric} ({float(weight):+.3f})" for metric, weight in loading_pairs),
        })

    return {
        'disclaimer': 'Exploratory analyses use PCA on robust-z-scored species fingerprints and should be interpreted as hypothesis-generating, not causal, views.',
        'method': 'pca_svd',
        'method_metadata': {
            'normalization': 'robust_zscore',
            'missing_policy': 'feature median imputation after species with fewer than four populated metrics removed',
            'n_entities': len(numeric_rows),
            'n_features': len(metrics),
            'n_missing': missing_total,
            'thresholds': {'minimum_populated_metrics_per_species': 4},
            'is_exploratory': True,
        },
        'embedding': embedding[:400],
        'anomaly_candidates': embedding[:20],
        'communities': communities,
        'feature_loadings': feature_loadings,
        'explained_variance_ratio': explained,
    }


@lru_cache(maxsize=1)
def analysis_hub_payload() -> dict[str, Any]:
    return {
        'release': current_release(),
        'real': {
            'omics_internal': _omics_internal_payload(),
            'cross_omics': _cross_omics_real_payload(),
            'cross_species': _cross_species_real_payload(),
            'functional_annotations': {
                'id': 'functional_annotations',
                'title': 'GO/KEGG functional annotation layer',
                'summary': function_annotations.release_payload(),
                'endpoints': [
                    '/api/stoichdb/annotations/status/',
                    '/api/stoichdb/analysis/enrichment/',
                    '/api/stoichdb/species/{species_id}/functional-summary/',
                ],
                'method_metadata': {
                    'method': 'Standard GO/KEGG annotation lookup and same-species enrichment analysis.',
                    'prediction_policy': 'Unsupported species are not predicted and remain explicitly labeled.',
                    'is_exploratory': False,
                },
            },
            'phylogeny': {
                'id': 'phylogeny_p0_p1',
                'title': 'Protist phylogeny foundation layer',
                'summary': phylogeny.release_payload(),
                'endpoints': [
                    '/api/stoichdb/phylogeny/releases/',
                    '/api/stoichdb/phylogeny/releases/protist_phylogeny_v1/tree/',
                    '/api/stoichdb/phylogeny/releases/protist_phylogeny_v1/validation/',
                    '/api/stoichdb/species/{species_id}/phylogeny/',
                ],
                'method_metadata': {
                    'method': 'P0/P1 taxonomy-backed reference topology generated from the platform-screened protist whitelist.',
                    'prediction_policy': 'No missing species are inferred beyond the frozen whitelist.',
                    'is_exploratory': False,
                    'interpretation_boundary': 'No branch lengths; not eligible for PGLS or phylogenetic signal inference.',
                },
            },
        },
        'exploratory': _exploratory_payload(),
    }


def _looks_like_annotation_query(query: str) -> bool:
    text = str(query or '').strip().upper()
    if not text:
        return False
    if text.startswith('GO:'):
        return True
    if text.startswith(('KO:', 'PATH:', 'MAP')):
        return True
    return text.startswith('K') and len(text) >= 6 and any(ch.isdigit() for ch in text[1:])


def universal_search(query: str, limit: int = 16) -> dict[str, Any]:
    raw_query = (query or '').strip()
    q = raw_query.lower()
    limit = _safe_int(limit, 16, minimum=1, maximum=64)
    if not q:
        return {'query': '', 'species': [], 'entities': [], 'modules': default_module_results()}
    if db_mode():
        species_qs = (
            Species.objects.only('species_id', 'display_name', 'source_database', 'assembly_version')
            .filter(
                Q(display_name__icontains=raw_query)
                | Q(species_id__icontains=raw_query)
                | Q(source_database__icontains=raw_query)
                | Q(assembly_version__icontains=raw_query)
                | Q(searchable_text__icontains=raw_query)
            )[:8]
        )
        species_hits = [
            {
                'kind': 'species',
                'species_id': row.species_id,
                'display_name': row.display_name,
                'source_context': _species_context_label(row),
                'route': f'/species/{row.species_id}',
            }
            for row in species_qs
        ]
        exact_values = []
        for value in (raw_query, raw_query.casefold(), raw_query.upper()):
            if value and value not in exact_values:
                exact_values.append(value)
        entity_base = EntityRecord.objects.select_related('species').only(
            'entity_id',
            'canonical_gene_id',
            'gene_name',
            'description',
            'omics_type',
            'species__species_id',
            'species__display_name',
        )
        entities = []
        seen_entities: set[tuple[str, str, str]] = set()
        for field in ['entity_id', 'canonical_gene_id', 'gene_name']:
            if len(entities) >= limit:
                break
            for row in entity_base.filter(**{f'{field}__in': exact_values}).order_by('omics_type', 'entity_id')[:limit]:
                key = (row.species.species_id, row.omics_type, row.entity_id)
                if key in seen_entities:
                    continue
                seen_entities.add(key)
                entities.append({
                    'kind': 'entity',
                    'species_id': row.species.species_id,
                    'species_name': row.species.display_name,
                    'omics': row.omics_type,
                    'entity_id': row.entity_id,
                    'gene_name': row.gene_name or row.description or row.entity_id,
                    'route': f"/species/{row.species.species_id}?panel={row.omics_type}&tab=table&q={row.entity_id}",
                })
                if len(entities) >= limit:
                    break
        annotations = (
            function_annotations.annotation_search_payload(raw_query, limit=min(limit, 12)).get('results', [])
            if _looks_like_annotation_query(raw_query)
            else []
        )
        return {
            'query': query,
            'species': species_hits,
            'entities': entities,
            'annotations': annotations,
            'modules': module_results_for_query(q),
            'entity_search_mode': 'global_exact_id',
            'entity_search_policy': 'Homepage entity hits use exact indexed ID fields only; broad EntityRecord text scans are disabled.',
        }

    species_rows = list(file_species_map().values())
    species_hits = []
    for row in species_rows:
        hay = ' '.join([str(row.get('display_name', '')), str(row.get('species_id', '')), str(row.get('source_database', '')), str(row.get('assembly_version', ''))]).lower()
        if q in hay:
            species_hits.append({'kind': 'species', 'species_id': row['species_id'], 'display_name': row['display_name'], 'source_context': _species_context_label(row), 'route': f"/species/{row['species_id']}"})
    entities = []
    meta_by_omics = omics_meta()
    for species_row in species_rows:
        if len(entities) >= limit:
            break
        for omics, meta in meta_by_omics.items():
            id_col = meta['primary_id']
            for row in load_json(f"{species_row['species_id']}/{omics}/rows.json"):
                hay = ' '.join([str(row.get(id_col, '')), str(row.get('entity_id', '')), str(row.get('gene_id', '')), str(row.get('ensembl_gene_id', '')), str(row.get('gene_name', '')), str(row.get('description', '')), omics, species_row['display_name']]).lower()
                if q in hay:
                    entity_id = row.get(id_col) or row.get('entity_id') or row.get('gene_id') or row.get('ensembl_gene_id')
                    entities.append({'kind': 'entity', 'species_id': species_row['species_id'], 'species_name': species_row['display_name'], 'omics': omics, 'entity_id': entity_id, 'gene_name': row.get('gene_name') or row.get('description') or entity_id, 'route': f"/species/{species_row['species_id']}?panel={omics}&tab=table&q={entity_id}"})
                    if len(entities) >= limit:
                        break
            if len(entities) >= limit:
                break
    annotations = function_annotations.annotation_search_payload(raw_query, limit=min(limit, 12)).get('results', [])
    return {'query': query, 'species': species_hits[:8], 'entities': entities[:limit], 'annotations': annotations, 'modules': module_results_for_query(q)}


@lru_cache(maxsize=1)
def species_facets() -> dict[str, Any]:
    if db_mode():
        source_databases = [
            row
            for row in Species.objects.values('source_database').annotate(count=Count('id')).order_by('source_database')
            if _clean_meta_value(row.get('source_database'))
        ]
        omics_counts = list(OmicsDataset.objects.values('omics_type').annotate(count=Count('id')).order_by('omics_type'))
        range_payload = Species.objects.aggregate(
            min_genome_size=Min('genome_size_mb'),
            max_genome_size=Max('genome_size_mb'),
        )
        ranges = {
            'genome_size_mb': {
                'min': round(range_payload.get('min_genome_size') or 0, 4),
                'max': round(range_payload.get('max_genome_size') or 0, 4),
            }
        }
        fingerprint_keys = sorted({key for row in Species.objects.only('fingerprint') for key in (row.fingerprint or {}).keys()})
        domains = [
            row
            for row in Species.objects.values('domain').annotate(count=Count('id')).order_by('domain')
            if _clean_meta_value(row.get('domain'))
        ]
        clades = [
            row
            for row in Species.objects.values('clade').annotate(count=Count('id')).order_by('clade')
            if _clean_meta_value(row.get('clade'))
        ][:200]
        habitats = [
            row
            for row in Species.objects.values('habitat').annotate(count=Count('id')).order_by('habitat')
            if _clean_meta_value(row.get('habitat'))
        ][:200]
        return {
            'source_databases': source_databases,
            'domains': domains,
            'clades': clades,
            'habitats': habitats,
            'omics_breakdown': [{'omics': row['omics_type'], 'count': row['count']} for row in omics_counts],
            'ranges': ranges,
            'fingerprint_keys': fingerprint_keys,
        }
    rows = list(file_species_map().values())
    return {
        'source_databases': [{'source_database': k, 'count': len([r for r in rows if r.get('source_database') == k])} for k in sorted({_clean_meta_value(r.get('source_database')) for r in rows if _clean_meta_value(r.get('source_database'))})],
        'domains': [{'domain': k, 'count': len([r for r in rows if r.get('domain') == k])} for k in sorted({_clean_meta_value(r.get('domain')) for r in rows if _clean_meta_value(r.get('domain'))})],
        'clades': [{'clade': k, 'count': len([r for r in rows if r.get('clade') == k])} for k in sorted({_clean_meta_value(r.get('clade')) for r in rows if _clean_meta_value(r.get('clade'))})],
        'habitats': [{'habitat': k, 'count': len([r for r in rows if r.get('habitat') == k])} for k in sorted({_clean_meta_value(r.get('habitat')) for r in rows if _clean_meta_value(r.get('habitat'))})],
        'omics_breakdown': [{'omics': key, 'count': sum(1 for row in rows if key in (row.get('omics') or {}))} for key in omics_meta().keys()],
        'ranges': {'genome_size_mb': {'min': min((r.get('genome_size_mb', 0) for r in rows), default=0), 'max': max((r.get('genome_size_mb', 0) for r in rows), default=0)}},
        'fingerprint_keys': sorted({key for r in rows for key in (r.get('fingerprint') or {}).keys()}),
    }


@lru_cache(maxsize=1)
def release_overview() -> dict[str, Any]:
    active = current_release()
    if not db_mode():
        return {
            'active_release': active,
            'history': [active],
            'database_mode': 'file_registry',
            'functional_annotation_release': function_annotations.release_payload(),
            'phylogeny_release': phylogeny.release_payload(),
            'provenance': {
                'storage_engine': 'file registry fallback',
                'import_mode': 'static files only',
                'release_registration': 'no persistent release registration in fallback mode',
            },
        }

    history = [
        _release_payload_from_record(record)
        for record in DataRelease.objects.order_by('-created_at')[:12]
    ]
    return {
        'active_release': active,
        'history': history,
        'database_mode': 'postgresql',
        'functional_annotation_release': function_annotations.release_payload(),
        'phylogeny_release': phylogeny.release_payload(),
        'provenance': {
            'storage_engine': 'PostgreSQL via Django ORM',
            'import_mode': 'staged pipeline import with chunked entity-row transactions',
            'release_registration': 'DataRelease records track manifest, counts, paths, and active release state',
        },
    }


@lru_cache(maxsize=4)
def quality_overview() -> dict[str, Any]:
    if not db_mode():
        rows = list(file_species_map().values())
        return {
            'release': current_release(),
            'qc_grade_rules': QC_GRADE_RULES,
            'qc_grade_summary': [],
            'summary': {
                'species_count': len(rows),
                'dataset_count': sum(len(row.get('omics', {})) for row in rows),
                'entity_row_count': sum(int(payload.get('row_count', 0)) for row in rows for payload in row.get('omics', {}).values()),
                'artifact_count': 0,
                'feature_file_count': 0,
                'species_with_all_omics': sum(1 for row in rows if {'genome', 'transcriptome', 'proteome'}.issubset(set(row.get('omics', {}).keys()))),
            },
            'omics_coverage': [{'omics': key, 'dataset_count': sum(1 for row in rows if key in row.get('omics', {})), 'row_count': sum(int(row.get('omics', {}).get(key, {}).get('row_count', 0)) for row in rows)} for key in omics_meta().keys()],
            'source_file_types': [],
            'artifact_types': [],
            'species_heaviest': [],
            'field_coverage_matrix': {'x_labels': [], 'y_labels': [], 'values': []},
            'missingness_matrix': {'x_labels': [], 'y_labels': [], 'values': []},
            'join_coverage_sankey': {'nodes': [], 'links': []},
            'core_full_gap': [],
            'provenance_flow': {'nodes': [], 'links': []},
            'functional_annotation_qc': function_annotations.quality_payload(),
            'phylogeny_qc': phylogeny.validation_payload() if phylogeny.release_payload().get('available') else {},
        }

    species_count = Species.objects.count()
    dataset_count = OmicsDataset.objects.count()
    entity_row_count = EntityRecord.objects.count()
    artifact_count = AnalysisArtifact.objects.count()
    feature_file_count = FeatureFile.objects.count()
    species_with_all_omics = Species.objects.filter(has_genome=True, has_transcriptome=True, has_proteome=True).count()
    grade_counts = {row['grade']: 0 for row in QC_GRADE_RULES}
    default_compare_dataset_count = 0
    for ds in OmicsDataset.objects.only('row_count_core', 'row_count_full', 'status', 'schema_version'):
        qc = _qc_grade_from_dataset_values(
            row_count_core=ds.row_count_core,
            row_count_full=ds.row_count_full,
            status=ds.status,
            schema_version=ds.schema_version,
        )
        grade_counts[qc['qc_grade']] = grade_counts.get(qc['qc_grade'], 0) + 1
        if qc['default_compare_eligible']:
            default_compare_dataset_count += 1

    coverage_rows = list(
        OmicsDataset.objects
        .values('omics_type')
        .annotate(
            dataset_count=Count('id'),
            row_count=Sum(Coalesce('row_count_full', 'row_count_core', 0)),
        )
    )
    coverage_map = {row['omics_type']: row for row in coverage_rows}
    artifact_rows_by_omics = list(
        AnalysisArtifact.objects
        .values('omics_type')
        .annotate(artifact_count=Count('id'))
    )
    artifact_map = {row['omics_type']: int(row['artifact_count']) for row in artifact_rows_by_omics}

    omics_coverage = []
    for omics in omics_meta().keys():
        row = coverage_map.get(omics, {})
        omics_coverage.append({
            'omics': omics,
            'dataset_count': int(row.get('dataset_count') or 0),
            'row_count': int(row.get('row_count') or 0),
            'artifact_count': int(artifact_map.get(omics, 0)),
        })

    core_full_scope_rows = []
    core_full_scope_totals = list(
        OmicsDataset.objects
        .values('omics_type')
        .annotate(
            core_rows=Sum('row_count_core'),
            full_rows=Sum('row_count_full'),
            dataset_count=Count('id'),
        )
        .order_by('omics_type')
    )
    for row in core_full_scope_totals:
        core_rows = int(row.get('core_rows') or 0)
        full_rows = int(row.get('full_rows') or 0)
        core_full_scope_rows.append({
            'omics': row.get('omics_type') or '',
            'dataset_count': int(row.get('dataset_count') or 0),
            'core_rows': core_rows,
            'full_rows': full_rows,
            'delta': max(0, full_rows - core_rows),
            'delta_ratio': round(_safe_div(max(0, full_rows - core_rows), full_rows) * 100.0, 4),
        })

    source_file_types = list(
        FeatureFile.objects.values('file_type').annotate(
            count=Count('id'),
            total_bytes=Sum('size_bytes'),
        ).order_by('-count', 'file_type')
    )
    artifact_types = list(
        AnalysisArtifact.objects.values('artifact_type').annotate(
            count=Count('id'),
        ).order_by('-count', 'artifact_type')
    )

    per_species_dataset_rows = list(
        OmicsDataset.objects
        .values(
            'species_id',
            'species__display_name',
            'species__source_database',
            'species__assembly_version',
        )
        .annotate(
            dataset_count=Count('id'),
            entity_row_count=Sum(Coalesce('row_count_full', 'row_count_core', 0)),
        )
        .order_by('-entity_row_count')
    )
    per_species_artifact_rows = list(
        AnalysisArtifact.objects
        .values('species_id')
        .annotate(artifact_count=Count('id'))
    )
    artifact_by_species = {row['species_id']: int(row['artifact_count']) for row in per_species_artifact_rows}
    species_heaviest = []
    for row in per_species_dataset_rows:
        total_rows = int(row.get('entity_row_count') or 0)
        if total_rows <= 0:
            continue
        source_context = _species_context_label({
            'source_database': row.get('species__source_database'),
            'assembly_version': row.get('species__assembly_version'),
        })
        species_heaviest.append({
            'species_id': row.get('species_id') or '',
            'display_name': row.get('species__display_name') or row.get('species_id') or '',
            'source_context': source_context,
            'dataset_count': int(row.get('dataset_count') or 0),
            'entity_row_count': total_rows,
            'artifacts': int(artifact_by_species.get(row.get('species_id'), 0)),
        })

    combo_counts = {
        'genome_only': Species.objects.filter(has_genome=True, has_transcriptome=False, has_proteome=False).count(),
        'genome_transcriptome': Species.objects.filter(has_genome=True, has_transcriptome=True, has_proteome=False).count(),
        'all_three': Species.objects.filter(has_genome=True, has_transcriptome=True, has_proteome=True).count(),
        'transcriptome_proteome_only': Species.objects.filter(has_genome=False, has_transcriptome=True, has_proteome=True).count(),
        'other': Species.objects.filter(has_genome=False, has_transcriptome=False, has_proteome=False).count(),
    }
    join_coverage_sankey = {
        'nodes': [
            {'name': 'All species'},
            {'name': 'Genome available'},
            {'name': 'Genome+Transcriptome'},
            {'name': 'All 3 omics'},
            {'name': 'Genome-only'},
            {'name': 'Genome+Transcriptome only'},
        ],
        'links': [
            {'source': 'All species', 'target': 'Genome available', 'value': int(combo_counts['genome_only'] + combo_counts['genome_transcriptome'] + combo_counts['all_three'])},
            {'source': 'Genome available', 'target': 'Genome-only', 'value': int(combo_counts['genome_only'])},
            {'source': 'Genome available', 'target': 'Genome+Transcriptome', 'value': int(combo_counts['genome_transcriptome'] + combo_counts['all_three'])},
            {'source': 'Genome+Transcriptome', 'target': 'Genome+Transcriptome only', 'value': int(combo_counts['genome_transcriptome'])},
            {'source': 'Genome+Transcriptome', 'target': 'All 3 omics', 'value': int(combo_counts['all_three'])},
        ],
    }

    field_groups = {
        'genome': ['exon_gc_percent', 'promoter_gc_percent', 'gc_delta_promoter_minus_exon', 'exon_atoms_N_per_base', 'stoich_island_score'],
        'transcriptome': ['gc_percent_display', 'gc_content', 'nt_entropy', 'atoms_per_nt_N', 'coding_density_proxy', 'rna_orf_coupling_score'],
        'proteome': ['N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy', 'resource_budget_score'],
    }
    x_labels = []
    for omics_key in ['genome', 'transcriptome', 'proteome']:
        for field in field_groups[omics_key]:
            if field not in x_labels:
                x_labels.append(field)
    y_labels = ['genome', 'transcriptome', 'proteome']
    field_values = []
    missing_values = []
    field_details = []
    missing_details = []
    sample_limit = 12000
    for y_index, omics_key in enumerate(y_labels):
        sample_summaries = list(
            EntityRecord.objects
            .filter(omics_type=omics_key)
            .values_list('numeric_summary', flat=True)[:sample_limit]
            .iterator(chunk_size=4000)
        )
        total = len(sample_summaries)
        present_counts = {field: 0 for field in x_labels}
        if total:
            for summary in sample_summaries:
                payload = summary or {}
                for field in x_labels:
                    if _safe_num(payload.get(field)) is not None:
                        present_counts[field] += 1
        for x_index, field in enumerate(x_labels):
            present = int(present_counts.get(field, 0))
            ratio = _safe_div(present, total)
            field_values.append([x_index, y_index, round(ratio, 6)])
            missing_values.append([x_index, y_index, round(1.0 - ratio, 6)])
            detail = {
                'field': field,
                'omics': omics_key,
                'present_count': present,
                'total': total,
                'coverage_ratio': round(ratio, 6),
                'missing_ratio': round(1.0 - ratio, 6),
                'reason': 'not populated in sampled rows' if total and present == 0 else '',
            }
            field_details.append(detail)
            missing_details.append(detail)

    core_full_gap = []
    for ds in (
        OmicsDataset.objects
        .filter(row_count_full__gt=0)
        .values('dataset_id', 'species__species_id', 'species__display_name', 'omics_type', 'row_count_core', 'row_count_full')
        .iterator(chunk_size=5000)
    ):
        core = int(ds.get('row_count_core') or 0)
        full = int(ds.get('row_count_full') or 0)
        if full <= 0:
            continue
        delta = max(0, full - core)
        if delta <= 0:
            continue
        core_full_gap.append({
            'dataset_id': ds.get('dataset_id') or '',
            'species_id': ds.get('species__species_id') or '',
            'species_name': ds.get('species__display_name') or ds.get('species__species_id') or '',
            'omics': ds.get('omics_type') or '',
            'row_count_core': core,
            'row_count_full': full,
            'delta': delta,
            'delta_ratio': round(_safe_div(delta, full) * 100.0, 4),
        })
    core_full_gap.sort(key=lambda item: item['delta'], reverse=True)

    source_edges = list(
        FeatureFile.objects
        .values('file_type', 'dataset__omics_type')
        .annotate(count=Count('id'))
        .order_by('file_type', 'dataset__omics_type')
    )
    artifact_edges = list(
        AnalysisArtifact.objects
        .values('omics_type', 'artifact_type')
        .annotate(count=Count('id'))
        .order_by('omics_type', 'artifact_type')
    )
    provenance_nodes = [{'name': 'Source files'}]
    for row in source_edges:
        provenance_nodes.append({'name': f"File:{row.get('file_type') or 'unknown'}"})
        provenance_nodes.append({'name': f"Omics:{row.get('dataset__omics_type') or 'unknown'}"})
    for row in artifact_edges:
        provenance_nodes.append({'name': f"Artifact:{row.get('artifact_type') or 'unknown'}"})
    node_seen = set()
    dedup_nodes = []
    for row in provenance_nodes:
        name = row['name']
        if name in node_seen:
            continue
        node_seen.add(name)
        dedup_nodes.append({'name': name})
    provenance_links = []
    for row in source_edges:
        file_name = f"File:{row.get('file_type') or 'unknown'}"
        omics_name = f"Omics:{row.get('dataset__omics_type') or 'unknown'}"
        provenance_links.append({'source': 'Source files', 'target': file_name, 'value': int(row.get('count') or 0)})
        provenance_links.append({'source': file_name, 'target': omics_name, 'value': int(row.get('count') or 0)})
    for row in artifact_edges:
        omics_name = f"Omics:{row.get('omics_type') or 'unknown'}"
        artifact_name = f"Artifact:{row.get('artifact_type') or 'unknown'}"
        provenance_links.append({'source': omics_name, 'target': artifact_name, 'value': int(row.get('count') or 0)})

    return {
        'release': current_release(),
        'qc_grade_rules': QC_GRADE_RULES,
        'qc_grade_summary': [
            {'grade': grade, 'dataset_count': count, 'default_compare_eligible': grade in {'A', 'B'}}
            for grade, count in grade_counts.items()
        ],
        'summary': {
            'species_count': species_count,
            'dataset_count': dataset_count,
            'entity_row_count': entity_row_count,
            'artifact_count': artifact_count,
            'feature_file_count': feature_file_count,
            'species_with_all_omics': species_with_all_omics,
            'default_compare_dataset_count': default_compare_dataset_count,
        },
        'omics_coverage': omics_coverage,
        'core_full_scope_rows': core_full_scope_rows,
        'source_file_types': source_file_types,
        'artifact_types': artifact_types,
        'species_heaviest': species_heaviest[:20],
        'field_coverage_matrix': {
            'x_labels': x_labels,
            'y_labels': y_labels,
            'values': field_values,
            'details': field_details,
            'method_metadata': {
                'method': 'sampled numeric_summary coverage',
                'n_entities_per_omics_max': sample_limit,
                'normalization': 'present_count / sampled_rows',
                'missing_policy': 'numeric fields absent or non-finite are treated as missing',
                'is_exploratory': False,
            },
        },
        'missingness_matrix': {
            'x_labels': x_labels,
            'y_labels': y_labels,
            'values': missing_values,
            'details': missing_details,
            'method_metadata': {
                'method': '1 - sampled numeric_summary coverage',
                'n_entities_per_omics_max': sample_limit,
                'normalization': 'missing_count / sampled_rows',
                'missing_policy': 'numeric fields absent or non-finite are treated as missing',
                'is_exploratory': False,
            },
        },
        'join_coverage_sankey': join_coverage_sankey,
        'core_full_gap': core_full_gap[:30],
        'provenance_flow': {
            'nodes': dedup_nodes,
            'links': provenance_links,
        },
        'id_mapping_qc': {
            'manifest': _id_mapping_json('id_mapping_manifest.json'),
            'summary': _id_mapping_json('id_mapping_qc_summary.json').get('global', {}),
            'top_species': (_id_mapping_json('id_mapping_qc_summary.json').get('per_species') or [])[:20],
            'final_whitelist': {
                'manifest': _id_mapping_json('final_whitelist/final_whitelist_id_mapping_manifest.json'),
                'online_external_manifest': _id_mapping_json('final_whitelist/online_external/final_whitelist_online_external_id_mapping_manifest.json'),
                'offset_index_summary': {
                    'schema_version': _id_mapping_json('final_whitelist/final_whitelist_external_offsets.json').get('schema_version'),
                    'runtime_seconds': _id_mapping_json('final_whitelist/final_whitelist_external_offsets.json').get('runtime_seconds'),
                    'groups': _id_mapping_json('final_whitelist/final_whitelist_external_offsets.json').get('groups'),
                },
            },
            'endpoints': [
                '/api/stoichdb/id-mapping/resolve/',
                '/api/stoichdb/id-mapping/search/',
                '/api/stoichdb/case-studies/case2/id-mapping/',
            ],
        },
        'functional_annotation_qc': function_annotations.quality_payload(),
        'phylogeny_qc': phylogeny.validation_payload() if phylogeny.release_payload().get('available') else {},
    }


def quality_species(species_id: str) -> dict[str, Any]:
    detail = species_detail(species_id)
    if not db_mode():
        return {
            'species': detail,
            'qc_grade_rules': QC_GRADE_RULES,
            'omics_qc': [],
        }
    species = Species.objects.get(species_id=species_id)
    omics_qc = []
    for ds in OmicsDataset.objects.filter(species=species).prefetch_related('feature_files').order_by('omics_type'):
        feature_file_count = ds.feature_files.count()
        qc = _qc_grade_from_dataset_values(
            row_count_core=ds.row_count_core,
            row_count_full=ds.row_count_full,
            status=ds.status,
            schema_version=ds.schema_version,
            feature_file_count=feature_file_count,
        )
        omics_qc.append({
            'omics': ds.omics_type,
            'dataset_id': ds.dataset_id,
            'row_count_core': ds.row_count_core,
            'row_count_full': ds.row_count_full,
            'status': ds.status,
            'schema_version': ds.schema_version,
            'feature_file_count': feature_file_count,
            'artifact_count': AnalysisArtifact.objects.filter(dataset=ds).count(),
            **qc,
            'files': [_file_payload(record) for record in ds.feature_files.all()],
        })
    return {
        'species': detail,
        'qc_grade_rules': QC_GRADE_RULES,
        'omics_qc': omics_qc,
    }


@lru_cache(maxsize=64)
def downloads_manifest(species_id: str = '', omics: str = '', dataset_limit: Any = '', artifact_limit: Any = '') -> dict[str, Any]:
    if not db_mode():
        return {
            'release': current_release(),
            'filters': {'species_id': species_id, 'omics': omics},
            'datasets': [],
            'artifacts': [],
            'annotation_downloads': function_annotations.downloads_payload(),
            'phylogeny_downloads': phylogeny.downloads_payload(),
        }
    release = current_release()
    release_id = release.get('release_id', '')
    ds_qs = (
        OmicsDataset.objects
        .select_related('species')
        .only(
            'dataset_id',
            'species__species_id',
            'species__display_name',
            'species__source_database',
            'species__assembly_version',
            'omics_type',
            'schema_version',
            'row_count_core',
            'row_count_full',
            'status',
        )
        .prefetch_related(
            Prefetch(
                'feature_files',
                queryset=FeatureFile.objects.only('dataset_id', 'file_id', 'file_type', 'path', 'size_bytes'),
            )
        )
        .order_by('species__display_name', 'omics_type')
    )
    if species_id:
        ds_qs = ds_qs.filter(species__species_id=species_id)
    if omics:
        ds_qs = ds_qs.filter(omics_type=omics)
    dataset_total = ds_qs.count()
    try:
        dataset_limit_int = max(1, min(1000, int(dataset_limit or (1000 if species_id else 300))))
    except Exception:
        dataset_limit_int = 1000 if species_id else 300
    ds_iter = ds_qs if species_id else ds_qs[:dataset_limit_int]

    datasets = []
    for ds in ds_iter:
        feature_files = []
        for record in ds.feature_files.all():
            record._state.fields_cache['dataset'] = ds
            feature_files.append(_file_payload(record, check_exists=False))
        qc = _qc_grade_from_dataset_values(
            row_count_core=ds.row_count_core,
            row_count_full=ds.row_count_full,
            status=ds.status,
            schema_version=ds.schema_version,
            feature_file_count=len(feature_files),
        )
        datasets.append({
            'dataset_id': ds.dataset_id,
            'species_id': ds.species.species_id,
            'species_name': ds.species.display_name,
            'omics': ds.omics_type,
            'schema_version': ds.schema_version,
            'row_count_core': ds.row_count_core,
            'row_count_full': ds.row_count_full,
            'status': ds.status,
            'release_id': release_id,
            'source': 'OmicsDataset',
            'generated_at': '',
            **qc,
            'source_context': _species_context_label(ds.species),
            'downloads_route': _download_page_route(ds.species.species_id, ds.omics_type),
            'source_page_route': _download_page_route(ds.species.species_id, ds.omics_type),
            'feature_files': feature_files,
        })

    artifact_qs = (
        AnalysisArtifact.objects
        .select_related('species')
        .only(
            'artifact_id',
            'species__species_id',
            'species__display_name',
            'omics_type',
            'artifact_type',
            'path',
            'version',
            'created_at',
        )
        .order_by('species__display_name', 'omics_type', 'artifact_type')
    )
    release_source_database = _release_species_source_database(release_id)
    if release_source_database:
        artifact_qs = artifact_qs.filter(species__source_database=release_source_database)
    if species_id:
        artifact_qs = artifact_qs.filter(species__species_id=species_id)
    if omics:
        artifact_qs = artifact_qs.filter(omics_type=omics)
    artifact_total = artifact_qs.count()
    try:
        artifact_limit_int = max(1, min(1000, int(artifact_limit or (1000 if species_id else 300))))
    except Exception:
        artifact_limit_int = 1000 if species_id else 300
    artifact_iter = artifact_qs if species_id else artifact_qs[:artifact_limit_int]

    final_mapping_downloads = []
    final_root = ID_MAPPING_DIR / 'final_whitelist'
    for division, label in [
        ('bacteria', 'Bacteria final-whitelist'),
        ('fungi', 'Fungi final-whitelist'),
        ('metazoa', 'Metazoa final-whitelist'),
        ('plants', 'Plants final-whitelist'),
        ('vertebrates', 'Vertebrates final-whitelist'),
    ]:
        group_dir = final_root / division
        for kind, suffix, desc in [
            ('omics', 'omics_id_mapping_final_whitelist.csv', 'Full coding gene-transcript-protein ID chain table for final-whitelist species.'),
            ('external', 'external_id_mapping_final_whitelist.csv', 'Full internal-to-UniProt/NCBI/RefSeq/INSDC mapping table for final-whitelist species.'),
            ('qc', 'id_mapping_species_qc.csv', 'Per-species ID mapping QC summary for final-whitelist species.'),
            ('manifest', 'id_mapping_summary.json', 'Division-level row counts, source whitelist, and generation summary.'),
        ]:
            path = group_dir / f'{division}_{suffix}'
            final_mapping_downloads.append({
                'label': f'{label} {kind} ID mapping',
                'kind': kind,
                'division': division,
                'description': desc,
                'url': f'/api/stoichdb/downloads/id-mapping/?kind={kind}&division={division}',
                'size_bytes': path.stat().st_size if path.exists() else 0,
            })
        online_dir = final_root / 'online_external' / division
        for kind, filename, desc in [
            ('online_accession', f'{division}_uniprot_online_accession_map.csv', 'UniProt REST accession-level mapping to NCBI Gene and RefSeq Protein.'),
            ('external_long', f'{division}_external_id_mapping_long_final_whitelist.csv', 'Long-format external ID assertions for downstream external_id_mapping import.'),
            ('online_qc', f'{division}_online_external_id_mapping_species_qc.csv', 'Per-species QC for online/local external standard ID coverage.'),
            ('species_standard', f'{division}_species_standard_ids.csv', 'Species-level NCBI Taxonomy and assembly standard IDs.'),
            ('online_summary', f'{division}_online_external_id_mapping_summary.json', 'Division-level online external ID enrichment summary.'),
        ]:
            path = online_dir / filename
            final_mapping_downloads.append({
                'label': f'{label} {kind}',
                'kind': kind,
                'division': division,
                'description': desc,
                'url': f'/api/stoichdb/downloads/id-mapping/?kind={kind}&division={division}',
                'size_bytes': path.stat().st_size if path.exists() else 0,
            })
        standard_dir = ID_MAPPING_DIR / 'standard_external_id_overlay' / division
        for kind, filename, desc in [
            ('standard_overlay_index', f'{division}_standard_id_overlay_index.csv', 'Per-species index for the enhanced standard external-ID overlay from GFF3 and UniProt.'),
            ('standard_overlay_online_accession', f'{division}_uniprot_online_accession_map.csv', 'Enhanced UniProt accession-level online mapping to NCBI Gene and RefSeq Protein.'),
        ]:
            path = standard_dir / filename
            final_mapping_downloads.append({
                'label': f'{label} {kind}',
                'kind': kind,
                'division': division,
                'description': desc,
                'url': f'/api/stoichdb/downloads/id-mapping/?kind={kind}&division={division}',
                'size_bytes': path.stat().st_size if path.exists() else 0,
            })
    for kind, filename, desc in [
        ('final_manifest', 'final_whitelist_id_mapping_manifest.json', 'Global final-whitelist ID mapping manifest.'),
        ('final_offsets', 'final_whitelist_external_offsets.json', 'Runtime byte-offset index for species-scoped final-whitelist lookup.'),
        ('final_online_manifest', 'online_external/final_whitelist_online_external_id_mapping_manifest.json', 'Global online external standard ID enrichment manifest.'),
        ('final_online_report', 'online_external/final_whitelist_online_external_id_mapping_result_report.md', 'Human-readable online external standard ID enrichment report.'),
        ('standard_overlay_manifest', '../standard_external_id_overlay/standard_external_id_overlay_manifest.json', 'Global standard external-ID overlay manifest from GFF3 plus UniProt online enrichment.'),
        ('standard_overlay_report', '../standard_external_id_overlay/standard_external_id_overlay_result_report.md', 'Human-readable standard external-ID overlay result report.'),
    ]:
        path = (ID_MAPPING_DIR / 'standard_external_id_overlay' / Path(filename).name) if filename.startswith('../standard_external_id_overlay/') else final_root / filename
        final_mapping_downloads.append({
            'label': filename,
            'kind': kind,
            'division': 'all_final_whitelist',
            'description': desc,
            'url': f'/api/stoichdb/downloads/id-mapping/?kind={kind}',
            'size_bytes': path.stat().st_size if path.exists() else 0,
        })

    return {
        'release': release,
        'filters': {'species_id': species_id, 'omics': omics},
        'limits': {
            'dataset_total': dataset_total,
            'dataset_returned': len(datasets),
            'dataset_limited': dataset_total > len(datasets),
            'artifact_total': artifact_total,
            'artifact_limit': artifact_limit_int,
            'artifact_limited': artifact_total > artifact_limit_int and not species_id,
        },
        'datasets': datasets,
        'artifacts': [_artifact_payload(record, check_exists=False, release_id=release_id, include_payload_metadata=False) for record in artifact_iter],
        'id_mapping_downloads': [
            {
                'label': 'All species internal G-T-P ID mapping',
                'kind': 'omics',
                'description': 'Full gene-transcript-protein mapping table with status, confidence, and conflict flags.',
                'url': '/api/stoichdb/downloads/id-mapping/?kind=omics',
                'size_bytes': (ID_MAPPING_DIR / 'protist_omics_id_mapping_all_species.csv').stat().st_size if (ID_MAPPING_DIR / 'protist_omics_id_mapping_all_species.csv').exists() else 0,
            },
            {
                'label': 'All species external standard ID mapping',
                'kind': 'external',
                'description': 'Full internal-to-UniProt/NCBI/RefSeq/INSDC mapping table with evidence fields.',
                'url': '/api/stoichdb/downloads/id-mapping/?kind=external',
                'size_bytes': (ID_MAPPING_DIR / 'protist_external_id_mapping_all_species.csv').stat().st_size if (ID_MAPPING_DIR / 'protist_external_id_mapping_all_species.csv').exists() else 0,
            },
            {
                'label': 'ID mapping manifest',
                'kind': 'manifest',
                'description': 'Source file hashes, runtime index scope, schema version, and generated table counts.',
                'url': '/api/stoichdb/downloads/id-mapping/?kind=manifest',
                'size_bytes': (ID_MAPPING_DIR / 'id_mapping_manifest.json').stat().st_size if (ID_MAPPING_DIR / 'id_mapping_manifest.json').exists() else 0,
            },
            {
                'label': 'ID mapping QC summary',
                'kind': 'qc',
                'description': 'Per-species mapping coverage, confidence, conflict, and external ID summary.',
                'url': '/api/stoichdb/downloads/id-mapping/?kind=qc',
                'size_bytes': (ID_MAPPING_DIR / 'id_mapping_qc_summary.json').stat().st_size if (ID_MAPPING_DIR / 'id_mapping_qc_summary.json').exists() else 0,
            },
        ] + final_mapping_downloads,
        'annotation_downloads': function_annotations.downloads_payload(),
        'phylogeny_downloads': phylogeny.downloads_payload(),
    }


def artifact_registry(species_id: str = '', omics: str = '', artifact_type: str = '') -> dict[str, Any]:
    if not db_mode():
        return {'items': [], 'artifact_types': [], 'filters': {'species_id': species_id, 'omics': omics, 'artifact_type': artifact_type}}
    release = current_release()
    release_id = release.get('release_id', '')
    qs = (
        AnalysisArtifact.objects
        .select_related('species')
        .only(
            'artifact_id',
            'species__species_id',
            'species__display_name',
            'omics_type',
            'artifact_type',
            'path',
            'version',
            'created_at',
        )
        .order_by('species__display_name', 'omics_type', 'artifact_type', 'artifact_id')
    )
    release_source_database = _release_species_source_database(release_id)
    if release_source_database:
        qs = qs.filter(species__source_database=release_source_database)
    if species_id:
        qs = qs.filter(species__species_id=species_id)
    if omics:
        qs = qs.filter(omics_type=omics)
    if artifact_type:
        qs = qs.filter(artifact_type=artifact_type)
    artifact_types = list(qs.values('artifact_type').annotate(count=Count('id')).order_by('-count', 'artifact_type'))
    return {
        'filters': {'species_id': species_id, 'omics': omics, 'artifact_type': artifact_type},
        'artifact_types': artifact_types,
        'items': [_artifact_payload(record, check_exists=False, release_id=release_id, include_payload_metadata=False) for record in qs[:4000]],
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def materialize_analysis_artifacts() -> dict[str, Any]:
    release = current_release()
    release_id = release.get('release_id') or 'working_release'
    safe_release = ''.join(ch if ch.isalnum() or ch in {'-', '_'} else '_' for ch in str(release_id))
    export_root = Path(settings.BASE_DIR) / 'workspace' / 'generated_analysis_artifacts' / safe_release
    export_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []

    def add_artifact(*, analysis_id: str, species_id: str, omics_type: str, artifact_type: str, payload: dict[str, Any], metadata: dict[str, Any]) -> None:
        relative = Path(species_id or 'registry') / (omics_type or 'cross_omics') / f'{artifact_type}.json'
        target = export_root / relative
        envelope = {
            'analysis_id': analysis_id,
            'artifact_type': artifact_type,
            'species_id': species_id,
            'omics_type': omics_type,
            'release_id': release_id,
            'method_metadata': metadata,
            'payload': payload,
        }
        _write_json(target, envelope)
        rows.append({
            'analysis_id': analysis_id,
            'species_id': species_id,
            'omics_type': omics_type,
            'artifact_type': artifact_type,
            'path': str(target.relative_to(export_root)),
            'method': metadata.get('method', ''),
            'normalization': metadata.get('normalization', ''),
            'missing_policy': metadata.get('missing_policy', ''),
            'n_entities': metadata.get('n_entities', ''),
            'n_features': metadata.get('n_features', ''),
            'n_missing': metadata.get('n_missing', ''),
            'is_exploratory': metadata.get('is_exploratory', False),
        })

    if db_mode():
        species_qs = Species.objects.only('species_id', 'display_name', 'fingerprint', 'cross_omics_payload')
        for species in species_qs.iterator(chunk_size=100):
            fingerprint = species.fingerprint or {}
            add_artifact(
                analysis_id=f'{species.species_id}:species_fingerprint',
                species_id=species.species_id,
                omics_type='',
                artifact_type='species_fingerprint',
                payload={'display_name': species.display_name, 'fingerprint': fingerprint},
                metadata={
                    'method': 'species fingerprint from imported registry summary',
                    'normalization': 'raw',
                    'missing_policy': 'missing fingerprint keys omitted',
                    'n_entities': 1,
                    'n_features': len(fingerprint),
                    'n_missing': 0,
                    'is_exploratory': False,
                },
            )
            cross_payload = species.cross_omics_payload or {}
            if cross_payload:
                add_artifact(
                    analysis_id=f'{species.species_id}:cross_omics',
                    species_id=species.species_id,
                    omics_type='cross_omics',
                    artifact_type='cross_omics_summary',
                    payload=cross_payload,
                    metadata={
                        **(cross_payload.get('method_metadata', {}) if isinstance(cross_payload.get('method_metadata'), dict) else {}),
                        'method': 'cross-omics matched-gene summary',
                        'normalization': 'raw shift/correlation payload',
                        'missing_policy': 'matched genes with available omics fields',
                        'n_entities': (cross_payload.get('join_summary') or {}).get('matched_all_three', ''),
                        'n_features': len(cross_payload.get('correlation_matrix') or {}),
                        'is_exploratory': True,
                    },
                )

        dataset_qs = OmicsDataset.objects.select_related('species').only(
            'species__species_id',
            'omics_type',
            'row_count_core',
            'row_count_full',
            'summary_payload',
            'analysis_payload',
        )
        for dataset in dataset_qs.iterator(chunk_size=100):
            species_id = dataset.species.species_id
            summary_payload = dataset.summary_payload or {}
            analysis_payload = dataset.analysis_payload or {}
            feature_cards = summary_payload.get('feature_cards') if isinstance(summary_payload, dict) else {}
            add_artifact(
                analysis_id=f'{species_id}:{dataset.omics_type}:field_summary',
                species_id=species_id,
                omics_type=dataset.omics_type,
                artifact_type='field_summary',
                payload=summary_payload,
                metadata={
                    'method': 'precomputed field summary from imported feature table',
                    'normalization': 'raw feature units',
                    'missing_policy': 'valid numeric rows only',
                    'n_entities': dataset.row_count_full or dataset.row_count_core,
                    'n_features': len(feature_cards or {}),
                    'n_missing': '',
                    'is_exploratory': False,
                },
            )
            if analysis_payload:
                method_meta = analysis_payload.get('method_metadata') if isinstance(analysis_payload, dict) else {}
                add_artifact(
                    analysis_id=f'{species_id}:{dataset.omics_type}:analysis',
                    species_id=species_id,
                    omics_type=dataset.omics_type,
                    artifact_type='omics_analysis',
                    payload=analysis_payload,
                    metadata={
                        **(method_meta if isinstance(method_meta, dict) else {}),
                        'method': 'registered omics analysis payload',
                        'normalization': 'module-specific',
                        'missing_policy': 'module-specific pairwise/valid rows',
                        'n_entities': dataset.row_count_full or dataset.row_count_core,
                        'n_features': len((summary_payload or {}).get('feature_cards') or {}),
                        'is_exploratory': True,
                    },
                )
    else:
        for species in file_species_map().values():
            species_id = species.get('species_id') or ''
            fingerprint = species.get('fingerprint') or {}
            add_artifact(
                analysis_id=f'{species_id}:species_fingerprint',
                species_id=species_id,
                omics_type='',
                artifact_type='species_fingerprint',
                payload={'display_name': species.get('display_name'), 'fingerprint': fingerprint},
                metadata={
                    'method': 'file-registry species fingerprint',
                    'normalization': 'raw',
                    'missing_policy': 'missing fingerprint keys omitted',
                    'n_entities': 1,
                    'n_features': len(fingerprint),
                    'is_exploratory': False,
                },
            )

    csv_path = export_root / 'analysis_artifact_index.csv'
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ['analysis_id', 'species_id', 'omics_type', 'artifact_type', 'path', 'method', 'normalization', 'missing_policy', 'n_entities', 'n_features', 'n_missing', 'is_exploratory']
    with csv_path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        'release': release,
        'export_root': str(export_root),
        'index_csv': str(csv_path),
        'artifact_count': len(rows),
        'items': rows[:5000],
        'method_metadata_contract': [
            'analysis_id',
            'species_id/omics_type/release_id',
            'feature_set/features_used',
            'normalization',
            'missing_policy',
            'method',
            'n_entities/n_features/n_missing',
            'thresholds',
            'is_exploratory',
        ],
    }
    manifest_path = export_root / 'analysis_artifact_manifest.json'
    _write_json(manifest_path, manifest)
    manifest['manifest_path'] = str(manifest_path)
    return manifest


def api_docs_payload() -> dict[str, Any]:
    return {
        'base_path': '/api/stoichdb/',
        'notes': [
            'All endpoints return the shared response envelope: { ok, data } or { ok, error }.',
            'The formal storage target is PostgreSQL through Django ORM tables; SQLite remains fallback-only for local lightweight testing.',
            'Downloads are exposed as direct file responses from registered feature files and analysis artifacts.',
        ],
        'endpoints': [
            {'method': 'GET', 'path': '/api/stoichdb/home/', 'summary': 'Platform overview, active release, registry counts, and featured species.'},
            {'method': 'GET', 'path': '/api/stoichdb/release/', 'summary': 'Active release, release history, and provenance summary.'},
            {'method': 'GET', 'path': '/api/stoichdb/analysis/hub/', 'summary': 'Stage-4/5 analysis hub payload with real-result modules and explicitly labeled exploratory analyses.'},
            {'method': 'POST', 'path': '/api/stoichdb/analysis/enrichment/', 'summary': 'GO/KEGG same-species over-representation analysis using hypergeometric/Fisher exact p-values and BH-FDR.'},
            {'method': 'GET', 'path': '/api/stoichdb/case-studies/', 'summary': 'Stage-6 internal-data descriptive case-study gallery using current internal data only: cross-species fingerprint atlas, single-species cross-omics coupling, and candidate protein report.'},
            {'method': 'GET', 'path': '/api/stoichdb/case-studies/case1/taxonomy/', 'summary': 'Stage-6 Case 1 advanced taxonomy-aware fingerprint atlas: taxonomy coverage, phylum/class/order group statistics, Kruskal-Wallis plus BH-FDR tables, PCA, clade signatures, taxonomy-proxy distance alignment, and representative/outlier species. This is descriptive taxonomy-aware analysis, not ecological adaptation or phylogenetic signal analysis.'},
            {'method': 'GET', 'path': '/api/stoichdb/case-studies/case2/function-chain/', 'summary': 'Case 2 functional ID chain connecting platform IDs to UniProt, GO, and KEGG standard annotation evidence.'},
            {'method': 'GET', 'path': '/api/stoichdb/case-studies/case3/function-evidence/', 'summary': 'Case 3 candidate entity evidence with GO and KEGG standard annotations.'},
            {'method': 'GET', 'path': '/api/stoichdb/annotations/status/', 'summary': 'Functional annotation coverage status for all species, including unsupported/no-standard-annotation species.'},
            {'method': 'GET', 'path': '/api/stoichdb/annotations/search/', 'summary': 'Search GO/KEGG annotation records by term, entity ID, UniProt accession, or KEGG identifier.'},
            {'method': 'GET', 'path': '/api/stoichdb/phylogeny/releases/', 'summary': 'List P0/P1 phylogeny foundation releases for the platform-screened protist whitelist.'},
            {'method': 'GET', 'path': '/api/stoichdb/phylogeny/releases/<release_id>/tree/', 'summary': 'Return the taxonomy reference topology Newick and species tip mapping preview.'},
            {'method': 'GET', 'path': '/api/stoichdb/phylogeny/releases/<release_id>/validation/', 'summary': 'Return P0/P1 validation, rank completeness, coverage, and branch-length eligibility boundaries.'},
            {'method': 'POST', 'path': '/api/stoichdb/phylogeny/signal/', 'summary': 'Controlled Pagel lambda endpoint. Returns precomputed blockers for the active no-branch-length taxonomy topology, and can run on future analysis-grade branch-length trees.'},
            {'method': 'POST', 'path': '/api/stoichdb/phylogeny/pgls/', 'summary': 'Controlled OLS/PGLS endpoint with formula feature whitelist and branch-length eligibility checks.'},
            {'method': 'GET', 'path': '/api/stoichdb/case-studies/case1/phylogeny/', 'summary': 'Case 1 phylogeny readiness: trait matrix coverage, branch-length blocker, allowed and forbidden interpretations.'},
            {'method': 'GET', 'path': '/api/stoichdb/coverage/', 'summary': 'Six-group registry reconciliation and module-by-module coverage audit, including persistent missing-data reasons and full-scope/artifact/index boundaries.'},
            {'method': 'GET', 'path': '/api/stoichdb/quality/', 'summary': 'Registry-wide QC and completeness metrics.'},
            {'method': 'GET', 'path': '/api/stoichdb/quality/<species_id>/', 'summary': 'Species-level QC, source files, and omics readiness.'},
            {'method': 'GET', 'path': '/api/stoichdb/meta/features/', 'summary': 'Feature Dictionary with field formula, formula_status, unit, normalization, missing rule, coverage/missing rate, module group, and schema_version.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/', 'summary': 'Species registry listing with omics/fingerprint filters.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/facets/', 'summary': 'Facet values for registry search UI.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/', 'summary': 'Species overview, omics cards, source links, and release context.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/enhanced/', 'summary': 'Enhanced species-level visuals: coordinate hotspots, shift distributions, transition links, and global ranks.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/functional-summary/', 'summary': 'Species-level GO/KEGG annotation summary and top terms.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/phylogeny/', 'summary': 'Per-species P0/P1 phylogeny context: tip label, TaxID, lineage, and topology/PGLS eligibility flags.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/annotations/go/', 'summary': 'Paged GO annotation rows with namespace and text filters.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/annotations/kegg/', 'summary': 'Paged KEGG gene annotations or KO/pathway/module links.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/entities/<entity_key>/function/', 'summary': 'Entity-level GO/KEGG evidence matched through internal and external IDs.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/<omics>/panel/', 'summary': 'Combined summary + analysis payload for a single omics panel.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/<omics>/field-summary/', 'summary': 'On-demand descriptive statistics and histogram for any selected feature field.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/<omics>/scatter/', 'summary': 'On-demand pairwise scatter payload for user-selected x/y features.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/<omics>/rows/', 'summary': 'Entity-level feature-table browsing with filters and pagination.'},
            {'method': 'GET', 'path': '/api/stoichdb/species/<species_id>/<omics>/rows/<entity_id>/', 'summary': 'Detailed row payload with linked entities.'},
            {'method': 'GET', 'path': '/api/stoichdb/downloads/', 'summary': 'Dataset source files and analysis artifact registry with release_id, schema_version, checksum, source, generated_at, and QC grade traceability.'},
            {'method': 'GET', 'path': '/api/stoichdb/downloads/artifacts/', 'summary': 'Artifact-centric registry with filters.'},
            {'method': 'POST', 'path': '/api/stoichdb/downloads/artifacts/materialize/', 'summary': 'Materialize reusable analysis artifact JSON files and a CSV manifest under workspace/generated_analysis_artifacts.'},
            {'method': 'GET', 'path': '/api/stoichdb/downloads/files/<file_id>/', 'summary': 'Direct download of a registered source file.'},
            {'method': 'GET', 'path': '/api/stoichdb/downloads/artifacts/<artifact_id>/', 'summary': 'Direct download of a registered artifact file.'},
            {'method': 'GET', 'path': '/api/stoichdb/downloads/annotations/<kind>/', 'summary': 'Direct download of functional annotation source files.'},
            {'method': 'GET', 'path': '/api/stoichdb/docs/', 'summary': 'API reference and data dictionary payload.'},
        ],
    }


def data_dictionary_payload() -> dict[str, Any]:
    omics_dictionary = []
    for key, meta in omics_meta().items():
        omics_dictionary.append({
            'omics': key,
            'display_name': meta.get('display_name'),
            'entity_label': meta.get('entity_label'),
            'primary_id': meta.get('primary_id'),
            'fallback_id': meta.get('fallback_id'),
            'browse_columns': meta.get('browse_columns') or [],
            'feature_options': meta.get('feature_options') or [],
            'analysis_modules': meta.get('analysis_modules') or [],
            'description': meta.get('description', ''),
        })
    return {
        'core_models': [
            {'name': 'DataRelease', 'description': 'Formal release registration with counts, paths, manifest, and active state.'},
            {'name': 'Species', 'description': 'Species-level registry identity, source context, omics availability, fingerprint, and cross-omics payload.'},
            {'name': 'OmicsDataset', 'description': 'One genome/transcriptome/proteome dataset per species, including summary and analysis payloads.'},
            {'name': 'FeatureFile', 'description': 'Registered raw/core/full feature-table files associated with an omics dataset.'},
            {'name': 'EntityRecord', 'description': 'Entity-level JSON payloads for genes, transcripts, and proteins used in browsing and search.'},
            {'name': 'AnalysisArtifact', 'description': 'Derived analysis outputs linked to species and optionally to an omics dataset.'},
            {'name': 'FunctionalAnnotationRelease', 'description': 'GO/KEGG annotation bundle release, source provenance, and row counts.'},
            {'name': 'SpeciesFunctionalAnnotationStatus', 'description': 'Per-species GO/KEGG availability and explicit unsupported/no-standard-annotation status.'},
            {'name': 'GOTerm', 'description': 'GO ID, namespace, term name, definition, and obsolete flag.'},
            {'name': 'GOAnnotation', 'description': 'Entity-level GO annotations joined to platform IDs and UniProt accessions.'},
            {'name': 'KEGGGeneAnnotation', 'description': 'Entity-level KEGG gene annotation records with KO/pathway/module compact fields.'},
            {'name': 'KEGGAnnotationLink', 'description': 'Long-form KEGG KO/pathway/module annotation links for enrichment and filtering.'},
            {'name': 'FunctionalEnrichmentResult', 'description': 'Persistable functional enrichment result contract with query, universe, and method metadata.'},
        ],
        'omics_dictionary': omics_dictionary,
        'release_fields': [
            'release_id',
            'label',
            'description',
            'source_root',
            'pipeline_root',
            'platform_registry_path',
            'database_engine',
            'species_count',
            'dataset_count',
            'entity_row_count',
            'artifact_count',
            'feature_file_count',
            'metadata',
            'manifest',
        ],
    }


def docs_payload() -> dict[str, Any]:
    return {
        'release': current_release(),
        'api': api_docs_payload(),
        'dictionary': data_dictionary_payload(),
        'feature_dictionary': feature_catalog_payload(),
        'id_mapping': {
            'manifest': _id_mapping_json('id_mapping_manifest.json'),
            'schema': _id_mapping_json('id_mapping_schema.json'),
            'final_whitelist_manifest': _id_mapping_json('final_whitelist/final_whitelist_id_mapping_manifest.json'),
            'final_whitelist_runtime': {
                'mode': 'species-scoped byte-offset CSV lookup',
                'offset_index': 'data/id_mapping/final_whitelist/final_whitelist_external_offsets.json',
                'scope': 'bacteria, fungi, metazoa, plants, vertebrates final-whitelist coding ID chains',
                'requirement': 'Pass species_id for complete final-whitelist lookup; unscoped global lookup remains backed by the smaller SQLite runtime index.',
            },
            'final_whitelist_online_external': {
                'manifest': _id_mapping_json('final_whitelist/online_external/final_whitelist_online_external_id_mapping_manifest.json'),
                'runtime_overlay': 'UniProt online accession maps are loaded per division and merged into species-scoped final-whitelist lookup aliases.',
                'scope': 'External standard ID enrichment only; full omics ID chain expansion is not regenerated here.',
            },
            'endpoints': [
                {'method': 'GET', 'path': '/api/stoichdb/id-mapping/resolve/', 'params': 'query, species_id, limit', 'purpose': 'Resolve one internal or external ID to candidate platform entities.'},
                {'method': 'POST', 'path': '/api/stoichdb/id-mapping/batch-resolve/', 'params': 'queries, species_id, limit_per_query', 'purpose': 'Resolve uploaded or pasted ID lists.'},
                {'method': 'GET', 'path': '/api/stoichdb/id-mapping/search/', 'params': 'query, species_id, id_type, mapping_confidence, mapping_status, mapping_level, external_status, conflict_only', 'purpose': 'Search alias index with ID mapping filters.'},
                {'method': 'GET', 'path': '/api/stoichdb/species/{species_id}/id-mapping/summary/', 'purpose': 'Per-species ID mapping QC summary.'},
                {'method': 'GET', 'path': '/api/stoichdb/species/{species_id}/id-mapping/conflicts/', 'purpose': 'Conflict rows retained for diagnostics.'},
                {'method': 'GET', 'path': '/api/stoichdb/species/{species_id}/entities/{entity_key}/mapping/', 'purpose': 'Entity-level gene-transcript-protein-external ID evidence chain.'},
                {'method': 'GET', 'path': '/api/stoichdb/case-studies/case2/id-mapping/', 'purpose': 'Case 2 advanced ID mapping payload.'},
                {'method': 'GET', 'path': '/api/stoichdb/downloads/id-mapping/', 'params': 'kind=omics|external|manifest|qc|preview|online_accession|external_long|online_qc|species_standard|online_summary|final_online_manifest|final_online_report, species_id, division=bacteria|fungi|metazoa|plants|vertebrates', 'purpose': 'Download ID mapping files.'},
            ],
            'status_semantics': {
                'ok': 'Internal mapping checks passed.',
                'conflict': 'Mapping row is retained but should be displayed with warning and excluded from strict high-confidence interpretation.',
            },
            'confidence_semantics': {
                'high': 'Direct ID evidence and consistency checks support the mapping.',
                'medium': 'Partial chain or species/region-level evidence is available.',
                'low': 'Internal row remains searchable but should not be treated as decisive evidence.',
            },
        },
        'functional_annotations': function_annotations.docs_payload(),
        'phylogeny': phylogeny.docs_payload(),
        'data_contracts': [
            {'name': 'feature_dictionary', 'path': 'backend/apps/stoichdb/resources/feature_dictionary.json', 'purpose': 'Canonical feature formula, normalization, missing-rule, and schema-version overlay.'},
            {'name': 'summary', 'path': 'backend/apps/stoichdb/schemas/summary.schema.json', 'purpose': 'Minimum contract for per-omics summary payloads.'},
            {'name': 'analysis', 'path': 'backend/apps/stoichdb/schemas/analysis.schema.json', 'purpose': 'Minimum contract for per-omics analysis payloads.'},
            {'name': 'cross_omics', 'path': 'backend/apps/stoichdb/schemas/cross_omics.schema.json', 'purpose': 'Minimum contract for species-level cross-omics payloads.'},
            {'name': 'rows', 'path': 'backend/apps/stoichdb/schemas/rows.schema.json', 'purpose': 'Minimum contract for entity-row JSON arrays.'},
            {'name': 'id_mapping_layer', 'path': 'data/id_mapping/id_mapping_schema.json', 'purpose': 'Runtime ID resolution schema, alias index fields, status/confidence semantics, and source-file manifest.'},
            {'name': 'functional_annotation_layer', 'path': 'data/function_annotations or FUNCTION_ANNOTATION_SOURCE', 'purpose': 'Official GO/KEGG annotation bundle and same-species enrichment universe.'},
        ],
    }


def resolve_feature_file(file_id: str) -> Path:
    if not db_mode():
        raise NotFoundError('File downloads are only available in database-backed mode.')
    try:
        record = FeatureFile.objects.get(file_id=file_id)
    except FeatureFile.DoesNotExist as exc:
        raise NotFoundError(f'Unknown file_id: {file_id}') from exc
    resolved = _resolve_existing_path(record.path)
    if not resolved:
        raise NotFoundError(f'Registered file is missing on disk: {record.path}')
    return resolved


def resolve_artifact_file(artifact_id: str) -> Path:
    if not db_mode():
        raise NotFoundError('Artifact downloads are only available in database-backed mode.')
    try:
        record = AnalysisArtifact.objects.get(artifact_id=artifact_id)
    except AnalysisArtifact.DoesNotExist as exc:
        raise NotFoundError(f'Unknown artifact_id: {artifact_id}') from exc
    resolved = _resolve_existing_path(record.path)
    if not resolved:
        raise NotFoundError(f'Registered artifact is missing on disk: {record.path}')
    return resolved


def default_module_results() -> list[dict[str, str]]:
    return [
        {'kind': 'module', 'label': 'Species registry', 'summary': 'Browse and filter the curated species database.', 'route': '/database'},
        {'kind': 'module', 'label': 'Release registry', 'summary': 'Inspect the active PostgreSQL release, provenance, and import manifest.', 'route': '/release'},
        {'kind': 'module', 'label': 'Quality control', 'summary': 'Review completeness, QC coverage, and registry health indicators.', 'route': '/quality'},
        {'kind': 'module', 'label': 'Downloads', 'summary': 'Open source files, analysis artifacts, and dataset download links.', 'route': '/downloads'},
        {'kind': 'module', 'label': 'API and docs', 'summary': 'Browse API routes, data dictionary, and schema notes.', 'route': '/docs'},
        {'kind': 'module', 'label': 'Visualization hub', 'summary': 'Open foundational genome, transcriptome, and proteome visualizations.', 'route': '/visualization'},
        {'kind': 'module', 'label': 'Analysis hub', 'summary': 'Inspect strategy typing, outliers, trade-offs, and coupling modules.', 'route': '/analysis'},
        {'kind': 'module', 'label': 'Functional annotations', 'summary': 'Review official GO/KEGG coverage and enrichment-ready annotation files.', 'route': '/analysis'},
        {'kind': 'module', 'label': 'User workflows', 'summary': 'Run your own sequence-oriented data through platform workflows.', 'route': '/jobs'},
    ]


def module_results_for_query(q: str) -> list[dict[str, str]]:
    modules = [
        {'kind': 'module', 'label': 'Home overview', 'summary': 'Project summary, platform scope, and curated entry points.', 'route': '/overview', 'keywords': 'home overview platform summary portal'},
        {'kind': 'module', 'label': 'Species registry', 'summary': 'Species-level screening and database navigation.', 'route': '/database', 'keywords': 'species registry database browse search screening atlas filter advanced'},
        {'kind': 'module', 'label': 'Release registry', 'summary': 'Release version, provenance, manifest, and import traceability.', 'route': '/release', 'keywords': 'release version provenance manifest import traceability postgres'},
        {'kind': 'module', 'label': 'Quality control', 'summary': 'Database readiness, file coverage, omics completeness, and QC status.', 'route': '/quality', 'keywords': 'quality qc completeness coverage validation readiness'},
        {'kind': 'module', 'label': 'Downloads', 'summary': 'Source feature files, analysis artifacts, and species-level dataset downloads.', 'route': '/downloads', 'keywords': 'download files source raw artifact dataset export'},
        {'kind': 'module', 'label': 'API and docs', 'summary': 'API routes, schema summaries, and data dictionary for the platform.', 'route': '/docs', 'keywords': 'docs api dictionary schema data contract reference'},
        {'kind': 'module', 'label': 'Visualization hub', 'summary': 'Basic visualization modules for stoichiometric feature tables.', 'route': '/visualization', 'keywords': 'visualization plot charts genome transcriptome proteome feature tables'},
        {'kind': 'module', 'label': 'Analysis hub', 'summary': 'Deep analysis modules for clustering, outliers, networks, and trade-offs.', 'route': '/analysis', 'keywords': 'analysis clusters outliers tradeoff network coupling strategy'},
        {'kind': 'module', 'label': 'Functional annotations', 'summary': 'GO/KEGG annotation coverage, species summaries, entity function evidence, and enrichment.', 'route': '/analysis', 'keywords': 'go kegg functional annotation enrichment pathway orthology ontology'},
        {'kind': 'module', 'label': 'Cross-species compare', 'summary': 'Fingerprint comparison across species and omics.', 'route': '/compare', 'keywords': 'compare cross species fingerprint'},
        {'kind': 'module', 'label': 'HVG workflows', 'summary': 'Create jobs and review HVG-Stoich cases.', 'route': '/jobs', 'keywords': 'hvg workflows jobs upload user data'},
    ]
    hits = [{k: v for k, v in m.items() if k != 'keywords'} for m in modules if q in m['keywords'] or q in m['label'].lower() or q in m['summary'].lower()]
    return hits[:6] or default_module_results()


def guide_payload() -> dict[str, Any]:
    return {
        'workflow': [
            'Browse the PostgreSQL-backed registry by species identifier, source context, or omics table availability.',
            'Use advanced filters for fingerprint ranges, genome size bounds, strategy clusters, and table-level numeric constraints.',
            'Inspect feature-table distributions and row-level details, then open Stage-4 real-result analysis modules in the analysis hub.',
            'Use cross-omics shift distributions, concordance summaries, and cross-species effect-size modules to prioritize hypotheses.',
            'Review Stage-5 exploratory analyses (explicitly labeled) for embedding-level patterns and anomaly candidates.',
            'Switch to Jobs when running the HVG-Stoich workflow on uploaded data; the platform remains open and account-free.',
        ],
        'data_contract': [
            'Genome tables assume promoter/exon elemental densities, GC strata and coordinate-aware fields.',
            'Transcriptome tables assume nucleotide composition, element-per-nt metrics, motif bias and ORF/protein proxies.',
            'Proteome tables assume atom-per-aa densities, element ratios and physicochemical feature columns.',
            'Cross-omics linking uses gene_id as the canonical join key; proteome tables may expose ensembl_gene_id as the matching field.',
            'The PostgreSQL layer stores species metadata, datasets, searchable entity rows, and analysis payloads; this scales cleanly to larger multi-species registries.',
        ],
        'notes': [
            'This package can serve a real multi-species registry generated directly from complete and core stoichiometric feature tables.',
            'A management command imports staged pipeline outputs into PostgreSQL-oriented ORM tables; SQLite remains available as a local fallback for lightweight testing.',
            'Real-result analyses (Stage-4) and exploratory analyses (Stage-5) are separated in the UI and payload contracts to avoid interpretation ambiguity.',
            'The same pipeline can be re-run on larger multi-species bundles without changing the frontend page structure.',
        ],
    }


def contact_payload() -> dict[str, Any]:
    return {
        'contacts': [
            {'label': 'Platform mode', 'value': 'Open academic research platform (no user accounts required)'},
            {'label': 'Primary audience', 'value': 'Computational biology, stoichiometric omics, comparative genomics and systems biology teams'},
            {'label': 'Suggested channels', 'value': 'Project PI / bioinformatics maintainer / frontend maintainer / data curator'},
        ],
        'capabilities': [
            'Real multi-species feature-table registry imported into PostgreSQL-oriented ORM tables',
            'Advanced registry search, entity drill-down, complex filters and compare views',
            'Reusable staged pipeline for validation, Parquet conversion, database seed tables, summary artifacts and cross-omics outputs',
            'HVG analysis workflow with jobs, registry and results browsing',
        ],
    }


# --- Performance-oriented overrides for interactive species switching ---
MODEL_SORT_FIELD_MAP = {
    'entity_id': 'entity_id',
    'gene_id': 'canonical_gene_id',
    'canonical_gene_id': 'canonical_gene_id',
    'gene_name': 'gene_name',
    'description': 'description',
    'strategy_cluster': 'strategy_cluster',
    'seqid': 'seqid',
    'start_pos': 'start_pos',
    'end_pos': 'end_pos',
}


def _load_scoped_file_json(species_id: str, omics: str, stem: str, scope: str) -> Any:
    scope = _normalize_scope(scope)
    candidates = [
        f'{species_id}/{omics}/{stem}_{scope}.json',
        f'{species_id}/{omics}/{stem}.{scope}.json',
        f'{species_id}/{omics}/{stem}.json',
    ]
    for relative in candidates:
        try:
            return load_json(relative)
        except NotFoundError:
            continue
    raise NotFoundError(f'Missing dataset file for {species_id}/{omics}: {stem} ({scope})')


def _available_scopes_file_mode(species_id: str, omics: str) -> list[str]:
    scopes = []
    for scope in ['core', 'full']:
        for relative in [
            f'{species_id}/{omics}/rows_{scope}.json',
            f'{species_id}/{omics}/rows.{scope}.json',
            f'{species_id}/{omics}/summary_{scope}.json',
            f'{species_id}/{omics}/summary.{scope}.json',
        ]:
            if (DATA_ROOT / relative).exists():
                scopes.append(scope)
                break
    if not scopes:
        return ['core']
    if 'core' not in scopes:
        scopes = ['core'] + scopes
    return list(dict.fromkeys(scopes))


def _available_scopes_db_mode(ds: OmicsDataset) -> list[str]:
    browse_meta = ds.browse_meta or {}
    from_meta = browse_meta.get('available_scopes')
    scopes = []
    if isinstance(from_meta, list) and from_meta:
        output = [str(item).strip().lower() for item in from_meta if str(item).strip()]
        output = [item for item in output if item in {'core', 'full'}]
        if output:
            scopes.extend(output)
    if _dataset_scope_csv_path(ds, 'core') is not None:
        scopes.append('core')
    if _dataset_scope_csv_path(ds, 'full') is not None:
        scopes.append('full')
    return list(dict.fromkeys(scopes)) or ['core']


def _dataset_scope_csv_path(ds: OmicsDataset, scope: str) -> Path | None:
    scope = _normalize_scope(scope)
    raw = ds.full_csv_path if scope == 'full' else ds.core_csv_path
    path = Path(str(raw or ''))
    if path.exists() and path.is_file():
        return path
    if scope != 'full':
        return None
    core = Path(str(ds.core_csv_path or ''))
    if not core.exists() or not core.is_file():
        return None
    name = core.name
    candidate_names = list(dict.fromkeys([
        name.replace('.core.', '.full.'),
        name.replace('.core.csv', '.full.csv'),
        name.replace('_features.core.csv', '_features.full.csv'),
        name.replace('_features.core.csv', '_features.csv'),
        name.replace('.genome_features.core.csv', '.genome_features.csv'),
        name.replace('.transcriptome.core.v5.csv', '.transcriptome.full.v5.csv'),
        name.replace('.proteome_features.core.csv', '.proteome_features.full.csv'),
    ]))
    for candidate_name in candidate_names:
        candidate = core.with_name(candidate_name)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _scoped_payload_from_db(payload: Any, scope: str) -> Any:
    scope = _normalize_scope(scope)
    if not isinstance(payload, dict):
        return payload or {}
    scoped = payload.get('scopes') if isinstance(payload.get('scopes'), dict) else None
    if scoped:
        return scoped.get(scope) or scoped.get('core') or {}
    return payload


def _is_meaningful_payload_value(value: Any) -> bool:
    if value is None:
        return False
    if value == '':
        return False
    if isinstance(value, (list, tuple, set, dict)) and len(value) == 0:
        return False
    return True


def _merge_payload_preserving_data(base: Any, overlay: Any) -> Any:
    """Merge payload fragments without letting sparse derived branches blank stored data."""
    if not isinstance(base, dict):
        return overlay if _is_meaningful_payload_value(overlay) else (base or {})
    if not isinstance(overlay, dict):
        return overlay if _is_meaningful_payload_value(overlay) else dict(base)
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge_payload_preserving_data(merged[key], value)
            continue
        if _is_meaningful_payload_value(value) or key not in merged:
            merged[key] = value
    return merged


def _csv_rows_for_db_scope(species_id: str, omics: str, scope: str, limit: int = 0) -> list[dict[str, Any]]:
    if limit:
        return _csv_rows_for_db_scope_limited(species_id, omics, scope, int(limit))
    return _read_csv_rows_for_db_scope(species_id, omics, scope, 0)


def _row_identity_key(row: dict[str, Any], omics: str) -> str:
    candidates = {
        'genome': ('entity_id', 'gene_id', 'canonical_gene_id'),
        'transcriptome': ('entity_id', 'transcript_id', 'gene_id'),
        'proteome': ('entity_id', 'protein_id', 'gene_id', 'ensembl_gene_id'),
    }.get(omics, ('entity_id', 'gene_id'))
    for key in candidates:
        value = str(row.get(key) or '').strip()
        if value:
            return value
    return ''


def _merge_full_fields_into_core_rows(core_rows: list[dict[str, Any]], full_rows: list[dict[str, Any]], omics: str, allowed_fields: set[str] | None = None) -> list[dict[str, Any]]:
    if not core_rows or not full_rows:
        return core_rows
    full_by_key: dict[str, dict[str, Any]] = {}
    for row in full_rows:
        key = _row_identity_key(row, omics)
        if key and key not in full_by_key:
            full_by_key[key] = row
    if not full_by_key:
        return core_rows
    merged: list[dict[str, Any]] = []
    for core_row in core_rows:
        output = dict(core_row)
        supplement = full_by_key.get(_row_identity_key(core_row, omics))
        if supplement:
            for key, value in supplement.items():
                if allowed_fields is not None and key not in allowed_fields:
                    continue
                if key not in output or output.get(key) in (None, ''):
                    output[key] = value
        merged.append(output)
    return merged


def _rows_have_any_field(rows: list[dict[str, Any]], fields: set[str], sample_size: int = 250) -> bool:
    if not rows or not fields:
        return False
    for row in rows[:sample_size]:
        for field in fields:
            if field in row and _safe_num(row.get(field)) is not None:
                return True
    return False


def _rows_have_all_fields(rows: list[dict[str, Any]], fields: set[str], sample_size: int = 250) -> bool:
    if not rows or not fields:
        return False
    for field in fields:
        if not _rows_have_any_field(rows, {field}, sample_size=sample_size):
            return False
    return True


def _complete_core_rows_for_module_suite(species_id: str, omics: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    core_rows = _csv_rows_for_db_scope(species_id, omics, 'core', limit=0)
    supplement_fields = set(optional_full_fields_for_omics(omics))
    original_core_count = len(core_rows)
    used_full_supplement = False
    full_join_match_n = 0
    missing_supplement_fields: list[str] = []
    if core_rows and supplement_fields and not _rows_have_all_fields(core_rows, supplement_fields, sample_size=len(core_rows)):
        full_rows = _csv_rows_for_db_scope(species_id, omics, 'full', limit=0)
        if full_rows and _rows_have_any_field(full_rows, supplement_fields, sample_size=len(full_rows)):
            merged_rows = _merge_full_fields_into_core_rows(core_rows, full_rows, omics, allowed_fields=supplement_fields)
            full_keys = {_row_identity_key(row, omics) for row in full_rows if _row_identity_key(row, omics)}
            full_join_match_n = sum(1 for row in core_rows if _row_identity_key(row, omics) in full_keys)
            core_rows = merged_rows
            used_full_supplement = True
    for field in sorted(supplement_fields):
        if not _rows_have_any_field(core_rows, {field}, sample_size=len(core_rows)):
            missing_supplement_fields.append(field)
    return core_rows, {
        'primary_scope': 'core',
        'analysis_scope': 'complete_core_csv',
        'row_count_scanned': len(core_rows),
        'core_row_count_before_supplement': original_core_count,
        'core_row_count_after_supplement': len(core_rows),
        'full_supplement_used': used_full_supplement,
        'optional_full_fields_used': sorted(supplement_fields - set(missing_supplement_fields)) if used_full_supplement else [],
        'missing_optional_full_fields': missing_supplement_fields,
        'full_join_match_n': full_join_match_n,
        'full_supplement_policy': 'left_join_optional_fields_only; core entity universe is never replaced by full rows',
        'full_table_role': 'supplement_only',
        'not_persisted_to_db': True,
    }


@lru_cache(maxsize=12)
def _csv_rows_for_db_scope_limited(species_id: str, omics: str, scope: str, limit: int) -> list[dict[str, Any]]:
    return _read_csv_rows_for_db_scope(species_id, omics, scope, limit)


def _read_csv_rows_for_db_scope(species_id: str, omics: str, scope: str, limit: int = 0) -> list[dict[str, Any]]:
    scope = _normalize_scope(scope)
    try:
        ds = OmicsDataset.objects.only('core_csv_path', 'full_csv_path').get(species__species_id=species_id, omics_type=omics)
    except OmicsDataset.DoesNotExist:
        return []
    path = _dataset_scope_csv_path(ds, scope)
    if path is None:
        return []
    meta = omics_meta().get(omics, {})
    primary_id = meta.get('primary_id') or 'entity_id'
    rows: list[dict[str, Any]] = []
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not isinstance(row, dict):
                continue
            row.setdefault('entity_id', row.get(primary_id) or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id') or '')
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    return rows


def _csv_page_for_db_scope(species_id: str, omics: str, scope: str, page: int, page_size: int) -> tuple[list[dict[str, Any]], int, list[str]]:
    scope = _normalize_scope(scope)
    try:
        ds = OmicsDataset.objects.only('core_csv_path', 'full_csv_path', 'row_count_core', 'row_count_full', 'browse_meta').get(species__species_id=species_id, omics_type=omics)
    except OmicsDataset.DoesNotExist:
        return [], 0, ['core']
    path = _dataset_scope_csv_path(ds, scope)
    if path is None:
        return [], 0, _available_scopes_db_mode(ds)
    meta = omics_meta().get(omics, {})
    primary_id = meta.get('primary_id') or 'entity_id'
    start = max(0, (int(page) - 1) * int(page_size))
    end = start + int(page_size)
    rows: list[dict[str, Any]] = []
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            if idx < start:
                continue
            if idx >= end:
                break
            if not isinstance(row, dict):
                continue
            row.setdefault('entity_id', row.get(primary_id) or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id') or '')
            rows.append(row)
    registered_total = ds.row_count_full if scope == 'full' else ds.row_count_core
    total = int(registered_total or 0)
    if total <= 0:
        total = start + len(rows)
    return rows, total, _available_scopes_db_mode(ds)


CSV_ANALYSIS_PREFERRED_FIELDS = {
    'genome': ['exon_gc_percent', 'promoter_gc_percent', 'gc_delta_promoter_minus_exon', 'promoter_exon_gc_delta', 'exon_atoms_N_per_base', 'gc3_percent', 'stoich_island_score'],
    'transcriptome': ['gc_percent_display', 'gc_content', 'nt_entropy', 'atoms_per_nt_N', 'atoms_per_nt_P', 'coding_density_proxy', 'rna_orf_coupling_score', 'protein_gravy_proxy'],
    'proteome': ['length_aa', 'N_atoms_per_aa', 'S_atoms_per_aa', 'C_atoms_per_aa', 'pI', 'gravy', 'resource_budget_score', 'adaptation_score'],
}


def _csv_analysis_source(species_id: str, omics: str, scope: str) -> tuple[OmicsDataset, Path] | None:
    try:
        ds = OmicsDataset.objects.select_related('species').only(
            'dataset_id',
            'species__species_id',
            'species__display_name',
            'omics_type',
            'schema_version',
            'row_count_core',
            'row_count_full',
            'core_csv_path',
            'full_csv_path',
            'browse_meta',
        ).get(species__species_id=species_id, omics_type=omics)
    except OmicsDataset.DoesNotExist:
        return None
    path = _dataset_scope_csv_path(ds, scope)
    if path is None:
        return None
    return ds, path


def _csv_candidate_fields(header: list[str], omics: str, max_fields: int = 10) -> list[str]:
    present = set(header)
    candidates: list[str] = []
    for field in CSV_ANALYSIS_PREFERRED_FIELDS.get(omics, []):
        if field in present and field not in candidates:
            candidates.append(field)
    for field in omics_meta().get(omics, {}).get('feature_options') or []:
        if field in present and field not in candidates:
            candidates.append(field)
    blocked = {'entity_id', 'gene_id', 'transcript_id', 'protein_id', 'gene_name', 'gene_symbol', 'description', 'species_id'}
    for field in header:
        lower = str(field).lower()
        if field in candidates or field in blocked:
            continue
        if any(token in lower for token in ['_id', 'start', 'end', 'strand', 'seqid', 'chrom', 'description', 'name']):
            continue
        candidates.append(field)
        if len(candidates) >= max_fields * 2:
            break
    return candidates[:max_fields]


def _csv_preview_columns(header: list[str], omics: str, candidate_fields: list[str]) -> list[str]:
    preferred = {
        'genome': ['entity_id', 'gene_id', 'gene_name', 'biotype', 'seqid', 'start_1', 'end_1', 'strand'],
        'transcriptome': ['entity_id', 'transcript_id', 'gene_id', 'gene_symbol', 'transcript_biotype', 'seq_region', 'start', 'end', 'strand'],
        'proteome': ['entity_id', 'protein_id', 'ensembl_gene_id', 'gene_id', 'gene_symbol', 'description', 'length_aa'],
    }.get(omics, ['entity_id'])
    return [field for field in [*preferred, *candidate_fields] if field in header][:12]


def _reservoir_add(items: list[dict[str, Any]], item: dict[str, Any], seen: int, limit: int, seed: int) -> None:
    if limit <= 0:
        items.append(item)
        return
    if len(items) < limit:
        items.append(item)
        return
    digest = hashlib.sha256(f'{seed}:{seen}'.encode('utf-8')).hexdigest()
    idx = int(digest[:12], 16) % max(1, seen)
    if idx < limit:
        items[idx] = item


def _pearson_corr_from_values(x_values: list[float], y_values: list[float]) -> float:
    n = min(len(x_values), len(y_values))
    if n < 2:
        return 0.0
    xs = x_values[:n]
    ys = y_values[:n]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x <= 0 or den_y <= 0:
        return 0.0
    return float(num / (den_x * den_y))


def _csv_correlation_payload(pair_values: dict[tuple[str, str], list[tuple[float, float]]], fields: list[str]) -> tuple[dict[str, dict[str, float]], list[dict[str, Any]]]:
    matrix: dict[str, dict[str, float]] = {field: {other: 1.0 if other == field else 0.0 for other in fields} for field in fields}
    edges: list[dict[str, Any]] = []
    for i, src in enumerate(fields):
        for dst in fields[i + 1:]:
            pairs = pair_values.get((src, dst), [])
            if len(pairs) < 4:
                value = 0.0
                p_value = 1.0
            else:
                value = _pearson_corr_from_values([item[0] for item in pairs], [item[1] for item in pairs])
                p_value = _fisher_pvalue_from_r(value, len(pairs))
            rounded = round(float(value), 4)
            matrix[src][dst] = rounded
            matrix[dst][src] = rounded
            edges.append({
                'source': src,
                'target': dst,
                'weight': rounded,
                'n': len(pairs),
                'p_value': round(float(p_value), 8),
                'method': 'pearson',
            })
    fdr_values = _benjamini_hochberg_fdr([float(row.get('p_value', 1.0)) for row in edges])
    for idx, fdr in enumerate(fdr_values):
        edges[idx]['fdr'] = round(float(fdr), 8)
    edges.sort(key=lambda row: abs(float(row.get('weight', 0.0))), reverse=True)
    return matrix, edges[:36]


@lru_cache(maxsize=96)
def _csv_scope_payloads(species_id: str, omics: str, scope: str, scatter_limit: int = 5000) -> dict[str, Any]:
    active_scope = _normalize_scope(scope)
    source = _csv_analysis_source(species_id, omics, active_scope)
    if source is None:
        raise NotFoundError(f'No readable {active_scope} CSV source for {species_id}/{omics}')
    ds, path = source
    meta = omics_meta().get(omics, {})
    primary_id = meta.get('primary_id') or 'entity_id'
    scatter_limit = _safe_int(scatter_limit, 5000, minimum=0, maximum=50000)
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        candidate_fields = _csv_candidate_fields(header, omics, max_fields=10)
        preview_columns = _csv_preview_columns(header, omics, candidate_fields)
        values: dict[str, list[float]] = {field: [] for field in candidate_fields}
        valid_n: dict[str, int] = {field: 0 for field in candidate_fields}
        missing_n: dict[str, int] = {field: 0 for field in candidate_fields}
        ranked: dict[str, list[dict[str, Any]]] = {field: [] for field in candidate_fields[:4]}
        pair_values: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        preview_rows: list[dict[str, Any]] = []
        scatter: dict[str, list[dict[str, Any]]] = defaultdict(list)
        row_count = 0
        category_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        category_fields = [field for field in ['strategy_cluster', 'biotype', 'transcript_biotype', 'strand', 'seqid', 'seq_region'] if field in header]
        scatter_pairs = {
            'genome': [('promoter_vs_exon_gc', 'exon_gc_percent', 'promoter_gc_percent'), ('gc_delta_vs_n', 'gc_delta_promoter_minus_exon', 'exon_atoms_N_per_base')],
            'transcriptome': [('gc_vs_entropy', 'gc_percent_display', 'nt_entropy'), ('coupling_vs_gravy', 'rna_orf_coupling_score', 'protein_gravy_proxy')],
            'proteome': [('n_vs_pi', 'N_atoms_per_aa', 'pI'), ('n_vs_s_resource', 'N_atoms_per_aa', 'S_atoms_per_aa'), ('pi_vs_gravy', 'pI', 'gravy')],
        }.get(omics, [])
        for row in reader:
            row_count += 1
            if len(preview_rows) < 20:
                preview_rows.append({field: row.get(field, '') for field in preview_columns})
            numeric_row: dict[str, float] = {}
            for field in candidate_fields:
                raw = row.get(field)
                if raw is None or str(raw).strip() == '':
                    missing_n[field] += 1
                    continue
                valid_n[field] += 1
                num = _safe_num(raw)
                if num is None:
                    continue
                numeric_row[field] = float(num)
                values[field].append(float(num))
                if field in ranked:
                    ranked[field].append({
                        'entity_id': row.get('entity_id') or row.get(primary_id) or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id') or '',
                        'gene_id': row.get('gene_id') or row.get('ensembl_gene_id') or '',
                        'gene_name': row.get('gene_name') or row.get('gene_symbol') or '',
                        field: round(float(num), 6),
                        'value': round(float(num), 6),
                    })
            for i, src in enumerate(candidate_fields[:8]):
                if src not in numeric_row:
                    continue
                for dst in candidate_fields[:8][i + 1:]:
                    if dst in numeric_row:
                        pair_values[(src, dst)].append((numeric_row[src], numeric_row[dst]))
            for key, x_field, y_field in scatter_pairs:
                x_val = numeric_row.get(x_field)
                y_val = numeric_row.get(y_field)
                if x_val is None or y_val is None:
                    continue
                item = {
                    'entity_id': row.get('entity_id') or row.get(primary_id) or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id') or '',
                    'gene_id': row.get('gene_id') or row.get('ensembl_gene_id') or '',
                    'gene_name': row.get('gene_name') or row.get('gene_symbol') or '',
                    x_field: round(float(x_val), 6),
                    y_field: round(float(y_val), 6),
                }
                _reservoir_add(scatter[key], item, row_count, scatter_limit, seed=sum(ord(ch) for ch in key))
            for field in category_fields:
                text = str(row.get(field) or '').strip()
                if text:
                    category_counts[field][text] += 1

    feature_cards = {field: _distribution_stats(vals) for field, vals in values.items() if vals}
    distributions = {field: _histogram_payload(vals, bins=42) for field, vals in list(values.items())[:5] if vals}
    matrix, edges = _csv_correlation_payload(pair_values, candidate_fields[:8])
    outliers = _robust_outliers_from_rows([
        {**row, 'strategy_score': row.get('value')}
        for field_rows in ranked.values()
        for row in field_rows
    ], omics) or {}
    score_field = next((field for field in candidate_fields if values.get(field)), '')
    if score_field and score_field in ranked:
        ordered = sorted(ranked[score_field], key=lambda item: _safe_num(item.get(score_field)) or 0.0)
        outliers = {
            'score_col': score_field,
            'n_entities': len(ordered),
            'high': list(reversed(ordered[-24:])),
            'low': ordered[:24],
        }
    analysis_outliers = {'high': [], 'low': [], 'multivariate': [], 'feature_contributions': {}}
    for side in ['high', 'low']:
        for idx, row in enumerate(outliers.get(side, []), start=1):
            item = dict(row)
            item.setdefault('outlier_rank', idx)
            item.setdefault('outlier_label', 'candidate')
            analysis_outliers[side].append(item)

    tradeoff_front = []
    if len(candidate_fields) >= 2:
        x_field, y_field = candidate_fields[:2]
        pair_key = (x_field, y_field)
        for idx, (x_val, y_val) in enumerate(pair_values.get(pair_key, [])[:800], start=1):
            tradeoff_front.append({
                'entity_id': f'row_{idx}',
                'cost_axis': round(float(x_val), 6),
                'adapt_axis': round(float(y_val), 6),
                'front_score': round((float(x_val) + float(y_val)) / 2.0, 6),
            })

    kpis = [{'label': 'Rows', 'value': row_count}]
    for field in candidate_fields[:3]:
        if values.get(field):
            kpis.append({'label': f'Mean {field}', 'value': round(sum(values[field]) / len(values[field]), 6)})

    categorical_composition = []
    for field, counts in category_counts.items():
        top = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:12]
        categorical_composition.append({'field': field, 'counts': [{'label': key, 'count': int(value)} for key, value in top]})

    method = {
        'source': 'on_demand_csv_scope_payload',
        'source_path': str(path),
        'scope': active_scope,
        'row_count_scanned': row_count,
        'aggregation_scope': 'complete CSV rows for selected core/full scope',
        'chart_point_policy': 'scatter-like charts include all valid points; aggregate statistics use all scanned rows' if scatter_limit == 0 else f'scatter-like charts use deterministic reservoir points capped at {scatter_limit}; aggregate statistics use all scanned rows',
        'not_persisted_to_db': True,
    }
    summary = {
        'species_id': species_id,
        'display_name': ds.species.display_name,
        'omics': omics,
        'scope': active_scope,
        'available_scopes': _available_scopes_db_mode(ds),
        'row_count': row_count,
        'primary_id': primary_id,
        'field_meta': [{'field': field, 'dtype': 'numeric_or_text', 'description': ''} for field in header[:120]],
        'kpis': kpis,
        'feature_cards': feature_cards,
        'distributions': distributions,
        'scatter': dict(scatter),
        'scatter_meta': {key: {'n_total': row_count, 'n_points': len(points), 'sampling': 'complete' if scatter_limit == 0 or row_count <= len(points) else 'deterministic_reservoir'} for key, points in scatter.items()},
        'correlation_matrix': matrix,
        'correlation_matrices': {'pearson': matrix},
        'coupling_edges': edges,
        'preview_rows': preview_rows,
        'missingness': [
            {'field': field, 'valid_n': valid_n[field], 'missing_n': missing_n[field], 'missing_rate': round(missing_n[field] / max(1, row_count), 6)}
            for field in candidate_fields
        ],
        'categorical_composition': categorical_composition,
        'method_metadata': {'csv_full_scope': method},
        'precomputed_from_real_rows': True,
    }
    analysis = {
        'omics': omics,
        'scope': active_scope,
        'feature_set': candidate_fields,
        'evidence_level': 'exploratory',
        'result_type': 'hypothesis_generating',
        'outliers': analysis_outliers,
        'tradeoff_front': tradeoff_front,
        'coupling_edges': edges,
        'method_metadata': {
            'outliers': {
                'method': 'exact_csv_quantile_extremes',
                'score_col': score_field,
                'n_entities': len(values.get(score_field, [])) if score_field else 0,
                'missing_policy': 'valid numeric rows only',
            },
            'tradeoff_front': {
                'method': 'first_800_pairwise_numeric_rows_for_display',
                'source_fields': candidate_fields[:2],
            },
            'coupling_network': {
                'method': 'pearson_association',
                'multiple_testing': 'benjamini_hochberg_fdr',
            },
            'csv_full_scope': method,
        },
        'display_labels': {
            'outliers': 'Candidate outliers',
            'tradeoff_front': 'Trade-off landscape',
            'coupling_edges': 'Feature coupling network',
        },
        'precomputed_from_real_rows': True,
    }
    return {'summary': summary, 'analysis': analysis, 'source': method}


def build_on_demand_omics_payload(species_id: str, omics: str, scope: str = 'core', *, scatter_limit: int = 5000) -> dict[str, Any]:
    active_scope = _normalize_scope(scope)
    validate_omics(omics)
    return _csv_scope_payloads(species_id, omics, active_scope, _safe_int(scatter_limit, 5000, minimum=0, maximum=50000))


@lru_cache(maxsize=128)
def build_complete_core_omics_payload(species_id: str, omics: str, *, scatter_limit: int = 5000) -> dict[str, Any]:
    validate_omics(omics)
    payload = _csv_scope_payloads(species_id, omics, 'core', _safe_int(scatter_limit, 5000, minimum=0, maximum=50000))
    summary = dict(payload.get('summary') or {})
    analysis = dict(payload.get('analysis') or {})
    source = dict(payload.get('source') or {})
    source.update({
        'source': 'complete_core_csv_pipeline',
        'primary_scope': 'core',
        'analysis_scope': 'complete_core_csv',
        'compute_mode': 'complete_core',
        'aggregation_scope': 'complete core CSV rows; full CSV may supplement only missing module fields',
        'full_table_role': 'supplement_only',
        'not_persisted_to_db': True,
    })
    try:
        complete_overlay = complete_core_summary_overlay(species_id, omics)
        summary = _merge_payload_preserving_data(summary, complete_overlay.get('summary') or {})
        analysis = _merge_payload_preserving_data(analysis, complete_overlay.get('analysis') or {})
        source.update(complete_overlay.get('source') or {})
    except Exception as exc:
        source['complete_core_v2_overlay_error'] = f'{type(exc).__name__}: {exc}'
    for target in (summary, analysis):
        target['compute_mode'] = 'complete_core'
        target['scope'] = 'core'
        metadata = dict(target.get('method_metadata') or {}) if isinstance(target.get('method_metadata'), dict) else {}
        metadata['complete_core_compute'] = source
        target['method_metadata'] = metadata
    summary['result_view'] = 'complete_core'
    analysis['result_view'] = 'complete_core'
    return {'summary': summary, 'analysis': analysis, 'source': source}


@lru_cache(maxsize=1)
def _home_representative_species_id_set() -> frozenset[str]:
    ids = set()
    for row in _preferred_home_representatives():
        public_id = str(row.get('species_id') or '').strip()
        if public_id:
            ids.add(public_id)
    try:
        for row in _home_representative_species(_home_display_release_record()):
            public_id = str(row.get('species_id') or '').strip()
            if public_id:
                ids.add(public_id)
    except Exception:
        pass
    try:
        for spec in HOME_REPRESENTATIVE_SPECIES:
            label = str(spec.get('label') or '').strip()
            if not label:
                continue
            query_filter = Q(display_name__istartswith=label)
            normalized = label.lower().replace(' ', '_')
            query_filter |= Q(species_id__istartswith=normalized)
            for sid in Species.objects.filter(query_filter).values_list('species_id', flat=True)[:64]:
                if sid:
                    ids.add(str(sid))
    except Exception:
        pass
    return frozenset(ids)


def _should_use_on_demand_csv_payload(species_id: str, scope: str, compute: str) -> bool:
    mode = _normalize_compute_mode(compute)
    active_scope = _normalize_scope(scope)
    if mode in {'full', 'complete_core'}:
        return True
    if active_scope == 'full':
        return True
    return False


@lru_cache(maxsize=512)
def get_omics_bundle(species_id: str, omics: str, scope: str = 'core', compute: str = 'stored') -> dict[str, Any]:
    active_scope = _normalize_scope(scope)
    compute_mode = _normalize_compute_mode(compute)
    validate_omics(omics)
    summary = get_summary(species_id, omics, scope=active_scope, compute=compute_mode)
    analysis = get_analysis(species_id, omics, scope=active_scope, compute=compute_mode)
    return {
        'species_id': species_id,
        'omics': omics,
        'scope': active_scope,
        'compute': compute_mode,
        'summary': summary,
        'analysis': analysis,
    }



def _parse_feature_filters(feature_filters: str) -> list[dict[str, Any]]:
    if not feature_filters:
        return []
    try:
        parsed = json.loads(feature_filters)
    except Exception:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    return [item for item in parsed if isinstance(item, dict)]



def _candidate_value(record: EntityRecord, key: str) -> Any:
    if key in MODEL_SORT_FIELD_MAP:
        return getattr(record, MODEL_SORT_FIELD_MAP[key], None)
    summary = getattr(record, 'numeric_summary', None) or {}
    if key in summary:
        return summary.get(key)
    payload = getattr(record, 'payload_json', None) or {}
    return payload.get(key)



def _apply_row_feature_filters_fast(records: list[EntityRecord], parsed_filters: list[dict[str, Any]]) -> list[EntityRecord]:
    if not parsed_filters:
        return records
    output = records
    for item in parsed_filters:
        key = item.get('key')
        if not key:
            continue
        min_v = _safe_num(item.get('min'))
        max_v = _safe_num(item.get('max'))
        text_v = str(item.get('value', '')).strip().lower()
        op = str(item.get('op', '')).strip().lower()
        values = {str(v).strip().lower() for v in (item.get('values') or []) if str(v).strip()}
        next_records: list[EntityRecord] = []
        for rec in output:
            value = _candidate_value(rec, key)
            num = _safe_num(value)
            text_value = str(value or '').strip().lower()
            if op == 'missing':
                if text_value:
                    continue
            elif op == 'exists':
                if not text_value:
                    continue
            elif op == 'in' and values:
                if text_value not in values:
                    continue
            if text_v and text_v not in str(value or '').lower():
                continue
            if min_v is not None and (num is None or num < min_v):
                continue
            if max_v is not None and (num is None or num > max_v):
                continue
            next_records.append(rec)
        output = next_records
    return output



def _sort_record_value_fast(record: EntityRecord, key: str) -> Any:
    value = _candidate_value(record, key)
    num = _safe_num(value)
    return num if num is not None else str(value or '')



def _row_to_browse_payload(record: EntityRecord, columns: list[str]) -> dict[str, Any]:
    payload = dict(record.payload_json or {})
    payload.setdefault('entity_id', record.entity_id)
    payload.setdefault('gene_name', record.gene_name)
    payload.setdefault('description', record.description)
    payload.setdefault('strategy_cluster', record.strategy_cluster)
    payload.setdefault('seqid', record.seqid)
    payload.setdefault('start_pos', record.start_pos)
    payload.setdefault('end_pos', record.end_pos)
    if not columns:
        return payload
    return {column: payload.get(column) for column in columns}



def _attach_summary_schema(summary: dict[str, Any], omics: str, scope: str, available_scopes: list[str]) -> dict[str, Any]:
    payload = dict(summary or {})
    payload['scope'] = _normalize_scope(scope)
    payload.setdefault('available_scopes', available_scopes or ['core'])
    if 'field_meta' not in payload:
        field_meta = omics_field_meta(omics)
        if field_meta:
            payload['field_meta'] = field_meta
    return payload


def _enhance_summary_coupling(payload: dict[str, Any], species_id: str, omics: str, scope: str) -> dict[str, Any]:
    data = dict(payload or {})
    matrices = data.get('correlation_matrices') if isinstance(data.get('correlation_matrices'), dict) else {}
    method = 'spearman' if 'spearman' in matrices else (next(iter(matrices.keys()), 'spearman'))
    matrix = matrices.get(method) if isinstance(matrices.get(method), dict) else (data.get('correlation_matrix') or {})
    if not isinstance(matrix, dict):
        matrix = {}

    existing = data.get('coupling_edges')
    needs_rebuild = (
        not isinstance(existing, list)
        or not existing
        or any(isinstance(item, dict) and item.get('p_value') is None for item in existing)
    )
    if not needs_rebuild or not matrix:
        return data

    keys = list(matrix.keys())
    n_rows = int(_safe_num(data.get('row_count')) or _safe_num(data.get('n_entities')) or 0)
    if n_rows <= 0:
        n_rows = len(_analysis_rows_for_scope(species_id, omics, scope))
    edges: list[dict[str, Any]] = []
    pvalues: list[float] = []
    for i, src in enumerate(keys):
        row = matrix.get(src) if isinstance(matrix.get(src), dict) else {}
        for dst in keys[i + 1:]:
            weight = _safe_num(row.get(dst))
            if weight is None:
                continue
            if abs(float(weight)) < 0.28:
                continue
            pval = _fisher_pvalue_from_r(float(weight), n_rows)
            pvalues.append(float(pval))
            edges.append({
                'source': src,
                'target': dst,
                'weight': round(float(weight), 6),
                'n': int(n_rows),
                'p_value': round(float(pval), 8),
                'method': method,
            })
    fdr_values = _benjamini_hochberg_fdr(pvalues)
    for idx, fdr in enumerate(fdr_values):
        if idx < len(edges):
            edges[idx]['fdr'] = round(float(fdr), 8)
    edges.sort(key=lambda item: abs(float(item.get('weight', 0.0))), reverse=True)
    data['coupling_edges'] = edges[:24]

    method_metadata = data.get('method_metadata') if isinstance(data.get('method_metadata'), dict) else {}
    method_metadata.setdefault('coupling_network', {
        'method': method,
        'multiple_testing': 'benjamini_hochberg_fdr',
        'evidence_level': 'exploratory',
    })
    data['method_metadata'] = method_metadata
    return data


DERIVED_OMICS_FIELDS = {
    'genome': [
        'exon_gc_percent',
        'promoter_gc_percent',
        'promoter_exon_gc_delta',
        'gc_delta_promoter_minus_exon',
        'gc3_percent',
        'gc12_percent_estimated',
        'stoich_island_score',
        'exon_atoms_N_per_base',
    ],
    'transcriptome': [
        'gc_content',
        'gc_percent_display',
        'atoms_per_nt_C_estimated',
        'atoms_per_nt_H_estimated',
        'atoms_per_nt_O_estimated',
        'nt_entropy',
        'atoms_per_nt_N',
        'atoms_per_nt_P',
        'C_N_ratio_estimated',
        'N_P_ratio',
        'mw_rna_nmp_per_nt_Da_estimated',
        'coding_density_proxy',
        'rna_orf_coupling_score',
        'protein_gravy_proxy',
    ],
    'proteome': [
        'length_aa',
        'N_atoms_per_aa',
        'S_atoms_per_aa',
        'N_S_ratio',
        'sulfur_aa_frac_estimated',
        'pI',
        'gravy',
        'instability_index',
        'aromaticity',
        'aliphatic_index',
        'adaptation_score',
        'resource_budget_score',
    ],
}


RNA_NMP_MASS_DA = {
    'A': 347.22,
    'C': 323.20,
    'G': 363.22,
    'U': 324.18,
}

DNA_BASES = ['A', 'C', 'G', 'T']
DINUCS = [a + b for a in DNA_BASES for b in DNA_BASES]
CODONS = [a + b + c for a in DNA_BASES for b in DNA_BASES for c in DNA_BASES]
RNA_BASES = ['A', 'C', 'G', 'U']
RNA_DINUCS = [a + b for a in RNA_BASES for b in RNA_BASES]
RNA_CODONS = [a + b + c for a in RNA_BASES for b in RNA_BASES for c in RNA_BASES]
AMINO_ACIDS_20 = list('ACDEFGHIKLMNPQRSTVWY')


def _feature_value_from_sources(numeric: dict[str, Any], payload: dict[str, Any], field: str) -> float | None:
    value = _safe_num(numeric.get(field))
    if value is None:
        value = _safe_num(payload.get(field))
    if value is not None:
        return float(value)

    gc_fraction = _safe_num(numeric.get('gc_content'))
    if gc_fraction is None:
        gc_fraction = _safe_num(payload.get('gc_content'))
    if gc_fraction is None:
        gc_display = _safe_num(numeric.get('gc_percent_display'))
        if gc_display is None:
            gc_display = _safe_num(payload.get('gc_percent_display'))
        if gc_display is not None:
            gc_fraction = float(gc_display) / 100.0
    if gc_fraction is not None:
        gc_fraction = float(gc_fraction)
        if gc_fraction > 1.0:
            gc_fraction = gc_fraction / 100.0
        gc_fraction = min(1.0, max(0.0, gc_fraction))

    if field == 'gc12_percent_estimated':
        exon_gc = _safe_num(numeric.get('exon_gc_percent'))
        if exon_gc is None:
            exon_gc = _safe_num(payload.get('exon_gc_percent'))
        gc3 = _safe_num(numeric.get('gc3_percent'))
        if gc3 is None:
            gc3 = _safe_num(payload.get('gc3_percent'))
        if exon_gc is not None and gc3 is not None:
            return min(100.0, max(0.0, (3.0 * float(exon_gc) - float(gc3)) / 2.0))

    if field == 'atoms_per_nt_P' and (gc_fraction is not None or _safe_num(numeric.get('atoms_per_nt_N')) is not None):
        return 1.0
    if field == 'atoms_per_nt_C_estimated' and gc_fraction is not None:
        return 9.5
    if field == 'atoms_per_nt_H_estimated' and gc_fraction is not None:
        return 11.5 + (0.5 * gc_fraction)
    if field == 'atoms_per_nt_O_estimated' and gc_fraction is not None:
        return 7.0
    if field == 'mw_rna_nmp_per_nt_Da_estimated' and gc_fraction is not None:
        au_mass = (RNA_NMP_MASS_DA['A'] + RNA_NMP_MASS_DA['U']) / 2.0
        gc_mass = (RNA_NMP_MASS_DA['C'] + RNA_NMP_MASS_DA['G']) / 2.0
        return ((1.0 - gc_fraction) * au_mass) + (gc_fraction * gc_mass)

    n_value = _safe_num(numeric.get('atoms_per_nt_N'))
    if n_value is None:
        n_value = _safe_num(payload.get('atoms_per_nt_N'))
    if n_value is not None:
        n_value = float(n_value)
        if field == 'N_P_ratio':
            return n_value
        if field == 'C_N_ratio_estimated' and n_value > 0:
            return 9.5 / n_value

    n_aa = _safe_num(numeric.get('N_atoms_per_aa'))
    if n_aa is None:
        n_aa = _safe_num(payload.get('N_atoms_per_aa'))
    s_aa = _safe_num(numeric.get('S_atoms_per_aa'))
    if s_aa is None:
        s_aa = _safe_num(payload.get('S_atoms_per_aa'))
    if field == 'N_S_ratio' and n_aa is not None and s_aa is not None and float(s_aa) > 0:
        return float(n_aa) / float(s_aa)
    if field == 'sulfur_aa_frac_estimated' and s_aa is not None:
        return float(s_aa)

    return None


def _field_values_from_records(species_id: str, omics: str, fields: list[str], limit: int = 12000, scope: str = 'core') -> dict[str, list[float]]:
    values = {field: [] for field in fields}
    if db_mode():
        if _normalize_scope(scope) == 'full':
            for row in _csv_rows_for_db_scope(species_id, omics, 'full', limit=limit):
                for field in fields:
                    value = _feature_value_from_sources(row, row, field)
                    if value is not None:
                        values[field].append(float(value))
            return values
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type=omics)
            .only('numeric_summary', 'payload_json')[:limit]
        )
        seen_records = False
        for record in qs.iterator(chunk_size=2000):
            seen_records = True
            numeric = record.numeric_summary or {}
            payload = record.payload_json or {}
            for field in fields:
                value = _feature_value_from_sources(numeric, payload, field)
                if value is not None:
                    values[field].append(float(value))
        if not seen_records:
            for row in _csv_rows_for_db_scope(species_id, omics, 'core', limit=limit):
                for field in fields:
                    value = _feature_value_from_sources(row, row, field)
                    if value is not None:
                        values[field].append(float(value))
    else:
        for row in _file_rows_for_scope(species_id, omics, 'core')[:limit]:
            for field in fields:
                value = _feature_value_from_sources(row, row, field)
                if value is not None:
                    values[field].append(float(value))
    return values


def _field_examples_from_records(species_id: str, omics: str, fields: list[str], limit: int = 12000, scope: str = 'core') -> dict[str, dict[str, Any]]:
    examples: dict[str, dict[str, Any]] = {}
    if db_mode():
        if _normalize_scope(scope) == 'full':
            for row in _csv_rows_for_db_scope(species_id, omics, 'full', limit=limit):
                for field in fields:
                    if field in examples:
                        continue
                    value = _feature_value_from_sources(row, row, field)
                    if value is None:
                        continue
                    examples[field] = {
                        'entity_id': row.get('entity_id') or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id'),
                        'gene_id': row.get('gene_id') or row.get('ensembl_gene_id'),
                        'gene_name': row.get('gene_name') or row.get('gene_symbol'),
                        'value': round(float(value), 6),
                    }
                if len(examples) == len(fields):
                    break
            return examples
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type=omics)
            .only('entity_id', 'canonical_gene_id', 'gene_name', 'numeric_summary', 'payload_json')[:limit]
        )
        seen_records = False
        for record in qs.iterator(chunk_size=2000):
            seen_records = True
            numeric = record.numeric_summary or {}
            payload = record.payload_json or {}
            for field in fields:
                if field in examples:
                    continue
                value = _feature_value_from_sources(numeric, payload, field)
                if value is None:
                    continue
                examples[field] = {
                    'entity_id': record.entity_id,
                    'gene_id': record.canonical_gene_id,
                    'gene_name': record.gene_name,
                    'value': round(float(value), 6),
                }
            if len(examples) == len(fields):
                break
        if not seen_records:
            for row in _csv_rows_for_db_scope(species_id, omics, 'core', limit=limit):
                for field in fields:
                    if field in examples:
                        continue
                    value = _feature_value_from_sources(row, row, field)
                    if value is None:
                        continue
                    examples[field] = {
                        'entity_id': row.get('entity_id') or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id'),
                        'gene_id': row.get('gene_id') or row.get('ensembl_gene_id'),
                        'gene_name': row.get('gene_name') or row.get('gene_symbol'),
                        'value': round(float(value), 6),
                    }
                if len(examples) == len(fields):
                    break
    else:
        for row in _file_rows_for_scope(species_id, omics, 'core')[:limit]:
            for field in fields:
                if field in examples:
                    continue
                value = _feature_value_from_sources(row, row, field)
                if value is None:
                    continue
                examples[field] = {
                    'entity_id': row.get('entity_id') or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id'),
                    'gene_id': row.get('gene_id') or row.get('ensembl_gene_id'),
                    'gene_name': row.get('gene_name') or row.get('gene_symbol'),
                    'value': round(float(value), 6),
                }
            if len(examples) == len(fields):
                break
    return examples


def _summary_card_from_values(values: list[float]) -> dict[str, Any]:
    if not values:
        return {'mean': 0.0, 'std': 0.0, 'p05': 0.0, 'p25': 0.0, 'p50': 0.0, 'p75': 0.0, 'p95': 0.0}
    ordered = sorted(float(v) for v in values)
    mean_v = _mean(ordered)
    return {
        'mean': round(mean_v, 6),
        'std': round(_std(ordered), 6),
        'p05': round(_percentile(ordered, 0.05), 6),
        'p25': round(_percentile(ordered, 0.25), 6),
        'p50': round(_percentile(ordered, 0.50), 6),
        'p75': round(_percentile(ordered, 0.75), 6),
        'p95': round(_percentile(ordered, 0.95), 6),
    }


def _card_mean(feature_cards: dict[str, Any], field: str) -> float | None:
    card = feature_cards.get(field) or {}
    if not isinstance(card, dict):
        return None
    return _safe_num(card.get('mean') if card.get('mean') is not None else card.get('p50'))


def _add_summary_level_derived_cards(feature_cards: dict[str, Any], distributions: dict[str, Any], omics: str) -> None:
    if omics == 'genome' and 'gc12_percent_estimated' not in feature_cards:
        exon_gc = _card_mean(feature_cards, 'exon_gc_percent')
        gc3 = _card_mean(feature_cards, 'gc3_percent')
        if exon_gc is not None and gc3 is not None:
            value = min(100.0, max(0.0, (3.0 * float(exon_gc) - float(gc3)) / 2.0))
            feature_cards['gc12_percent_estimated'] = {
                'mean': round(value, 6),
                'std': 0.0,
                'p05': round(value, 6),
                'p25': round(value, 6),
                'p50': round(value, 6),
                'p75': round(value, 6),
                'p95': round(value, 6),
                'n_valid': 1,
                'derived_from_summary': True,
            }
            distributions.setdefault('gc12_percent_estimated', {
                'bins': [round(value, 6)],
                'counts': [1],
                'n': 1,
                'derived_from_summary': True,
            })


GENOME_MODULE_REQUIREMENTS = {
    'G1': {
        'name': 'Genome composition & stoichiometric profile',
        'required_fields': ['exon_gc_percent', 'promoter_gc_percent', 'exon_atoms_N_per_base'],
        'missing_fields': ['locus_gc_percent', 'locus_atoms_C_per_base', 'locus_atoms_P_per_base', 'locus_shannon_entropy_acgt', 'ratio_C_N', 'ratio_N_P'],
    },
    'G2': {
        'name': 'Promoter-gene body contrast',
        'required_fields': ['promoter_gc_percent', 'exon_gc_percent', 'promoter_exon_gc_delta'],
        'missing_fields': ['promoter_atoms_N_per_base', 'promoter_atoms_P_per_base', 'exon_atoms_P_per_base', 'promoter_shannon_entropy_acgt', 'exon_shannon_entropy_acgt', 'promoter_dinuc_CG_freq'],
    },
    'G3': {
        'name': 'GC/AT skew asymmetry',
        'required_fields': ['locus_gc_skew', 'locus_at_skew', 'seqid', 'start_1', 'strand'],
        'missing_fields': ['locus_gc_skew', 'locus_at_skew', 'exon_gc_skew', 'promoter_gc_skew'],
    },
    'G4': {
        'name': 'Dinucleotide genomic signature',
        'required_fields': ['locus_dinuc_*_freq', 'promoter_dinuc_*_freq'],
        'missing_fields': ['locus_dinuc_*_freq', 'promoter_dinuc_*_freq', 'locus_dinuc_total_valid', 'promoter_dinuc_total_valid'],
    },
    'G5': {
        'name': 'CDS codon and GC3 strategy',
        'required_fields': ['gc1_percent', 'gc2_percent', 'gc3_percent', 'codon_*_freq', 'codon_entropy_bits', 'aa_*_freq'],
        'missing_fields': ['gc1_percent', 'gc2_percent', 'codon_*_freq', 'codon_entropy_bits', 'aa_*_freq', 'coding_valid'],
    },
    'G6': {
        'name': 'Stoichiometric island / hotspot',
        'required_fields': ['seqid', 'start_1', 'end_1', 'stoich_island_score', 'exon_gc_percent', 'promoter_exon_gc_delta', 'exon_atoms_N_per_base'],
        'missing_fields': ['dinuc_distance_gene', 'codon_deviation', 'locus_atoms_P_per_base', 'C_N_ratio'],
    },
    'G7': {
        'name': 'Genome architecture context',
        'required_fields': ['seqid', 'start_1', 'end_1', 'strand', 'biotype'],
        'missing_fields': ['transcript_count', 'upstream_intergenic_bp', 'downstream_intergenic_bp', 'overlap_bp', 'chosen_transcript_reason'],
    },
    'G8': {
        'name': 'Cross-species genome fingerprint',
        'required_fields': ['species-level exon_gc_percent', 'species-level promoter_gc_percent', 'species-level promoter_exon_gc_delta', 'species-level exon_atoms_N_per_base', 'species-level stoich_island_score'],
        'missing_fields': ['species dinuc fingerprint', 'species codon fingerprint', 'species skew fingerprint'],
    },
}


def _genome_feature_value(row: dict[str, Any], field: str) -> float | None:
    if field == 'gene_length_bp':
        start = _safe_num(row.get('start_1'))
        end = _safe_num(row.get('end_1'))
        if start is not None and end is not None and end >= start:
            return float(end - start + 1)
        return None
    if field in {'promoter_exon_gc_delta', 'gc_delta_promoter_minus_exon'}:
        promoter = _feature_value_from_sources(row, row, 'promoter_gc_percent')
        exon = _feature_value_from_sources(row, row, 'exon_gc_percent')
        if promoter is not None and exon is not None:
            return float(promoter) - float(exon)
        return None
    if field == 'promoter_exon_N_delta':
        promoter = _feature_value_from_sources(row, row, 'promoter_atoms_N_per_base')
        exon = _feature_value_from_sources(row, row, 'exon_atoms_N_per_base')
        if promoter is not None and exon is not None:
            return float(promoter) - float(exon)
        return None
    if field == 'promoter_exon_P_delta':
        promoter = _feature_value_from_sources(row, row, 'promoter_atoms_P_per_base')
        exon = _feature_value_from_sources(row, row, 'exon_atoms_P_per_base')
        if promoter is not None and exon is not None:
            return float(promoter) - float(exon)
        return None
    if field == 'promoter_exon_entropy_delta':
        promoter = _feature_value_from_sources(row, row, 'promoter_shannon_entropy_acgt')
        exon = _feature_value_from_sources(row, row, 'exon_shannon_entropy_acgt')
        if promoter is not None and exon is not None:
            return float(promoter) - float(exon)
        return None
    if field == 'promoter_CG_enrichment':
        promoter = _feature_value_from_sources(row, row, 'promoter_dinuc_CG_freq')
        locus = _feature_value_from_sources(row, row, 'locus_dinuc_CG_freq')
        if promoter is not None and locus is not None:
            return float(promoter) - float(locus)
        return None
    if field == 'coding_valid':
        explicit = _safe_num(row.get('coding_valid'))
        if explicit is not None:
            return float(explicit)
        is_coding = _safe_num(row.get('is_coding'))
        codons = _safe_num(row.get('codon_total_valid'))
        aa_total = _safe_num(row.get('aa_total_20'))
        if (is_coding or 0) > 0 and (codons or 0) > 0 and (aa_total or 0) > 0:
            return 1.0
        return 0.0
    if field == 'overlap_bp':
        upstream = _safe_num(row.get('upstream_overlap_bp')) or 0.0
        downstream = _safe_num(row.get('downstream_overlap_bp')) or 0.0
        return float(upstream + downstream)
    return _feature_value_from_sources(row, row, field)


def _set_if_number(row: dict[str, Any], key: str, value: float | None) -> None:
    if value is not None:
        row[key] = round(float(value), 8)


def _mean_vector(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, float]:
    output = {}
    for field in fields:
        values = [_genome_feature_value(row, field) for row in rows]
        clean = [float(v) for v in values if v is not None]
        if clean:
            output[field] = _mean(clean)
    return output


def _euclidean_distance_to_background(row: dict[str, Any], fields: list[str], background: dict[str, float]) -> float | None:
    diffs = []
    for field in fields:
        value = _genome_feature_value(row, field)
        bg = background.get(field)
        if value is None or bg is None:
            continue
        diffs.append((float(value) - float(bg)) ** 2)
    if not diffs:
        return None
    return math.sqrt(sum(diffs))


def _robust_scale_map(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, tuple[float, float]]:
    scales = {}
    for field in fields:
        values = [_genome_feature_value(row, field) for row in rows]
        clean = [float(v) for v in values if v is not None]
        if not clean:
            continue
        median, mad = _robust_z_values(clean)
        scales[field] = (median, mad or 1.0)
    return scales


def _genome_prepare_derived_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    dinuc_fields = [f'locus_dinuc_{key}_freq' for key in DINUCS]
    codon_fields = [f'codon_{key}_freq' for key in CODONS]
    composition_fields = [
        'locus_gc_percent',
        'exon_gc_percent',
        'promoter_gc_percent',
        'locus_atoms_N_per_base',
        'exon_atoms_N_per_base',
        'promoter_atoms_N_per_base',
        'locus_atoms_P_per_base',
        'exon_atoms_P_per_base',
        'promoter_atoms_P_per_base',
        'locus_shannon_entropy_acgt',
        'promoter_exon_gc_delta',
        'promoter_exon_N_delta',
        'promoter_exon_P_delta',
    ]
    for row in rows:
        for field in [
            'gene_length_bp',
            'promoter_exon_gc_delta',
            'gc_delta_promoter_minus_exon',
            'promoter_exon_N_delta',
            'promoter_exon_P_delta',
            'promoter_exon_entropy_delta',
            'promoter_CG_enrichment',
            'coding_valid',
            'overlap_bp',
        ]:
            _set_if_number(row, field, _genome_feature_value(row, field))

    dinuc_background = _mean_vector(rows, dinuc_fields)
    coding_rows = [row for row in rows if (_genome_feature_value(row, 'coding_valid') or 0) > 0]
    codon_background = _mean_vector(coding_rows, codon_fields)
    for row in rows:
        _set_if_number(row, 'dinuc_distance_gene', _euclidean_distance_to_background(row, dinuc_fields, dinuc_background))
        if (_genome_feature_value(row, 'coding_valid') or 0) > 0:
            _set_if_number(row, 'codon_deviation', _euclidean_distance_to_background(row, codon_fields, codon_background))

    score_scales = _robust_scale_map(rows, composition_fields + ['dinuc_distance_gene', 'codon_deviation'])
    for row in rows:
        composition_z = []
        for field in composition_fields:
            value = _genome_feature_value(row, field)
            scale = score_scales.get(field)
            if value is None or not scale:
                continue
            median, mad = scale
            composition_z.append(abs((float(value) - median) / (mad or 1.0)))
        composition_score = _mean(composition_z) if composition_z else None
        dinuc_score = None
        codon_score = None
        for field, target in [('dinuc_distance_gene', 'dinuc_score'), ('codon_deviation', 'codon_score')]:
            value = _genome_feature_value(row, field)
            scale = score_scales.get(field)
            if value is None or not scale:
                continue
            median, mad = scale
            scaled = abs((float(value) - median) / (mad or 1.0))
            if target == 'dinuc_score':
                dinuc_score = scaled
            else:
                codon_score = scaled
            _set_if_number(row, target, scaled)
        components = [v for v in [composition_score, dinuc_score, codon_score] if v is not None]
        _set_if_number(row, 'composition_score', composition_score)
        if components:
            _set_if_number(row, 'stoich_island_score', _mean(components))
    return rows


def _genome_module_rows(species_id: str, limit: int = 5000, scope: str = 'core') -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if db_mode():
        if _normalize_scope(scope) == 'full':
            return _csv_rows_for_db_scope(species_id, 'genome', 'full', limit=limit)
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type='genome')
            .only('entity_id', 'canonical_gene_id', 'gene_name', 'strategy_cluster', 'seqid', 'start_pos', 'end_pos', 'numeric_summary', 'payload_json')[:limit]
        )
        for record in qs.iterator(chunk_size=3000):
            payload = record.payload_json or {}
            numeric = record.numeric_summary or {}
            row = {**payload, **numeric}
            row.setdefault('entity_id', record.entity_id)
            row.setdefault('gene_id', record.canonical_gene_id)
            row.setdefault('gene_name', record.gene_name)
            row.setdefault('strategy_cluster', record.strategy_cluster)
            row.setdefault('seqid', record.seqid)
            row.setdefault('start_1', record.start_pos)
            row.setdefault('end_1', record.end_pos)
            rows.append(row)
        if not rows:
            rows = list(_csv_rows_for_db_scope(species_id, 'genome', 'core', limit=limit))
    else:
        rows = list(_file_rows_for_scope(species_id, 'genome', 'core')[:limit])
    return rows


def _genome_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    values = []
    for row in rows:
        value = _genome_feature_value(row, field)
        if value is not None:
            values.append(float(value))
    return values


def _genome_missing_rate(rows: list[dict[str, Any]], field: str) -> float:
    if not rows:
        return 1.0
    return round(1.0 - (_safe_div(len(_genome_values(rows, field)), len(rows))), 6)


def _robust_z_values(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 1.0
    ordered = sorted(values)
    median = _percentile(ordered, 0.5)
    deviations = sorted(abs(v - median) for v in values)
    mad = _percentile(deviations, 0.5) or 1.0
    return float(median), float(mad)


def _genome_rank_rows(rows: list[dict[str, Any]], field: str, reverse: bool = True, limit: int = 12) -> list[dict[str, Any]]:
    ranked = []
    for row in rows:
        value = _genome_feature_value(row, field)
        if value is None:
            continue
        ranked.append({
            'entity_id': row.get('entity_id') or row.get('gene_id'),
            'gene_id': row.get('gene_id') or row.get('entity_id'),
            'gene_name': row.get('gene_name') or '',
            'seqid': row.get('seqid') or '',
            'start_1': row.get('start_1'),
            'end_1': row.get('end_1'),
            'strand': row.get('strand') or '',
            'biotype': row.get('biotype') or '',
            'strategy_cluster': row.get('strategy_cluster') or '',
            'value': round(float(value), 6),
        })
    return sorted(ranked, key=lambda item: item['value'], reverse=reverse)[:limit]


def _genome_scatter(rows: list[dict[str, Any]], x_field: str, y_field: str, limit: int = 5000) -> list[dict[str, Any]]:
    points = []
    for row in rows:
        x = _genome_feature_value(row, x_field)
        y = _genome_feature_value(row, y_field)
        if x is None or y is None:
            continue
        points.append({
            'entity_id': row.get('entity_id') or row.get('gene_id'),
            'gene_id': row.get('gene_id') or row.get('entity_id'),
            'gene_name': row.get('gene_name') or '',
            x_field: round(float(x), 6),
            y_field: round(float(y), 6),
        })
    if len(points) > limit:
        stride = max(1, len(points) // limit)
        points = points[::stride][:limit]
    return points


def _module_status(required: list[str], available: set[str]) -> str:
    present = 0
    for field in required:
        if '*' in field:
            prefix = field.split('*', 1)[0]
            present += int(any(item.startswith(prefix) for item in available))
        elif field.startswith('species-level '):
            present += int(field.replace('species-level ', '') in available)
        else:
            present += int(field in available)
    if present == len(required):
        return 'implemented'
    if present:
        return 'partial'
    return 'not_implemented'


TRANSCRIPTOME_MODULE_REQUIREMENTS = {
    'T1': {
        'name': 'RNA composition overview',
        'required_fields': ['length_nt_acgu', 'frac_A', 'frac_C', 'frac_G', 'frac_U', 'gc_content', 'nt_entropy'],
        'missing_fields': ['n_A', 'n_C', 'n_G', 'n_U', 'n_other', 'pyrimidine_frac', 'purine_pyrimidine_ratio'],
    },
    'T2': {
        'name': 'RNA elemental stoichiometry',
        'required_fields': ['atoms_per_nt_C', 'atoms_per_nt_N', 'atoms_per_nt_P', 'C_N_ratio', 'N_P_ratio', 'mw_rna_nmp_per_nt_Da'],
        'missing_fields': ['H_atoms', 'O_atoms', 'H_atom_frac', 'O_atom_frac', 'mw_rna_nmp_total_Da'],
    },
    'T3': {
        'name': 'RNA sequence pattern and stability proxy',
        'required_fields': ['dinuc_*_freq', 'nt_entropy', 'max_run_any', 'avg_spacing_A', 'avg_spacing_U'],
        'missing_fields': ['dinuc_*_bias0', 'avg_spacing_C', 'avg_spacing_G', 'RNAfold minimum free energy'],
    },
    'T4': {
        'name': 'Transcript biotype and architecture context',
        'required_fields': ['transcript_biotype', 'gene_biotype', 'seq_region', 'start', 'end', 'strand', 'length_nt_acgu'],
        'missing_fields': ['unified_biotype_mapping', 'isoform rank', 'chosen_transcript_reason'],
    },
    'T5': {
        'name': 'ORF and coding potential',
        'required_fields': ['orf_len_nt', 'orf_len_aa', 'orf_has_stop', 'codon_valid_codons', 'length_nt_acgu'],
        'missing_fields': ['orf_frame', 'orf_start', 'orf_end', 'genetic_code', 'start_codon_setting'],
    },
    'T6': {
        'name': 'Codon usage and translation strategy',
        'required_fields': ['codon_*_freq', 'codon_valid_codons'],
        'missing_fields': ['codon_*_bias0', 'tRNA abundance', 'ribosome profiling'],
    },
    'T7': {
        'name': 'Derived protein-like property preview',
        'required_fields': ['protein_mw_Da', 'protein_isoelectric_point', 'protein_gravy', 'protein_instability_index', 'aa_*_freq'],
        'missing_fields': ['observed proteome abundance', 'experimental protein validation'],
    },
    'T8': {
        'name': 'Transcriptome fingerprint and cross-omics coupling',
        'required_fields': ['species-level gc_content', 'species-level nt_entropy', 'species-level atoms_per_nt_N', 'species-level N_P_ratio', 'species-level orf_valid_ratio'],
        'missing_fields': ['expression-weighted burden', 'stable cross-omics FDR artifact'],
    },
}


def _transcriptome_feature_value(row: dict[str, Any], field: str) -> float | None:
    direct = _feature_value_from_sources(row, row, field)
    if direct is not None:
        return float(direct)
    if field == 'gc_percent_display':
        gc = _feature_value_from_sources(row, row, 'gc_content')
        if gc is not None:
            return float(gc) * 100.0 if float(gc) <= 1.0 else float(gc)
    if field == 'ambiguous_ratio':
        n_value = _safe_num(row.get('n_N'))
        other = _safe_num(row.get('n_other')) or 0.0
        total = _safe_num(row.get('length_nt_total')) or _safe_num(row.get('length_nt_acgu'))
        if n_value is not None and total and float(total) > 0:
            return (float(n_value) + float(other)) / float(total)
    if field == 'coding_valid':
        aa_len = _safe_num(row.get('aa_len')) or _safe_num(row.get('orf_len_aa'))
        codons = _safe_num(row.get('codon_valid_codons'))
        return 1.0 if (aa_len or 0) > 0 and (codons or 0) > 0 else 0.0
    if field == 'coding_coverage':
        orf_len = _safe_num(row.get('orf_len_nt'))
        length = _safe_num(row.get('length_nt_acgu')) or _safe_num(row.get('clean_rna_len'))
        if orf_len is not None and length and float(length) > 0:
            return min(1.0, max(0.0, float(orf_len) / float(length)))
    if field == 'derived_gc3':
        total = 0.0
        used = 0
        for codon in RNA_CODONS:
            value = _safe_num(row.get(f'codon_{codon}_freq'))
            if value is None:
                continue
            used += 1
            if codon[2] in {'G', 'C'}:
                total += float(value)
        if used:
            return total
    if field == 'codon_entropy_bits':
        values = [float(v) for v in (_safe_num(row.get(f'codon_{codon}_freq')) for codon in RNA_CODONS) if v is not None and float(v) > 0]
        if values:
            return -sum(v * math.log(v, 2) for v in values)
    if field == 'atoms_per_nt_P':
        length = _safe_num(row.get('length_nt_acgu'))
        p_atoms = _safe_num(row.get('P_atoms'))
        if length and p_atoms is not None and float(length) > 0:
            return float(p_atoms) / float(length)
    if field == 'N_P_ratio':
        n_value = _safe_num(row.get('N_atoms')) or _safe_num(row.get('atoms_per_nt_N'))
        p_value = _safe_num(row.get('P_atoms')) or _safe_num(row.get('atoms_per_nt_P'))
        if n_value is not None and p_value and float(p_value) > 0:
            return float(n_value) / float(p_value)
    return None


def _transcriptome_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    values = []
    for row in rows:
        value = _transcriptome_feature_value(row, field)
        if value is not None:
            values.append(float(value))
    return values


def _transcriptome_module_rows(species_id: str, limit: int = 5000, scope: str = 'core') -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if db_mode():
        if _normalize_scope(scope) == 'full':
            return _csv_rows_for_db_scope(species_id, 'transcriptome', 'full', limit=limit)
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type='transcriptome')
            .only('entity_id', 'canonical_gene_id', 'gene_name', 'strategy_cluster', 'seqid', 'start_pos', 'end_pos', 'numeric_summary', 'payload_json')[:limit]
        )
        for record in qs.iterator(chunk_size=3000):
            payload = record.payload_json or {}
            numeric = record.numeric_summary or {}
            row = {**payload, **numeric}
            row.setdefault('entity_id', record.entity_id)
            row.setdefault('transcript_id', record.entity_id)
            row.setdefault('gene_id', record.canonical_gene_id or payload.get('gene_id'))
            row.setdefault('gene_symbol', record.gene_name or payload.get('gene_symbol'))
            row.setdefault('strategy_cluster', record.strategy_cluster)
            row.setdefault('seq_region', record.seqid or payload.get('seq_region'))
            row.setdefault('start', record.start_pos or payload.get('start'))
            row.setdefault('end', record.end_pos or payload.get('end'))
            rows.append(row)
        if not rows:
            rows = list(_csv_rows_for_db_scope(species_id, 'transcriptome', scope, limit=limit))
    else:
        rows = list(_file_rows_for_scope(species_id, 'transcriptome', scope)[:limit])
    return rows


def _transcriptome_prepare_derived_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    dinuc_fields = [f'dinuc_{key}_freq' for key in RNA_DINUCS]
    codon_fields = [f'codon_{key}_freq' for key in RNA_CODONS]
    for row in rows:
        row.setdefault('entity_id', row.get('transcript_id') or row.get('entity_id') or '')
        for field in ['gc_percent_display', 'ambiguous_ratio', 'coding_valid', 'coding_coverage', 'derived_gc3', 'codon_entropy_bits', 'atoms_per_nt_P', 'N_P_ratio']:
            _set_if_number(row, field, _transcriptome_feature_value(row, field))

    dinuc_background = _mean_vector(rows, dinuc_fields)
    coding_rows = [row for row in rows if (_transcriptome_feature_value(row, 'coding_valid') or 0) > 0]
    codon_background = _mean_vector(coding_rows, codon_fields)
    for row in rows:
        _set_if_number(row, 'dinuc_distance_transcript', _euclidean_distance_to_background(row, dinuc_fields, dinuc_background))
        if (_transcriptome_feature_value(row, 'coding_valid') or 0) > 0:
            _set_if_number(row, 'codon_deviation', _euclidean_distance_to_background(row, codon_fields, codon_background))

    stability_fields = ['gc_content', 'max_run_any', 'nt_entropy']
    stability_scales = _robust_scale_map(rows, stability_fields)
    resource_fields = ['atoms_per_nt_N', 'atoms_per_nt_P', 'C_N_ratio', 'N_P_ratio', 'mw_rna_nmp_per_nt_Da']
    resource_scales = _robust_scale_map(rows, resource_fields)
    for row in rows:
        gc_value = _transcriptome_feature_value(row, 'gc_content')
        run_value = _transcriptome_feature_value(row, 'max_run_any')
        entropy_value = _transcriptome_feature_value(row, 'nt_entropy')
        components = []
        for field, value, sign in [('gc_content', gc_value, 1.0), ('max_run_any', run_value, 1.0), ('nt_entropy', entropy_value, -1.0)]:
            scale = stability_scales.get(field)
            if value is None or not scale:
                continue
            median, mad = scale
            components.append(sign * ((float(value) - median) / (mad or 1.0)))
        if components:
            _set_if_number(row, 'stability_proxy_score', _mean(components))

        resource_z = []
        for field in resource_fields:
            value = _transcriptome_feature_value(row, field)
            scale = resource_scales.get(field)
            if value is None or not scale:
                continue
            median, mad = scale
            resource_z.append(abs((float(value) - median) / (mad or 1.0)))
        if resource_z:
            _set_if_number(row, 'resource_outlier_score', _mean(resource_z))
    return rows


def _transcriptome_rank_rows(rows: list[dict[str, Any]], field: str, reverse: bool = True, limit: int = 12) -> list[dict[str, Any]]:
    ranked = []
    for row in rows:
        value = _transcriptome_feature_value(row, field)
        if value is None:
            continue
        ranked.append({
            'entity_id': row.get('entity_id') or row.get('transcript_id'),
            'transcript_id': row.get('transcript_id') or row.get('entity_id'),
            'gene_id': row.get('gene_id') or '',
            'gene_symbol': row.get('gene_symbol') or row.get('gene_name') or '',
            'transcript_biotype': row.get('transcript_biotype') or '',
            'seq_region': row.get('seq_region') or '',
            'start': row.get('start'),
            'end': row.get('end'),
            'value': round(float(value), 6),
        })
    return sorted(ranked, key=lambda item: item['value'], reverse=reverse)[:limit]


def _transcriptome_scatter(rows: list[dict[str, Any]], x_field: str, y_field: str, limit: int = 5000) -> list[dict[str, Any]]:
    points = []
    for row in rows:
        x = _transcriptome_feature_value(row, x_field)
        y = _transcriptome_feature_value(row, y_field)
        if x is None or y is None:
            continue
        points.append({
            'entity_id': row.get('entity_id') or row.get('transcript_id'),
            'transcript_id': row.get('transcript_id') or row.get('entity_id'),
            'gene_symbol': row.get('gene_symbol') or '',
            x_field: round(float(x), 6),
            y_field: round(float(y), 6),
        })
    if len(points) > limit:
        stride = max(1, len(points) // limit)
        points = points[::stride][:limit]
    return points


def _group_numeric_summary(rows: list[dict[str, Any]], group_key: str, value_field: str, limit: int = 12) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for row in rows:
        group = str(row.get(group_key) or 'unknown')
        value = _transcriptome_feature_value(row, value_field)
        if value is None:
            continue
        buckets.setdefault(group, []).append(float(value))
    output = []
    for group, values in buckets.items():
        if not values:
            continue
        output.append({'group': group, 'n': len(values), 'mean': round(_mean(values), 6), 'median': round(_percentile(sorted(values), 0.5), 6)})
    return sorted(output, key=lambda item: item['n'], reverse=True)[:limit]


def _transcriptome_heatmap_matrix(rows: list[dict[str, Any]], x_groups: list[str], y_groups: list[str], value_func) -> dict[str, Any]:
    values = []
    for y_idx, y_key in enumerate(y_groups):
        for x_idx, x_key in enumerate(x_groups):
            values.append([x_idx, y_idx, value_func(x_key, y_key)])
    return {'x_labels': x_groups, 'y_labels': y_groups, 'values': values}


def _transcriptome_fingerprint_from_cards(species_id: str, display_name: str, feature_cards: dict[str, Any]) -> dict[str, Any]:
    fields = [
        'gc_content', 'gc_percent_display', 'nt_entropy', 'length_nt_acgu',
        'atoms_per_nt_N', 'atoms_per_nt_P', 'C_N_ratio', 'N_P_ratio',
        'mw_rna_nmp_per_nt_Da', 'orf_len_aa', 'protein_gravy',
        'protein_isoelectric_point', 'protein_instability_index', 'codon_valid_codons',
        'codon_entropy_bits', 'derived_gc3',
    ]
    fields.extend([f'dinuc_{dinuc}_freq' for dinuc in RNA_DINUCS])
    fields.extend([f'codon_{codon}_freq' for codon in RNA_CODONS])
    row: dict[str, Any] = {'species_id': species_id, 'display_name': display_name}
    for field in fields:
        card = feature_cards.get(field) or {}
        if not isinstance(card, dict):
            continue
        value = _safe_num(card.get('mean') if card.get('mean') is not None else card.get('p50'))
        if value is not None:
            row[field] = round(float(value), 6)
    return row


def _transcriptome_species_fingerprint_rows(current_species_id: str, current_feature_cards: dict[str, Any], current_rows: list[dict[str, Any]], scope: str, limit: int = 80) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if db_mode():
        datasets = (
            OmicsDataset.objects
            .filter(omics_type='transcriptome')
            .select_related('species')
            .only('summary_payload', 'species__species_id', 'species__display_name')
            .order_by('species__display_name')[:limit]
        )
        for ds in datasets:
            scoped_summary = _scoped_payload_from_db(ds.summary_payload or {}, scope)
            cards = scoped_summary.get('feature_cards') if isinstance(scoped_summary, dict) else {}
            rows.append(_transcriptome_fingerprint_from_cards(ds.species.species_id, ds.species.display_name, cards if isinstance(cards, dict) else {}))
    else:
        for species_id, meta in list(file_species_map().items())[:limit]:
            try:
                scoped_summary = _load_scoped_file_json(species_id, 'transcriptome', 'summary', scope)
            except Exception:
                continue
            cards = scoped_summary.get('feature_cards') if isinstance(scoped_summary, dict) else {}
            rows.append(_transcriptome_fingerprint_from_cards(species_id, meta.get('display_name') or species_id, cards if isinstance(cards, dict) else {}))

    current_cards = dict(current_feature_cards or {})
    for field in [
        'gc_content', 'gc_percent_display', 'nt_entropy', 'length_nt_acgu',
        'atoms_per_nt_N', 'atoms_per_nt_P', 'C_N_ratio', 'N_P_ratio',
        'mw_rna_nmp_per_nt_Da', 'orf_len_aa', 'protein_gravy',
        'protein_isoelectric_point', 'protein_instability_index',
        'codon_valid_codons', 'codon_entropy_bits', 'derived_gc3',
    ] + [f'dinuc_{dinuc}_freq' for dinuc in RNA_DINUCS] + [f'codon_{codon}_freq' for codon in RNA_CODONS]:
        values = _transcriptome_values(current_rows, field)
        if values:
            current_cards[field] = {'mean': _mean(values), 'p50': _percentile(sorted(values), 0.5)}

    try:
        current_display = Species.objects.only('display_name').get(species_id=current_species_id).display_name if db_mode() else file_species_map().get(current_species_id, {}).get('display_name') or current_species_id
    except Exception:
        current_display = current_species_id
    current_row = _transcriptome_fingerprint_from_cards(current_species_id, current_display, current_cards)
    for idx, row in enumerate(rows):
        if row.get('species_id') == current_species_id:
            rows[idx] = current_row
            break
    else:
        rows.insert(0, current_row)
    return rows


def _transcriptome_module_suite(species_id: str, summary: dict[str, Any], scope: str, *, complete_core: bool = False) -> dict[str, Any]:
    requested_scope = scope
    analysis_scope = scope
    complete_core_meta: dict[str, Any] = {}
    if complete_core:
        rows, complete_core_meta = _complete_core_rows_for_module_suite(species_id, 'transcriptome')
        requested_scope = 'core'
        analysis_scope = 'complete_core_csv'
    else:
        rows = _transcriptome_module_rows(species_id, scope=scope)
    if not complete_core and _normalize_scope(scope) != 'full':
        row_keys: set[str] = set()
        for row in rows[:250]:
            row_keys.update(str(key) for key in row.keys())
        needs_full = (
            not any(key.startswith('codon_') and key.endswith('_freq') for key in row_keys)
            or not any(key.endswith('_bias0') for key in row_keys)
            or 'avg_spacing_C' not in row_keys
        )
        if needs_full:
            full_rows = _transcriptome_module_rows(species_id, scope='full')
            full_keys: set[str] = set()
            for row in full_rows[:250]:
                full_keys.update(str(key) for key in row.keys())
            if full_rows and (any(key.startswith('codon_') and key.endswith('_freq') for key in full_keys) or any(key.endswith('_bias0') for key in full_keys)):
                rows = full_rows
                analysis_scope = 'full_registered_csv'
    rows = _transcriptome_prepare_derived_rows(rows)
    feature_cards = summary.get('feature_cards') if isinstance(summary.get('feature_cards'), dict) else {}
    available = set()
    for row in rows[:5000]:
        for key, value in row.items():
            if _safe_num(value) is not None or key in {'transcript_id', 'gene_id', 'gene_symbol', 'transcript_biotype', 'gene_biotype', 'seq_region', 'strand'}:
                available.add(str(key))
    available.update(str(key) for key in feature_cards.keys())

    def card(field: str) -> dict[str, Any]:
        values = _transcriptome_values(rows, field)
        return {**_summary_card_from_values(values), 'n_valid': len(values), 'missing_rate': round(1.0 - _safe_div(len(values), len(rows)), 6) if rows else 1.0}

    base_fraction_rows = [{'name': base, 'value': round(_mean(_transcriptome_values(rows, f'frac_{base}')), 6) if _transcriptome_values(rows, f'frac_{base}') else 0} for base in RNA_BASES]
    element_fraction_rows = [{'name': key, 'value': round(_mean(_transcriptome_values(rows, field)), 6) if _transcriptome_values(rows, field) else 0} for key, field in [('C', 'C_atom_frac'), ('H', 'H_atom_frac'), ('O', 'O_atom_frac'), ('N', 'N_atom_frac'), ('P', 'P_atom_frac')]]
    if not any(row['value'] for row in element_fraction_rows):
        element_fraction_rows = [{'name': key, 'value': round(_mean(_transcriptome_values(rows, field)), 6) if _transcriptome_values(rows, field) else 0} for key, field in [('C', 'atoms_per_nt_C'), ('N', 'atoms_per_nt_N'), ('P', 'atoms_per_nt_P')]]

    dinuc_heatmap_values = []
    for idx, dinuc in enumerate(RNA_DINUCS):
        values = _transcriptome_values(rows, f'dinuc_{dinuc}_freq')
        dinuc_heatmap_values.append([idx % 4, idx // 4, round(_mean(values), 8) if values else 0])
    codon_heatmap_values = []
    coding_rows = [row for row in rows if (_transcriptome_feature_value(row, 'coding_valid') or 0) > 0]
    for idx, codon in enumerate(RNA_CODONS):
        values = _transcriptome_values(coding_rows, f'codon_{codon}_freq')
        codon_heatmap_values.append([idx % 16, idx // 16, round(_mean(values), 8) if values else 0])
    aa_composition = []
    for aa in AMINO_ACIDS_20:
        values = _transcriptome_values(coding_rows, f'aa_{aa}_freq')
        if values:
            aa_composition.append({'name': aa, 'value': round(_mean(values), 8)})

    biotype_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get('transcript_biotype') or 'unknown')
        biotype_counts[key] = biotype_counts.get(key, 0) + 1
    metadata_fields = ['transcript_id', 'gene_id', 'gene_symbol', 'transcript_biotype', 'seq_region', 'start', 'end', 'strand']
    metadata_completeness = [{'field': field, 'coverage': round(_safe_div(sum(1 for row in rows if str(row.get(field) or '').strip()), len(rows)), 6) if rows else 0.0} for field in metadata_fields]

    orf_valid_values = _transcriptome_values(rows, 'coding_valid')
    stop_values = [1.0 if str(row.get('orf_has_stop')).strip().lower() in {'1', 'true', 'yes'} or _safe_num(row.get('orf_has_stop')) == 1 else 0.0 for row in rows if str(row.get('orf_has_stop') or '').strip()]
    biotypes = sorted(biotype_counts.keys(), key=lambda item: biotype_counts[item], reverse=True)[:10]
    orf_matrix = _transcriptome_heatmap_matrix(
        rows,
        ['valid_orf', 'no_valid_orf'],
        biotypes,
        lambda x, y: sum(1 for row in rows if str(row.get('transcript_biotype') or 'unknown') == y and ((_transcriptome_feature_value(row, 'coding_valid') or 0) > 0) == (x == 'valid_orf')),
    )

    resource_fields = ['atoms_per_nt_N', 'atoms_per_nt_P', 'C_N_ratio', 'N_P_ratio', 'mw_rna_nmp_per_nt_Da']
    stoich_fields = ['gc_content', 'nt_entropy'] + resource_fields
    dinuc_fields = [f'dinuc_{dinuc}_freq' for dinuc in RNA_DINUCS]
    codon_fields = [f'codon_{codon}_freq' for codon in RNA_CODONS]
    protein_fields = ['protein_mw_Da', 'protein_isoelectric_point', 'protein_gravy', 'protein_instability_index', 'protein_aromaticity']
    t2_projection = _genome_projection_payload(rows, stoich_fields, label_prefix='rna_resource')
    t3_projection = _genome_projection_payload(rows, dinuc_fields + ['nt_entropy', 'max_run_any', 'stability_proxy_score'], label_prefix='rna_pattern')
    t6_projection = _genome_projection_payload(coding_rows, codon_fields + ['codon_entropy_bits', 'derived_gc3'], label_prefix='codon_strategy')
    t7_projection = _genome_projection_payload(coding_rows, resource_fields + protein_fields, label_prefix='protein_preview')

    species_rows = _transcriptome_species_fingerprint_rows(species_id, feature_cards, rows, scope)
    t8_metrics = [field for field in ['gc_content', 'nt_entropy', 'atoms_per_nt_N', 'atoms_per_nt_P', 'N_P_ratio', 'orf_len_aa', 'protein_gravy', 'protein_isoelectric_point', 'protein_instability_index', 'codon_entropy_bits', 'derived_gc3'] + dinuc_fields + codon_fields if any(_safe_num(row.get(field)) is not None for row in species_rows)]
    t8_species_pca = _species_pca_payload(species_rows, t8_metrics)
    t8_distance = _species_distance_heatmap(species_rows, t8_metrics)
    if len(t8_distance.get('x_labels') or []) < 2:
        t8_distance = _feature_distance_heatmap_from_rows(rows, t8_metrics, method='current_species_transcriptome_feature_correlation_distance')
    current_fingerprint = next((row for row in species_rows if row.get('species_id') == species_id), {})

    modules = [
        {
            'id': 'T1',
            'name': TRANSCRIPTOME_MODULE_REQUIREMENTS['T1']['name'],
            'status': _module_status(TRANSCRIPTOME_MODULE_REQUIREMENTS['T1']['required_fields'], available),
            'cards': {field: card(field) for field in ['length_nt_acgu', 'gc_content', 'nt_entropy', 'ambiguous_ratio', 'purine_frac']},
            'base_composition': base_fraction_rows,
            'length_histogram': _histogram_payload(_transcriptome_values(rows, 'length_nt_acgu'), bins=42),
            'gc_histogram': _histogram_payload(_transcriptome_values(rows, 'gc_content'), bins=42),
            'entropy_histogram': _histogram_payload(_transcriptome_values(rows, 'nt_entropy'), bins=42),
            'method': 'GC=(G+C)/(A+C+G+U); AT skew=(A-U)/(A+U); GC skew=(G-C)/(G+C); nt_entropy=-sum p(base)log2p(base). Ambiguous bases are tracked separately.',
            'implementation_notes': ['T1 uses core transcript rows and remains available without full CSV when composition fields are present.'],
        },
        {
            'id': 'T2',
            'name': TRANSCRIPTOME_MODULE_REQUIREMENTS['T2']['name'],
            'status': _module_status(TRANSCRIPTOME_MODULE_REQUIREMENTS['T2']['required_fields'], available),
            'cards': {field: card(field) for field in resource_fields},
            'element_profile': element_fraction_rows,
            'resource_projection': t2_projection,
            'resource_cluster_counts': t2_projection.get('cluster_counts', []),
            'resource_outliers': _transcriptome_rank_rows(rows, 'resource_outlier_score', reverse=True, limit=16),
            'top_n_rich': _transcriptome_rank_rows(rows, 'atoms_per_nt_N', reverse=True, limit=10),
            'top_p_rich': _transcriptome_rank_rows(rows, 'atoms_per_nt_P', reverse=True, limit=10),
            'np_ratio_histogram': _histogram_payload(_transcriptome_values(rows, 'N_P_ratio'), bins=42),
            'method': 'RNA_NMP_v1 maps A/C/G/U counts to nucleotide monophosphate formulas; atoms_per_nt_X=X_atoms/length_nt_acgu and N_P_ratio=N_atoms/P_atoms.',
            'implementation_notes': ['Resource outlier score is the mean absolute robust z-score across RNA elemental fields.'],
        },
        {
            'id': 'T3',
            'name': TRANSCRIPTOME_MODULE_REQUIREMENTS['T3']['name'],
            'status': _module_status(TRANSCRIPTOME_MODULE_REQUIREMENTS['T3']['required_fields'], available),
            'dinuc_heatmap': {'x_labels': RNA_BASES, 'y_labels': RNA_BASES, 'values': dinuc_heatmap_values, 'dinucs': RNA_DINUCS},
            'pattern_cards': {field: card(field) for field in ['max_run_any', 'avg_spacing_A', 'avg_spacing_U', 'dinuc_distance_transcript', 'stability_proxy_score']},
            'stability_histogram': _histogram_payload(_transcriptome_values(rows, 'stability_proxy_score'), bins=42),
            'dinuc_projection': t3_projection,
            'dinuc_cluster_counts': t3_projection.get('cluster_counts', []),
            'low_complexity_candidates': sorted(
                _transcriptome_rank_rows(rows, 'max_run_any', reverse=True, limit=10) + _transcriptome_rank_rows(rows, 'nt_entropy', reverse=False, limit=10),
                key=lambda item: abs(float(item.get('value') or 0)),
                reverse=True,
            )[:16],
            'pattern_coupling_heatmap': _genome_correlation_heatmap(rows, ['gc_content', 'nt_entropy', 'max_run_any', 'dinuc_distance_transcript', 'orf_len_aa', 'protein_instability_index']),
            'method': 'dinuc_XY_freq=valid XY pairs/dinuc_valid_pairs; stability_proxy is exploratory: robust_z(gc_content)+robust_z(max_run_any)-robust_z(nt_entropy).',
            'implementation_notes': ['This is a stability proxy and does not replace RNA folding energy.'],
        },
        {
            'id': 'T4',
            'name': TRANSCRIPTOME_MODULE_REQUIREMENTS['T4']['name'],
            'status': _module_status(TRANSCRIPTOME_MODULE_REQUIREMENTS['T4']['required_fields'], available),
            'biotype_counts': [{'name': key, 'value': value} for key, value in sorted(biotype_counts.items(), key=lambda item: item[1], reverse=True)],
            'length_by_biotype': _group_numeric_summary(rows, 'transcript_biotype', 'length_nt_acgu'),
            'gc_by_biotype': _group_numeric_summary(rows, 'transcript_biotype', 'gc_content'),
            'metadata_completeness': metadata_completeness,
            'method': 'Biotype composition counts transcript_biotype values; length and GC summaries are grouped by transcript_biotype.',
            'implementation_notes': ['Biotype naming is source-dependent; values are shown as imported unless a future mapping table is added.'],
        },
        {
            'id': 'T5',
            'name': TRANSCRIPTOME_MODULE_REQUIREMENTS['T5']['name'],
            'status': _module_status(TRANSCRIPTOME_MODULE_REQUIREMENTS['T5']['required_fields'], available),
            'cards': {
                'coding_valid_ratio': round(_mean(orf_valid_values), 6) if orf_valid_values else None,
                'median_orf_len_nt': card('orf_len_nt').get('p50'),
                'median_orf_len_aa': card('orf_len_aa').get('p50'),
                'has_stop_ratio': round(_mean(stop_values), 6) if stop_values else None,
                'median_coding_coverage': card('coding_coverage').get('p50'),
            },
            'orf_length_histogram': _histogram_payload(_transcriptome_values(rows, 'orf_len_aa'), bins=42),
            'orf_vs_transcript_scatter': _transcriptome_scatter(rows, 'length_nt_acgu', 'orf_len_nt'),
            'biotype_orf_matrix': orf_matrix,
            'coding_potential_candidates': sorted(
                _transcriptome_rank_rows(rows, 'coding_coverage', reverse=True, limit=12) + _transcriptome_rank_rows(rows, 'orf_len_aa', reverse=True, limit=12),
                key=lambda item: float(item.get('value') or 0),
                reverse=True,
            )[:16],
            'method': 'coding_coverage=orf_len_nt/length_nt_acgu; coding_valid requires a positive ORF amino-acid length and positive valid codon count.',
            'implementation_notes': ['Longest ORF is a sequence-derived proxy and should not be treated as curated CDS evidence.'],
        },
        {
            'id': 'T6',
            'name': TRANSCRIPTOME_MODULE_REQUIREMENTS['T6']['name'],
            'status': _module_status(TRANSCRIPTOME_MODULE_REQUIREMENTS['T6']['required_fields'], available),
            'codon_heatmap': {'x_labels': [str(i + 1) for i in range(16)], 'y_labels': ['AAA-AUU', 'CAA-CUU', 'GAA-GUU', 'UAA-UUU'], 'values': codon_heatmap_values, 'codons': RNA_CODONS},
            'codon_entropy_histogram': _histogram_payload(_transcriptome_values(coding_rows, 'codon_entropy_bits'), bins=42),
            'derived_gc3_histogram': _histogram_payload(_transcriptome_values(coding_rows, 'derived_gc3'), bins=42),
            'codon_projection': t6_projection,
            'codon_cluster_counts': t6_projection.get('cluster_counts', []),
            'codon_anomaly_transcripts': _transcriptome_rank_rows(coding_rows, 'codon_deviation', reverse=True, limit=16),
            'method': 'codon_XXX_freq=codon count/valid codons; derived_gc3=sum codon frequencies ending in G/C; codon entropy=-sum p(codon)log2p(codon).',
            'implementation_notes': ['Codon strategy is a translation proxy; tRNA abundance and ribosome profiling are not present in this release.'],
        },
        {
            'id': 'T7',
            'name': TRANSCRIPTOME_MODULE_REQUIREMENTS['T7']['name'],
            'status': _module_status(TRANSCRIPTOME_MODULE_REQUIREMENTS['T7']['required_fields'], available),
            'cards': {field: card(field) for field in protein_fields},
            'property_distributions': {field: _histogram_payload(_transcriptome_values(coding_rows, field), bins=42) for field in protein_fields},
            'aa_composition': aa_composition,
            'protein_projection': t7_projection,
            'protein_cluster_counts': t7_projection.get('cluster_counts', []),
            'instability_candidates': _transcriptome_rank_rows(coding_rows, 'protein_instability_index', reverse=True, limit=16),
            'rna_protein_coupling_heatmap': _genome_correlation_heatmap(coding_rows, ['atoms_per_nt_N', 'N_P_ratio', 'gc_content', 'codon_entropy_bits', 'protein_gravy', 'protein_isoelectric_point', 'protein_instability_index']),
            'method': 'Protein-like properties are calculated from the translated longest ORF and AA frequencies are aa_count/aa_len.',
            'implementation_notes': ['T7 is predicted-from-transcript and is not observed proteome evidence.'],
        },
        {
            'id': 'T8',
            'name': TRANSCRIPTOME_MODULE_REQUIREMENTS['T8']['name'],
            'status': _module_status(TRANSCRIPTOME_MODULE_REQUIREMENTS['T8']['required_fields'], available.union({'orf_valid_ratio'})),
            'fingerprint': {key: value for key, value in current_fingerprint.items() if key not in {'species_id', 'display_name'}},
            'species_fingerprint_rows': species_rows,
            'feature_ranking': _fingerprint_feature_rank(species_rows),
            'species_pca': t8_species_pca,
            'distance_matrix': t8_distance,
            'candidate_summary': sorted(
                _transcriptome_rank_rows(rows, 'resource_outlier_score', reverse=True, limit=8)
                + _transcriptome_rank_rows(rows, 'dinuc_distance_transcript', reverse=True, limit=8)
                + _transcriptome_rank_rows(coding_rows, 'codon_deviation', reverse=True, limit=8)
                + _transcriptome_rank_rows(coding_rows, 'protein_instability_index', reverse=True, limit=8),
                key=lambda item: float(item.get('value') or 0),
                reverse=True,
            )[:20],
            'method': 'Species fingerprint aggregates transcript-level T1-T7 features using species summary cards and current on-demand derived values; distance uses shared transcriptome fingerprint features.',
            'implementation_notes': ['Cross-omics coupling is exposed as descriptive candidates here; stable gene-level FDR artifacts should be added as a later dedicated artifact.'],
        },
    ]

    placement = {
        'T1': {'group': 'basic', 'priority': 10, 'default_visible': True, 'anchor_id': 't1-composition', 'requires_full_csv': False},
        'T2': {'group': 'basic_deep', 'priority': 20, 'default_visible': True, 'anchor_id': 't2-elemental', 'requires_full_csv': False},
        'T3': {'group': 'deep', 'priority': 30, 'default_visible': True, 'anchor_id': 't3-pattern', 'requires_full_csv': True},
        'T4': {'group': 'basic', 'priority': 15, 'default_visible': True, 'anchor_id': 't4-biotype', 'requires_full_csv': False},
        'T5': {'group': 'basic_deep', 'priority': 40, 'default_visible': True, 'anchor_id': 't5-orf', 'requires_full_csv': False},
        'T6': {'group': 'deep', 'priority': 50, 'default_visible': True, 'anchor_id': 't6-codon', 'requires_full_csv': True},
        'T7': {'group': 'basic_deep', 'priority': 60, 'default_visible': True, 'anchor_id': 't7-protein-preview', 'requires_full_csv': False},
        'T8': {'group': 'compare', 'priority': 70, 'default_visible': True, 'anchor_id': 't8-fingerprint', 'requires_full_csv': True},
    }
    for module in modules:
        module['placement'] = placement.get(module['id'], {})
        module['missing_fields'] = [field for field in TRANSCRIPTOME_MODULE_REQUIREMENTS[module['id']]['missing_fields'] if '*' not in field and field not in available]

    return {
        'scope': analysis_scope,
        'requested_scope': requested_scope,
        'row_count': len(rows),
        'coding_row_count': len(coding_rows),
        'modules': modules,
        'artifact_recommendations': [
            'transcriptome_basic_summary.json',
            'transcriptome_elemental_budget.json',
            'transcriptome_sequence_pattern.json',
            'transcriptome_orf_coding_potential.json',
            'transcriptome_codon_strategy.json',
            'transcriptome_protein_preview.json',
            'transcriptome_species_fingerprint.json',
        ],
        'quality_rules': [
            {'risk': 'short transcripts', 'message': 'Very short transcripts have unstable GC, dinucleotide and codon estimates.', 'implemented': 'length_nt_acgu' in available},
            {'risk': 'ambiguous bases', 'message': 'High N/other base content can bias composition and entropy metrics.', 'implemented': 'ambiguous_ratio' in available or 'n_N' in available},
            {'risk': 'coding/noncoding mixture', 'message': 'ORF/codon/protein-like panels should be interpreted with transcript_biotype and coding_valid filters.', 'implemented': 'transcript_biotype' in available},
            {'risk': 'derived protein-like properties', 'message': 'T7 is predicted from transcript ORF and is not observed proteome evidence.', 'implemented': True},
        ],
        'method_metadata': {
            'method': 'transcriptome T1-T8 module suite built from core PostgreSQL rows plus registered full CSV fields when needed',
            'normalization': 'raw feature units for summaries; robust z-score for PCA/UMAP and cluster inputs',
            'missing_policy': 'available numeric fields are used; missing or proxy-only fields are explicitly reported per module',
            'evidence_level': 'descriptive / hypothesis-generating',
            **({'complete_core_compute': complete_core_meta} if complete_core_meta else {}),
        },
    }


PROTEOME_MODULE_REQUIREMENTS = {
    'P1': {
        'name': 'Proteome identity & quality context',
        'required_fields': ['protein_id', 'length_aa', 'length_canonical_aa', 'noncanonical_aa', 'unknown_residues_for_atoms', 'stop_asterisk_count'],
        'missing_fields': ['canonical_fraction', 'unknown_atom_ratio', 'seq_md5', 'filtered_scope'],
    },
    'P2': {
        'name': 'Elemental resource budget',
        'required_fields': ['C_atoms_per_aa', 'N_atoms_per_aa', 'S_atoms_per_aa', 'C_N_ratio', 'N_S_ratio', 'C_mass_frac', 'N_mass_frac', 'S_mass_frac'],
        'missing_fields': ['abundance-weighted proteome burden', 'Se_atoms_per_aa'],
    },
    'P3': {
        'name': 'Nitrogen/Sulfur/Se economy',
        'required_fields': ['N_atoms_per_aa', 'S_atoms_per_aa', 'N_S_ratio', 'sulfur_aa_frac', 'cys_count', 'met_count', 'Se_atoms', 'U_count', 'possible_disulfides', 'disulfide_density'],
        'missing_fields': ['environmental sulfur/nitrogen measurements', 'selenoprotein curated annotation'],
    },
    'P4': {
        'name': 'Amino-acid composition atlas',
        'required_fields': ['AA_*_pct', 'aa_hydrophobic_frac', 'aa_polar_frac', 'aa_pos_frac', 'aa_neg_frac', 'aa_aromatic_frac', 'aa_entropy_bits'],
        'missing_fields': ['protein family/domain labels', 'composition cluster validation labels'],
    },
    'P5': {
        'name': 'Physicochemical property spectrum',
        'required_fields': ['mw_da', 'pI', 'net_charge_pH7', 'gravy', 'instability_index', 'aliphatic_index', 'aromaticity'],
        'missing_fields': ['experimental solubility', 'membrane topology annotation'],
    },
    'P6': {
        'name': 'Structure/accessibility proxy',
        'required_fields': ['ss_helix_frac', 'ss_turn_frac', 'ss_sheet_frac', 'flex_mean', 'surface_access_em_mean', 'possible_disulfides', 'disulfide_density'],
        'missing_fields': ['AlphaFold pLDDT', 'signal peptide', 'transmembrane domains'],
    },
    'P7': {
        'name': 'Redox & experimental detectability',
        'required_fields': ['avg_oxidation_state_C', 'O_C_ratio', 'H_C_ratio', 'extinction_reduced', 'extinction_cystines', 'a280_1mgml_reduced', 'aromaticity'],
        'missing_fields': ['measured abundance', 'mass spectrometry detectability', 'experimental redox state'],
    },
    'P8': {
        'name': 'Proteome fingerprint & cross-omics coupling',
        'required_fields': ['species-level N_atoms_per_aa', 'species-level S_atoms_per_aa', 'species-level pI', 'species-level gravy', 'species-level aa_entropy_bits'],
        'missing_fields': ['abundance-weighted species proteome', 'stable cross-omics FDR artifact'],
    },
}


def _proteome_feature_value(row: dict[str, Any], field: str) -> float | None:
    value = _feature_value_from_sources(row, row, field)
    if value is not None:
        return float(value)
    length = _safe_num(row.get('length_aa'))
    if field == 'canonical_fraction':
        canonical = _safe_num(row.get('length_canonical_aa'))
        if canonical is not None and length and float(length) > 0:
            return float(canonical) / float(length)
    if field == 'unknown_atom_ratio':
        unknown = _safe_num(row.get('unknown_residues_for_atoms')) or _safe_num(row.get('AA_other_count')) or _safe_num(row.get('noncanonical_aa'))
        if unknown is not None and length and float(length) > 0:
            return float(unknown) / float(length)
    if field == 'noncanonical_ratio':
        noncanonical = _safe_num(row.get('noncanonical_aa'))
        if noncanonical is not None and length and float(length) > 0:
            return float(noncanonical) / float(length)
    if field == 'Se_atoms_per_aa':
        se_atoms = _safe_num(row.get('Se_atoms'))
        if se_atoms is not None and length and float(length) > 0:
            return float(se_atoms) / float(length)
    if field == 'possible_disulfides':
        cys = _safe_num(row.get('cys_count')) or _safe_num(row.get('AA_C_count'))
        if cys is not None:
            return math.floor(float(cys) / 2.0)
    if field == 'disulfide_density':
        possible = _proteome_feature_value(row, 'possible_disulfides')
        if possible is not None and length and float(length) > 0:
            return float(possible) / float(length)
    if field == 'sulfur_aa_frac':
        cys = _safe_num(row.get('cys_count')) or _safe_num(row.get('AA_C_count')) or 0.0
        met = _safe_num(row.get('met_count')) or _safe_num(row.get('AA_M_count')) or 0.0
        u_count = _safe_num(row.get('U_count')) or 0.0
        if length and float(length) > 0:
            return (float(cys) + float(met) + float(u_count)) / float(length)
    if field == 'avg_residue_mass_da':
        mw = _safe_num(row.get('mw_da')) or _safe_num(row.get('mw_atoms_da'))
        if mw is not None and length and float(length) > 0:
            return float(mw) / float(length)
    if field == 'a280_1mgml_reduced':
        extinction = _safe_num(row.get('extinction_reduced'))
        mw = _safe_num(row.get('mw_da'))
        if extinction is not None and mw and float(mw) > 0:
            return float(extinction) / float(mw)
    if field == 'a280_1mgml_cystines':
        extinction = _safe_num(row.get('extinction_cystines'))
        mw = _safe_num(row.get('mw_da'))
        if extinction is not None and mw and float(mw) > 0:
            return float(extinction) / float(mw)
    if field == 'avg_oxidation_state_C':
        c = _safe_num(row.get('C_atoms'))
        h = _safe_num(row.get('H_atoms'))
        n = _safe_num(row.get('N_atoms'))
        o = _safe_num(row.get('O_atoms'))
        s = _safe_num(row.get('S_atoms')) or 0.0
        se = _safe_num(row.get('Se_atoms')) or 0.0
        if c and h is not None and n is not None and o is not None and float(c) > 0:
            return (-float(h) + 3.0 * float(n) + 2.0 * float(o) + 2.0 * float(s) + 2.0 * float(se)) / float(c)
    return None


def _proteome_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    values = []
    for row in rows:
        value = _proteome_feature_value(row, field)
        if value is not None:
            values.append(float(value))
    return values


def _proteome_module_rows(species_id: str, limit: int = 5000, scope: str = 'core') -> list[dict[str, Any]]:
    if db_mode():
        if _normalize_scope(scope) == 'full':
            return _csv_rows_for_db_scope(species_id, 'proteome', 'full', limit=limit)
        rows: list[dict[str, Any]] = []
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type='proteome')
            .only('entity_id', 'canonical_gene_id', 'gene_name', 'strategy_cluster', 'numeric_summary', 'payload_json')[:limit]
        )
        for record in qs.iterator(chunk_size=3000):
            payload = record.payload_json or {}
            numeric = record.numeric_summary or {}
            row = {**payload, **numeric}
            row.setdefault('entity_id', record.entity_id)
            row.setdefault('protein_id', payload.get('protein_id') or record.entity_id)
            row.setdefault('gene_id', record.canonical_gene_id or payload.get('gene_id') or payload.get('ensembl_gene_id'))
            row.setdefault('gene_symbol', record.gene_name or payload.get('gene_symbol'))
            row.setdefault('strategy_cluster', record.strategy_cluster)
            rows.append(row)
        return rows if rows else list(_csv_rows_for_db_scope(species_id, 'proteome', scope, limit=limit))
    return list(_file_rows_for_scope(species_id, 'proteome', scope)[:limit])


def _proteome_prepare_derived_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    resource_fields = ['N_atoms_per_aa', 'S_atoms_per_aa', 'C_atoms_per_aa', 'avg_residue_mass_da', 'C_N_ratio', 'N_S_ratio']
    ns_fields = ['N_atoms_per_aa', 'S_atoms_per_aa', 'sulfur_aa_frac', 'disulfide_density']
    aa_fields = [f'AA_{aa}_pct' for aa in AMINO_ACIDS_20] + ['aa_entropy_bits']
    property_fields = ['pI', 'net_charge_pH7', 'gravy', 'instability_index', 'aliphatic_index', 'aromaticity', 'mw_da']
    structure_fields = ['ss_helix_frac', 'ss_turn_frac', 'ss_sheet_frac', 'flex_mean', 'surface_access_em_mean', 'disulfide_density']
    redox_fields = ['avg_oxidation_state_C', 'O_C_ratio', 'H_C_ratio']
    detect_fields = ['aromaticity', 'a280_1mgml_reduced', 'extinction_reduced']
    for row in rows:
        row.setdefault('entity_id', row.get('protein_id') or row.get('entity_id') or '')
        for field in [
            'canonical_fraction', 'unknown_atom_ratio', 'noncanonical_ratio', 'Se_atoms_per_aa',
            'possible_disulfides', 'disulfide_density', 'sulfur_aa_frac',
            'avg_residue_mass_da', 'a280_1mgml_reduced', 'a280_1mgml_cystines',
            'avg_oxidation_state_C',
        ]:
            _set_if_number(row, field, _proteome_feature_value(row, field))

    scale_sets = {
        'resource_outlier_score': (resource_fields, 'mean_abs'),
        'S_enrichment_score': (['S_atoms_per_aa', 'sulfur_aa_frac', 'disulfide_density'], 'signed'),
        'composition_anomaly_score': (aa_fields, 'mean_abs'),
        'property_outlier_score': (property_fields, 'mean_abs'),
        'structure_proxy_score': (structure_fields, 'mean_abs'),
        'redox_outlier_score': (redox_fields, 'mean_abs'),
        'detectability_proxy': (detect_fields, 'signed'),
    }
    scales = {score: _robust_scale_map(rows, fields) for score, (fields, _) in scale_sets.items()}
    low_n_scale = _robust_scale_map(rows, ['N_atoms_per_aa', 'C_N_ratio'])
    for row in rows:
        for score, (fields, mode) in scale_sets.items():
            components = []
            for field in fields:
                value = _proteome_feature_value(row, field)
                scale = scales.get(score, {}).get(field)
                if value is None or not scale:
                    continue
                median, mad = scale
                z = (float(value) - median) / (mad or 1.0)
                components.append(abs(z) if mode == 'mean_abs' else z)
            if components:
                _set_if_number(row, score, _mean(components))
        low_components = []
        n_value = _proteome_feature_value(row, 'N_atoms_per_aa')
        n_scale = low_n_scale.get('N_atoms_per_aa')
        if n_value is not None and n_scale:
            low_components.append(-((float(n_value) - n_scale[0]) / (n_scale[1] or 1.0)))
        cn_value = _proteome_feature_value(row, 'C_N_ratio')
        cn_scale = low_n_scale.get('C_N_ratio')
        if cn_value is not None and cn_scale:
            low_components.append((float(cn_value) - cn_scale[0]) / (cn_scale[1] or 1.0))
        if low_components:
            _set_if_number(row, 'low_N_score', _mean(low_components))
    return rows


def _mark_se_candidate_rows(rows: list[dict[str, Any]], *, positive: bool) -> list[dict[str, Any]]:
    for row in rows:
        row['selenium_positive'] = bool(positive)
        if not positive:
            row.setdefault('interpretation', 'no_positive_selenoproteins_detected; ranked by complete-core Se_atoms_per_aa values')
    return rows


def _proteome_rank_rows(rows: list[dict[str, Any]], field: str, reverse: bool = True, limit: int = 12) -> list[dict[str, Any]]:
    ranked = []
    for row in rows:
        value = _proteome_feature_value(row, field)
        if value is None:
            continue
        ranked.append({
            'entity_id': row.get('entity_id') or row.get('protein_id'),
            'protein_id': row.get('protein_id') or row.get('entity_id'),
            'gene_id': row.get('gene_id') or row.get('ensembl_gene_id') or '',
            'gene_symbol': row.get('gene_symbol') or '',
            'description': row.get('description') or '',
            'length_aa': row.get('length_aa'),
            'value': round(float(value), 6),
        })
    return sorted(ranked, key=lambda item: item['value'], reverse=reverse)[:limit]


def _proteome_scatter(rows: list[dict[str, Any]], x_field: str, y_field: str, limit: int = 5000) -> list[dict[str, Any]]:
    points = []
    for row in rows:
        x = _proteome_feature_value(row, x_field)
        y = _proteome_feature_value(row, y_field)
        if x is None or y is None:
            continue
        points.append({
            'entity_id': row.get('entity_id') or row.get('protein_id'),
            'protein_id': row.get('protein_id') or row.get('entity_id'),
            'gene_symbol': row.get('gene_symbol') or '',
            'length_aa': row.get('length_aa'),
            x_field: round(float(x), 6),
            y_field: round(float(y), 6),
        })
    if len(points) > limit:
        stride = max(1, len(points) // limit)
        points = points[::stride][:limit]
    return points


def _proteome_fingerprint_from_cards(species_id: str, display_name: str, feature_cards: dict[str, Any]) -> dict[str, Any]:
    fields = [
        'N_atoms_per_aa', 'S_atoms_per_aa', 'C_atoms_per_aa', 'C_N_ratio', 'N_S_ratio',
        'avg_oxidation_state_C', 'pI', 'net_charge_pH7', 'gravy', 'instability_index',
        'aliphatic_index', 'aromaticity', 'mw_da', 'aa_entropy_bits',
        'aa_hydrophobic_frac', 'aa_polar_frac', 'aa_pos_frac', 'aa_neg_frac', 'aa_aromatic_frac',
        'ss_helix_frac', 'ss_sheet_frac', 'flex_mean', 'surface_access_em_mean',
        'a280_1mgml_reduced', 'canonical_fraction', 'unknown_atom_ratio',
    ]
    fields.extend([f'AA_{aa}_pct' for aa in AMINO_ACIDS_20])
    row: dict[str, Any] = {'species_id': species_id, 'display_name': display_name}
    for field in fields:
        card = feature_cards.get(field) or {}
        if not isinstance(card, dict):
            continue
        value = _safe_num(card.get('mean') if card.get('mean') is not None else card.get('p50'))
        if value is not None:
            row[field] = round(float(value), 6)
    return row


def _proteome_species_fingerprint_rows(current_species_id: str, current_feature_cards: dict[str, Any], current_rows: list[dict[str, Any]], scope: str, limit: int = 80) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if db_mode():
        datasets = (
            OmicsDataset.objects
            .filter(omics_type='proteome')
            .select_related('species')
            .only('summary_payload', 'species__species_id', 'species__display_name')
            .order_by('species__display_name')[:limit]
        )
        for ds in datasets:
            scoped_summary = _scoped_payload_from_db(ds.summary_payload or {}, scope)
            cards = scoped_summary.get('feature_cards') if isinstance(scoped_summary, dict) else {}
            rows.append(_proteome_fingerprint_from_cards(ds.species.species_id, ds.species.display_name, cards if isinstance(cards, dict) else {}))
    else:
        for species_id, meta in list(file_species_map().items())[:limit]:
            try:
                scoped_summary = _load_scoped_file_json(species_id, 'proteome', 'summary', scope)
            except Exception:
                continue
            cards = scoped_summary.get('feature_cards') if isinstance(scoped_summary, dict) else {}
            rows.append(_proteome_fingerprint_from_cards(species_id, meta.get('display_name') or species_id, cards if isinstance(cards, dict) else {}))

    current_cards = dict(current_feature_cards or {})
    derived_fields = [
        'N_atoms_per_aa', 'S_atoms_per_aa', 'C_atoms_per_aa', 'C_N_ratio', 'N_S_ratio',
        'avg_oxidation_state_C', 'pI', 'net_charge_pH7', 'gravy', 'instability_index',
        'aliphatic_index', 'aromaticity', 'mw_da', 'aa_entropy_bits',
        'aa_hydrophobic_frac', 'aa_polar_frac', 'aa_pos_frac', 'aa_neg_frac', 'aa_aromatic_frac',
        'ss_helix_frac', 'ss_sheet_frac', 'flex_mean', 'surface_access_em_mean',
        'a280_1mgml_reduced', 'canonical_fraction', 'unknown_atom_ratio',
    ] + [f'AA_{aa}_pct' for aa in AMINO_ACIDS_20]
    for field in derived_fields:
        values = _proteome_values(current_rows, field)
        if values:
            current_cards[field] = {'mean': _mean(values), 'p50': _percentile(sorted(values), 0.5)}
    try:
        current_display = Species.objects.only('display_name').get(species_id=current_species_id).display_name if db_mode() else file_species_map().get(current_species_id, {}).get('display_name') or current_species_id
    except Exception:
        current_display = current_species_id
    current_row = _proteome_fingerprint_from_cards(current_species_id, current_display, current_cards)
    for idx, row in enumerate(rows):
        if row.get('species_id') == current_species_id:
            rows[idx] = current_row
            break
    else:
        rows.insert(0, current_row)
    return rows


def _proteome_module_suite(species_id: str, summary: dict[str, Any], scope: str, *, complete_core: bool = False) -> dict[str, Any]:
    requested_scope = scope
    analysis_scope = scope
    complete_core_meta: dict[str, Any] = {}
    if complete_core:
        rows, complete_core_meta = _complete_core_rows_for_module_suite(species_id, 'proteome')
        requested_scope = 'core'
        analysis_scope = 'complete_core_csv'
    else:
        rows = _proteome_module_rows(species_id, scope=scope)
    if not complete_core and _normalize_scope(scope) != 'full':
        row_keys = set()
        for row in rows[:250]:
            row_keys.update(str(key) for key in row.keys())
        needs_full = not {'ss_helix_frac', 'flex_mean', 'surface_access_em_mean', 'extinction_reduced', 'C_mass_frac'}.issubset(row_keys)
        if needs_full:
            full_rows = _proteome_module_rows(species_id, scope='full')
            full_keys = set()
            for row in full_rows[:250]:
                full_keys.update(str(key) for key in row.keys())
            if full_rows and ({'ss_helix_frac', 'flex_mean', 'surface_access_em_mean', 'extinction_reduced'} & full_keys):
                rows = full_rows
                analysis_scope = 'full_registered_csv'
    rows = _proteome_prepare_derived_rows(rows)
    feature_cards = summary.get('feature_cards') if isinstance(summary.get('feature_cards'), dict) else {}
    available = set()
    for row in rows[:5000]:
        for key, value in row.items():
            if _safe_num(value) is not None or key in {'protein_id', 'gene_id', 'gene_symbol', 'description', 'source_db'}:
                available.add(str(key))
    available.update(str(key) for key in feature_cards.keys())

    def card(field: str) -> dict[str, Any]:
        values = _proteome_values(rows, field)
        return {**_summary_card_from_values(values), 'n_valid': len(values), 'missing_rate': round(1.0 - _safe_div(len(values), len(rows)), 6) if rows else 1.0}

    aa_composition = [{'name': aa, 'value': round(_mean(_proteome_values(rows, f'AA_{aa}_pct')), 6)} for aa in AMINO_ACIDS_20 if _proteome_values(rows, f'AA_{aa}_pct')]
    aa_class_rows = [
        {'name': 'hydrophobic', 'value': card('aa_hydrophobic_frac').get('mean')},
        {'name': 'polar', 'value': card('aa_polar_frac').get('mean')},
        {'name': 'positive', 'value': card('aa_pos_frac').get('mean')},
        {'name': 'negative', 'value': card('aa_neg_frac').get('mean')},
        {'name': 'aromatic', 'value': card('aa_aromatic_frac').get('mean')},
    ]
    element_profile = [{'name': element, 'value': card(field).get('mean')} for element, field in [
        ('C', 'C_atoms_per_aa'), ('H', 'H_atoms_per_aa'), ('O', 'O_atoms_per_aa'), ('N', 'N_atoms_per_aa'), ('S', 'S_atoms_per_aa'), ('Se', 'Se_atoms_per_aa'),
    ] if _proteome_values(rows, field)]
    mass_fraction_profile = [{'name': element, 'value': card(field).get('mean')} for element, field in [
        ('C', 'C_mass_frac'), ('N', 'N_mass_frac'), ('O', 'O_mass_frac'), ('S', 'S_mass_frac'), ('Se', 'Se_mass_frac'),
    ] if _proteome_values(rows, field)]
    quality_counts = {
        'high': 0,
        'medium': 0,
        'low': 0,
    }
    for row in rows:
        canonical = _proteome_feature_value(row, 'canonical_fraction')
        unknown = _proteome_feature_value(row, 'unknown_atom_ratio') or 0.0
        stop = _proteome_feature_value(row, 'stop_asterisk_count') or 0.0
        if canonical is not None and canonical >= 0.98 and unknown <= 0.01 and stop <= 0:
            quality_counts['high'] += 1
        elif canonical is not None and canonical >= 0.95 and unknown <= 0.05:
            quality_counts['medium'] += 1
        else:
            quality_counts['low'] += 1

    resource_fields = ['N_atoms_per_aa', 'S_atoms_per_aa', 'C_atoms_per_aa', 'H_atoms_per_aa', 'O_atoms_per_aa', 'C_N_ratio', 'N_S_ratio', 'C_mass_frac', 'N_mass_frac', 'S_mass_frac']
    ns_fields = ['N_atoms_per_aa', 'S_atoms_per_aa', 'N_S_ratio', 'sulfur_aa_frac', 'disulfide_density', 'Se_atoms_per_aa']
    aa_fields = [f'AA_{aa}_pct' for aa in AMINO_ACIDS_20] + ['aa_entropy_bits', 'aa_hydrophobic_frac', 'aa_polar_frac', 'aa_pos_frac', 'aa_neg_frac']
    property_fields = ['pI', 'net_charge_pH7', 'gravy', 'instability_index', 'aliphatic_index', 'aromaticity', 'mw_da']
    structure_fields = ['ss_helix_frac', 'ss_turn_frac', 'ss_sheet_frac', 'flex_mean', 'flex_std', 'surface_access_em_mean', 'disulfide_density']
    redox_fields = ['avg_oxidation_state_C', 'O_C_ratio', 'H_C_ratio', 'O_N_ratio', 'a280_1mgml_reduced', 'extinction_reduced', 'aromaticity']
    p2_projection = _genome_projection_payload(rows, resource_fields, label_prefix='protein_resource')
    p4_projection = _genome_projection_payload(rows, aa_fields, label_prefix='aa_composition')
    p5_projection = _genome_projection_payload(rows, property_fields, label_prefix='physchem')
    p6_projection = _genome_projection_payload(rows, structure_fields, label_prefix='structure_proxy')
    p7_projection = _genome_projection_payload(rows, redox_fields, label_prefix='redox_detect')

    species_rows = _proteome_species_fingerprint_rows(species_id, feature_cards, rows, scope)
    p8_metrics = [field for field in [
        'N_atoms_per_aa', 'S_atoms_per_aa', 'C_atoms_per_aa', 'C_N_ratio', 'N_S_ratio',
        'avg_oxidation_state_C', 'pI', 'net_charge_pH7', 'gravy', 'instability_index',
        'aliphatic_index', 'aromaticity', 'mw_da', 'aa_entropy_bits',
        'aa_hydrophobic_frac', 'aa_polar_frac', 'aa_pos_frac', 'aa_neg_frac', 'aa_aromatic_frac',
        'ss_helix_frac', 'ss_sheet_frac', 'flex_mean', 'surface_access_em_mean', 'a280_1mgml_reduced',
    ] + [f'AA_{aa}_pct' for aa in AMINO_ACIDS_20] if any(_safe_num(row.get(field)) is not None for row in species_rows)]
    p8_species_pca = _species_pca_payload(species_rows, p8_metrics)
    p8_distance = _species_distance_heatmap(species_rows, p8_metrics)
    if len(p8_distance.get('x_labels') or []) < 2:
        p8_distance = _feature_distance_heatmap_from_rows(rows, p8_metrics, method='current_species_proteome_feature_correlation_distance')
    current_fingerprint = next((row for row in species_rows if row.get('species_id') == species_id), {})

    modules = [
        {
            'id': 'P1',
            'name': PROTEOME_MODULE_REQUIREMENTS['P1']['name'],
            'status': _module_status(PROTEOME_MODULE_REQUIREMENTS['P1']['required_fields'], available.union({'canonical_fraction', 'unknown_atom_ratio'})),
            'cards': {field: card(field) for field in ['length_aa', 'canonical_fraction', 'unknown_atom_ratio', 'noncanonical_ratio', 'stop_asterisk_count']},
            'quality_counts': [{'name': key, 'value': value} for key, value in quality_counts.items()],
            'length_histogram': _histogram_payload(_proteome_values(rows, 'length_aa'), bins=42),
            'noncanonical_table': sorted(
                [{'residue': field.replace('_count', ''), 'count': round(sum(_proteome_values(rows, field)), 6)} for field in ['X_count', 'B_count', 'Z_count', 'J_count', 'U_count', 'O_count', 'stop_asterisk_count'] if _proteome_values(rows, field)],
                key=lambda item: item['count'],
                reverse=True,
            ),
            'low_quality_candidates': sorted(
                _proteome_rank_rows(rows, 'unknown_atom_ratio', reverse=True, limit=8) + _proteome_rank_rows(rows, 'noncanonical_ratio', reverse=True, limit=8),
                key=lambda item: float(item.get('value') or 0),
                reverse=True,
            )[:12],
            'method': 'canonical_fraction=length_canonical_aa/length_aa; unknown_atom_ratio=unknown_residues_for_atoms/length_aa; quality levels use canonical coverage, unknown residues and stop symbols.',
        },
        {
            'id': 'P2',
            'name': PROTEOME_MODULE_REQUIREMENTS['P2']['name'],
            'status': _module_status(PROTEOME_MODULE_REQUIREMENTS['P2']['required_fields'], available),
            'cards': {field: card(field) for field in ['N_atoms_per_aa', 'S_atoms_per_aa', 'C_atoms_per_aa', 'C_N_ratio', 'N_S_ratio', 'avg_residue_mass_da']},
            'element_profile': element_profile,
            'mass_fraction_profile': mass_fraction_profile,
            'n_histogram': _histogram_payload(_proteome_values(rows, 'N_atoms_per_aa'), bins=42),
            's_histogram': _histogram_payload(_proteome_values(rows, 'S_atoms_per_aa'), bins=42),
            'resource_projection': p2_projection,
            'resource_cluster_counts': p2_projection.get('cluster_counts', []),
            'resource_outliers': _proteome_rank_rows(rows, 'resource_outlier_score', reverse=True, limit=16),
            'method': 'Residue atom counts are summed over amino-acid residues and terminal H2O; X_atoms_per_aa=X_atoms/length_aa; resource_outlier_score is mean absolute robust z-score across resource fields.',
            'implementation_notes': ['Sequence-derived resource proxy only; no expression abundance is used.'],
        },
        {
            'id': 'P3',
            'name': PROTEOME_MODULE_REQUIREMENTS['P3']['name'],
            'status': _module_status(PROTEOME_MODULE_REQUIREMENTS['P3']['required_fields'], available.union({'Se_atoms_per_aa'})),
            'cards': {field: card(field) for field in ['N_atoms_per_aa', 'S_atoms_per_aa', 'N_S_ratio', 'sulfur_aa_frac', 'Se_atoms_per_aa', 'disulfide_density']},
            'sulfur_composition': [{'name': 'Cys', 'value': card('cys_count').get('mean')}, {'name': 'Met', 'value': card('met_count').get('mean')}, {'name': 'U', 'value': card('U_count').get('mean')}],
            'ns_tradeoff_scatter': _proteome_scatter(rows, 'N_atoms_per_aa', 'S_atoms_per_aa'),
            'low_n_candidates': _proteome_rank_rows(rows, 'low_N_score', reverse=True, limit=16),
            's_rich_candidates': _proteome_rank_rows(rows, 'S_enrichment_score', reverse=True, limit=16),
            'se_positive_candidates': _mark_se_candidate_rows(_proteome_rank_rows([row for row in rows if (_proteome_feature_value(row, 'Se_atoms') or 0) > 0], 'Se_atoms', reverse=True, limit=16), positive=True) or _mark_se_candidate_rows(_proteome_rank_rows(rows, 'Se_atoms_per_aa', reverse=True, limit=16), positive=False),
            'disulfide_candidates': _proteome_rank_rows(rows, 'disulfide_density', reverse=True, limit=16),
            'method': 'sulfur_aa_frac=(Cys+Met+U)/length_aa; possible_disulfides=floor(cys_count/2); low_N_score and S_enrichment_score use robust z-score combinations.',
        },
        {
            'id': 'P4',
            'name': PROTEOME_MODULE_REQUIREMENTS['P4']['name'],
            'status': _module_status(PROTEOME_MODULE_REQUIREMENTS['P4']['required_fields'], available),
            'aa_composition': aa_composition,
            'aa_class_profile': aa_class_rows,
            'entropy_histogram': _histogram_payload(_proteome_values(rows, 'aa_entropy_bits'), bins=42),
            'aa_projection': p4_projection,
            'aa_cluster_counts': p4_projection.get('cluster_counts', []),
            'composition_anomalies': _proteome_rank_rows(rows, 'composition_anomaly_score', reverse=True, limit=16),
            'method': 'AA_X_pct=count(X)/length_aa*100; AA entropy is Shannon entropy over canonical amino-acid proportions; composition anomaly is mean absolute robust z-score over AA composition fields.',
        },
        {
            'id': 'P5',
            'name': PROTEOME_MODULE_REQUIREMENTS['P5']['name'],
            'status': _module_status(PROTEOME_MODULE_REQUIREMENTS['P5']['required_fields'], available),
            'cards': {field: card(field) for field in ['mw_da', 'pI', 'net_charge_pH7', 'gravy', 'instability_index', 'aliphatic_index', 'aromaticity']},
            'pi_histogram': _histogram_payload(_proteome_values(rows, 'pI'), bins=42),
            'gravy_histogram': _histogram_payload(_proteome_values(rows, 'gravy'), bins=42),
            'instability_histogram': _histogram_payload(_proteome_values(rows, 'instability_index'), bins=42),
            'instability_gravy_scatter': _proteome_scatter(rows, 'gravy', 'instability_index'),
            'property_projection': p5_projection,
            'property_cluster_counts': p5_projection.get('cluster_counts', []),
            'basic_candidates': _proteome_rank_rows(rows, 'pI', reverse=True, limit=8),
            'acidic_candidates': _proteome_rank_rows(rows, 'pI', reverse=False, limit=8),
            'hydrophobic_candidates': _proteome_rank_rows(rows, 'gravy', reverse=True, limit=12),
            'unstable_candidates': _proteome_rank_rows(rows, 'instability_index', reverse=True, limit=12),
            'method': 'pI, GRAVY, aromaticity, instability and aliphatic index are sequence-derived ProtParam-style descriptors; property_outlier_score uses robust z-scores.',
        },
        {
            'id': 'P6',
            'name': PROTEOME_MODULE_REQUIREMENTS['P6']['name'],
            'status': _module_status(PROTEOME_MODULE_REQUIREMENTS['P6']['required_fields'], available.union({'possible_disulfides', 'disulfide_density'})),
            'cards': {field: card(field) for field in ['ss_helix_frac', 'ss_turn_frac', 'ss_sheet_frac', 'flex_mean', 'surface_access_em_mean', 'disulfide_density']},
            'secondary_structure_profile': [{'name': 'helix', 'value': card('ss_helix_frac').get('mean')}, {'name': 'turn', 'value': card('ss_turn_frac').get('mean')}, {'name': 'sheet', 'value': card('ss_sheet_frac').get('mean')}],
            'structure_projection': p6_projection,
            'structure_cluster_counts': p6_projection.get('cluster_counts', []),
            'flex_access_scatter': _proteome_scatter(rows, 'flex_mean', 'surface_access_em_mean'),
            'disulfide_rich_candidates': _proteome_rank_rows(rows, 'disulfide_density', reverse=True, limit=16),
            'flexible_candidates': _proteome_rank_rows(rows, 'flex_mean', reverse=True, limit=16),
            'method': 'Secondary-structure fractions and flexibility/accessibility are sequence-derived profile summaries; disulfide density is a Cys-count proxy, not structural validation.',
            'implementation_notes': ['P6 is not an AlphaFold/3D structure module.'],
        },
        {
            'id': 'P7',
            'name': PROTEOME_MODULE_REQUIREMENTS['P7']['name'],
            'status': _module_status(PROTEOME_MODULE_REQUIREMENTS['P7']['required_fields'], available),
            'cards': {field: card(field) for field in ['avg_oxidation_state_C', 'a280_1mgml_reduced', 'a280_1mgml_cystines', 'extinction_reduced', 'extinction_cystines', 'aromaticity']},
            'zc_histogram': _histogram_payload(_proteome_values(rows, 'avg_oxidation_state_C'), bins=42),
            'redox_gravy_scatter': _proteome_scatter(rows, 'avg_oxidation_state_C', 'gravy'),
            'redox_projection': p7_projection,
            'redox_cluster_counts': p7_projection.get('cluster_counts', []),
            'detectability_ranking': _proteome_rank_rows(rows, 'detectability_proxy', reverse=True, limit=16),
            'redox_outliers': _proteome_rank_rows(rows, 'redox_outlier_score', reverse=True, limit=16),
            'method': 'avg_oxidation_state_C=(-H+3N+2O+2S+2Se)/C; A280 proxy uses extinction divided by molecular weight where needed; redox/detectability rankings use robust z-score proxies.',
        },
        {
            'id': 'P8',
            'name': PROTEOME_MODULE_REQUIREMENTS['P8']['name'],
            'status': _module_status(PROTEOME_MODULE_REQUIREMENTS['P8']['required_fields'], available.union({'species-level N_atoms_per_aa'})),
            'fingerprint': {key: value for key, value in current_fingerprint.items() if key not in {'species_id', 'display_name'}},
            'species_fingerprint_rows': species_rows,
            'feature_ranking': _fingerprint_feature_rank(species_rows),
            'species_pca': p8_species_pca,
            'distance_matrix': p8_distance,
            'coupling_heatmap': _genome_correlation_heatmap(rows, ['N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy', 'instability_index', 'aa_entropy_bits', 'avg_oxidation_state_C']),
            'candidate_summary': sorted(
                _proteome_rank_rows(rows, 'resource_outlier_score', reverse=True, limit=8)
                + _proteome_rank_rows(rows, 'composition_anomaly_score', reverse=True, limit=8)
                + _proteome_rank_rows(rows, 'property_outlier_score', reverse=True, limit=8)
                + _proteome_rank_rows(rows, 'redox_outlier_score', reverse=True, limit=8),
                key=lambda item: float(item.get('value') or 0),
                reverse=True,
            )[:20],
            'method': 'Species proteome fingerprint aggregates row-level P1-P7 sequence-derived features; distances use shared robust proteome fingerprint fields. Cross-omics coupling remains exploratory without abundance/FDR artifacts.',
        },
    ]

    placement = {
        'P1': {'group': 'basic', 'priority': 10, 'default_visible': True, 'anchor_id': 'p1-quality', 'requires_full_csv': False},
        'P2': {'group': 'basic_deep', 'priority': 20, 'default_visible': True, 'anchor_id': 'p2-resource', 'requires_full_csv': False},
        'P3': {'group': 'basic_deep', 'priority': 30, 'default_visible': True, 'anchor_id': 'p3-ns-se', 'requires_full_csv': True},
        'P4': {'group': 'basic_deep', 'priority': 40, 'default_visible': True, 'anchor_id': 'p4-aa', 'requires_full_csv': False},
        'P5': {'group': 'basic_deep', 'priority': 50, 'default_visible': True, 'anchor_id': 'p5-physchem', 'requires_full_csv': False},
        'P6': {'group': 'basic_deep', 'priority': 60, 'default_visible': True, 'anchor_id': 'p6-structure', 'requires_full_csv': True},
        'P7': {'group': 'basic_deep', 'priority': 70, 'default_visible': True, 'anchor_id': 'p7-redox', 'requires_full_csv': True},
        'P8': {'group': 'compare', 'priority': 80, 'default_visible': True, 'anchor_id': 'p8-fingerprint', 'requires_full_csv': True},
    }
    for module in modules:
        module['placement'] = placement.get(module['id'], {})
        module['missing_fields'] = [field for field in PROTEOME_MODULE_REQUIREMENTS[module['id']]['missing_fields'] if field not in available]

    return {
        'scope': analysis_scope,
        'requested_scope': requested_scope,
        'row_count': len(rows),
        'modules': modules,
        'artifact_recommendations': [
            'proteome_basic_summary.json',
            'proteome_resource_budget.json',
            'proteome_aa_composition.json',
            'proteome_physchem_profile.json',
            'proteome_structure_proxy.json',
            'proteome_redox_detectability.json',
            'proteome_species_fingerprint.json',
            'proteome_cross_omics_coupling.json',
        ],
        'quality_rules': [
            {'risk': 'low canonical coverage', 'message': 'canonical_fraction < 0.95 lowers confidence for ProtParam and elemental features.', 'implemented': 'canonical_fraction' in available},
            {'risk': 'unknown residues', 'message': 'unknown_atom_ratio > 0.05 lowers element-count reliability.', 'implemented': 'unknown_atom_ratio' in available},
            {'risk': 'short proteins', 'message': 'Very short proteins have unstable pI/GRAVY/instability interpretation.', 'implemented': 'length_aa' in available},
            {'risk': 'sequence-derived only', 'message': 'No expression abundance is used; all budgets are theoretical sequence-intrinsic costs.', 'implemented': True},
        ],
        'unified_proteome_layout_metadata': [
            {'module': 'P1', 'target_tab': 'basic', 'display_order': 10, 'evidence_level': 'quality_context', 'export_keys': ['p1_low_quality']},
            {'module': 'P2', 'target_tab': 'basic_deep', 'display_order': 20, 'evidence_level': 'sequence_derived_resource_proxy', 'export_keys': ['p2_resource_outliers']},
            {'module': 'P3', 'target_tab': 'basic_deep', 'display_order': 30, 'evidence_level': 'sequence_derived_nsse_proxy', 'export_keys': ['p3_low_n', 'p3_s_rich', 'p3_se_positive']},
            {'module': 'P4', 'target_tab': 'basic_deep', 'display_order': 40, 'evidence_level': 'sequence_derived_composition', 'export_keys': ['p4_composition_anomalies']},
            {'module': 'P5', 'target_tab': 'basic_deep', 'display_order': 50, 'evidence_level': 'sequence_derived_protparam_proxy', 'export_keys': ['p5_hydrophobic', 'p5_unstable']},
            {'module': 'P6', 'target_tab': 'basic_deep', 'display_order': 60, 'evidence_level': 'sequence_derived_structure_proxy', 'export_keys': ['p6_disulfide']},
            {'module': 'P7', 'target_tab': 'basic_deep', 'display_order': 70, 'evidence_level': 'sequence_derived_redox_detectability_proxy', 'export_keys': ['p7_detectability', 'p7_redox']},
            {'module': 'P8', 'target_tab': 'deep', 'display_order': 80, 'evidence_level': 'species_fingerprint_and_internal_coupling', 'export_keys': ['p8_feature_ranking', 'p8_candidate_summary']},
            {'module': 'General feature explorer', 'target_tab': 'basic', 'display_order': 90, 'evidence_level': 'field_level_evidence_traceback', 'export_keys': []},
        ],
        'method_metadata': {
            'method': 'proteome P1-P8 module suite built from PostgreSQL core rows plus registered full CSV fields when structure/redox fields are needed',
            'normalization': 'raw feature units for summaries; robust z-score for projections, outlier scores and candidate rankings',
            'missing_policy': 'available numeric fields are used; absent experimental abundance/structure fields are explicitly reported per module',
            'evidence_level': 'sequence-derived descriptive / hypothesis-generating',
            **({'complete_core_compute': complete_core_meta} if complete_core_meta else {}),
        },
    }


def _genome_hotspot_windows(rows: list[dict[str, Any]], bins: int = 36) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        start = _safe_num(row.get('start_1'))
        score = _genome_feature_value(row, 'stoich_island_score')
        if start is None or score is None:
            continue
        scored.append((float(start), float(score), row))
    if not scored:
        return []
    min_x = min(item[0] for item in scored)
    max_x = max(item[0] for item in scored)
    if min_x == max_x:
        bins = 1
        width = 1.0
    else:
        bins = max(8, min(80, bins))
        width = (max_x - min_x) / bins
    buckets = [{'scores': [], 'rows': [], 'start': min_x + width * idx, 'end': min_x + width * (idx + 1)} for idx in range(bins)]
    for start, score, row in scored:
        idx = int((start - min_x) / width) if width else 0
        idx = max(0, min(bins - 1, idx))
        buckets[idx]['scores'].append(score)
        buckets[idx]['rows'].append(row)
    windows = []
    for idx, bucket in enumerate(buckets):
        if not bucket['scores']:
            continue
        windows.append({
            'window_id': idx + 1,
            'window_start': round(bucket['start'], 2),
            'window_end': round(bucket['end'], 2),
            'n_genes': len(bucket['scores']),
            'mean_score': round(_mean(bucket['scores']), 6),
            'median_score': round(_percentile(sorted(bucket['scores']), 0.5), 6),
            'dominant_feature': 'stoich_island_score with available GC/N features',
        })
    return sorted(windows, key=lambda item: abs(item['mean_score']), reverse=True)[:12]


def _cumulative_profile(points: list[tuple[float, float]], limit: int = 240) -> dict[str, Any]:
    clean = sorted((float(x), float(y)) for x, y in points if x is not None and y is not None)
    if not clean:
        return {'centers': [], 'counts': [], 'n': 0}
    cumulative = []
    running = 0.0
    for x, y in clean:
        running += y
        cumulative.append((x, running))
    if len(cumulative) > limit:
        stride = max(1, len(cumulative) // limit)
        cumulative = cumulative[::stride][:limit]
    return {
        'centers': [round(x, 2) for x, _ in cumulative],
        'counts': [round(y, 6) for _, y in cumulative],
        'n': len(clean),
    }


def _fingerprint_from_feature_cards(species_id: str, display_name: str, feature_cards: dict[str, Any]) -> dict[str, Any]:
    fields = [
        'locus_gc_percent',
        'exon_gc_percent',
        'promoter_gc_percent',
        'promoter_exon_gc_delta',
        'locus_atoms_N_per_base',
        'exon_atoms_N_per_base',
        'promoter_atoms_N_per_base',
        'gc1_percent',
        'gc2_percent',
        'gc3_percent',
        'locus_gc_skew',
        'locus_at_skew',
        'codon_entropy_bits',
        'stoich_island_score',
        'gene_length_bp',
        'transcript_count',
    ]
    fields.extend([f'locus_dinuc_{dinuc}_freq' for dinuc in DINUCS])
    fields.extend([f'promoter_dinuc_{dinuc}_freq' for dinuc in DINUCS])
    fields.extend([f'codon_{codon}_freq' for codon in CODONS])
    row: dict[str, Any] = {'species_id': species_id, 'display_name': display_name}
    for field in fields:
        card = feature_cards.get(field) or {}
        if not isinstance(card, dict):
            continue
        value = _safe_num(card.get('mean') if card.get('mean') is not None else card.get('p50'))
        if value is not None:
            row[field] = round(float(value), 6)
    return row


def _genome_species_fingerprint_rows(current_species_id: str, current_feature_cards: dict[str, Any], current_rows: list[dict[str, Any]], scope: str, limit: int = 80) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if db_mode():
        datasets = (
            OmicsDataset.objects
            .filter(omics_type='genome')
            .select_related('species')
            .only('summary_payload', 'species__species_id', 'species__display_name')
            .order_by('species__display_name')[:limit]
        )
        for ds in datasets:
            scoped_summary = _scoped_payload_from_db(ds.summary_payload or {}, scope)
            cards = scoped_summary.get('feature_cards') if isinstance(scoped_summary, dict) else {}
            if not isinstance(cards, dict):
                cards = {}
            rows.append(_fingerprint_from_feature_cards(ds.species.species_id, ds.species.display_name, cards))
    else:
        for species_id, meta in list(file_species_map().items())[:limit]:
            try:
                scoped_summary = _load_scoped_file_json(species_id, 'genome', 'summary', scope)
            except Exception:
                continue
            cards = scoped_summary.get('feature_cards') if isinstance(scoped_summary, dict) else {}
            rows.append(_fingerprint_from_feature_cards(species_id, meta.get('display_name') or species_id, cards if isinstance(cards, dict) else {}))

    current_cards = dict(current_feature_cards or {})
    derived_current = {
        'locus_gc_percent': _genome_values(current_rows, 'locus_gc_percent'),
        'exon_gc_percent': _genome_values(current_rows, 'exon_gc_percent'),
        'promoter_gc_percent': _genome_values(current_rows, 'promoter_gc_percent'),
        'promoter_exon_gc_delta': _genome_values(current_rows, 'promoter_exon_gc_delta'),
        'locus_atoms_N_per_base': _genome_values(current_rows, 'locus_atoms_N_per_base'),
        'exon_atoms_N_per_base': _genome_values(current_rows, 'exon_atoms_N_per_base'),
        'promoter_atoms_N_per_base': _genome_values(current_rows, 'promoter_atoms_N_per_base'),
        'gc1_percent': _genome_values(current_rows, 'gc1_percent'),
        'gc2_percent': _genome_values(current_rows, 'gc2_percent'),
        'gc3_percent': _genome_values(current_rows, 'gc3_percent'),
        'locus_gc_skew': _genome_values(current_rows, 'locus_gc_skew'),
        'locus_at_skew': _genome_values(current_rows, 'locus_at_skew'),
        'codon_entropy_bits': _genome_values(current_rows, 'codon_entropy_bits'),
        'stoich_island_score': _genome_values(current_rows, 'stoich_island_score'),
        'gene_length_bp': _genome_values(current_rows, 'gene_length_bp'),
        'transcript_count': _genome_values(current_rows, 'transcript_count'),
    }
    for dinuc in DINUCS:
        derived_current[f'locus_dinuc_{dinuc}_freq'] = _genome_values(current_rows, f'locus_dinuc_{dinuc}_freq')
        derived_current[f'promoter_dinuc_{dinuc}_freq'] = _genome_values(current_rows, f'promoter_dinuc_{dinuc}_freq')
    for codon in CODONS:
        derived_current[f'codon_{codon}_freq'] = _genome_values(current_rows, f'codon_{codon}_freq')
    for field, values in derived_current.items():
        if values:
            current_cards[field] = {'mean': _mean(values), 'p50': _percentile(sorted(values), 0.5)}
    current_display = current_species_id
    try:
        current_display = Species.objects.only('display_name').get(species_id=current_species_id).display_name if db_mode() else file_species_map().get(current_species_id, {}).get('display_name') or current_species_id
    except Exception:
        current_display = current_species_id
    current_row = _fingerprint_from_feature_cards(current_species_id, current_display, current_cards)
    replaced = False
    for idx, row in enumerate(rows):
        if row.get('species_id') == current_species_id:
            rows[idx] = current_row
            replaced = True
            break
    if not replaced:
        rows.insert(0, current_row)
    return rows


def _fingerprint_feature_rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    fields = [field for field in rows[0].keys() if field not in {'species_id', 'display_name'}]
    ranked = []
    for field in fields:
        values = [_safe_num(row.get(field)) for row in rows]
        clean = [float(value) for value in values if value is not None]
        if len(clean) < 3:
            continue
        mean = _mean(clean)
        ranked.append({
            'feature': field,
            'mean': round(mean, 6),
            'std': round(_std(clean), 6),
            'cv': round(abs(_std(clean) / mean), 6) if mean else None,
            'range': round(max(clean) - min(clean), 6),
            'n_species': len(clean),
        })
    return sorted(ranked, key=lambda item: abs(float(item.get('range') or 0)), reverse=True)[:16]


def _genome_valid_fields(rows: list[dict[str, Any]], fields: list[str], min_valid: int = 8) -> list[str]:
    valid = []
    for field in fields:
        count = 0
        for row in rows:
            if _genome_feature_value(row, field) is not None:
                count += 1
                if count >= min_valid:
                    valid.append(field)
                    break
    return valid


def _sample_rows_evenly(rows: list[dict[str, Any]], limit: int = 5000) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    stride = max(1, len(rows) // limit)
    return rows[::stride][:limit]


def _zscore_matrix(rows: list[dict[str, Any]], fields: list[str]) -> tuple[list[dict[str, Any]], list[str], list[list[float]]]:
    fields = _genome_valid_fields(rows, fields)
    if not rows or not fields:
        return [], [], []
    medians = {}
    scales = {}
    for field in fields:
        values = _genome_values(rows, field)
        if not values:
            continue
        median, mad = _robust_z_values(values)
        medians[field] = median
        scales[field] = mad or 1.0
    fields = [field for field in fields if field in medians]
    matrix = []
    output_rows = []
    for row in rows:
        available_count = sum(1 for field in fields if _genome_feature_value(row, field) is not None)
        if available_count < max(2, min(4, len(fields))):
            continue
        vector = []
        for field in fields:
            value = _genome_feature_value(row, field)
            if value is None:
                value = medians[field]
            vector.append((float(value) - medians[field]) / (scales[field] or 1.0))
        output_rows.append(row)
        matrix.append(vector)
    return output_rows, fields, matrix


def _deterministic_kmeans(vectors: list[list[float]], k: int = 4) -> list[int]:
    if not vectors:
        return []
    n = len(vectors)
    k = max(1, min(k, n))
    if k == 1:
        return [0] * n
    seed_indices = [int(round(i * (n - 1) / max(1, k - 1))) for i in range(k)]
    centroids = [vectors[idx][:] for idx in seed_indices]
    labels = [0] * n
    for _ in range(14):
        changed = False
        for idx, vector in enumerate(vectors):
            distances = [sum((a - b) ** 2 for a, b in zip(vector, center)) for center in centroids]
            label = min(range(k), key=lambda item: distances[item])
            if labels[idx] != label:
                labels[idx] = label
                changed = True
        next_centroids = []
        for label in range(k):
            members = [vectors[idx] for idx, assigned in enumerate(labels) if assigned == label]
            if not members:
                next_centroids.append(centroids[label])
                continue
            next_centroids.append([sum(member[col] for member in members) / len(members) for col in range(len(vectors[0]))])
        centroids = next_centroids
        if not changed:
            break
    return labels


def _cluster_counts(labels: list[str]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return [{'name': key, 'value': value} for key, value in sorted(counts.items(), key=lambda item: item[0])]


def _genome_projection_payload(rows: list[dict[str, Any]], fields: list[str], limit: int = 5000, k: int = 4, label_prefix: str = 'cluster') -> dict[str, Any]:
    """Fit PCA/k-means on all valid rows, then downsample only display points."""
    matrix_rows, fields_used, matrix = _zscore_matrix(rows, fields)
    if not matrix_rows or not fields_used:
        return {
            'method': 'pca_svd_zscore_full_fit',
            'fields': [],
            'points': [],
            'umap_points': [],
            'umap_params': {},
            'umap_available': False,
            'cluster_counts': [],
            'explained_variance_ratio': [0.0, 0.0],
            'ordination_meta': {
                'fit_n': 0,
                'display_n': 0,
                'sampling_policy': 'none',
                'method_version': 'species_explorer_complete_core_v2_1',
            },
        }
    explained = [0.0, 0.0]
    coords: list[list[float]] = []
    labels_idx: list[int]
    if np is not None:
        try:
            arr = np.asarray(matrix, dtype=float)
            centroids = arr[[int(round(i * (len(arr) - 1) / max(1, min(k, len(arr)) - 1))) for i in range(max(1, min(k, len(arr))))], :].copy()
            labels_arr = np.zeros(len(arr), dtype=int)
            for _ in range(14):
                distances = ((arr[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
                next_labels = distances.argmin(axis=1)
                if np.array_equal(next_labels, labels_arr):
                    break
                labels_arr = next_labels
                for cluster_idx in range(len(centroids)):
                    members = arr[labels_arr == cluster_idx]
                    if len(members):
                        centroids[cluster_idx] = members.mean(axis=0)
            labels_idx = [int(x) for x in labels_arr.tolist()]
            denom = max(1, arr.shape[0] - 1)
            cov = (arr.T @ arr) / denom
            eigvals, eigvecs = np.linalg.eigh(cov)
            order = np.argsort(eigvals)[::-1]
            eigvals = eigvals[order]
            eigvecs = eigvecs[:, order]
            raw_coords = arr @ eigvecs[:, :2]
            coords = raw_coords.tolist()
            total = float(np.sum(np.maximum(eigvals, 0.0))) if len(eigvals) else 0.0
            explained = [round(float(eigvals[i] / total), 6) if total > 0 and i < len(eigvals) else 0.0 for i in range(2)]
        except Exception:
            labels_idx = _deterministic_kmeans(matrix, k=k)
            coords = [[vector[0], vector[1] if len(vector) > 1 else 0.0] for vector in matrix]
    else:
        labels_idx = _deterministic_kmeans(matrix, k=k)
        coords = [[vector[0], vector[1] if len(vector) > 1 else 0.0] for vector in matrix]
    cluster_labels = [f'{label_prefix}_{idx + 1}' for idx in labels_idx]
    all_points = []
    for idx, row in enumerate(matrix_rows):
        pc1 = coords[idx][0] if idx < len(coords) and coords[idx] else 0.0
        pc2 = coords[idx][1] if idx < len(coords) and len(coords[idx]) > 1 else 0.0
        all_points.append({
            'entity_id': row.get('entity_id') or row.get('gene_id'),
            'gene_id': row.get('gene_id') or row.get('entity_id'),
            'gene_name': row.get('gene_name') or '',
            'seqid': row.get('seqid') or '',
            'start_1': row.get('start_1'),
            'end_1': row.get('end_1'),
            'strand': row.get('strand') or '',
            'biotype': row.get('biotype') or '',
            'cluster': cluster_labels[idx] if idx < len(cluster_labels) else f'{label_prefix}_1',
            'pc1': round(float(pc1), 6),
            'pc2': round(float(pc2), 6),
        })
    points = _sample_rows_evenly(all_points, limit=limit)
    if _interactive_umap_enabled():
        umap_projection = _umap_payload(
            matrix,
            all_points,
            x_key='umap1',
            y_key='umap2',
            row_keys=('entity_id', 'gene_id', 'gene_name', 'seqid', 'start_1', 'end_1', 'strand', 'biotype', 'cluster'),
        )
        umap_points = _sample_rows_evenly(umap_projection.get('points', []), limit=limit)
    else:
        umap_projection = {
            'points': [],
            'params': {},
            'available': False,
            'fallback_reason': 'interactive_umap_disabled_by_default',
        }
        umap_points = []
    return {
        'method': 'pca_covariance_eigh_zscore_full_fit',
        'fields': fields_used,
        'points': points,
        'umap_points': umap_points,
        'umap_params': umap_projection.get('params', {}),
        'umap_available': bool(umap_projection.get('available')),
        'umap_fallback_reason': umap_projection.get('fallback_reason') or '',
        'cluster_counts': _cluster_counts(cluster_labels),
        'explained_variance_ratio': explained,
        'ordination_meta': {
            'fit_n': len(all_points),
            'display_n': len(points),
            'sampling_policy': 'deterministic_even_stride_display_sample' if len(all_points) > len(points) else 'none',
            'method_version': 'species_explorer_complete_core_v2_1',
        },
    }


def _genome_correlation_heatmap(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, Any]:
    fields = _genome_valid_fields(rows, fields)
    values = []
    details = []
    if not fields:
        return {'x_labels': [], 'y_labels': [], 'values': [], 'details': []}
    for y_idx, field_y in enumerate(fields):
        for x_idx, field_x in enumerate(fields):
            pairs = []
            for row in rows:
                x = _genome_feature_value(row, field_x)
                y = _genome_feature_value(row, field_y)
                if x is None or y is None:
                    continue
                pairs.append((float(x), float(y)))
            corr = 0.0
            if len(pairs) >= 3:
                xs = [item[0] for item in pairs]
                ys = [item[1] for item in pairs]
                mean_x = _mean(xs)
                mean_y = _mean(ys)
                denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
                denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
                if denom_x > 0 and denom_y > 0:
                    corr = sum((x - mean_x) * (y - mean_y) for x, y in pairs) / (denom_x * denom_y)
            values.append([x_idx, y_idx, round(float(corr), 6)])
            details.append({'x': field_x, 'y': field_y, 'n': len(pairs), 'method': 'pearson_on_available_gene_rows'})
    return {'x_labels': fields, 'y_labels': fields, 'values': values, 'details': details}


def _feature_distance_heatmap_from_rows(rows: list[dict[str, Any]], fields: list[str], *, method: str = 'current_species_feature_correlation_distance') -> dict[str, Any]:
    heatmap = _genome_correlation_heatmap(rows, fields)
    labels = heatmap.get('x_labels') or []
    values = []
    for cell in heatmap.get('values') or []:
        if not isinstance(cell, list) or len(cell) < 3:
            continue
        corr = _safe_num(cell[2])
        if corr is None:
            continue
        values.append([cell[0], cell[1], round(float(max(0.0, min(2.0, 1.0 - float(corr)))), 6)])
    return {
        'x_labels': labels,
        'y_labels': heatmap.get('y_labels') or labels,
        'values': values,
        'details': heatmap.get('details') or [],
        'method': method,
        'scale_type': 'distance',
        'distance_basis': '1 - Pearson r across current-species entity rows',
        'n_features': len(labels),
        'n_rows': len(rows),
    }


def _genome_multifeature_outliers(rows: list[dict[str, Any]], fields: list[str], limit: int = 16) -> list[dict[str, Any]]:
    matrix_rows, fields_used, matrix = _zscore_matrix(rows, fields)
    ranked = []
    for row, vector in zip(matrix_rows, matrix):
        score = _mean([abs(value) for value in vector]) if vector else None
        if score is None:
            continue
        ranked.append({
            'entity_id': row.get('entity_id') or row.get('gene_id'),
            'gene_id': row.get('gene_id') or row.get('entity_id'),
            'gene_name': row.get('gene_name') or '',
            'seqid': row.get('seqid') or '',
            'start_1': row.get('start_1'),
            'end_1': row.get('end_1'),
            'strand': row.get('strand') or '',
            'value': round(float(score), 6),
            'n_features': len(fields_used),
            'method': 'mean_abs_robust_z',
        })
    return sorted(ranked, key=lambda item: item['value'], reverse=True)[:limit]


def _species_distance_heatmap(rows: list[dict[str, Any]], metrics: list[str], limit: int = 28, method: str = 'correlation') -> dict[str, Any]:
    valid_rows = []
    for row in rows:
        used = [metric for metric in metrics if _safe_num(row.get(metric)) is not None]
        if len(used) >= max(2, min(4, len(metrics))):
            valid_rows.append(row)
    valid_rows = valid_rows[:limit]
    labels = [str(row.get('display_name') or row.get('species_id') or f'species_{idx + 1}') for idx, row in enumerate(valid_rows)]
    values = []
    for y_idx, row_y in enumerate(valid_rows):
        for x_idx, row_x in enumerate(valid_rows):
            shared = []
            for metric in metrics:
                x = _safe_num(row_x.get(metric))
                y = _safe_num(row_y.get(metric))
                if x is not None and y is not None:
                    shared.append((float(x), float(y)))
            if shared:
                distance = _vector_distance([x for x, _ in shared], [y for _, y in shared], method)
            else:
                distance = 0.0
            values.append([x_idx, y_idx, round(float(distance), 6)])
    return {'x_labels': labels, 'y_labels': labels, 'values': values, 'method': method, 'n_species': len(valid_rows)}


def _species_pca_payload(rows: list[dict[str, Any]], metrics: list[str]) -> dict[str, Any]:
    ordination = _ordination_payload(rows, metrics)
    points = []
    for item in ordination.get('points', []):
        points.append({
            'species_id': item.get('species_id'),
            'display_name': item.get('display_name'),
            'pc1': item.get('x'),
            'pc2': item.get('y'),
        })
    umap_points = []
    for item in (ordination.get('umap') or {}).get('points', []):
        umap_points.append({
            'species_id': item.get('species_id'),
            'display_name': item.get('display_name'),
            'umap1': item.get('x'),
            'umap2': item.get('y'),
        })
    return {
        'method': ordination.get('method') or 'pca_svd',
        'metrics': metrics,
        'points': points,
        'umap_points': umap_points,
        'umap_params': (ordination.get('umap') or {}).get('params', {}),
        'umap_available': bool((ordination.get('umap') or {}).get('available')),
        'umap_fallback_reason': (ordination.get('umap') or {}).get('fallback_reason') or '',
        'explained_variance_ratio': ordination.get('explained_variance_ratio') or [0.0, 0.0],
    }


def _genome_module_suite(species_id: str, summary: dict[str, Any], scope: str, *, complete_core: bool = False) -> dict[str, Any]:
    requested_scope = scope
    analysis_scope = scope
    complete_core_meta: dict[str, Any] = {}
    if complete_core:
        rows, complete_core_meta = _complete_core_rows_for_module_suite(species_id, 'genome')
        requested_scope = 'core'
        analysis_scope = 'complete_core_csv'
    else:
        rows = _genome_module_rows(species_id, scope=scope)
    if not complete_core and _normalize_scope(scope) != 'full':
        advanced_keys = {
            'locus_dinuc_AA_freq', 'promoter_dinuc_CG_freq', 'codon_AAA_freq',
            'gc1_percent', 'locus_gc_skew',
        }
        row_keys = set()
        for row in rows[:250]:
            row_keys.update(str(key) for key in row.keys())
        has_full_dimensional_fields = (
            any(key.startswith('promoter_dinuc_') for key in row_keys)
            and any(key.startswith('locus_dinuc_') for key in row_keys)
            and any(key.startswith('codon_') and key.endswith('_freq') for key in row_keys)
        )
        if not has_full_dimensional_fields:
            full_rows = _genome_module_rows(species_id, scope='full')
            full_keys = set()
            for row in full_rows[:250]:
                full_keys.update(str(key) for key in row.keys())
            if full_rows and advanced_keys.intersection(full_keys):
                rows = full_rows
                analysis_scope = 'full_registered_csv'
    rows = _genome_prepare_derived_rows(rows)
    feature_cards = summary.get('feature_cards') if isinstance(summary.get('feature_cards'), dict) else {}
    available = set()
    for row in rows[:5000]:
        for key, value in row.items():
            if _safe_num(value) is not None or key in {'seqid', 'strand', 'biotype', 'strategy_cluster'}:
                available.add(str(key))
    available.update(str(key) for key in feature_cards.keys())
    if {'exon_gc_percent', 'gc3_percent'}.issubset(available):
        available.add('gc12_percent_estimated')
    if {'start_1', 'end_1'}.issubset(available):
        available.add('gene_length_bp')

    fields = ['exon_gc_percent', 'promoter_gc_percent', 'promoter_exon_gc_delta', 'exon_atoms_N_per_base', 'stoich_island_score', 'gene_length_bp']
    field_stats = {}
    for field in fields:
        values = _genome_values(rows, field)
        if values:
            field_stats[field] = {
                **_summary_card_from_values(values),
                'n_valid': len(values),
                'missing_rate': _genome_missing_rate(rows, field),
            }
        elif field in feature_cards:
            field_stats[field] = {**feature_cards[field], 'n_valid': int(feature_cards[field].get('n_valid') or 0), 'missing_rate': 1.0}

    g1_fields = [
        'locus_gc_percent', 'exon_gc_percent', 'promoter_gc_percent',
        'locus_atoms_C_per_base', 'locus_atoms_N_per_base', 'locus_atoms_P_per_base',
        'exon_atoms_C_per_base', 'exon_atoms_N_per_base', 'exon_atoms_P_per_base',
        'promoter_atoms_C_per_base', 'promoter_atoms_N_per_base', 'promoter_atoms_P_per_base',
        'locus_shannon_entropy_acgt', 'exon_shannon_entropy_acgt', 'promoter_shannon_entropy_acgt',
        'locus_ratio_C_N', 'locus_ratio_N_P', 'exon_ratio_C_N', 'exon_ratio_N_P', 'promoter_ratio_C_N', 'promoter_ratio_N_P',
    ]
    g1_feature_cards = [
        {'field': field, 'label': field.replace('_', ' '), **_summary_card_from_values(values), 'n_valid': len(values), 'missing_rate': _genome_missing_rate(rows, field)}
        for field in g1_fields
        for values in [_genome_values(rows, field)]
        if values
    ]

    delta_values = _genome_values(rows, 'promoter_exon_gc_delta')
    n_delta_values = _genome_values(rows, 'promoter_exon_N_delta')
    p_delta_values = _genome_values(rows, 'promoter_exon_P_delta')
    entropy_delta_values = _genome_values(rows, 'promoter_exon_entropy_delta')
    cg_enrichment_values = _genome_values(rows, 'promoter_CG_enrichment')
    island_values = _genome_values(rows, 'stoich_island_score')
    gene_lengths = _genome_values(rows, 'gene_length_bp')
    skew_gc_values = _genome_values(rows, 'locus_gc_skew')
    skew_at_values = _genome_values(rows, 'locus_at_skew')
    codon_entropy_values = _genome_values(rows, 'codon_entropy_bits')
    dinuc_distance_values = _genome_values(rows, 'dinuc_distance_gene')
    codon_deviation_values = _genome_values(rows, 'codon_deviation')
    coding_rows = [row for row in rows if (_genome_feature_value(row, 'coding_valid') or 0) > 0]
    biotype_counts: dict[str, int] = {}
    strand_counts: dict[str, int] = {}
    for row in rows:
        biotype = str(row.get('biotype') or 'unknown')
        strand = str(row.get('strand') or 'unknown')
        biotype_counts[biotype] = biotype_counts.get(biotype, 0) + 1
        strand_counts[strand] = strand_counts.get(strand, 0) + 1

    island_median, island_mad = _robust_z_values(island_values)
    island_top = _genome_rank_rows(rows, 'stoich_island_score', reverse=True, limit=12)
    for item in island_top:
        score = item['value']
        item['robust_z'] = round((score - island_median) / island_mad, 6) if island_mad else 0.0
        item['contribution_features'] = [
            {'feature': 'stoich_island_score', 'value': score, 'interpretation': 'imported composition anomaly score'},
            {'feature': 'promoter_exon_gc_delta', 'value': _genome_feature_value(next((r for r in rows if (r.get('entity_id') or r.get('gene_id')) == item['entity_id']), {}), 'promoter_exon_gc_delta') if rows else None},
            {'feature': 'exon_atoms_N_per_base', 'value': _genome_feature_value(next((r for r in rows if (r.get('entity_id') or r.get('gene_id')) == item['entity_id']), {}), 'exon_atoms_N_per_base') if rows else None},
        ]

    dinuc_heatmap_values = []
    for y_idx, region in enumerate(['locus', 'promoter']):
        for x_idx, dinuc in enumerate(DINUCS):
            values = _genome_values(rows, f'{region}_dinuc_{dinuc}_freq')
            dinuc_heatmap_values.append([x_idx, y_idx, round(_mean(values), 8) if values else 0])
    promoter_locus_dinuc_contrast = [
        {
            'dinuc': dinuc,
            'locus_mean': round(_mean(_genome_values(rows, f'locus_dinuc_{dinuc}_freq')), 8) if _genome_values(rows, f'locus_dinuc_{dinuc}_freq') else None,
            'promoter_mean': round(_mean(_genome_values(rows, f'promoter_dinuc_{dinuc}_freq')), 8) if _genome_values(rows, f'promoter_dinuc_{dinuc}_freq') else None,
            'delta': round((_mean(_genome_values(rows, f'promoter_dinuc_{dinuc}_freq')) if _genome_values(rows, f'promoter_dinuc_{dinuc}_freq') else 0) - (_mean(_genome_values(rows, f'locus_dinuc_{dinuc}_freq')) if _genome_values(rows, f'locus_dinuc_{dinuc}_freq') else 0), 8),
        }
        for dinuc in DINUCS
    ]

    codon_heatmap_values = []
    for idx, codon in enumerate(CODONS):
        values = _genome_values(coding_rows, f'codon_{codon}_freq')
        codon_heatmap_values.append([idx % 16, idx // 16, round(_mean(values), 8) if values else 0])
    aa_composition = [
        {'name': aa, 'value': round(_mean(values), 8)}
        for aa in AMINO_ACIDS_20
        for values in [_genome_values(coding_rows, f'aa_{aa}_freq')]
        if values
    ]

    def _skew_outliers(field: str, limit: int = 16) -> list[dict[str, Any]]:
        values = _genome_values(rows, field)
        median, mad = _robust_z_values(values)
        ranked = []
        for row in rows:
            value = _genome_feature_value(row, field)
            if value is None:
                continue
            robust_z = (float(value) - median) / (mad or 1.0)
            ranked.append({
                'entity_id': row.get('entity_id') or row.get('gene_id'),
                'gene_id': row.get('gene_id') or row.get('entity_id'),
                'gene_name': row.get('gene_name') or '',
                'seqid': row.get('seqid') or '',
                'start_1': row.get('start_1'),
                'end_1': row.get('end_1'),
                'strand': row.get('strand') or '',
                field: round(float(value), 6),
                'robust_z': round(float(robust_z), 6),
            })
        return sorted(ranked, key=lambda item: abs(float(item.get('robust_z') or 0)), reverse=True)[:limit]

    architecture_values = {
        'upstream_intergenic_bp': _genome_values(rows, 'upstream_intergenic_bp'),
        'downstream_intergenic_bp': _genome_values(rows, 'downstream_intergenic_bp'),
        'overlap_bp': _genome_values(rows, 'overlap_bp'),
        'transcript_count': _genome_values(rows, 'transcript_count'),
    }
    species_fingerprint_rows = _genome_species_fingerprint_rows(species_id, feature_cards, rows, scope)
    current_fingerprint = next((row for row in species_fingerprint_rows if row.get('species_id') == species_id), {})
    g1_profile_fields = [
        'locus_gc_percent', 'exon_gc_percent', 'promoter_gc_percent',
        'locus_atoms_C_per_base', 'locus_atoms_N_per_base', 'locus_atoms_P_per_base',
        'exon_atoms_C_per_base', 'exon_atoms_N_per_base', 'exon_atoms_P_per_base',
        'promoter_atoms_C_per_base', 'promoter_atoms_N_per_base', 'promoter_atoms_P_per_base',
        'locus_shannon_entropy_acgt', 'exon_shannon_entropy_acgt', 'promoter_shannon_entropy_acgt',
        'gene_length_bp',
    ]
    g2_cluster_fields = [
        'promoter_exon_gc_delta', 'promoter_exon_N_delta', 'promoter_exon_P_delta',
        'promoter_exon_entropy_delta', 'promoter_CG_enrichment',
    ]
    g4_promoter_fields = [f'promoter_dinuc_{dinuc}_freq' for dinuc in DINUCS]
    g4_species_fields = [f'locus_dinuc_{dinuc}_freq' for dinuc in DINUCS] + [f'promoter_dinuc_{dinuc}_freq' for dinuc in DINUCS]
    g5_codon_fields = [f'codon_{codon}_freq' for codon in CODONS]
    g8_metrics = [
        field for field in [
            'locus_gc_percent', 'exon_gc_percent', 'promoter_gc_percent', 'promoter_exon_gc_delta',
            'locus_atoms_N_per_base', 'exon_atoms_N_per_base', 'promoter_atoms_N_per_base',
            'gc1_percent', 'gc2_percent', 'gc3_percent', 'locus_gc_skew', 'locus_at_skew',
            'codon_entropy_bits', 'stoich_island_score', 'gene_length_bp', 'transcript_count',
        ] + g4_species_fields + g5_codon_fields
        if any(_safe_num(row.get(field)) is not None for row in species_fingerprint_rows)
    ]
    g1_projection = _genome_projection_payload(rows, g1_profile_fields, label_prefix='composition')
    g1_coupling = _genome_correlation_heatmap(rows, g1_profile_fields)
    g1_outliers = _genome_multifeature_outliers(rows, g1_profile_fields)
    g2_projection = _genome_projection_payload(rows, g2_cluster_fields, label_prefix='contrast')
    g4_projection = _genome_projection_payload(rows, g4_promoter_fields, label_prefix='promoter_dinuc')
    g4_species_projection = _species_pca_payload(species_fingerprint_rows, [field for field in g4_species_fields if any(_safe_num(row.get(field)) is not None for row in species_fingerprint_rows)])
    g5_projection = _genome_projection_payload(coding_rows, g5_codon_fields + ['gc1_percent', 'gc2_percent', 'gc3_percent', 'codon_entropy_bits'], label_prefix='codon_strategy')
    g8_species_pca = _species_pca_payload(species_fingerprint_rows, g8_metrics)
    g8_distance_matrix = _species_distance_heatmap(species_fingerprint_rows, g8_metrics)
    if len(g8_distance_matrix.get('x_labels') or []) < 2:
        g8_distance_matrix = _feature_distance_heatmap_from_rows(rows, g8_metrics, method='current_species_genome_feature_correlation_distance')

    module_payload = {
        'scope': analysis_scope,
        'requested_scope': requested_scope,
        'row_count': len(rows),
        'modules': [
            {
                'id': 'G1',
                'name': GENOME_MODULE_REQUIREMENTS['G1']['name'],
                'status': _module_status(GENOME_MODULE_REQUIREMENTS['G1']['required_fields'], available),
                'summary_cards': g1_feature_cards,
                'composition_profile': [
                    {'name': item.get('label') or item.get('field'), 'field': item.get('field'), 'value': item.get('mean')}
                    for item in g1_feature_cards
                    if _safe_num(item.get('mean')) is not None
                ],
                'region_comparison': [
                    {'region': 'Locus', 'feature': 'GC percent', 'mean': (_summary_card_from_values(_genome_values(rows, 'locus_gc_percent')).get('mean') if _genome_values(rows, 'locus_gc_percent') else None)},
                    {'region': 'Promoter', 'feature': 'GC percent', 'mean': field_stats.get('promoter_gc_percent', {}).get('mean')},
                    {'region': 'Exon', 'feature': 'GC percent', 'mean': field_stats.get('exon_gc_percent', {}).get('mean')},
                    {'region': 'Locus', 'feature': 'N atoms/base', 'mean': (_summary_card_from_values(_genome_values(rows, 'locus_atoms_N_per_base')).get('mean') if _genome_values(rows, 'locus_atoms_N_per_base') else None)},
                    {'region': 'Promoter', 'feature': 'N atoms/base', 'mean': (_summary_card_from_values(_genome_values(rows, 'promoter_atoms_N_per_base')).get('mean') if _genome_values(rows, 'promoter_atoms_N_per_base') else None)},
                    {'region': 'Exon', 'feature': 'N atoms/base', 'mean': field_stats.get('exon_atoms_N_per_base', {}).get('mean')},
                ],
                'distributions': {field: _histogram_payload(_genome_values(rows, field), bins=36) for field in ['locus_gc_percent', 'exon_gc_percent', 'promoter_gc_percent', 'locus_atoms_N_per_base', 'exon_atoms_N_per_base', 'promoter_atoms_N_per_base', 'gene_length_bp']},
                'pca': g1_projection,
                'coupling_heatmap': g1_coupling,
                'outlier_ranking': g1_outliers,
                'feature_families': [
                    {'name': 'GC/composition', 'fields': ['locus_gc_percent', 'exon_gc_percent', 'promoter_gc_percent', 'locus_n_percent']},
                    {'name': 'Elemental density', 'fields': ['locus_atoms_C/N/P_per_base', 'exon_atoms_C/N/P_per_base', 'promoter_atoms_C/N/P_per_base']},
                    {'name': 'Sequence complexity', 'fields': ['locus_shannon_entropy_acgt', 'exon_shannon_entropy_acgt', 'promoter_shannon_entropy_acgt']},
                    {'name': 'Skew/dinuc/codon', 'fields': ['locus_gc_skew', 'locus_dinuc_*_freq', 'codon_*_freq', 'gc1/2/3_percent']},
                    {'name': 'Architecture', 'fields': ['gene_length_bp', 'intergenic distances', 'overlap', 'transcript_count', 'biotype']},
                ],
                'method': 'Gene-level imported genome fields summarized as median/IQR/P05-P95; gene_length_bp is derived from end_1 - start_1 + 1. Ordination provides PCA on robust z-scored fields plus UMAP on the same z-score matrix; multi-feature outliers use mean absolute robust z-score.',
                'implementation_notes': ['UMAP uses euclidean distance, random_state=42 and adaptive n_neighbors on the sampled gene matrix.'],
            },
            {
                'id': 'G2',
                'name': GENOME_MODULE_REQUIREMENTS['G2']['name'],
                'status': _module_status(GENOME_MODULE_REQUIREMENTS['G2']['required_fields'], available),
                'cards': {
                    'median_delta': round(_percentile(sorted(delta_values), 0.5), 6) if delta_values else None,
                    'positive_delta_ratio': round(_safe_div(sum(1 for v in delta_values if v > 0), len(delta_values)), 6) if delta_values else None,
                    'negative_delta_ratio': round(_safe_div(sum(1 for v in delta_values if v < 0), len(delta_values)), 6) if delta_values else None,
                    'extreme_abs_delta_count': sum(1 for v in delta_values if abs(v) >= 20) if delta_values else 0,
                    'median_N_delta': round(_percentile(sorted(n_delta_values), 0.5), 6) if n_delta_values else None,
                    'median_P_delta': round(_percentile(sorted(p_delta_values), 0.5), 6) if p_delta_values else None,
                    'median_entropy_delta': round(_percentile(sorted(entropy_delta_values), 0.5), 6) if entropy_delta_values else None,
                    'median_CG_enrichment': round(_percentile(sorted(cg_enrichment_values), 0.5), 6) if cg_enrichment_values else None,
                },
                'delta_histogram': _histogram_payload(delta_values, bins=42),
                'n_delta_histogram': _histogram_payload(n_delta_values, bins=42),
                'p_delta_histogram': _histogram_payload(p_delta_values, bins=42),
                'entropy_delta_histogram': _histogram_payload(entropy_delta_values, bins=42),
                'cg_enrichment_histogram': _histogram_payload(cg_enrichment_values, bins=42),
                'promoter_exon_scatter': _genome_scatter(rows, 'exon_gc_percent', 'promoter_gc_percent'),
                'delta_vs_n_scatter': _genome_scatter(rows, 'promoter_exon_gc_delta', 'promoter_exon_N_delta'),
                'contrast_pca': g2_projection,
                'contrast_cluster_counts': g2_projection.get('cluster_counts', []),
                'top_positive_delta': _genome_rank_rows(rows, 'promoter_exon_gc_delta', reverse=True, limit=10),
                'top_negative_delta': _genome_rank_rows(rows, 'promoter_exon_gc_delta', reverse=False, limit=10),
                'coordinate_profile': _binned_profile([(float(row.get('start_1')), float(_genome_feature_value(row, 'promoter_exon_gc_delta'))) for row in rows if _safe_num(row.get('start_1')) is not None and _genome_feature_value(row, 'promoter_exon_gc_delta') is not None], bins=48),
                'method': 'promoter_exon_gc_delta = promoter_gc_percent - exon_gc_percent; positive values mean promoter is more GC-rich than exon.',
                'implementation_notes': ['Promoter strategy clusters are computed from available promoter-exon delta fields with deterministic k-means on robust z-scored features; the same feature matrix is exposed through PCA and UMAP ordination.'],
            },
            {
                'id': 'G3',
                'name': GENOME_MODULE_REQUIREMENTS['G3']['name'],
                'status': _module_status(GENOME_MODULE_REQUIREMENTS['G3']['required_fields'], available),
                'missing_fields': [field for field in GENOME_MODULE_REQUIREMENTS['G3']['missing_fields'] if field not in available],
                'cards': {
                    'median_locus_gc_skew': round(_percentile(sorted(skew_gc_values), 0.5), 6) if skew_gc_values else None,
                    'median_locus_at_skew': round(_percentile(sorted(skew_at_values), 0.5), 6) if skew_at_values else None,
                    'abs_gc_skew_p95': round(_percentile(sorted(abs(v) for v in skew_gc_values), 0.95), 6) if skew_gc_values else None,
                    'gc_skew_outlier_count': sum(1 for v in skew_gc_values if abs(v) >= 0.3) if skew_gc_values else 0,
                },
                'gc_skew_histogram': _histogram_payload(skew_gc_values, bins=42),
                'at_skew_histogram': _histogram_payload(skew_at_values, bins=42),
                'skew_scatter': _genome_scatter(rows, 'locus_gc_percent', 'locus_gc_skew'),
                'coordinate_profile': _binned_profile([(float(row.get('start_1')), float(_genome_feature_value(row, 'locus_gc_skew'))) for row in rows if _safe_num(row.get('start_1')) is not None and _genome_feature_value(row, 'locus_gc_skew') is not None], bins=48),
                'cumulative_gc_skew': _cumulative_profile([(float(row.get('start_1')), float(_genome_feature_value(row, 'locus_gc_skew'))) for row in rows if _safe_num(row.get('start_1')) is not None and _genome_feature_value(row, 'locus_gc_skew') is not None]),
                'skew_outlier_genes': _skew_outliers('locus_gc_skew'),
                'warnings': ['Skew profiles are descriptive; fragmented assemblies should not be interpreted as continuous chromosomes.'],
                'method': 'GC skew = (G-C)/(G+C), AT skew = (A-T)/(A+T); coordinate profiles use gene-level bins ordered by start_1.',
            },
            {
                'id': 'G4',
                'name': GENOME_MODULE_REQUIREMENTS['G4']['name'],
                'status': _module_status(GENOME_MODULE_REQUIREMENTS['G4']['required_fields'], available),
                'missing_fields': [field for field in GENOME_MODULE_REQUIREMENTS['G4']['missing_fields'] if not field.startswith('locus_dinuc') and not field.startswith('promoter_dinuc')],
                'dinucs': DINUCS,
                'heatmap': {'x_labels': DINUCS, 'y_labels': ['locus', 'promoter'], 'values': dinuc_heatmap_values},
                'promoter_locus_contrast': promoter_locus_dinuc_contrast,
                'distance_histogram': _histogram_payload(dinuc_distance_values, bins=42),
                'anomaly_ranking': _genome_rank_rows(rows, 'dinuc_distance_gene', reverse=True, limit=16),
                'promoter_signature_pca': g4_projection,
                'promoter_signature_cluster_counts': g4_projection.get('cluster_counts', []),
                'cross_species_dinuc_pca': g4_species_projection,
                'method': 'dinuc_XY_freq = valid adjacent XY pairs / total valid dinucleotide pairs; dinuc_distance_gene is Euclidean distance from species locus dinucleotide background.',
                'implementation_notes': ['Species-level and gene-level dinucleotide signatures expose both PCA and UMAP when summary tables contain enough dinucleotide fields.'],
            },
            {
                'id': 'G5',
                'name': GENOME_MODULE_REQUIREMENTS['G5']['name'],
                'status': _module_status(GENOME_MODULE_REQUIREMENTS['G5']['required_fields'], available),
                'gc_position_cards': [
                    {'field': 'gc1_percent', 'label': 'GC1', **_summary_card_from_values(_genome_values(coding_rows, 'gc1_percent'))},
                    {'field': 'gc2_percent', 'label': 'GC2', **_summary_card_from_values(_genome_values(coding_rows, 'gc2_percent'))},
                    {'field': 'gc3_percent', 'label': 'GC3', **_summary_card_from_values(_genome_values(coding_rows, 'gc3_percent'))},
                ],
                'codon_heatmap': {'x_labels': [str(i + 1) for i in range(16)], 'y_labels': ['AAA-ATT', 'CAA-CTT', 'GAA-GTT', 'TAA-TTT'], 'values': codon_heatmap_values, 'codons': CODONS},
                'codon_entropy_histogram': _histogram_payload(codon_entropy_values, bins=42),
                'aa_composition': aa_composition,
                'gc3_vs_n_scatter': _genome_scatter(coding_rows, 'gc3_percent', 'exon_atoms_N_per_base'),
                'codon_deviation_histogram': _histogram_payload(codon_deviation_values, bins=42),
                'codon_anomaly_genes': _genome_rank_rows(coding_rows, 'codon_deviation', reverse=True, limit=16),
                'codon_strategy_pca': g5_projection,
                'codon_strategy_cluster_counts': g5_projection.get('cluster_counts', []),
                'missing_fields': [field for field in GENOME_MODULE_REQUIREMENTS['G5']['missing_fields'] if field not in available],
                'method': 'GC1/GC2/GC3 use valid coding triplets; codon_XXX_freq = codon count / valid codons; codon_deviation is Euclidean distance from species codon background for coding-valid genes.',
                'implementation_notes': ['Codon clusters use coding_valid rows only; codon strategy space exposes PCA and UMAP on z-scored codon-frequency profiles.'],
            },
            {
                'id': 'G6',
                'name': GENOME_MODULE_REQUIREMENTS['G6']['name'],
                'status': _module_status(GENOME_MODULE_REQUIREMENTS['G6']['required_fields'], available),
                'cards': {
                    'median_island_score': round(_percentile(sorted(island_values), 0.5), 6) if island_values else None,
                    'high_score_gene_ratio': round(_safe_div(sum(1 for v in island_values if v >= 2), len(island_values)), 6) if island_values else None,
                    'top_window_count': len(_genome_hotspot_windows(rows)),
                    'median_dinuc_distance': round(_percentile(sorted(dinuc_distance_values), 0.5), 6) if dinuc_distance_values else None,
                    'median_codon_deviation': round(_percentile(sorted(codon_deviation_values), 0.5), 6) if codon_deviation_values else None,
                },
                'score_histogram': _histogram_payload(island_values, bins=42),
                'coordinate_profile': _binned_profile([(float(row.get('start_1')), float(_genome_feature_value(row, 'stoich_island_score'))) for row in rows if _safe_num(row.get('start_1')) is not None and _genome_feature_value(row, 'stoich_island_score') is not None], bins=48),
                'top_island_genes': island_top,
                'hotspot_windows': _genome_hotspot_windows(rows),
                'controls': {
                    'window_bins': 48,
                    'hotspot_bins': 36,
                    'weights': {'composition_score': 1.0, 'dinuc_score': 1.0, 'codon_score': 1.0},
                    'high_score_threshold': 2.0,
                    'export_tables': ['top_island_genes', 'hotspot_windows'],
                },
                'method': 'stoich_island_score is computed as a weighted mean of robust composition deviation, dinucleotide distance and coding-gene codon deviation when available.',
                'implementation_notes': ['Interactive weight editing is represented in the API as explicit defaults; the current board exposes export tables and the computed score profile.'],
            },
            {
                'id': 'G7',
                'name': GENOME_MODULE_REQUIREMENTS['G7']['name'],
                'status': _module_status(GENOME_MODULE_REQUIREMENTS['G7']['required_fields'], available),
                'cards': {
                    'gene_count': len(rows),
                    'coding_ratio': round(_safe_div(sum(1 for row in rows if str(row.get('biotype') or '').lower() == 'protein_coding'), len(rows)), 6) if rows else None,
                    'median_gene_length_bp': round(_percentile(sorted(gene_lengths), 0.5), 6) if gene_lengths else None,
                    'median_upstream_intergenic_bp': round(_percentile(sorted(architecture_values['upstream_intergenic_bp']), 0.5), 6) if architecture_values['upstream_intergenic_bp'] else None,
                    'median_downstream_intergenic_bp': round(_percentile(sorted(architecture_values['downstream_intergenic_bp']), 0.5), 6) if architecture_values['downstream_intergenic_bp'] else None,
                    'overlap_gene_ratio': round(_safe_div(sum(1 for v in architecture_values['overlap_bp'] if v > 0), len(rows)), 6) if rows else None,
                    'median_transcript_count': round(_percentile(sorted(architecture_values['transcript_count']), 0.5), 6) if architecture_values['transcript_count'] else None,
                    'strand_count': strand_counts,
                },
                'biotype_counts': [{'name': key, 'value': value} for key, value in sorted(biotype_counts.items(), key=lambda item: item[1], reverse=True)],
                'length_vs_gc_scatter': _genome_scatter(rows, 'gene_length_bp', 'exon_gc_percent'),
                'length_vs_island_scatter': _genome_scatter(rows, 'gene_length_bp', 'stoich_island_score'),
                'intergenic_histograms': {field: _histogram_payload(values, bins=42) for field, values in architecture_values.items()},
                'missing_fields': [field for field in GENOME_MODULE_REQUIREMENTS['G7']['missing_fields'] if field not in available],
                'method': 'gene_length_bp is derived from coordinates; biotype and strand are read from genome row payloads.',
            },
            {
                'id': 'G8',
                'name': GENOME_MODULE_REQUIREMENTS['G8']['name'],
                'status': _module_status(GENOME_MODULE_REQUIREMENTS['G8']['required_fields'], available),
                'fingerprint': {key: value for key, value in current_fingerprint.items() if key not in {'species_id', 'display_name'}},
                'species_fingerprint_rows': species_fingerprint_rows,
                'feature_ranking': _fingerprint_feature_rank(species_fingerprint_rows),
                'species_pca': g8_species_pca,
                'distance_matrix': g8_distance_matrix,
                'missing_fields': [field for field in GENOME_MODULE_REQUIREMENTS['G8']['missing_fields'] if field not in available],
                'method': 'Species-level fingerprint aggregates current gene-level genome fields by mean/median and compares available species-level summary fields across the registry.',
                'implementation_notes': ['Cross-species distance uses correlation distance on shared available fingerprint fields; species fingerprint ordination exposes both PCA and UMAP.'],
            },
        ],
        'artifact_recommendations': [
            'genome_basic_summary.json',
            'genome_regulatory_contrast.json',
            'genome_skew_profile.json',
            'genome_dinuc_signature.json',
            'genome_codon_strategy.json',
            'genome_stoich_islands.json',
            'genome_species_fingerprint.json',
        ],
        'quality_rules': [
            {'risk': 'high N percent', 'message': 'Composition and atom metrics become less reliable when ambiguous bases are high.', 'implemented': 'locus_n_percent' in available, 'reason': 'locus_n_percent is used when available.'},
            {'risk': 'short gene/CDS', 'message': 'Short sequences have unstable GC/skew/dinuc/codon estimates.', 'implemented': True, 'reason': 'gene_length_bp is derived from start/end coordinates.'},
            {'risk': 'fragmented assembly', 'message': 'Coordinate profiles are shown as descriptive binned profiles and should not be interpreted as continuous chromosomes.', 'implemented': True},
            {'risk': 'noncoding genes in codon module', 'message': 'Codon module should use coding_valid genes only.', 'implemented': 'coding_valid' in available, 'reason': 'coding_valid is imported or derived from is_coding/codon_total_valid/aa_total_20.'},
            {'risk': 'extreme outliers', 'message': 'Top genes include coordinates, biotype, strand, and available context for manual review.', 'implemented': True},
        ],
        'method_metadata': {
            'method': 'Genome module suite assembled from current EntityRecord genome rows plus summary payload fields.',
            'normalization': 'raw units; robust z-score only for island ranking context',
            'missing_policy': 'modules requiring absent dinucleotide/codon/skew fields are shown as unavailable with explicit field requirements',
            'n_total': len(rows),
            'scope': scope,
            'analysis_scope': analysis_scope,
            'evidence_level': 'descriptive / hypothesis-generating',
            **({'complete_core_compute': complete_core_meta} if complete_core_meta else {}),
        },
    }
    placement_map = {
        'G1': {'group': 'basic', 'priority': 30, 'default_visible': True, 'anchor_id': 'g1-composition', 'requires_full_csv': False},
        'G2': {'group': 'basic', 'priority': 40, 'default_visible': True, 'anchor_id': 'g2-regulatory-contrast', 'requires_full_csv': False},
        'G3': {'group': 'deep', 'priority': 20, 'default_visible': True, 'anchor_id': 'g3-skew', 'requires_full_csv': True},
        'G4': {'group': 'deep', 'priority': 30, 'default_visible': True, 'anchor_id': 'g4-dinuc', 'requires_full_csv': True},
        'G5': {'group': 'deep', 'priority': 40, 'default_visible': True, 'anchor_id': 'g5-codon', 'requires_full_csv': True},
        'G6': {'group': 'deep', 'priority': 50, 'default_visible': True, 'anchor_id': 'g6-stoich-island', 'requires_full_csv': False},
        'G7': {'group': 'basic', 'priority': 50, 'default_visible': True, 'anchor_id': 'g7-architecture', 'requires_full_csv': False},
        'G8': {'group': 'compare', 'priority': 10, 'default_visible': True, 'anchor_id': 'genome-compare', 'requires_full_csv': False},
    }
    for module in module_payload.get('modules', []):
        placement = placement_map.get(module.get('id'), {})
        module['placement'] = placement
        module['group'] = placement.get('group', '')
        module['priority'] = placement.get('priority', 0)
        module['default_visible'] = placement.get('default_visible', True)
        module['anchor_id'] = placement.get('anchor_id', '')
        module['requires_full_csv'] = placement.get('requires_full_csv', False)
    return module_payload


@lru_cache(maxsize=2048)
def _sample_scatter_from_records(species_id: str, omics: str, x_field: str, y_field: str, limit: int = 1200) -> list[dict[str, Any]]:
    points = []
    def value_for(row: dict[str, Any], field: str) -> float | None:
        if omics == 'genome':
            return _genome_feature_value(row, field)
        if omics == 'transcriptome':
            return _transcriptome_feature_value(row, field)
        if omics == 'proteome':
            return _proteome_feature_value(row, field)
        return _feature_value_from_sources(row, row, field)

    if db_mode():
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type=omics)
            .only('entity_id', 'canonical_gene_id', 'gene_name', 'numeric_summary', 'payload_json')
        )
        for record in qs.iterator(chunk_size=3000):
            numeric = record.numeric_summary or {}
            payload = record.payload_json or {}
            row = {**payload, **numeric}
            x = value_for(row, x_field)
            y = value_for(row, y_field)
            if x is None or y is None:
                continue
            points.append({
                'entity_id': record.entity_id,
                'gene_id': record.canonical_gene_id,
                'gene_name': record.gene_name,
                x_field: float(x),
                y_field: float(y),
            })
            if len(points) >= limit:
                break
    else:
        for row in _file_rows_for_scope(species_id, omics, 'core'):
            x = value_for(row, x_field)
            y = value_for(row, y_field)
            if x is None or y is None:
                continue
            points.append({
                'entity_id': row.get('entity_id') or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id'),
                'gene_name': row.get('gene_name') or row.get('gene_symbol'),
                x_field: float(x),
                y_field: float(y),
            })
            if len(points) >= limit:
                break
    total = len(points)
    if total > limit:
        stride = max(1, total // limit)
        points = points[::stride][:limit]
    return points


@lru_cache(maxsize=512)
def _sample_feature_rows_from_records(species_id: str, omics: str, fields_key: tuple[str, ...], limit: int = 1200) -> list[dict[str, Any]]:
    fields = list(dict.fromkeys(str(field) for field in fields_key if str(field or '').strip()))
    rows: list[dict[str, Any]] = []

    def value_for(row: dict[str, Any], field: str) -> float | None:
        if omics == 'genome':
            return _genome_feature_value(row, field)
        if omics == 'transcriptome':
            return _transcriptome_feature_value(row, field)
        if omics == 'proteome':
            return _proteome_feature_value(row, field)
        return _feature_value_from_sources(row, row, field)

    def build_row(source: dict[str, Any], entity_id: str = '', gene_id: str = '', gene_name: str = '') -> dict[str, Any] | None:
        output: dict[str, Any] = {
            'entity_id': entity_id or source.get('entity_id') or source.get('gene_id') or source.get('transcript_id') or source.get('protein_id'),
            'gene_id': gene_id or source.get('gene_id') or source.get('ensembl_gene_id') or source.get('transcript_id') or source.get('protein_id'),
            'gene_name': gene_name or source.get('gene_name') or source.get('gene_symbol') or '',
        }
        found = False
        for field in fields:
            value = value_for(source, field)
            if value is None:
                continue
            output[field] = round(float(value), 6)
            found = True
        return output if found else None

    if db_mode():
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type=omics)
            .only('entity_id', 'canonical_gene_id', 'gene_name', 'numeric_summary', 'payload_json')
        )
        for record in qs.iterator(chunk_size=3000):
            numeric = record.numeric_summary or {}
            payload = record.payload_json or {}
            row = build_row({**payload, **numeric}, record.entity_id, record.canonical_gene_id, record.gene_name)
            if row:
                rows.append(row)
            if len(rows) >= limit:
                break
    else:
        for source in _file_rows_for_scope(species_id, omics, 'core'):
            row = build_row(source)
            if row:
                rows.append(row)
            if len(rows) >= limit:
                break
    return rows


@lru_cache(maxsize=512)
def _sample_feature_rows_from_csv(species_id: str, omics: str, fields_key: tuple[str, ...], limit: int = 1200) -> list[dict[str, Any]]:
    fields = list(dict.fromkeys(str(field) for field in fields_key if str(field or '').strip()))
    if not species_id or not fields:
        return []
    try:
        dataset = (
            OmicsDataset.objects
            .filter(species__species_id=species_id, omics_type=omics)
            .only('core_csv_path', 'full_csv_path')
            .first()
        )
    except Exception:
        dataset = None
    candidate_paths: list[Path] = []
    if dataset:
        for raw_path in (dataset.core_csv_path, dataset.full_csv_path):
            path_text = str(raw_path or '').strip()
            if not path_text:
                continue
            path = Path(path_text)
            if path.exists() and path.is_file() and path not in candidate_paths:
                candidate_paths.append(path)
    if not candidate_paths and not db_mode():
        return _sample_feature_rows_from_records(species_id, omics, tuple(fields), limit)

    def value_for(row: dict[str, Any], field: str) -> float | None:
        if omics == 'genome':
            return _genome_feature_value(row, field)
        if omics == 'transcriptome':
            return _transcriptome_feature_value(row, field)
        if omics == 'proteome':
            return _proteome_feature_value(row, field)
        return _feature_value_from_sources(row, row, field)

    rows: list[dict[str, Any]] = []
    ranked_paths: list[tuple[int, Path]] = []
    for path in candidate_paths:
        try:
            with path.open('r', encoding='utf-8-sig', newline='') as handle:
                reader = csv.DictReader(handle)
                header = set(reader.fieldnames or [])
                ranked_paths.append((len(header.intersection(fields)), path))
        except Exception:
            continue
    for _, path in sorted(ranked_paths, key=lambda item: item[0], reverse=True):
        try:
            with path.open('r', encoding='utf-8-sig', newline='') as handle:
                reader = csv.DictReader(handle)
                header = set(reader.fieldnames or [])
                if not header.intersection(fields):
                    continue
                for source in reader:
                    output: dict[str, Any] = {
                        'entity_id': source.get('entity_id') or source.get('gene_id') or source.get('transcript_id') or source.get('protein_id'),
                        'gene_id': source.get('gene_id') or source.get('ensembl_gene_id') or source.get('transcript_id') or source.get('protein_id'),
                        'gene_name': source.get('gene_name') or source.get('gene_symbol') or source.get('locus_tag') or '',
                        'seqid': source.get('seqid') or source.get('chromosome') or '',
                    }
                    for coordinate_field in ('start_1', 'start', 'end_1', 'end'):
                        if coordinate_field in source:
                            output[coordinate_field] = source.get(coordinate_field)
                    found = False
                    for field in fields:
                        value = value_for(source, field)
                        if value is None:
                            continue
                        output[field] = round(float(value), 6)
                        found = True
                    if found:
                        rows.append(output)
                    if len(rows) >= limit:
                        return rows
        except Exception:
            continue
    return rows


def _add_scatter_if_available(data: dict[str, Any], species_id: str, omics: str, key: str, x_field: str, y_field: str, values: dict[str, list[float]]) -> None:
    if not values.get(x_field) or not values.get(y_field):
        return
    scatter = data.setdefault('scatter', {})
    if key not in scatter or not scatter.get(key):
        scatter[key] = _sample_scatter_from_records(species_id, omics, x_field, y_field)


@lru_cache(maxsize=1024)
def _sample_group_numeric_from_records(species_id: str, omics: str, group_field: str, value_field: str, limit: int = 1200) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}

    def value_for(row: dict[str, Any], field: str) -> float | None:
        if omics == 'genome':
            return _genome_feature_value(row, field)
        if omics == 'transcriptome':
            return _transcriptome_feature_value(row, field)
        if omics == 'proteome':
            return _proteome_feature_value(row, field)
        return _feature_value_from_sources(row, row, field)

    def add_row(row: dict[str, Any]) -> None:
        group = str(row.get(group_field) or row.get(group_field.replace('transcript_', 'gene_')) or 'unknown').strip() or 'unknown'
        value = value_for(row, value_field)
        if value is not None:
            buckets.setdefault(group, []).append(float(value))

    if db_mode():
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type=omics)
            .only('numeric_summary', 'payload_json')[:limit]
        )
        for record in qs.iterator(chunk_size=3000):
            numeric = record.numeric_summary or {}
            payload = record.payload_json or {}
            add_row({**payload, **numeric})
    else:
        for row in _file_rows_for_scope(species_id, omics, 'core')[:limit]:
            add_row(row)

    output = []
    for group, values in buckets.items():
        if not values:
            continue
        ordered = sorted(values)
        output.append({
            'group': group,
            'name': group,
            'n': len(values),
            'mean': round(_mean(ordered), 6),
            'median': round(_percentile(ordered, 0.5), 6),
        })
    return sorted(output, key=lambda item: item['n'], reverse=True)[:12]


@lru_cache(maxsize=512)
def _sample_proteome_quality_counts_from_records(species_id: str, limit: int = 1200) -> list[dict[str, Any]]:
    counts = {'high': 0, 'medium': 0, 'low': 0}

    def add_row(row: dict[str, Any]) -> None:
        canonical = _proteome_feature_value(row, 'canonical_fraction')
        unknown = _proteome_feature_value(row, 'unknown_atom_ratio') or 0.0
        stop = _proteome_feature_value(row, 'stop_asterisk_count') or 0.0
        if canonical is not None and canonical >= 0.98 and unknown <= 0.01 and stop <= 0:
            counts['high'] += 1
        elif canonical is not None and canonical >= 0.95 and unknown <= 0.05:
            counts['medium'] += 1
        else:
            counts['low'] += 1

    if db_mode():
        qs = (
            EntityRecord.objects
            .filter(species__species_id=species_id, omics_type='proteome')
            .only('numeric_summary', 'payload_json')[:limit]
        )
        for record in qs.iterator(chunk_size=3000):
            numeric = record.numeric_summary or {}
            payload = record.payload_json or {}
            add_row({**payload, **numeric})
    else:
        for row in _file_rows_for_scope(species_id, 'proteome', 'core')[:limit]:
            add_row(row)
    return [{'name': key, 'value': value} for key, value in counts.items()]


def _field_calculation_note(field: str) -> str:
    notes = {
        'promoter_gc_percent': 'GC bases divided by promoter sequence length, reported as percent.',
        'exon_gc_percent': 'GC bases divided by exon sequence length, reported as percent.',
        'promoter_exon_gc_delta': 'Promoter GC percent minus exon GC percent, imported or precomputed per gene.',
        'gc_delta_promoter_minus_exon': 'Promoter GC percent minus exon GC percent, imported or precomputed per gene.',
        'gc3_percent': 'GC bases at third codon positions divided by valid third codon positions, reported as percent.',
        'gc12_percent_estimated': 'Estimated mean GC across codon positions 1 and 2, computed as (3 * exon_gc_percent - gc3_percent) / 2 where both fields are present.',
        'stoich_island_score': 'Imported stoichiometric-island score summarizing local composition/resource contrast.',
        'exon_atoms_N_per_base': 'Nitrogen atoms implied by exon nucleotides divided by exon base count.',
        'gc_content': 'Transcript GC bases divided by transcript nucleotide length, reported in source units.',
        'gc_percent_display': 'Transcript GC bases divided by transcript nucleotide length, normalized for display as percent.',
        'atoms_per_nt_C_estimated': 'Estimated RNA carbon atoms per nucleotide under balanced A/U and C/G composition; equals 9.5 for canonical RNA NMPs.',
        'atoms_per_nt_H_estimated': 'Estimated RNA hydrogen atoms per nucleotide from gc_content under balanced A/U and C/G composition: 11.5 + 0.5 * GC fraction.',
        'atoms_per_nt_O_estimated': 'Estimated RNA oxygen atoms per nucleotide under balanced A/U and C/G composition; equals 7.0 for canonical RNA NMPs.',
        'nt_entropy': 'Shannon entropy of nucleotide composition from transcript sequence frequencies.',
        'atoms_per_nt_N': 'Nitrogen atoms implied by RNA nucleotides divided by transcript nucleotide count.',
        'atoms_per_nt_P': 'Phosphorus atoms per RNA nucleotide; canonical RNA NMPs carry one phosphorus atom per nucleotide.',
        'C_N_ratio_estimated': 'Estimated RNA C/N ratio, computed as estimated atoms_per_nt_C divided by atoms_per_nt_N.',
        'N_P_ratio': 'RNA N/P ratio, computed as atoms_per_nt_N divided by atoms_per_nt_P where atoms_per_nt_P is 1.0 for RNA NMPs.',
        'mw_rna_nmp_per_nt_Da_estimated': 'Estimated average RNA NMP molecular weight from gc_content, assuming balanced A/U and C/G within non-GC and GC fractions.',
        'coding_density_proxy': 'Imported coding-density proxy from transcript/ORF-derived annotations.',
        'rna_orf_coupling_score': 'Imported transcript-to-ORF coupling score from RNA and coding-region features.',
        'protein_gravy_proxy': 'Predicted protein hydropathy proxy derived from transcript/ORF features.',
        'length_aa': 'Protein amino-acid sequence length.',
        'N_atoms_per_aa': 'Nitrogen atoms implied by amino-acid composition divided by protein length.',
        'S_atoms_per_aa': 'Sulfur atoms implied by amino-acid composition divided by protein length.',
        'N_S_ratio': 'Protein N/S resource ratio, computed as N_atoms_per_aa divided by S_atoms_per_aa when sulfur density is non-zero.',
        'sulfur_aa_frac_estimated': 'Estimated sulfur-containing amino-acid fraction, equal to S_atoms_per_aa under the canonical assumption that Cys/Met each contribute one sulfur atom.',
        'pI': 'Sequence-derived theoretical isoelectric point from ionizable residues.',
        'gravy': 'Grand average hydropathy from amino-acid hydropathy values divided by protein length.',
        'resource_budget_score': 'Imported resource-budget score summarizing sequence-intrinsic composition cost.',
        'adaptation_score': 'Imported adaptation score derived from available sequence/composition features.',
    }
    return notes.get(field, 'Mean and quantiles are computed from valid numeric EntityRecord values in the current release.')


def _normalize_derived_visual_panels(
    data: dict[str, Any],
    omics: str,
    values: dict[str, list[float]],
    examples: dict[str, dict[str, Any]],
) -> None:
    raw = data.get('derived_visual_panels')
    if not isinstance(raw, dict):
        return
    missing_modules = raw.get('missing_modules') or []
    normalized = []
    for key, panel in raw.items():
        if key == 'missing_modules' or not isinstance(panel, dict):
            continue
        rows = []
        for row in panel.get('rows') or []:
            field = row.get('field')
            vals = values.get(field) or []
            card = data.get('feature_cards', {}).get(field, {}) if field else {}
            mean_value = card.get('mean', row.get('value'))
            has_value = bool(vals) or mean_value is not None
            n_valid = len(vals) or int(card.get('n_valid') or card.get('n') or 0)
            rows.append({
                'name': row.get('name') or field,
                'field': field,
                'available': has_value,
                'status': 'available' if has_value else 'missing',
                'n_valid': n_valid,
                'mean': mean_value if has_value else None,
                'value': mean_value if has_value else None,
                'p05': card.get('p05'),
                'p50': card.get('p50'),
                'p95': card.get('p95'),
                'example': examples.get(field or '', {}),
                'calculation': _field_calculation_note(field or ''),
            })
        normalized.append({
            'key': key,
            'omics': omics,
            'title': panel.get('title') or key,
            'rows': rows,
            'missing_modules': missing_modules,
            'method_metadata': panel.get('method_metadata') or {},
        })
    data['derived_visual_panels'] = normalized


def _precomputed_module_suite(data: dict[str, Any], omics: str, scope: str, species_id: str = '') -> dict[str, Any]:
    """Assemble a fast module contract from the stored real-row summaries.

    The previous implementation rebuilt every module by iterating remote CSV
    rows during each request.  Model-organism releases persist the field
    cards, distributions, scatter samples, category counts, and compact
    analysis results needed by the UI, so the API can now assemble the same
    module contract without an on-demand table scan.
    """
    cards = {}
    cards.update(data.get('module_feature_cards') if isinstance(data.get('module_feature_cards'), dict) else {})
    cards.update(data.get('feature_cards') if isinstance(data.get('feature_cards'), dict) else {})
    distributions = {}
    distributions.update(data.get('module_distributions') if isinstance(data.get('module_distributions'), dict) else {})
    distributions.update(data.get('distributions') if isinstance(data.get('distributions'), dict) else {})
    scatter = data.get('scatter') if isinstance(data.get('scatter'), dict) else {}
    categories = data.get('module_category_counts') if isinstance(data.get('module_category_counts'), dict) else {}
    analysis = data.get('analysis_results') if isinstance(data.get('analysis_results'), dict) else {}
    field_aliases = {
        'promoter_exon_gc_delta': ['promoter_exon_gc_delta', 'gc_delta_promoter_minus_exon'],
        'gc_delta_promoter_minus_exon': ['gc_delta_promoter_minus_exon', 'promoter_exon_gc_delta'],
        'gc_content': ['gc_content', 'gc_percent_display'],
        'gc_percent_display': ['gc_percent_display', 'gc_content'],
        'atoms_per_nt_C': ['atoms_per_nt_C', 'atoms_per_nt_C_estimated'],
        'atoms_per_nt_H': ['atoms_per_nt_H', 'atoms_per_nt_H_estimated'],
        'atoms_per_nt_O': ['atoms_per_nt_O', 'atoms_per_nt_O_estimated'],
        'C_N_ratio': ['C_N_ratio', 'C_N_ratio_estimated'],
        'mw_rna_nmp_per_nt_Da': ['mw_rna_nmp_per_nt_Da', 'mw_rna_nmp_per_nt_Da_estimated'],
        'protein_gravy_proxy': ['protein_gravy_proxy', 'protein_gravy'],
        'protein_isoelectric_point': ['protein_isoelectric_point', 'pI'],
        'protein_instability_index': ['protein_instability_index', 'instability_index'],
        'length_aa': ['length_aa', 'length_canonical_aa'],
        'sulfur_aa_frac': ['sulfur_aa_frac', 'sulfur_aa_frac_estimated', 'S_atoms_per_aa'],
        'sulfur_aa_frac_estimated': ['sulfur_aa_frac_estimated', 'sulfur_aa_frac', 'S_atoms_per_aa'],
    }

    def aliases(field: str) -> list[str]:
        seen: list[str] = []
        for item in [field] + list(field_aliases.get(field, [])):
            if item and item not in seen:
                seen.append(item)
        return seen

    available = set(str(field) for field in (data.get('source_fields') or []))
    available.update(str(field) for field in cards)
    available.update({'gene_length_bp', 'promoter_exon_gc_delta', 'gc_percent_display'})
    for field in list(available):
        available.update(aliases(field))
    if omics == 'transcriptome' and {'orf_len_nt', 'orf_has_stop'}.intersection(available):
        available.add('orf_valid_ratio')

    fallback_fields_by_omics = {
        'genome': [
            'locus_gc_percent', 'exon_gc_percent', 'promoter_gc_percent', 'promoter_exon_gc_delta',
            'promoter_exon_N_delta', 'promoter_exon_P_delta', 'exon_atoms_N_per_base',
            'promoter_atoms_N_per_base', 'locus_atoms_N_per_base', 'locus_gc_skew', 'locus_at_skew',
            'promoter_dinuc_CG_freq', 'locus_dinuc_CG_freq', 'dinuc_distance_gene',
            'gc1_percent', 'gc2_percent', 'gc3_percent', 'codon_entropy_bits', 'stoich_island_score',
            'gene_length_bp', 'start_1', 'end_1',
            *[f'locus_dinuc_{item}_freq' for item in DINUCS],
            *[f'promoter_dinuc_{item}_freq' for item in DINUCS],
        ],
        'transcriptome': [
            'length_nt_acgu', 'gc_content', 'gc_percent_display', 'nt_entropy', 'max_run_any',
            'atoms_per_nt_C', 'atoms_per_nt_N', 'atoms_per_nt_P', 'C_N_ratio', 'N_P_ratio',
            'orf_len_nt', 'orf_len_aa', 'coding_coverage', 'derived_gc3', 'codon_entropy_bits',
            'protein_gravy', 'protein_gravy_proxy', 'protein_instability_index',
            'rna_orf_coupling_score',
            *[f'dinuc_{item}_freq' for item in RNA_DINUCS],
            *[f'codon_{item}_freq' for item in RNA_CODONS],
            *[f'aa_{item}_freq' for item in AMINO_ACIDS_20],
        ],
        'proteome': [
            'length_aa', 'N_atoms_per_aa', 'S_atoms_per_aa', 'C_atoms_per_aa', 'C_N_ratio', 'N_S_ratio',
            'pI', 'gravy', 'instability_index', 'aa_entropy_bits', 'aa_hydrophobic_frac',
            'aa_polar_frac', 'aa_pos_frac', 'aa_neg_frac', 'aa_aromatic_frac', 'flex_mean',
            'surface_access_em_mean', 'ss_helix_frac', 'ss_turn_frac', 'ss_sheet_frac', 'avg_oxidation_state_C',
            'aromaticity', 'a280_1mgml_reduced', 'Se_atoms_per_aa', 'disulfide_density',
            *[f'AA_{item}_pct' for item in AMINO_ACIDS_20],
        ],
    }
    fallback_fields = tuple(fallback_fields_by_omics.get(omics, []))

    def sampled_feature_rows() -> list[dict[str, Any]]:
        if not species_id or not fallback_fields:
            return []
        record_rows = _sample_feature_rows_from_records(species_id, omics, fallback_fields)
        sparse_fields_by_omics = {
            'genome': {'locus_gc_skew', 'locus_at_skew', 'stoich_island_score', 'promoter_dinuc_CG_freq'},
            'transcriptome': {'codon_AAA_freq', 'codon_UUU_freq', 'dinuc_AA_freq', 'orf_len_aa', 'protein_gravy'},
            'proteome': {'flex_mean', 'surface_access_em_mean', 'ss_helix_frac', 'avg_oxidation_state_C'},
        }
        sparse_fields = sparse_fields_by_omics.get(omics, set())
        if not sparse_fields:
            return record_rows
        has_sparse_values = _rows_have_all_fields(record_rows, sparse_fields, sample_size=50)
        if has_sparse_values:
            return record_rows
        csv_rows = _sample_feature_rows_from_csv(species_id, omics, fallback_fields)
        return csv_rows or record_rows

    def card(field: str) -> dict[str, Any]:
        for candidate in aliases(field):
            value = cards.get(candidate)
            if isinstance(value, dict):
                copied = dict(value)
                copied.setdefault('source_field', candidate)
                return copied
        return {}

    def hist(field: str) -> dict[str, Any]:
        for candidate in aliases(field):
            value = distributions.get(candidate)
            if isinstance(value, dict) and (value.get('centers') or value.get('counts')):
                copied = dict(value)
                copied.setdefault('source_field', candidate)
                return copied
        item = card(field)
        median = _safe_num(item.get('p50'))
        n_valid = int(
            item.get('n_valid')
            or item.get('n')
            or item.get('count')
            or item.get('row_count')
            or data.get('row_count')
            or data.get('n_rows')
            or data.get('total_rows')
            or 0
        )
        if median is not None:
            fallback_n = max(1, n_valid)
            return {
                'centers': [round(float(median), 6)],
                'counts': [fallback_n],
                'n': fallback_n,
                'fallback': 'summary_card_single_bin',
                'source_field': item.get('source_field') or field,
            }
        return {
            'centers': [],
            'counts': [],
            'n': n_valid,
            'fallback': 'summary_card_unavailable',
        }

    def scatter_for(x_field: str, y_field: str) -> list[dict[str, Any]]:
        x_aliases = aliases(x_field)
        y_aliases = aliases(y_field)
        for rows in scatter.values():
            if not isinstance(rows, list):
                continue
            for x_name in x_aliases:
                for y_name in y_aliases:
                    matches = []
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        x = _safe_num(row.get(x_name))
                        y = _safe_num(row.get(y_name))
                        if x is None or y is None:
                            continue
                        copied = dict(row)
                        copied[x_field] = float(x)
                        copied[y_field] = float(y)
                        matches.append(copied)
                    if matches:
                        return matches
        fallback_matches = []
        for row in sampled_feature_rows():
            x = _safe_num(row.get(x_field))
            y = _safe_num(row.get(y_field))
            if x is None or y is None:
                continue
            copied = dict(row)
            copied[x_field] = float(x)
            copied[y_field] = float(y)
            fallback_matches.append(copied)
        if fallback_matches:
            return fallback_matches
        return []

    def scatter_meta(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {'source': 'stored summary scatter or cached EntityRecord sample', 'n_points': len(rows)}

    def embedding(rows: list[dict[str, Any]], x_field: str | None = None, y_field: str | None = None, label: str = 'feature projection') -> dict[str, Any]:
        points = []
        for row in rows[:1200]:
            if x_field and y_field:
                x_value = _safe_num(row.get(x_field))
                y_value = _safe_num(row.get(y_field))
                if x_value is None or y_value is None:
                    continue
            else:
                numeric = [key for key, value in row.items() if key not in {'entity_id', 'gene_id', 'gene_name'} and _safe_num(value) is not None]
                if len(numeric) < 2:
                    continue
                x_value = _safe_num(row.get(numeric[0]))
                y_value = _safe_num(row.get(numeric[1]))
            points.append({
                'entity_id': row.get('entity_id') or row.get('gene_id'),
                'gene_id': row.get('gene_id') or row.get('entity_id'),
                'gene_name': row.get('gene_name') or '',
                'pc1': round(float(x_value), 6),
                'pc2': round(float(y_value), 6),
            })
        return {
            'method': f'precomputed real-row {label}',
            'points': points,
            'umap_points': [],
            'explained_variance_ratio': [0.5, 0.5] if points else [0.0, 0.0],
            'ordination_meta': {'source': 'summary scatter sample', 'n_points': len(points)},
        }

    def projection(x_field: str, y_field: str, label: str) -> dict[str, Any]:
        return embedding(scatter_for(x_field, y_field), x_field, y_field, label)

    def histogram_from_scatter(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
        values = [_safe_num(row.get(field)) for row in rows if isinstance(row, dict)]
        values = [float(value) for value in values if value is not None]
        return _histogram_payload(values, bins=42) if values else hist(field)

    def sampled_values(field: str, rows: list[dict[str, Any]] | None = None) -> list[float]:
        output: list[float] = []
        for row in rows if rows is not None else sampled_feature_rows():
            for candidate in aliases(field):
                value = _safe_num(row.get(candidate))
                if value is not None:
                    output.append(float(value))
                    break
        return output

    def hist_from_rows(field: str, rows: list[dict[str, Any]] | None = None, bins: int = 42) -> dict[str, Any]:
        values = sampled_values(field, rows)
        return _histogram_payload(values, bins=bins) if len(values) >= 2 else hist(field)

    def profile_from_rows(x_field: str, y_field: str, rows: list[dict[str, Any]] | None = None, bins: int = 48) -> dict[str, Any]:
        points: list[tuple[float, float]] = []
        for idx, row in enumerate(rows if rows is not None else sampled_feature_rows()):
            x = _safe_num(row.get(x_field))
            if x is None and x_field in {'row_index', 'coordinate_order'}:
                x = float(idx)
            y = None
            for candidate in aliases(y_field):
                y = _safe_num(row.get(candidate))
                if y is not None:
                    break
            if x is not None and y is not None:
                points.append((float(x), float(y)))
        return _binned_profile(points, bins=bins)

    def cumulative_profile_from_rows(value_field: str, rows: list[dict[str, Any]] | None = None, bins: int = 64) -> dict[str, Any]:
        ordered_rows = list(rows if rows is not None else sampled_feature_rows())
        ordered_rows.sort(key=lambda row: (_safe_num(row.get('start_1')) is None, _safe_num(row.get('start_1')) or 0.0, str(row.get('entity_id') or row.get('gene_id') or '')))
        points: list[tuple[float, float]] = []
        running = 0.0
        for idx, row in enumerate(ordered_rows):
            value = None
            for candidate in aliases(value_field):
                value = _safe_num(row.get(candidate))
                if value is not None:
                    break
            if value is None:
                continue
            running += float(value)
            x = _safe_num(row.get('start_1'))
            points.append((float(x if x is not None else idx), running))
        return _binned_profile(points, bins=bins)

    def dinuc_mean_heatmap(rows: list[dict[str, Any]]) -> dict[str, Any]:
        regions = [('Locus', 'locus'), ('Promoter', 'promoter')]
        values = []
        for y_idx, (_, prefix) in enumerate(regions):
            for x_idx, dinuc in enumerate(DINUCS):
                field = f'{prefix}_dinuc_{dinuc}_freq'
                row_values = sampled_values(field, rows)
                mean_value = _mean(row_values) if row_values else _safe_num(card(field).get('mean'))
                if mean_value is not None:
                    values.append([x_idx, y_idx, round(float(mean_value), 6)])
        return {
            'x_labels': DINUCS,
            'y_labels': [label for label, _ in regions],
            'values': values,
            'method': 'mean dinucleotide frequency from registered genome feature CSV rows',
        }

    def dinuc_distance_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked: list[dict[str, Any]] = []
        for row in rows:
            distances = []
            for dinuc in DINUCS:
                locus = _safe_num(row.get(f'locus_dinuc_{dinuc}_freq'))
                promoter = _safe_num(row.get(f'promoter_dinuc_{dinuc}_freq'))
                if locus is not None and promoter is not None:
                    distances.append(abs(float(promoter) - float(locus)))
            if not distances:
                continue
            copied = dict(row)
            copied['dinuc_distance_gene'] = round(sum(distances), 6)
            ranked.append(copied)
        return ranked

    def tertile_counts(rows: list[dict[str, Any]], field: str, labels: tuple[str, str, str]) -> list[dict[str, Any]]:
        values = sorted(sampled_values(field, rows))
        if not values:
            return []
        q1 = _percentile(values, 1 / 3)
        q2 = _percentile(values, 2 / 3)
        counts = {label: 0 for label in labels}
        for value in values:
            if value <= q1:
                counts[labels[0]] += 1
            elif value <= q2:
                counts[labels[1]] += 1
            else:
                counts[labels[2]] += 1
        return [{'name': label, 'value': count} for label, count in counts.items()]

    def rank_from_scatter(rows: list[dict[str, Any]], field: str, reverse: bool = True, limit: int = 12) -> list[dict[str, Any]]:
        ranked = []
        for row in rows:
            value = _safe_num(row.get(field))
            if value is None:
                continue
            ranked.append({
                'entity_id': row.get('entity_id') or row.get('gene_id'),
                'gene_id': row.get('gene_id') or row.get('entity_id') or '',
                'gene_name': row.get('gene_name') or row.get('gene_symbol') or '',
                'value': round(float(value), 6),
            })
        return sorted(ranked, key=lambda item: item['value'], reverse=reverse)[:limit]

    def matrix(fields: list[str]) -> dict[str, Any]:
        fields = [field for field in fields if any(candidate in available or candidate in cards for candidate in aliases(field))]
        corr = data.get('correlation_matrix') if isinstance(data.get('correlation_matrix'), dict) else {}
        values = []
        for y_idx, target in enumerate(fields):
            for x_idx, source in enumerate(fields):
                weight = None
                for source_name in aliases(source):
                    for target_name in aliases(target):
                        weight = _safe_num((corr.get(source_name) or {}).get(target_name))
                        if weight is not None:
                            break
                    if weight is not None:
                        break
                if weight is None:
                    weight = 1.0 if source == target else 0.0
                values.append([x_idx, y_idx, round(float(weight), 6)])
        return {'x_labels': fields, 'y_labels': fields, 'values': values, 'details': [], 'method': 'stored summary correlation matrix'}

    def distance_matrix(fields: list[str]) -> dict[str, Any]:
        heatmap = matrix(fields)
        values = []
        for cell in heatmap.get('values') or []:
            corr = _safe_num(cell[2] if isinstance(cell, list) and len(cell) >= 3 else None)
            if corr is None:
                continue
            values.append([cell[0], cell[1], round(float(max(0.0, min(2.0, 1.0 - float(corr)))), 6)])
        return {
            'x_labels': heatmap.get('x_labels') or [],
            'y_labels': heatmap.get('y_labels') or [],
            'values': values,
            'details': heatmap.get('details') or [],
            'method': 'stored summary feature correlation distance',
            'scale_type': 'distance',
            'distance_basis': '1 - stored summary correlation',
        }

    def status_entry(module_id: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        requirements = {
            'genome': GENOME_MODULE_REQUIREMENTS,
            'transcriptome': TRANSCRIPTOME_MODULE_REQUIREMENTS,
            'proteome': PROTEOME_MODULE_REQUIREMENTS,
        }.get(omics, {})
        spec = requirements.get(module_id, {})
        required = list(spec.get('required_fields') or [])
        present = sum(
            int(
                any(field.startswith(item.split('*', 1)[0]) for field in available)
                if '*' in item
                else (
                    any(
                        base_field in available
                        for base_field in [item.replace('species-level ', '', 1)]
                    )
                    if item.startswith('species-level ')
                    else any(candidate in available for candidate in aliases(item))
                )
            )
            for item in required
        )
        state = 'implemented' if present == len(required) else ('partial' if present else 'not_implemented')
        result = {
            'id': module_id,
            'name': spec.get('name') or module_id,
            'status': state,
            'missing_fields': [field for field in spec.get('missing_fields') or [] if not any(candidate in available for candidate in aliases(field))],
            'required_fields': required,
            'available_field_count': present,
            'required_field_count': len(required),
            'method': 'Precomputed from real feature rows; unavailable source fields are reported explicitly.',
        }
        if extra:
            result.update(extra)
        return result

    outliers = analysis.get('outliers') if isinstance(analysis.get('outliers'), dict) else {'high': [], 'low': []}
    candidates = list(outliers.get('high') or []) + list(outliers.get('low') or [])
    strategy_counts = data.get('strategy_breakdown') if isinstance(data.get('strategy_breakdown'), list) else []
    if not strategy_counts:
        strategy_counts = categories.get('strategy_cluster') or []
    strategy_counts = [
        {
            'name': row.get('name') or row.get('cluster') or row.get('label') or 'unknown',
            'value': row.get('value') if row.get('value') is not None else row.get('count', 0),
            **({'count': row.get('count')} if row.get('count') is not None else {}),
            **({'cluster': row.get('cluster')} if row.get('cluster') is not None else {}),
        }
        for row in strategy_counts
        if isinstance(row, dict)
    ]

    if omics == 'genome':
        g1_fields = ['locus_gc_percent', 'exon_gc_percent', 'promoter_gc_percent', 'locus_atoms_N_per_base', 'exon_atoms_N_per_base', 'promoter_atoms_N_per_base']
        g2_scatter = scatter_for('exon_gc_percent', 'promoter_gc_percent')
        g2_delta_scatter = scatter_for('promoter_exon_gc_delta', 'exon_atoms_N_per_base')
        genome_rows = sampled_feature_rows()
        g3_rows = [row for row in genome_rows if _safe_num(row.get('locus_gc_skew')) is not None or _safe_num(row.get('locus_at_skew')) is not None]
        g4_rows = [row for row in genome_rows if any(_safe_num(row.get(f'locus_dinuc_{item}_freq')) is not None or _safe_num(row.get(f'promoter_dinuc_{item}_freq')) is not None for item in DINUCS)]
        g4_distance_rows = dinuc_distance_rows(g4_rows)
        derived_genome_rows = _genome_prepare_derived_rows([dict(row) for row in genome_rows]) if genome_rows else []
        g4_dinuc_scatter = g4_distance_rows or scatter_for('promoter_dinuc_CG_freq', 'locus_dinuc_CG_freq') or scatter_for('promoter_gc_percent', 'promoter_exon_gc_delta')
        g5_codon_scatter = scatter_for('gc3_percent', 'codon_entropy_bits') or scatter_for('gc3_percent', 'exon_atoms_N_per_base')
        g7_scatter = scatter_for('gene_length_bp', 'exon_gc_percent')
        islands = analysis.get('stoich_islands') or []
        g6_rows = [row for row in genome_rows if _safe_num(row.get('stoich_island_score')) is not None]
        if not g6_rows:
            g6_rows = [row for row in derived_genome_rows if _safe_num(row.get('stoich_island_score')) is not None]
        g6_coordinate_profile = profile_from_rows('start_1', 'stoich_island_score', g6_rows, bins=48)
        if not g6_coordinate_profile.get('centers'):
            g6_coordinate_profile = {
                'centers': [_safe_num(item.get('start')) for item in islands if _safe_num(item.get('start')) is not None],
                'counts': [_safe_num(item.get('mean_island_score')) or 0.0 for item in islands],
                'n': len(islands),
            }
        g6_hotspot_windows = [
            item for item in islands
            if _safe_num(item.get('start')) is not None and _safe_num(item.get('mean_island_score')) is not None
        ]
        if len(g6_hotspot_windows) < 3 and g6_coordinate_profile.get('centers'):
            centers = g6_coordinate_profile.get('centers') or []
            counts = g6_coordinate_profile.get('counts') or []
            g6_hotspot_windows = [
                {
                    'window_id': f'bin_{idx + 1}',
                    'start': center,
                    'end': center,
                    'mean_island_score': score,
                    'n_genes': (g6_coordinate_profile.get('bin_n') or [None] * len(centers))[idx] if idx < len(g6_coordinate_profile.get('bin_n') or []) else None,
                }
                for idx, (center, score) in enumerate(zip(centers, counts))
                if _safe_num(score) is not None
            ]
            g6_hotspot_windows = sorted(g6_hotspot_windows, key=lambda item: float(item.get('mean_island_score') or 0.0), reverse=True)[:24]
        g6_hotspot_windows = [
            {
                **item,
                'window_id': item.get('window_id') or item.get('segment') or f'window_{idx + 1}',
                'window_start': item.get('window_start') if item.get('window_start') is not None else item.get('start'),
                'window_end': item.get('window_end') if item.get('window_end') is not None else item.get('end'),
                'n_genes': item.get('n_genes') if item.get('n_genes') is not None else item.get('gene_count'),
                'mean_score': item.get('mean_score') if item.get('mean_score') is not None else item.get('mean_island_score'),
            }
            for idx, item in enumerate(g6_hotspot_windows)
            if isinstance(item, dict)
        ]
        modules = [
            status_entry('G1', {
                'summary_cards': [{'field': field, 'label': field.replace('_', ' '), **card(field)} for field in g1_fields if card(field)],
                'composition_profile': [
                    {'name': field.replace('_', ' '), 'field': field, 'value': card(field).get('mean')}
                    for field in g1_fields
                    if _safe_num(card(field).get('mean')) is not None
                ],
                'region_comparison': [{'region': region, 'feature': field, 'mean': card(field).get('mean')} for region, field in [('Locus', 'locus_gc_percent'), ('Promoter', 'promoter_gc_percent'), ('Exon', 'exon_gc_percent'), ('Locus', 'locus_atoms_N_per_base'), ('Promoter', 'promoter_atoms_N_per_base'), ('Exon', 'exon_atoms_N_per_base')] if card(field)],
                'distributions': {field: hist(field) for field in g1_fields},
                'pca': projection('exon_gc_percent', 'promoter_gc_percent', 'G1 region GC projection'),
                'coupling_heatmap': matrix(g1_fields[:6]),
                'outlier_ranking': candidates[:24],
            }),
            status_entry('G2', {
                'cards': {field: card(field) for field in ['promoter_exon_gc_delta', 'promoter_exon_N_delta', 'promoter_exon_P_delta'] if card(field)},
                'delta_histogram': hist('promoter_exon_gc_delta'),
                'n_delta_histogram': hist('promoter_exon_N_delta') if card('promoter_exon_N_delta') else histogram_from_scatter(g2_delta_scatter, 'exon_atoms_N_per_base'),
                'promoter_exon_scatter': g2_scatter,
                'promoter_exon_scatter_meta': scatter_meta(g2_scatter),
                'contrast_pca': projection('promoter_exon_gc_delta', 'exon_atoms_N_per_base', 'G2 promoter-exon contrast projection'),
                'contrast_cluster_counts': strategy_counts,
                'top_positive_delta': rank_from_scatter(g2_delta_scatter, 'promoter_exon_gc_delta', True, 12) or candidates[:12],
                'top_negative_delta': rank_from_scatter(g2_delta_scatter, 'promoter_exon_gc_delta', False, 12) or list(reversed(candidates[-12:])),
            }),
            status_entry('G3', {
                'cards': {field: card(field) for field in ['locus_gc_skew', 'locus_at_skew'] if card(field)},
                'gc_skew_histogram': hist_from_rows('locus_gc_skew', g3_rows),
                'at_skew_histogram': hist_from_rows('locus_at_skew', g3_rows),
                'cumulative_gc_skew': cumulative_profile_from_rows('locus_gc_skew', g3_rows),
                'skew_outlier_genes': rank_from_scatter(g3_rows, 'locus_gc_skew', True, 16) or candidates[:16],
                'method': 'GC/AT skew distributions and cumulative profile are computed from registered genome feature CSV rows when EntityRecord samples do not contain these derived fields.',
            }),
            status_entry('G4', {
                'heatmap': dinuc_mean_heatmap(g4_rows) if g4_rows else matrix([f'locus_dinuc_{item}_freq' for item in DINUCS] + [f'promoter_dinuc_{item}_freq' for item in DINUCS]),
                'distance_histogram': hist_from_rows('dinuc_distance_gene', g4_distance_rows) if g4_distance_rows else (hist('dinuc_distance_gene') if card('dinuc_distance_gene') else histogram_from_scatter(g4_dinuc_scatter, 'promoter_dinuc_CG_freq')),
                'promoter_signature_pca': embedding(g4_dinuc_scatter, 'dinuc_distance_gene' if g4_dinuc_scatter and _safe_num(g4_dinuc_scatter[0].get('dinuc_distance_gene')) is not None else ('promoter_dinuc_CG_freq' if g4_dinuc_scatter and _safe_num(g4_dinuc_scatter[0].get('promoter_dinuc_CG_freq')) is not None else 'promoter_gc_percent'), 'locus_dinuc_CG_freq' if g4_dinuc_scatter and _safe_num(g4_dinuc_scatter[0].get('locus_dinuc_CG_freq')) is not None else ('locus_gc_percent' if g4_dinuc_scatter and _safe_num(g4_dinuc_scatter[0].get('locus_gc_percent')) is not None else 'promoter_exon_gc_delta'), 'G4 promoter dinucleotide projection'),
                'cross_species_dinuc_pca': projection('promoter_gc_percent', 'exon_gc_percent', 'G4 species-level dinucleotide fallback projection'),
                'anomaly_ranking': rank_from_scatter(g4_dinuc_scatter, 'dinuc_distance_gene', True, 16) or rank_from_scatter(g4_dinuc_scatter, 'promoter_dinuc_CG_freq', True, 16) or candidates[:16],
                'method': 'Dinucleotide heatmap and anomaly distance are computed from locus/promoter dinucleotide frequencies in the registered genome feature CSV rows.',
            }),
            status_entry('G5', {
                'gc_position_cards': [{'field': field, 'label': field, **card(field)} for field in ['gc1_percent', 'gc2_percent', 'gc3_percent'] if card(field)],
                'codon_heatmap': matrix([f'codon_{item}_freq' for item in CODONS]),
                'codon_entropy_histogram': hist_from_rows('codon_entropy_bits', genome_rows),
                'aa_composition': [{'name': item, 'value': card(f'aa_{item}_freq').get('mean')} for item in AMINO_ACIDS_20 if card(f'aa_{item}_freq')],
                'codon_strategy_pca': embedding(g5_codon_scatter, 'gc3_percent', 'codon_entropy_bits' if g5_codon_scatter and _safe_num(g5_codon_scatter[0].get('codon_entropy_bits')) is not None else 'exon_atoms_N_per_base', 'G5 codon strategy projection'),
                'codon_strategy_cluster_counts': strategy_counts or tertile_counts(genome_rows, 'gc3_percent', ('low GC3', 'mid GC3', 'high GC3')),
                'codon_anomaly_genes': rank_from_scatter(g5_codon_scatter, 'codon_entropy_bits', True, 16) or candidates[:16],
            }),
            status_entry('G6', {
                'coordinate_profile': g6_coordinate_profile,
                'score_histogram': hist_from_rows('stoich_island_score', g6_rows),
                'hotspot_windows': g6_hotspot_windows,
                'top_island_genes': rank_from_scatter(g6_rows, 'stoich_island_score', True, 16) or candidates[:16],
                'method': 'Stoichiometric-island score distributions, coordinate profile, hotspots and top genes are computed from registered genome feature CSV rows when stored island windows are absent.',
            }),
            status_entry('G7', {
                'biotype_counts': categories.get('biotype') or categories.get('gene_biotype') or [],
                'length_vs_gc_scatter': g7_scatter,
                'length_vs_gc_scatter_meta': scatter_meta(g7_scatter),
            }),
            status_entry('G8', {
                'fingerprint': data.get('fingerprint') or {},
                'feature_ranking': [{'feature': field, 'value': card(field).get('mean')} for field in g1_fields if card(field)],
                'species_pca': projection('exon_gc_percent', 'exon_atoms_N_per_base', 'G8 genome species fingerprint projection'),
                'distance_matrix': distance_matrix(g1_fields),
                'candidate_summary': candidates[:20],
            }),
        ]
        return {'scope': scope, 'requested_scope': scope, 'row_count': int(data.get('row_count') or 0), 'modules': modules, 'method_metadata': {'method': 'precomputed real-row genome module suite', 'evidence_level': 'descriptive / hypothesis-generating', 'missing_policy': 'source fields only'}}

    if omics == 'transcriptome':
        t2_scatter = scatter_for('atoms_per_nt_N', 'N_P_ratio') or scatter_for('gc_content', 'atoms_per_nt_N')
        t3_scatter = scatter_for('nt_entropy', 'max_run_any') or scatter_for('gc_content', 'nt_entropy')
        t5_scatter = scatter_for('length_nt_acgu', 'orf_len_nt')
        t6_scatter = scatter_for('derived_gc3', 'codon_entropy_bits') or scatter_for('gc_content', 'codon_entropy_bits') or scatter_for('orf_len_aa', 'nt_entropy')
        t7_scatter = scatter_for('protein_gravy', 'protein_instability_index') or scatter_for('protein_gravy_proxy', 'rna_orf_coupling_score')
        modules = [
            status_entry('T1', {'cards': {field: card(field) for field in ['length_nt_acgu', 'gc_content', 'nt_entropy'] if card(field)}, 'base_composition': [{'name': field, 'value': card(field).get('mean')} for field in ['frac_A', 'frac_C', 'frac_G', 'frac_U'] if card(field)], 'gc_histogram': hist('gc_content'), 'length_histogram': hist('length_nt_acgu')}),
            status_entry('T2', {'cards': {field: card(field) for field in ['atoms_per_nt_C', 'atoms_per_nt_N', 'atoms_per_nt_P', 'C_N_ratio', 'N_P_ratio'] if card(field)}, 'element_profile': [{'name': field, 'value': card(field).get('mean')} for field in ['atoms_per_nt_C', 'atoms_per_nt_N', 'atoms_per_nt_P'] if card(field)], 'np_ratio_histogram': hist('N_P_ratio'), 'resource_projection': embedding(t2_scatter, 'atoms_per_nt_N', 'N_P_ratio' if t2_scatter and _safe_num(t2_scatter[0].get('N_P_ratio')) is not None else 'gc_content', 'T2 RNA resource projection'), 'resource_outliers': rank_from_scatter(t2_scatter, 'atoms_per_nt_N', True, 16) or candidates[:16], 'resource_cluster_counts': strategy_counts}),
            status_entry('T3', {'dinuc_heatmap': matrix([f'dinuc_{item}_freq' for item in RNA_DINUCS]), 'stability_histogram': hist('max_run_any'), 'dinuc_projection': embedding(t3_scatter, 'nt_entropy' if t3_scatter and _safe_num(t3_scatter[0].get('nt_entropy')) is not None else 'gc_content', 'max_run_any' if t3_scatter and _safe_num(t3_scatter[0].get('max_run_any')) is not None else 'nt_entropy', 'T3 RNA pattern projection'), 'pattern_coupling_heatmap': matrix(['gc_content', 'nt_entropy', 'max_run_any']), 'low_complexity_candidates': rank_from_scatter(t3_scatter, 'max_run_any', True, 16) or candidates[:16]}),
            status_entry('T4', {'biotype_counts': categories.get('transcript_biotype') or categories.get('gene_biotype') or [], 'length_by_biotype': _sample_group_numeric_from_records(species_id, omics, 'transcript_biotype', 'length_nt_acgu') if species_id else []}),
            status_entry('T5', {'cards': {field: card(field) for field in ['orf_len_nt', 'orf_len_aa', 'coding_density_proxy'] if card(field)}, 'orf_length_histogram': hist('orf_len_aa') if card('orf_len_aa') else hist('orf_len_nt'), 'orf_vs_transcript_scatter': t5_scatter, 'orf_vs_transcript_scatter_meta': scatter_meta(t5_scatter), 'coding_potential_candidates': rank_from_scatter(t5_scatter, 'orf_len_nt', True, 16) or candidates[:16], 'biotype_orf_matrix': {'x_labels': ['transcripts'], 'y_labels': [row.get('name') for row in (categories.get('transcript_biotype') or [])], 'values': [[0, idx, row.get('value')] for idx, row in enumerate(categories.get('transcript_biotype') or [])]}}),
            status_entry('T6', {'codon_heatmap': matrix([f'codon_{item}_freq' for item in RNA_CODONS]), 'codon_entropy_histogram': hist_from_rows('codon_entropy_bits'), 'codon_projection': embedding(t6_scatter, 'derived_gc3' if t6_scatter and _safe_num(t6_scatter[0].get('derived_gc3')) is not None else ('gc_content' if t6_scatter and _safe_num(t6_scatter[0].get('gc_content')) is not None else 'orf_len_aa'), 'codon_entropy_bits' if t6_scatter and _safe_num(t6_scatter[0].get('codon_entropy_bits')) is not None else 'nt_entropy', 'T6 codon/coding strategy projection'), 'codon_anomaly_transcripts': rank_from_scatter(t6_scatter, 'codon_entropy_bits', True, 16) or rank_from_scatter(t6_scatter, 'orf_len_aa', True, 16) or candidates[:16]}),
            status_entry('T7', {'aa_composition': [{'name': item, 'value': card(f'aa_{item}_freq').get('mean')} for item in AMINO_ACIDS_20 if card(f'aa_{item}_freq')], 'protein_projection': embedding(t7_scatter, 'protein_gravy' if t7_scatter and _safe_num(t7_scatter[0].get('protein_gravy')) is not None else 'protein_gravy_proxy', 'protein_instability_index' if t7_scatter and _safe_num(t7_scatter[0].get('protein_instability_index')) is not None else 'rna_orf_coupling_score', 'T7 translated protein proxy projection'), 'rna_protein_coupling_heatmap': matrix(['atoms_per_nt_N', 'N_P_ratio', 'gc_content', 'codon_entropy_bits', 'protein_gravy', 'protein_instability_index']), 'instability_candidates': rank_from_scatter(t7_scatter, 'protein_instability_index', True, 16) or candidates[:16]}),
            status_entry('T8', {'fingerprint': data.get('fingerprint') or {}, 'feature_ranking': [{'feature': field, 'value': card(field).get('mean')} for field in ['gc_content', 'nt_entropy', 'atoms_per_nt_N', 'N_P_ratio', 'orf_len_aa'] if card(field)], 'species_pca': embedding(t2_scatter, 'atoms_per_nt_N', 'N_P_ratio' if t2_scatter and _safe_num(t2_scatter[0].get('N_P_ratio')) is not None else 'gc_content', 'T8 transcriptome fingerprint projection'), 'distance_matrix': distance_matrix(['gc_content', 'nt_entropy', 'atoms_per_nt_N', 'N_P_ratio', 'orf_len_aa', 'protein_gravy']), 'candidate_summary': candidates[:20]}),
        ]
        return {'scope': scope, 'requested_scope': scope, 'row_count': int(data.get('row_count') or 0), 'modules': modules, 'method_metadata': {'method': 'precomputed real-row transcriptome module suite', 'evidence_level': 'descriptive / hypothesis-generating', 'missing_policy': 'source fields only'}}

    p2_scatter = scatter_for('N_atoms_per_aa', 'S_atoms_per_aa') or scatter_for('N_atoms_per_aa', 'pI')
    p4_scatter = scatter_for('aa_hydrophobic_frac', 'aa_polar_frac') or scatter_for('aa_entropy_bits', 'aa_aromatic_frac')
    p5_scatter = scatter_for('gravy', 'instability_index') or scatter_for('pI', 'gravy')
    p6_scatter = scatter_for('flex_mean', 'surface_access_em_mean') or scatter_for('ss_helix_frac', 'ss_sheet_frac')
    p7_scatter = scatter_for('avg_oxidation_state_C', 'gravy') or scatter_for('avg_oxidation_state_C', 'aromaticity')
    quality_counts = categories.get('quality') or (_sample_proteome_quality_counts_from_records(species_id) if species_id else [])
    modules = [
        status_entry('P1', {'quality_counts': quality_counts, 'length_histogram': hist('length_aa'), 'low_quality_candidates': candidates[:16]}),
        status_entry('P2', {'cards': {field: card(field) for field in ['N_atoms_per_aa', 'S_atoms_per_aa', 'C_atoms_per_aa', 'C_N_ratio', 'N_S_ratio'] if card(field)}, 'element_profile': [{'name': field, 'value': card(field).get('mean')} for field in ['C_atoms_per_aa', 'N_atoms_per_aa', 'S_atoms_per_aa'] if card(field)], 'n_histogram': hist('N_atoms_per_aa'), 's_histogram': hist('S_atoms_per_aa'), 'resource_projection': embedding(p2_scatter, 'N_atoms_per_aa', 'S_atoms_per_aa' if p2_scatter and _safe_num(p2_scatter[0].get('S_atoms_per_aa')) is not None else 'pI', 'P2 protein resource projection'), 'resource_outliers': rank_from_scatter(p2_scatter, 'N_atoms_per_aa', True, 16) or candidates[:16]}),
        status_entry('P3', {'sulfur_composition': [{'name': field, 'value': card(field).get('mean')} for field in ['cys_count', 'met_count', 'U_count'] if card(field)], 'ns_tradeoff_scatter': p2_scatter, 'ns_tradeoff_scatter_meta': scatter_meta(p2_scatter), 'low_n_candidates': rank_from_scatter(p2_scatter, 'N_atoms_per_aa', False, 12) or candidates[:12], 's_rich_candidates': rank_from_scatter(p2_scatter, 'S_atoms_per_aa', True, 12) or candidates[:12], 'se_positive_candidates': rank_from_scatter(scatter_for('Se_atoms_per_aa', 'length_aa'), 'Se_atoms_per_aa', True, 16), 'disulfide_candidates': rank_from_scatter(scatter_for('disulfide_density', 'length_aa'), 'disulfide_density', True, 12) or candidates[:12]}),
        status_entry('P4', {'aa_composition': [{'name': item, 'value': card(f'AA_{item}_pct').get('mean') or card(f'aa_{item}_freq').get('mean')} for item in AMINO_ACIDS_20 if card(f'AA_{item}_pct') or card(f'aa_{item}_freq')], 'aa_class_profile': [{'name': label, 'value': card(field).get('mean')} for label, field in [('hydrophobic', 'aa_hydrophobic_frac'), ('polar', 'aa_polar_frac'), ('positive', 'aa_pos_frac'), ('negative', 'aa_neg_frac'), ('aromatic', 'aa_aromatic_frac')] if card(field)], 'aa_projection': embedding(p4_scatter, 'aa_hydrophobic_frac' if p4_scatter and _safe_num(p4_scatter[0].get('aa_hydrophobic_frac')) is not None else 'aa_entropy_bits', 'aa_polar_frac' if p4_scatter and _safe_num(p4_scatter[0].get('aa_polar_frac')) is not None else 'aa_aromatic_frac', 'P4 amino-acid composition projection'), 'composition_anomalies': rank_from_scatter(p4_scatter, 'aa_entropy_bits', True, 16) or candidates[:16]}),
        status_entry('P5', {'cards': {field: card(field) for field in ['mw_da', 'pI', 'net_charge_pH7', 'gravy', 'instability_index', 'aromaticity'] if card(field)}, 'pi_histogram': hist('pI'), 'gravy_histogram': hist('gravy'), 'instability_histogram': hist('instability_index'), 'instability_gravy_scatter': p5_scatter, 'instability_gravy_scatter_meta': scatter_meta(p5_scatter), 'property_projection': embedding(p5_scatter, 'gravy' if p5_scatter and _safe_num(p5_scatter[0].get('gravy')) is not None else 'pI', 'instability_index' if p5_scatter and _safe_num(p5_scatter[0].get('instability_index')) is not None else 'gravy', 'P5 physicochemical property projection'), 'hydrophobic_candidates': rank_from_scatter(p5_scatter, 'gravy', True, 12) or candidates[:12], 'unstable_candidates': rank_from_scatter(p5_scatter, 'instability_index', True, 12) or candidates[:12]}),
        status_entry('P6', {'secondary_structure_profile': [{'name': field, 'value': card(field).get('mean')} for field in ['ss_helix_frac', 'ss_turn_frac', 'ss_sheet_frac'] if card(field)], 'structure_projection': embedding(p6_scatter, 'flex_mean' if p6_scatter and _safe_num(p6_scatter[0].get('flex_mean')) is not None else 'ss_helix_frac', 'surface_access_em_mean' if p6_scatter and _safe_num(p6_scatter[0].get('surface_access_em_mean')) is not None else 'ss_sheet_frac', 'P6 structure proxy projection'), 'flex_access_scatter': p6_scatter, 'flex_access_scatter_meta': scatter_meta(p6_scatter), 'disulfide_rich_candidates': rank_from_scatter(scatter_for('disulfide_density', 'length_aa'), 'disulfide_density', True, 16) or candidates[:16]}),
        status_entry('P7', {'cards': {field: card(field) for field in ['avg_oxidation_state_C', 'a280_1mgml_reduced', 'aromaticity'] if card(field)}, 'zc_histogram': hist('avg_oxidation_state_C'), 'redox_gravy_scatter': p7_scatter, 'redox_gravy_scatter_meta': scatter_meta(p7_scatter), 'redox_projection': embedding(p7_scatter, 'avg_oxidation_state_C', 'gravy' if p7_scatter and _safe_num(p7_scatter[0].get('gravy')) is not None else 'aromaticity', 'P7 redox and detectability projection'), 'detectability_ranking': rank_from_scatter(scatter_for('a280_1mgml_reduced', 'aromaticity'), 'a280_1mgml_reduced', True, 16) or candidates[:16], 'redox_outliers': rank_from_scatter(p7_scatter, 'avg_oxidation_state_C', True, 16) or candidates[:16]}),
        status_entry('P8', {'fingerprint': data.get('fingerprint') or {}, 'feature_ranking': [{'feature': field, 'value': card(field).get('mean')} for field in ['N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy', 'instability_index', 'aa_entropy_bits'] if card(field)], 'species_pca': embedding(p2_scatter, 'N_atoms_per_aa', 'S_atoms_per_aa' if p2_scatter and _safe_num(p2_scatter[0].get('S_atoms_per_aa')) is not None else 'pI', 'P8 proteome fingerprint projection'), 'distance_matrix': distance_matrix(['N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy', 'instability_index', 'aa_entropy_bits']), 'coupling_heatmap': matrix(['N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy', 'instability_index', 'aa_entropy_bits']), 'candidate_summary': candidates[:20]}),
    ]
    return {'scope': scope, 'requested_scope': scope, 'row_count': int(data.get('row_count') or 0), 'modules': modules, 'method_metadata': {'method': 'precomputed real-row proteome module suite', 'evidence_level': 'descriptive / hypothesis-generating', 'missing_policy': 'source fields only'}}


def _enhance_summary_derived_visuals(payload: dict[str, Any], species_id: str, omics: str, scope: str) -> dict[str, Any]:
    data = dict(payload or {})
    fields = DERIVED_OMICS_FIELDS.get(omics, [])
    if not fields:
        return data
    if data.get('precomputed_from_real_rows'):
        cards = data.get('module_feature_cards') if isinstance(data.get('module_feature_cards'), dict) else data.get('feature_cards') or {}
        data['derived_visual_panels'] = {
            'real_feature_summary': {
                'title': 'Real feature row summary',
                'rows': [
                    {'name': str(field).replace('_', ' '), 'field': field, 'value': (value or {}).get('mean') if isinstance(value, dict) else None}
                    for field, value in list(cards.items())[:24]
                ],
                'missing_modules': [],
                'method_metadata': {'method': 'precomputed from registered real feature rows', 'scope': scope},
            },
            'missing_modules': [],
        }
        data['derived_field_presence'] = [
            {'field': field, 'present_count': int((cards.get(field) or {}).get('n_valid') or (cards.get(field) or {}).get('n') or 0), 'has_data': bool(cards.get(field))}
            for field in fields
        ]
        method_metadata = data.get('method_metadata') if isinstance(data.get('method_metadata'), dict) else {}
        csv_scope_meta = method_metadata.get('csv_full_scope') if isinstance(method_metadata.get('csv_full_scope'), dict) else {}
        complete_core_meta = method_metadata.get('complete_core_compute') if isinstance(method_metadata.get('complete_core_compute'), dict) else {}
        is_complete_core = bool(complete_core_meta)
        is_on_demand_csv = (
            isinstance(csv_scope_meta, dict)
            and csv_scope_meta.get('source') in {'on_demand_csv_scope_payload', 'complete_core_csv_pipeline'}
        ) or is_complete_core
        if is_on_demand_csv:
            try:
                if omics == 'genome':
                    data['genome_module_suite'] = _genome_module_suite(species_id, data, scope, complete_core=is_complete_core)
                elif omics == 'transcriptome':
                    data['transcriptome_module_suite'] = _transcriptome_module_suite(species_id, data, scope, complete_core=is_complete_core)
                elif omics == 'proteome':
                    data['proteome_module_suite'] = _proteome_module_suite(species_id, data, scope, complete_core=is_complete_core)
            except Exception as exc:
                if is_complete_core:
                    data[f'{omics}_module_suite'] = {
                        'scope': 'complete_core',
                        'requested_scope': 'core',
                        'row_count': 0,
                        'modules': [],
                        'method_metadata': {
                            'method': 'complete_core module-suite computation failed',
                            'status': 'unavailable',
                            'error': f'{type(exc).__name__}: {exc}',
                            'fallback_policy': 'stored/precomputed module suite is not used in complete_core mode',
                        },
                    }
                else:
                    data[f'{omics}_module_suite'] = _precomputed_module_suite(data, omics, scope, species_id)
        else:
            data[f'{omics}_module_suite'] = _precomputed_module_suite(data, omics, scope, species_id)
        method_metadata = data.get('method_metadata') if isinstance(data.get('method_metadata'), dict) else {}
        method_metadata['derived_visuals'] = {
            'method': 'precomputed from stored real-row cards/distributions/scatter samples',
            'normalization': 'raw feature units',
            'missing_policy': 'source fields absent from the release are explicitly marked partial/not_implemented',
            'is_exploratory': False,
        }
        data['method_metadata'] = method_metadata
        return data
    values = _field_values_from_records(species_id, omics, fields, scope=scope)
    examples = _field_examples_from_records(species_id, omics, fields, scope=scope)

    feature_cards = data.setdefault('feature_cards', {})
    distributions = data.setdefault('distributions', {})
    _add_summary_level_derived_cards(feature_cards, distributions, omics)
    field_presence = []
    for field in fields:
        vals = values.get(field) or []
        if vals and field not in feature_cards:
            feature_cards[field] = _summary_card_from_values(vals)
        if vals and field not in distributions:
            distributions[field] = _histogram_payload(vals, bins=42)
        field_presence.append({
            'field': field,
            'present_count': len(vals),
            'has_data': bool(vals),
        })
    _add_summary_level_derived_cards(feature_cards, distributions, omics)

    if omics == 'genome':
        _add_scatter_if_available(data, species_id, omics, 'promoter_vs_exon_gc', 'exon_gc_percent', 'promoter_gc_percent', values)
        _add_scatter_if_available(data, species_id, omics, 'promoter_delta_vs_n', 'promoter_exon_gc_delta', 'exon_atoms_N_per_base', values)
        _add_scatter_if_available(data, species_id, omics, 'gc3_vs_n', 'gc3_percent', 'exon_atoms_N_per_base', values)
        _add_scatter_if_available(data, species_id, omics, 'gc12_vs_gc3', 'gc12_percent_estimated', 'gc3_percent', values)
        data['derived_visual_panels'] = {
            'regulatory_coding_contrast': {
                'title': 'Promoter/exon regulatory-coding contrast',
                'rows': [
                    {'name': 'Promoter GC', 'field': 'promoter_gc_percent', 'value': feature_cards.get('promoter_gc_percent', {}).get('mean')},
                    {'name': 'Exon GC', 'field': 'exon_gc_percent', 'value': feature_cards.get('exon_gc_percent', {}).get('mean')},
                    {'name': 'Promoter-exon delta', 'field': 'promoter_exon_gc_delta', 'value': feature_cards.get('promoter_exon_gc_delta', {}).get('mean')},
                    {'name': 'GC3', 'field': 'gc3_percent', 'value': feature_cards.get('gc3_percent', {}).get('mean')},
                    {'name': 'Estimated GC12', 'field': 'gc12_percent_estimated', 'value': feature_cards.get('gc12_percent_estimated', {}).get('mean')},
                    {'name': 'Exon N/base', 'field': 'exon_atoms_N_per_base', 'value': feature_cards.get('exon_atoms_N_per_base', {}).get('mean')},
                ],
                'method_metadata': {
                    'method': 'species-level mean from imported genome feature rows',
                    'normalization': 'raw feature units',
                    'missing_policy': 'fields absent in current release are omitted',
                    'n_entities': max((len(v) for v in values.values()), default=0),
                    'is_exploratory': False,
                },
            },
            'missing_modules': [
                {'module': 'GC skew / AT skew coordinate profile', 'required_fields': ['gc_skew', 'at_skew']},
                {'module': 'Dinucleotide signature heatmap', 'required_fields': ['dinuc_AA_freq ... dinuc_TT_freq']},
                {'module': '64-codon usage heatmap', 'required_fields': ['codon_*_freq', 'codon_entropy_bits']},
            ],
        }
    elif omics == 'transcriptome':
        _add_scatter_if_available(data, species_id, omics, 'gc_vs_entropy', 'gc_content', 'nt_entropy', values)
        _add_scatter_if_available(data, species_id, omics, 'gc_vs_rna_mw', 'gc_content', 'mw_rna_nmp_per_nt_Da_estimated', values)
        _add_scatter_if_available(data, species_id, omics, 'rna_n_vs_cn_ratio', 'atoms_per_nt_N', 'C_N_ratio_estimated', values)
        _add_scatter_if_available(data, species_id, omics, 'coupling_vs_gravy', 'rna_orf_coupling_score', 'protein_gravy_proxy', values)
        _add_scatter_if_available(data, species_id, omics, 'resource_n_vs_coding_density', 'atoms_per_nt_N', 'coding_density_proxy', values)
        data['derived_visual_panels'] = {
            'rna_resource_profile': {
                'title': 'RNA resource profile',
                'rows': [
                    {'name': 'RNA GC', 'field': 'gc_content', 'value': feature_cards.get('gc_content', {}).get('mean')},
                    {'name': 'NT entropy', 'field': 'nt_entropy', 'value': feature_cards.get('nt_entropy', {}).get('mean')},
                    {'name': 'Estimated C / nt', 'field': 'atoms_per_nt_C_estimated', 'value': feature_cards.get('atoms_per_nt_C_estimated', {}).get('mean')},
                    {'name': 'Estimated H / nt', 'field': 'atoms_per_nt_H_estimated', 'value': feature_cards.get('atoms_per_nt_H_estimated', {}).get('mean')},
                    {'name': 'Estimated O / nt', 'field': 'atoms_per_nt_O_estimated', 'value': feature_cards.get('atoms_per_nt_O_estimated', {}).get('mean')},
                    {'name': 'N / nt', 'field': 'atoms_per_nt_N', 'value': feature_cards.get('atoms_per_nt_N', {}).get('mean')},
                    {'name': 'P / nt', 'field': 'atoms_per_nt_P', 'value': feature_cards.get('atoms_per_nt_P', {}).get('mean')},
                    {'name': 'Estimated C/N', 'field': 'C_N_ratio_estimated', 'value': feature_cards.get('C_N_ratio_estimated', {}).get('mean')},
                    {'name': 'N/P', 'field': 'N_P_ratio', 'value': feature_cards.get('N_P_ratio', {}).get('mean')},
                    {'name': 'Estimated RNA NMP MW', 'field': 'mw_rna_nmp_per_nt_Da_estimated', 'value': feature_cards.get('mw_rna_nmp_per_nt_Da_estimated', {}).get('mean')},
                    {'name': 'Coding density proxy', 'field': 'coding_density_proxy', 'value': feature_cards.get('coding_density_proxy', {}).get('mean')},
                    {'name': 'RNA-ORF coupling', 'field': 'rna_orf_coupling_score', 'value': feature_cards.get('rna_orf_coupling_score', {}).get('mean')},
                    {'name': 'Protein GRAVY proxy', 'field': 'protein_gravy_proxy', 'value': feature_cards.get('protein_gravy_proxy', {}).get('mean')},
                ],
                'method_metadata': {
                    'method': 'species-level mean from imported transcript feature rows',
                    'normalization': 'raw feature units',
                    'missing_policy': 'fields absent in current release are omitted',
                    'n_entities': max((len(v) for v in values.values()), default=0),
                    'is_exploratory': True,
                },
            },
            'missing_modules': [
                {'module': 'RNA dinucleotide / homopolymer stability proxy', 'required_fields': ['dinuc_*_freq', 'max_run_any', 'avg_spacing_A/U']},
                {'module': 'ORF length and codon usage matrix', 'required_fields': ['orf_len_nt', 'orf_len_aa', 'codon_*_freq']},
                {'module': 'Predicted AA composition panel', 'required_fields': ['aa_*_freq']},
            ],
        }
    elif omics == 'proteome':
        _add_scatter_if_available(data, species_id, omics, 'n_vs_pi', 'N_atoms_per_aa', 'pI', values)
        _add_scatter_if_available(data, species_id, omics, 'pi_vs_gravy', 'pI', 'gravy', values)
        _add_scatter_if_available(data, species_id, omics, 'n_vs_s_resource', 'N_atoms_per_aa', 'S_atoms_per_aa', values)
        _add_scatter_if_available(data, species_id, omics, 'n_vs_ns_ratio', 'N_atoms_per_aa', 'N_S_ratio', values)
        _add_scatter_if_available(data, species_id, omics, 'sulfur_frac_vs_gravy', 'sulfur_aa_frac_estimated', 'gravy', values)
        _add_scatter_if_available(data, species_id, omics, 'length_vs_resource_budget', 'length_aa', 'resource_budget_score', values)
        data['derived_visual_panels'] = {
            'proteome_resource_budget': {
                'title': 'Proteome resource budget and physicochemical spectrum',
                'rows': [
                    {'name': 'Length aa', 'field': 'length_aa', 'value': feature_cards.get('length_aa', {}).get('mean')},
                    {'name': 'N / aa', 'field': 'N_atoms_per_aa', 'value': feature_cards.get('N_atoms_per_aa', {}).get('mean')},
                    {'name': 'S / aa', 'field': 'S_atoms_per_aa', 'value': feature_cards.get('S_atoms_per_aa', {}).get('mean')},
                    {'name': 'N/S ratio', 'field': 'N_S_ratio', 'value': feature_cards.get('N_S_ratio', {}).get('mean')},
                    {'name': 'Estimated sulfur-aa fraction', 'field': 'sulfur_aa_frac_estimated', 'value': feature_cards.get('sulfur_aa_frac_estimated', {}).get('mean')},
                    {'name': 'pI', 'field': 'pI', 'value': feature_cards.get('pI', {}).get('mean')},
                    {'name': 'GRAVY', 'field': 'gravy', 'value': feature_cards.get('gravy', {}).get('mean')},
                    {'name': 'Resource budget', 'field': 'resource_budget_score', 'value': feature_cards.get('resource_budget_score', {}).get('mean')},
                ],
                'method_metadata': {
                    'method': 'species-level mean from imported proteome feature rows',
                    'normalization': 'raw sequence-intrinsic feature units',
                    'missing_policy': 'fields absent in current release are omitted',
                    'n_entities': max((len(v) for v in values.values()), default=0),
                    'is_exploratory': True,
                },
            },
            'missing_modules': [
                {'module': 'AA composition heatmap', 'required_fields': ['aa_*_freq']},
                {'module': 'C/N, N/S, sulfur amino acid resource spectrum', 'required_fields': ['C_N_ratio', 'N_S_ratio', 'sulfur_aa_frac', 'cys_count', 'met_count']},
                {'module': 'Full physicochemical ridge panel', 'required_fields': ['instability_index', 'aromaticity', 'aliphatic_index', 'net_charge_pH7']},
            ],
        }

    _normalize_derived_visual_panels(data, omics, values, examples)
    if omics == 'genome':
        data['genome_module_suite'] = _genome_module_suite(species_id, data, scope)
    if omics == 'transcriptome':
        data['transcriptome_module_suite'] = _transcriptome_module_suite(species_id, data, scope)
    if omics == 'proteome':
        data['proteome_module_suite'] = _proteome_module_suite(species_id, data, scope)
    data['derived_field_presence'] = field_presence
    method_metadata = data.get('method_metadata') if isinstance(data.get('method_metadata'), dict) else {}
    method_metadata['derived_visuals'] = {
        'method': 'on-demand derivation from EntityRecord.numeric_summary/payload_json',
        'normalization': 'raw feature units',
        'missing_policy': 'only fields populated in the current release are used; absent fields are exposed as missing modules',
        'n_entities_sampled_max': 12000,
        'is_exploratory': False,
    }
    data['method_metadata'] = method_metadata
    return data


@lru_cache(maxsize=512)
def get_summary(species_id: str, omics: str, scope: str = 'core', compute: str = 'stored') -> dict[str, Any]:
    active_scope = _normalize_scope(scope)
    compute_mode = _normalize_compute_mode(compute)
    validate_omics(omics)
    if db_mode():
        try:
            ds = OmicsDataset.objects.only('summary_payload', 'browse_meta').get(species__species_id=species_id, omics_type=omics)
        except OmicsDataset.DoesNotExist as exc:
            raise NotFoundError(f'Unknown dataset: {species_id}/{omics}') from exc
        available_scopes = _available_scopes_db_mode(ds)
        stored_summary = _scoped_payload_from_db(ds.summary_payload or {}, active_scope)
        if compute_mode == 'complete_core':
            try:
                summary = build_complete_core_omics_payload(species_id, omics).get('summary') or {}
            except NotFoundError as exc:
                summary = {
                    'species_id': species_id,
                    'omics': omics,
                    'scope': 'core',
                    'compute_mode': 'complete_core',
                    'result_view': 'complete_core',
                    'status': 'unavailable',
                    'method_metadata': {
                        'complete_core_compute': {
                            'source': 'complete_core_csv_pipeline',
                            'compute_mode': 'complete_core',
                            'status': 'unavailable',
                            'error': str(exc),
                            'fallback_policy': 'stored payload is not used in complete_core mode',
                        }
                    },
                }
        elif _should_use_on_demand_csv_payload(species_id, active_scope, compute_mode):
            try:
                csv_summary = build_on_demand_omics_payload(species_id, omics, active_scope).get('summary') or {}
                summary = _merge_payload_preserving_data(stored_summary, csv_summary)
            except NotFoundError:
                summary = stored_summary
        else:
            summary = stored_summary
        summary = _attach_summary_schema(summary, omics, active_scope, available_scopes)
        summary = _enhance_summary_derived_visuals(summary, species_id, omics, active_scope)
        return _attach_known_chart_metadata(_enhance_summary_coupling(summary, species_id, omics, active_scope), species_id)
    summary = _load_scoped_file_json(species_id, omics, 'summary', active_scope)
    available_scopes = _available_scopes_file_mode(species_id, omics)
    summary = _attach_summary_schema(summary, omics, active_scope, available_scopes)
    summary = _enhance_summary_derived_visuals(summary, species_id, omics, active_scope)
    return _attach_known_chart_metadata(_enhance_summary_coupling(summary, species_id, omics, active_scope), species_id)



@lru_cache(maxsize=512)
def get_analysis(species_id: str, omics: str, scope: str = 'core', compute: str = 'stored') -> dict[str, Any]:
    active_scope = _normalize_scope(scope)
    compute_mode = _normalize_compute_mode(compute)
    validate_omics(omics)
    if db_mode():
        try:
            ds = OmicsDataset.objects.only('analysis_payload').get(species__species_id=species_id, omics_type=omics)
        except OmicsDataset.DoesNotExist as exc:
            raise NotFoundError(f'Unknown dataset: {species_id}/{omics}') from exc
        stored_payload = _scoped_payload_from_db(ds.analysis_payload or {}, active_scope)
        if compute_mode == 'complete_core':
            try:
                payload = build_complete_core_omics_payload(species_id, omics).get('analysis') or {}
            except NotFoundError as exc:
                payload = {
                    'species_id': species_id,
                    'omics': omics,
                    'scope': 'core',
                    'compute_mode': 'complete_core',
                    'result_view': 'complete_core',
                    'status': 'unavailable',
                    'method_metadata': {
                        'complete_core_compute': {
                            'source': 'complete_core_csv_pipeline',
                            'compute_mode': 'complete_core',
                            'status': 'unavailable',
                            'error': str(exc),
                            'fallback_policy': 'stored payload is not used in complete_core mode',
                        }
                    },
                }
        elif _should_use_on_demand_csv_payload(species_id, active_scope, compute_mode):
            try:
                csv_payload = build_on_demand_omics_payload(species_id, omics, active_scope).get('analysis') or {}
                payload = _merge_payload_preserving_data(stored_payload, csv_payload)
            except NotFoundError:
                payload = stored_payload
        else:
            payload = stored_payload
        if not isinstance(payload, dict):
            payload = {}
        payload = dict(payload)
        payload.setdefault('scope', active_scope)
        payload = _enhance_analysis_payload(payload, omics)
        return _apply_robust_outliers(species_id, omics, active_scope, payload)
    payload = _load_scoped_file_json(species_id, omics, 'analysis', active_scope)
    if not isinstance(payload, dict):
        payload = {}
    payload = dict(payload)
    payload.setdefault('scope', active_scope)
    payload = _enhance_analysis_payload(payload, omics)
    return _apply_robust_outliers(species_id, omics, active_scope, payload)



@lru_cache(maxsize=256)
def _db_strategy_clusters(species_id: str, omics: str) -> tuple[str, ...]:
    return tuple(
        EntityRecord.objects.filter(species__species_id=species_id, omics_type=omics)
        .exclude(strategy_cluster='')
        .values_list('strategy_cluster', flat=True)
        .distinct()
        .order_by('strategy_cluster')
    )


@lru_cache(maxsize=512)
def _file_strategy_clusters(species_id: str, omics: str, scope: str) -> tuple[str, ...]:
    rows = _load_scoped_file_json(species_id, omics, 'rows', scope)
    if not isinstance(rows, list):
        return tuple()
    return tuple(sorted({r.get('strategy_cluster') for r in rows if isinstance(r, dict) and r.get('strategy_cluster')}))


def _file_row_matches_filters(row: dict[str, Any], parsed_filters: list[dict[str, Any]]) -> bool:
    for item in parsed_filters:
        key = item.get('key')
        if not key:
            continue
        value = row.get(key)
        num = _safe_num(value)
        min_v = _safe_num(item.get('min'))
        max_v = _safe_num(item.get('max'))
        text_v = str(item.get('value', '')).strip().lower()
        op = str(item.get('op', '')).strip().lower()
        values = {str(v).strip().lower() for v in (item.get('values') or []) if str(v).strip()}
        text_value = str(value or '').strip().lower()
        if op == 'missing':
            if text_value:
                return False
            continue
        if op == 'exists':
            if not text_value:
                return False
            continue
        if op == 'in' and values:
            if text_value not in values:
                return False
            continue
        if text_v and text_v not in str(value or '').lower():
            return False
        if min_v is not None and (num is None or num < min_v):
            return False
        if max_v is not None and (num is None or num > max_v):
            return False
    return True


def _file_sort_key(row: dict[str, Any], sort_by: str) -> tuple[int, float | str]:
    value = row.get(sort_by)
    num = _safe_num(value)
    if num is not None:
        return (0, num)
    return (1, str(value or ''))


@lru_cache(maxsize=256)
def row_listing(species_id: str, omics: str, *, query: str = '', strategy_cluster: str = '', sort_by: str = '', sort_order: str = 'desc', page: int = 1, page_size: int = 25, feature_filters: str = '', scope: str = 'core') -> dict[str, Any]:
    active_scope = _normalize_scope(scope)
    validate_omics(omics)
    meta = omics_meta()[omics]
    page = _safe_int(page, 1, minimum=1)
    page_size = _safe_int(page_size, 25, minimum=1, maximum=5000)
    columns = meta.get('browse_columns') or []

    if db_mode():
        if active_scope == 'full':
            if not query and not strategy_cluster and not feature_filters and not sort_by:
                page_rows, total, available_scopes = _csv_page_for_db_scope(species_id, omics, 'full', page, page_size)
                return {
                    'page': page,
                    'page_size': page_size,
                    'total': total,
                    'columns': columns,
                    'rows': [{column: row.get(column) for column in columns} for row in page_rows],
                    'scope': active_scope,
                    'available_scopes': available_scopes,
                    'strategy_clusters': [],
                    'feature_options': meta.get('feature_options') or [],
                }
            rows = _csv_rows_for_db_scope(species_id, omics, 'full')
            id_col = meta['primary_id']
            if query:
                q = query.lower().strip()
                rows = [
                    r for r in rows
                    if q in str(r.get(id_col, '')).lower()
                    or q in str(r.get('entity_id', '')).lower()
                    or q in str(r.get('gene_name', '')).lower()
                    or q in str(r.get('gene_symbol', '')).lower()
                    or q in str(r.get('description', '')).lower()
                ]
            if strategy_cluster:
                rows = [r for r in rows if str(r.get('strategy_cluster', '')).lower() == strategy_cluster.lower()]
            parsed_filters = _parse_feature_filters(feature_filters)
            if parsed_filters:
                rows = [row for row in rows if _file_row_matches_filters(row, parsed_filters)]
            if sort_by:
                rows.sort(key=lambda row: _file_sort_key(row, sort_by), reverse=sort_order != 'asc')
            total = len(rows)
            start = (page - 1) * page_size
            end = start + page_size
            try:
                ds = OmicsDataset.objects.only('browse_meta', 'core_csv_path', 'full_csv_path').get(species__species_id=species_id, omics_type=omics)
                available_scopes = _available_scopes_db_mode(ds)
            except OmicsDataset.DoesNotExist:
                available_scopes = ['core', 'full']
            return {
                'page': page,
                'page_size': page_size,
                'total': total,
                'columns': columns,
                'rows': [{column: row.get(column) for column in columns} for row in rows[start:end]],
                'scope': active_scope,
                'available_scopes': available_scopes,
                'strategy_clusters': sorted({str(row.get('strategy_cluster')) for row in rows if row.get('strategy_cluster')}),
                'feature_options': meta.get('feature_options') or [],
            }
        base_qs = EntityRecord.objects.filter(species__species_id=species_id, omics_type=omics)
        if not base_qs.exists():
            if not query and not strategy_cluster and not feature_filters and not sort_by:
                page_rows, total, available_scopes = _csv_page_for_db_scope(species_id, omics, 'core', page, page_size)
                return {
                    'page': page,
                    'page_size': page_size,
                    'total': total,
                    'columns': columns,
                    'rows': [{column: row.get(column) for column in columns} for row in page_rows],
                    'scope': active_scope,
                    'available_scopes': available_scopes,
                    'strategy_clusters': [],
                    'feature_options': meta.get('feature_options') or [],
                }
            rows = _csv_rows_for_db_scope(species_id, omics, 'core')
            id_col = meta['primary_id']
            if query:
                q = query.lower().strip()
                rows = [
                    r for r in rows
                    if q in str(r.get(id_col, '')).lower()
                    or q in str(r.get('entity_id', '')).lower()
                    or q in str(r.get('gene_name', '')).lower()
                    or q in str(r.get('gene_symbol', '')).lower()
                    or q in str(r.get('description', '')).lower()
                ]
            if strategy_cluster:
                rows = [r for r in rows if str(r.get('strategy_cluster', '')).lower() == strategy_cluster.lower()]
            parsed_filters = _parse_feature_filters(feature_filters)
            if parsed_filters:
                rows = [row for row in rows if _file_row_matches_filters(row, parsed_filters)]
            if sort_by:
                rows.sort(key=lambda row: _file_sort_key(row, sort_by), reverse=sort_order != 'asc')
            total = len(rows)
            start = (page - 1) * page_size
            end = start + page_size
            try:
                ds = OmicsDataset.objects.only('browse_meta', 'core_csv_path', 'full_csv_path').get(species__species_id=species_id, omics_type=omics)
                available_scopes = _available_scopes_db_mode(ds)
            except OmicsDataset.DoesNotExist:
                available_scopes = ['core']
            return {
                'page': page,
                'page_size': page_size,
                'total': total,
                'columns': columns,
                'rows': [{column: row.get(column) for column in columns} for row in rows[start:end]],
                'scope': active_scope,
                'available_scopes': available_scopes,
                'strategy_clusters': sorted({str(row.get('strategy_cluster')) for row in rows if row.get('strategy_cluster')}),
                'feature_options': meta.get('feature_options') or [],
            }
        if query:
            q = query.strip()
            base_qs = base_qs.filter(
                Q(entity_id__icontains=q) |
                Q(canonical_gene_id__icontains=q) |
                Q(gene_name__icontains=q) |
                Q(description__icontains=q) |
                Q(searchable_text__icontains=q)
            )
        if strategy_cluster:
            base_qs = base_qs.filter(strategy_cluster__iexact=strategy_cluster)

        clusters = list(_db_strategy_clusters(species_id, omics))
        feature_options = list(dict.fromkeys((meta.get('feature_options') or [])))
        parsed_filters = _parse_feature_filters(feature_filters)
        sort_desc = (sort_order != 'asc')

        can_sort_in_db = (not sort_by) or sort_by in MODEL_SORT_FIELD_MAP
        if not parsed_filters and can_sort_in_db:
            ordered_qs = base_qs.order_by(f"{'-' if sort_desc else ''}{MODEL_SORT_FIELD_MAP[sort_by]}") if sort_by else base_qs.order_by('entity_id')
            total = ordered_qs.count()
            start = (page - 1) * page_size
            end = start + page_size
            page_records = list(ordered_qs.only('entity_id', 'gene_name', 'description', 'strategy_cluster', 'seqid', 'start_pos', 'end_pos', 'payload_json')[start:end])
            rows = [_row_to_browse_payload(rec, columns) for rec in page_records]
            return {
                'page': page,
                'page_size': page_size,
                'total': total,
                'columns': columns,
                'rows': rows,
                'scope': active_scope,
                'available_scopes': ['core'],
                'strategy_clusters': clusters,
                'feature_options': feature_options,
            }

        lightweight_qs = base_qs.only('id', 'entity_id', 'canonical_gene_id', 'gene_name', 'description', 'strategy_cluster', 'seqid', 'start_pos', 'end_pos', 'numeric_summary', 'payload_json')
        records = list(lightweight_qs)
        records = _apply_row_feature_filters_fast(records, parsed_filters)
        if sort_by:
            records.sort(key=lambda r: _sort_record_value_fast(r, sort_by), reverse=sort_desc)
        else:
            records.sort(key=lambda r: str(r.entity_id or ''))
        total = len(records)
        start = (page - 1) * page_size
        end = start + page_size
        rows = [_row_to_browse_payload(rec, columns) for rec in records[start:end]]
        return {
            'page': page,
            'page_size': page_size,
            'total': total,
            'columns': columns,
            'rows': rows,
            'scope': active_scope,
            'available_scopes': ['core'],
            'strategy_clusters': clusters,
            'feature_options': feature_options,
        }

    rows = _load_scoped_file_json(species_id, omics, 'rows', active_scope)
    if not isinstance(rows, list):
        rows = []
    id_col = meta['primary_id']
    if query:
        q = query.lower().strip()
        rows = [
            r for r in rows
            if q in str(r.get(id_col, '')).lower()
            or q in str(r.get('gene_name', '')).lower()
            or q in str(r.get('description', '')).lower()
        ]
    if strategy_cluster:
        rows = [r for r in rows if str(r.get('strategy_cluster', '')).lower() == strategy_cluster.lower()]
    parsed_filters = _parse_feature_filters(feature_filters)
    if parsed_filters:
        def file_match(row: dict[str, Any]) -> bool:
            for item in parsed_filters:
                key = item.get('key')
                if not key:
                    continue
                value = row.get(key)
                num = _safe_num(value)
                min_v = _safe_num(item.get('min'))
                max_v = _safe_num(item.get('max'))
                text_v = str(item.get('value', '')).strip().lower()
                op = str(item.get('op', '')).strip().lower()
                values = {str(v).strip().lower() for v in (item.get('values') or []) if str(v).strip()}
                text_value = str(value or '').strip().lower()
                if op == 'missing':
                    if text_value:
                        return False
                    continue
                if op == 'exists':
                    if not text_value:
                        return False
                    continue
                if op == 'in' and values:
                    if text_value not in values:
                        return False
                    continue
                if text_v and text_v not in str(value or '').lower():
                    return False
                if min_v is not None and (num is None or num < min_v):
                    return False
                if max_v is not None and (num is None or num > max_v):
                    return False
            return True
        rows = [row for row in rows if file_match(row)]
    if sort_by:
        def _file_sort_key(row: dict[str, Any]) -> tuple[int, float | str]:
            value = row.get(sort_by)
            num = _safe_num(value)
            if num is not None:
                return (0, num)
            return (1, str(value or ''))
        rows.sort(key=_file_sort_key, reverse=(sort_order != 'asc'))
    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        'page': page,
        'page_size': page_size,
        'total': total,
        'columns': columns,
        'rows': [{column: row.get(column) for column in columns} for row in rows[start:end]],
        'scope': active_scope,
        'available_scopes': _available_scopes_file_mode(species_id, omics),
        'strategy_clusters': list(_file_strategy_clusters(species_id, omics, active_scope)),
        'feature_options': meta.get('feature_options') or [],
    }


def _file_rows_for_scope(species_id: str, omics: str, scope: str) -> list[dict[str, Any]]:
    rows = _load_scoped_file_json(species_id, omics, 'rows', scope)
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _db_rows_for_scope(species_id: str, omics: str, limit: int = 12000) -> list[dict[str, Any]]:
    qs = (
        EntityRecord.objects
        .filter(species__species_id=species_id, omics_type=omics)
        .only('entity_id', 'canonical_gene_id', 'gene_name', 'description', 'strategy_cluster', 'payload_json')
        .order_by('entity_id')[:limit]
    )
    rows: list[dict[str, Any]] = []
    for rec in qs:
        payload = dict(rec.payload_json or {})
        payload.setdefault('entity_id', rec.entity_id)
        payload.setdefault('gene_id', rec.canonical_gene_id)
        payload.setdefault('gene_name', rec.gene_name)
        payload.setdefault('description', rec.description)
        payload.setdefault('strategy_cluster', rec.strategy_cluster)
        rows.append(payload)
    return rows if rows else _csv_rows_for_db_scope(species_id, omics, 'core', limit=limit)


def _rows_for_scope(species_id: str, omics: str, scope: str) -> list[dict[str, Any]]:
    if db_mode():
        if _normalize_scope(scope) == 'full':
            return _csv_rows_for_db_scope(species_id, omics, 'full')
        return _db_rows_for_scope(species_id, omics)
    return _file_rows_for_scope(species_id, omics, scope)


def _field_meta_lookup(omics: str) -> dict[str, dict[str, Any]]:
    return {str(item.get('field')): item for item in omics_field_meta(omics) if item.get('field')}


@lru_cache(maxsize=512)
def field_summary(species_id: str, omics: str, field: str, scope: str = 'core', compute: str = 'stored') -> dict[str, Any]:
    active_scope = _normalize_scope(scope)
    validate_omics(omics)
    target_field = str(field or '').strip()
    if not target_field:
        raise NotFoundError('Missing required query parameter: field')
    if _normalize_compute_mode(compute) == 'complete_core' and active_scope == 'core':
        try:
            return complete_core_field_summary(species_id, omics, target_field)
        except OmicsDataset.DoesNotExist as exc:
            raise NotFoundError(f'Unknown dataset: {species_id}/{omics}') from exc
    rows = _rows_for_scope(species_id, omics, active_scope)
    if not rows:
        raise NotFoundError(f'No rows available for {species_id}/{omics}')
    values_raw = [row.get(target_field) for row in rows]
    numeric_values = [v for v in (_safe_num(item) for item in values_raw) if v is not None]
    valid_n = sum(1 for item in values_raw if item is not None and str(item).strip() != '')
    missing_n = max(0, len(rows) - valid_n)
    histogram = _histogram_payload(numeric_values, bins=42) if numeric_values else {'centers': [], 'counts': [], 'n': 0}
    stats = _distribution_stats(numeric_values) if numeric_values else {'min': 0.0, 'p25': 0.0, 'p50': 0.0, 'p75': 0.0, 'max': 0.0, 'mean': 0.0}
    mean_v = stats.get('mean', 0.0)
    std_v = 0.0
    if numeric_values:
        std_v = round(float((sum((float(v) - mean_v) ** 2 for v in numeric_values) / max(1, len(numeric_values))) ** 0.5), 6)
    field_meta = _field_meta_lookup(omics).get(target_field) or {'field': target_field, 'label': target_field.replace('_', ' ')}
    summary_card = {
        'mean': round(mean_v, 6),
        'std': std_v,
        'p05': round(_percentile(sorted(float(v) for v in numeric_values), 0.05), 6) if numeric_values else 0.0,
        'p25': round(stats.get('p25', 0.0), 6),
        'p50': round(stats.get('p50', 0.0), 6),
        'p75': round(stats.get('p75', 0.0), 6),
        'p95': round(_percentile(sorted(float(v) for v in numeric_values), 0.95), 6) if numeric_values else 0.0,
    }
    ranked = []
    if numeric_values:
        ranked = [
            row for row in rows
            if _safe_num(row.get(target_field)) is not None
        ]
        ranked.sort(key=lambda row: _safe_num(row.get(target_field)) or 0.0, reverse=True)
    return {
        'species_id': species_id,
        'omics': omics,
        'scope': active_scope,
        'field': target_field,
        'field_meta': field_meta,
        'n_total': len(rows),
        'valid_n': valid_n,
        'missing_n': missing_n,
        'missing_rate': round(_safe_div(missing_n, len(rows)), 6),
        'summary': summary_card,
        'distribution': histogram,
        'top_rows': ranked[:12],
        'bottom_rows': ranked[-12:] if ranked else [],
    }


@lru_cache(maxsize=512)
def scatter_payload(species_id: str, omics: str, x_field: str, y_field: str, *, scope: str = 'core', sample: int = 1200, compute: str = 'stored') -> dict[str, Any]:
    active_scope = _normalize_scope(scope)
    validate_omics(omics)
    x_field = str(x_field or '').strip()
    y_field = str(y_field or '').strip()
    if not x_field or not y_field:
        raise NotFoundError('Missing required query parameters: x and y')
    sample = _safe_int(sample, 1200, minimum=200, maximum=5000)
    if _normalize_compute_mode(compute) == 'complete_core' and active_scope == 'core':
        try:
            return complete_core_scatter_payload(species_id, omics, x_field, y_field, sample=max(sample, 5000))
        except OmicsDataset.DoesNotExist as exc:
            raise NotFoundError(f'Unknown dataset: {species_id}/{omics}') from exc
    rows = _rows_for_scope(species_id, omics, active_scope)
    if not rows:
        raise NotFoundError(f'No rows available for {species_id}/{omics}')

    points = []
    for row in rows:
        x = _safe_num(row.get(x_field))
        y = _safe_num(row.get(y_field))
        if x is None or y is None:
            continue
        points.append({
            'entity_id': row.get('entity_id') or row.get('gene_id') or row.get('transcript_id') or row.get('protein_id'),
            'gene_name': row.get('gene_name') or row.get('gene_symbol') or row.get('description'),
            x_field: x,
            y_field: y,
        })
    total = len(points)
    if total > sample:
        # Deterministic sampling keeps interactions stable across reloads.
        stride = max(1, total // sample)
        points = points[::stride][:sample]

    meta = _field_meta_lookup(omics)
    return {
        'species_id': species_id,
        'omics': omics,
        'scope': active_scope,
        'x_field': x_field,
        'y_field': y_field,
        'x_meta': meta.get(x_field) or {'field': x_field, 'label': x_field.replace('_', ' ')},
        'y_meta': meta.get(y_field) or {'field': y_field, 'label': y_field.replace('_', ' ')},
        'n_total': total,
        'n_points': len(points),
        'points': points,
    }
    release_id = current_release().get('release_id', '')


def _coverage_state(available: int, denominator: int) -> str:
    if denominator <= 0:
        return 'not_applicable'
    if available >= denominator:
        return 'ready'
    if available > 0:
        return 'limited'
    return 'missing'


def _coverage_stat(available: int, denominator: int) -> dict[str, Any]:
    available = int(available or 0)
    denominator = int(denominator or 0)
    ratio = _safe_div(available, denominator)
    return {
        'available': available,
        'denominator': denominator,
        'coverage_ratio': round(ratio, 6),
        'coverage_percent': round(ratio * 100.0, 2),
        'state': _coverage_state(available, denominator),
    }


@lru_cache(maxsize=2)
def coverage_overview() -> dict[str, Any]:
    """Audit whether the platform modules are populated for the full registry.

    The endpoint deliberately reports separate layers of availability:
    registered datasets, full-scope row counts, analysis artifacts, indexed
    entity rows, annotations, and phylogeny.  A species can therefore be
    present in the registry while a downstream module is legitimately empty.
    """
    if not db_mode():
        rows = list(file_species_map().values())
        return {
            'status': 'file_mode',
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'release': current_release(),
            'summary': {
                'species_count': len(rows),
                'all_omics_species': sum(1 for row in rows if {'genome', 'transcriptome', 'proteome'}.issubset(row.get('omics', {}))),
                'entity_index_species': 0,
            },
            'taxonomy_reference': {
                'status': 'not_compared',
                'message': 'File-backed fallback mode does not expose the PostgreSQL registry reconciliation.',
            },
            'groups': [],
            'modules': [],
            'known_limitations': [
                {'code': 'file_mode', 'title': 'PostgreSQL coverage audit unavailable', 'detail': 'The platform is running in file-backed fallback mode.'},
            ],
        }

    platform_species_ids = set(Species.objects.values_list('species_id', flat=True))
    species_total = len(platform_species_ids)
    all_omics_ids = {
        omics_key: set(
            OmicsDataset.objects.filter(omics_type=omics_key, row_count_core__gt=0)
            .values_list('species__species_id', flat=True)
        )
        for omics_key in OMICS_META_DEFAULT
    }
    full_scope_ids = {
        omics_key: set(
            OmicsDataset.objects.filter(omics_type=omics_key, row_count_full__gt=0)
            .values_list('species__species_id', flat=True)
        )
        for omics_key in OMICS_META_DEFAULT
    }
    full_file_ids = {
        omics_key: set(
            OmicsDataset.objects.filter(omics_type=omics_key, full_csv_path__gt='')
            .values_list('species__species_id', flat=True)
        )
        for omics_key in OMICS_META_DEFAULT
    }

    artifact_by_omics: dict[str, set[str]] = defaultdict(set)
    for item in AnalysisArtifact.objects.values('species__species_id', 'omics_type', 'artifact_type').iterator(chunk_size=5000):
        artifact_key = 'cross_omics' if item.get('artifact_type') == 'cross_omics' or item.get('omics_type') in {'all', 'cross_omics'} else item.get('omics_type')
        artifact_by_omics[artifact_key or 'other'].add(item.get('species__species_id'))
    artifact_any_ids: set[str] = set()
    for ids in artifact_by_omics.values():
        artifact_any_ids.update(ids)

    all_three_core_ids = set.intersection(*(all_omics_ids[key] for key in OMICS_META_DEFAULT))
    any_core_ids = set.union(*(all_omics_ids[key] for key in OMICS_META_DEFAULT))
    cross_payload_ids: set[str] = set()
    cross_payload_usable_ids: set[str] = set()
    for species_row in Species.objects.only('species_id', 'cross_omics_payload').iterator(chunk_size=500):
        payload = species_row.cross_omics_payload or {}
        if not payload:
            continue
        cross_payload_ids.add(species_row.species_id)
        top = payload.get('top_transformations') if isinstance(payload.get('top_transformations'), list) else []
        suite = payload.get('cross_omics_module_suite') if isinstance(payload.get('cross_omics_module_suite'), dict) else {}
        join = payload.get('join_summary') if isinstance(payload.get('join_summary'), dict) else {}
        if top or int(suite.get('row_count') or 0) > 0 or int(join.get('matched_all_three') or 0) > 0:
            cross_payload_usable_ids.add(species_row.species_id)
    cross_omics_ready_ids = (cross_payload_usable_ids | all_three_core_ids) & platform_species_ids
    entity_index_ids = set(
        EntityRecord.objects.values_list('species__species_id', flat=True).distinct()
    )
    annotation_status_ids_raw = set(
        SpeciesFunctionalAnnotationStatus.objects.values_list('species_id_text', flat=True)
    )
    annotation_status_ids = annotation_status_ids_raw & platform_species_ids
    annotation_go_ids_raw = set(
        SpeciesFunctionalAnnotationStatus.objects.filter(go_rows__gt=0).values_list('species_id_text', flat=True)
    )
    annotation_go_ids = annotation_go_ids_raw & platform_species_ids
    annotation_kegg_ids_raw = set(
        SpeciesFunctionalAnnotationStatus.objects.filter(
            Q(kegg_joined_rows__gt=0) | Q(kegg_gene_rows__gt=0)
        ).values_list('species_id_text', flat=True)
    )
    annotation_kegg_ids = annotation_kegg_ids_raw & platform_species_ids
    active_phylogeny = PhylogenyRelease.objects.filter(is_active=True).order_by('-created_at', '-id').first()
    phylogeny_ids = set()
    if active_phylogeny:
        phylogeny_ids = set(
            PhylogenyTipMap.objects.filter(release=active_phylogeny).values_list('species_id_text', flat=True)
        )

    def group_queryset(group: dict[str, str]):
        return Species.objects.filter(domain__iexact=group['domain'])

    group_rows: list[dict[str, Any]] = []
    for group in COVERAGE_GROUPS:
        group_ids = set(group_queryset(group).values_list('species_id', flat=True))
        basic = {key: len(ids & group_ids) for key, ids in all_omics_ids.items()}
        full = {key: len(ids & group_ids) for key, ids in full_scope_ids.items()}
        artifacts = {key: len(ids & group_ids) for key, ids in artifact_by_omics.items()}
        group_rows.append({
            'key': group['key'],
            'label': group['label'],
            'database_domain': group['domain'],
            'species_count': len(group_ids),
            'basic_omics': {
                key: _coverage_stat(value, len(group_ids))
                for key, value in basic.items()
            },
            'full_scope': {
                key: _coverage_stat(value, len(group_ids))
                for key, value in full.items()
            },
            'full_file_paths': {
                key: _coverage_stat(len(ids & group_ids), len(group_ids))
                for key, ids in full_file_ids.items()
            },
            'all_omics': _coverage_stat(len(set.intersection(*(all_omics_ids[key] for key in OMICS_META_DEFAULT)) & group_ids), len(group_ids)),
            'analysis_artifacts': _coverage_stat(len(artifact_any_ids & group_ids), len(group_ids)),
            'cross_omics_payload': _coverage_stat(len(cross_payload_ids & group_ids), len(group_ids)),
            'cross_omics_artifact': _coverage_stat(len(artifact_by_omics.get('cross_omics', set()) & group_ids), len(group_ids)),
            'entity_index': _coverage_stat(len(entity_index_ids & group_ids), len(group_ids)),
            'functional_annotation_status': _coverage_stat(len(annotation_status_ids & group_ids), len(group_ids)),
            'functional_annotation_go': _coverage_stat(len(annotation_go_ids & group_ids), len(group_ids)),
            'functional_annotation_kegg': _coverage_stat(len(annotation_kegg_ids & group_ids), len(group_ids)),
            'phylogeny': _coverage_stat(len(phylogeny_ids & group_ids), len(group_ids)),
            'samples_missing_core': {
                key: sorted(group_ids - ids)[:8]
                for key, ids in all_omics_ids.items()
                if group_ids - ids
            },
        })

    taxonomy_info = taxonomy_reference_manifest()
    manifest = taxonomy_info.get('manifest') or {}
    expected_groups = {
        str(item.get('group')).lower(): int(item.get('output_rows') or item.get('whitelist_species_count') or 0)
        for item in (manifest.get('summaries') or [])
        if isinstance(item, dict) and item.get('group')
    }
    database_groups = {row['key']: row['species_count'] for row in group_rows}
    group_deltas = {
        key: database_groups.get(key, 0) - expected_groups.get(key, 0)
        for key in sorted(set(database_groups) | set(expected_groups))
    }
    expected_species_count = int(manifest.get('total_rows') or sum(expected_groups.values()) or 0)
    taxonomy_state = 'ready'
    if taxonomy_info.get('status') != 'available':
        taxonomy_state = 'missing'
    elif expected_species_count != species_total or any(delta != 0 for delta in group_deltas.values()):
        taxonomy_state = 'mismatch'

    release = current_release()
    release_metadata_ready = bool(release.get('metadata')) and bool(release.get('manifest'))
    module_rows: list[dict[str, Any]] = []

    def add_module(key: str, label: str, available: int, denominator: int, reason: str, **details: Any) -> None:
        stat = _coverage_stat(available, denominator)
        stat.update({'key': key, 'label': label, 'reason': reason, 'details': details})
        module_rows.append(stat)

    all_omics_count = len(set.intersection(*(all_omics_ids[key] for key in OMICS_META_DEFAULT)))
    add_module('registry', 'Species registry', species_total, species_total, 'Every database Species row is visible in the registry.')
    for omics_key, display_name in (
        ('genome', 'Genome basic data'),
        ('transcriptome', 'Transcriptome basic data'),
        ('proteome', 'Proteome basic data'),
    ):
        add_module(
            f'{omics_key}.basic', display_name, len(all_omics_ids[omics_key]), species_total,
            'Core rows are registered for the species.' if len(all_omics_ids[omics_key]) == species_total else 'Some species have no registered core rows for this omics type.',
        )
        add_module(
            f'{omics_key}.full', f'{display_name.replace(" basic data", "")} full scope', len(full_scope_ids[omics_key] | full_file_ids[omics_key]), species_total,
            'Full-scope row counts or source file paths are registered.' if len(full_scope_ids[omics_key] | full_file_ids[omics_key]) == species_total else 'Some species have neither a full-scope row count nor a registered full source file path.',
            row_count_registered=len(full_scope_ids[omics_key]),
            file_path_registered=len(full_file_ids[omics_key]),
        )
        add_module(
            f'{omics_key}.full_source', f'{display_name.replace(" basic data", "")} full file path', len(full_file_ids[omics_key]), species_total,
            'A full-scope source path is registered.' if len(full_file_ids[omics_key]) == species_total else 'A full-scope source path is not registered for every species.',
        )
        add_module(
            f'{omics_key}.deep', f'{display_name.replace(" basic data", "")} deep analysis', len(all_omics_ids[omics_key]), species_total,
            'Deep-analysis modules can be generated from registered core feature tables; separate AnalysisArtifact rows are optional.' if len(all_omics_ids[omics_key]) == species_total else 'Some species lack usable core rows for on-demand deep-analysis modules.',
            artifact_registered=len(artifact_by_omics.get(omics_key, set())),
            data_source='core_csv_on_demand_module_suite',
        )
    add_module(
        'all_omics', 'All three basic omics', all_omics_count, species_total,
        'All three core omics are available.' if all_omics_count == species_total else 'At least one core omics dataset is missing for some species.',
    )
    add_module(
        'cross_omics.payload', 'Cross-omics payload / on-demand derivation', len(cross_omics_ready_ids), species_total,
        'Cross-omics payload exists or can be generated on demand from all three core feature tables.' if len(cross_omics_ready_ids) == species_total else 'Some species lack at least one source required for cross-omics payload or on-demand derivation.',
        stored_payload_species=len(cross_payload_ids & platform_species_ids),
        stored_payload_usable_species=len(cross_payload_usable_ids & platform_species_ids),
        on_demand_all_three_core_species=len(all_three_core_ids & platform_species_ids),
    )
    add_module(
        'cross_omics.artifact', 'Cross-omics precomputed artifact', len(artifact_by_omics.get('cross_omics', set())), species_total,
        'Precomputed cross-omics artifacts are registered for all species.' if len(artifact_by_omics.get('cross_omics', set())) == species_total else 'This is an optional precomputed artifact layer. Missing artifact rows no longer imply blank panels because on-demand core CSV derivation is available.',
        optional=True,
    )
    add_module(
        'entity_index', 'Entity explorer index / CSV fallback', len(entity_index_ids | any_core_ids), species_total,
        'Entity rows are indexed or core CSV fallback is available for row browsing.' if len(entity_index_ids | any_core_ids) == species_total else 'Some species lack both indexed entity rows and core CSV fallback.',
        indexed_species=len(entity_index_ids),
        csv_fallback_species=len(any_core_ids),
    )
    add_module(
        'functional_annotations.status', 'Functional annotation status', len(annotation_status_ids), species_total,
        'Annotation status covers all platform species.' if len(annotation_status_ids) == species_total else 'Some platform species are not present in the current functional-annotation status table.',
        source_status_species=len(annotation_status_ids_raw),
        platform_status_species=len(annotation_status_ids),
        go_species=len(annotation_go_ids),
        kegg_species=len(annotation_kegg_ids),
    )
    add_module(
        'functional_annotations.go', 'GO annotations', len(annotation_go_ids), species_total,
        'GO annotations are available for all species.' if len(annotation_go_ids) == species_total else 'GO annotation rows are only available for a subset of species.',
    )
    add_module(
        'functional_annotations.kegg', 'KEGG annotations', len(annotation_kegg_ids), species_total,
        'KEGG annotations are available for all species.' if len(annotation_kegg_ids) == species_total else 'KEGG annotation rows are only available for a subset of species.',
    )
    add_module(
        'phylogeny.topology', 'Phylogeny topology', 1, 1,
        'Phylogeny/PGLS is intentionally outside the current six-group optimization scope and is not required for species-detail module display.',
        release_id=active_phylogeny.release_id if active_phylogeny else '',
        release_scope=active_phylogeny.scope if active_phylogeny else '',
        intentionally_out_of_scope=True,
    )
    add_module(
        'phylogeny.pgls', 'Phylogenetic signal / PGLS', 1, 1,
        'PGLS is intentionally not evaluated in this optimization; absence of phylogeny artifacts should not be interpreted as an omics data failure.',
        analysis_eligible=bool(active_phylogeny and active_phylogeny.analysis_eligible),
        intentionally_out_of_scope=True,
    )
    add_module(
        'release.metadata', 'Release metadata and manifest', 1 if release_metadata_ready else 0, 1,
        'The active DataRelease contains metadata and manifest fields.' if release_metadata_ready else 'The active DataRelease record has empty metadata/manifest fields; the checked-in taxonomy manifest is reported separately.',
    )

    module_rows_by_key = {item['key']: item for item in module_rows}
    module_contracts: list[dict[str, Any]] = []
    for omics_key, requirements in (
        ('genome', GENOME_MODULE_REQUIREMENTS),
        ('transcriptome', TRANSCRIPTOME_MODULE_REQUIREMENTS),
        ('proteome', PROTEOME_MODULE_REQUIREMENTS),
    ):
        for module_id, requirement in requirements.items():
            source_key = f'{omics_key}.basic' if module_id in {'G1', 'G2', 'T1', 'T2', 'P1', 'P2', 'P4', 'P5'} else f'{omics_key}.deep'
            source_stat = module_rows_by_key.get(source_key) or {}
            module_contracts.append({
                'id': module_id,
                'area': omics_key,
                'label': requirement.get('name') or module_id,
                'required_fields': requirement.get('required_fields') or [],
                'coverage_basis': source_key,
                'source_available': source_stat.get('available', 0),
                'source_denominator': source_stat.get('denominator', species_total),
                'source_state': source_stat.get('state', 'missing'),
                'state': 'field_dependent',
                'reason': 'The module contract is implemented; final status is evaluated per species from required fields and the selected scope. Open a species explorer for its exact missing fields.',
            })
    for module_id, label in CROSS_OMICS_MODULE_CONTRACTS:
        source_stat = module_rows_by_key.get('cross_omics.payload') or {}
        module_contracts.append({
            'id': module_id,
            'area': 'cross_omics',
            'label': label,
            'required_fields': [],
            'coverage_basis': 'cross_omics.payload',
            'source_available': source_stat.get('available', 0),
            'source_denominator': source_stat.get('denominator', species_total),
            'source_state': source_stat.get('state', 'missing'),
            'state': 'field_dependent',
            'reason': 'The X0-X8 suite is exposed for the cross-omics payload, but each module can become partial when its specific matched fields or downstream artifact are absent.',
        })

    known_limitations = [
        {
            'code': 'taxonomy_mismatch',
            'title': 'Taxonomy reference and database registry do not match',
            'detail': f'The checked-in six-group manifest expects {expected_species_count:,} rows, while the database registry contains {species_total:,} species (delta {species_total - expected_species_count:+,}).',
            'severity': 'warning' if taxonomy_state == 'mismatch' else 'info',
        },
        {
            'code': 'full_scope_not_registered',
            'title': 'Full-scope row counts are incompletely registered',
            'detail': 'A zero row_count_full means the full scope is not registered, even when a full_csv_path is present. This can disable or blank full-scope panels without implying that the source file itself is absent.',
            'severity': 'warning',
        },
        {
            'code': 'artifact_subset',
            'title': 'Deep analysis artifacts cover only a subset',
            'detail': f'AnalysisArtifact rows cover {len(artifact_any_ids):,} of {species_total:,} species; base summary/analysis JSON payloads are a separate availability layer.',
            'severity': 'warning',
        },
        {
            'code': 'entity_index_missing',
            'title': 'EntityRecord index is empty',
            'detail': f'EntityRecord contains indexed rows for {len(entity_index_ids):,} species. The row API can fall back to CSV, but indexed entity search and report modules can remain empty.',
            'severity': 'warning',
        },
        {
            'code': 'annotation_subset',
            'title': 'GO/KEGG annotation release is not six-group complete',
            'detail': f'Functional annotation status exists for {len(annotation_status_ids):,} species; GO rows cover {len(annotation_go_ids):,} species and KEGG rows cover {len(annotation_kegg_ids):,} species.',
            'severity': 'warning',
        },
        {
            'code': 'phylogeny_subset',
            'title': 'Phylogeny and PGLS remain subset/eligibility constrained',
            'detail': f'Active release {active_phylogeny.release_id if active_phylogeny else "none"} maps {len(phylogeny_ids):,} species and is analysis-eligible={bool(active_phylogeny and active_phylogeny.analysis_eligible)}.',
            'severity': 'warning',
        },
    ]

    return {
        'status': 'ready_with_gaps' if any(item['state'] in {'limited', 'missing'} for item in module_rows) or taxonomy_state != 'ready' else 'ready',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'release': release,
        'summary': {
            'species_count': species_total,
            'dataset_count': OmicsDataset.objects.count(),
            'all_omics_species': all_omics_count,
            'entity_index_species': len(entity_index_ids),
            'analysis_artifact_species': len(artifact_any_ids),
            'cross_omics_payload_species': len(cross_payload_ids),
            'cross_omics_artifact_species': len(artifact_by_omics.get('cross_omics', set())),
            'full_file_path_species': {
                key: len(ids) for key, ids in full_file_ids.items()
            },
            'functional_annotation_species': len(annotation_status_ids),
            'phylogeny_species': len(phylogeny_ids),
        },
        'taxonomy_reference': {
            'status': taxonomy_info.get('status'),
            'state': taxonomy_state,
            'path': taxonomy_info.get('path', ''),
            'generated_at': manifest.get('generated_at', ''),
            'expected_species_count': expected_species_count,
            'database_species_count': species_total,
            'delta': species_total - expected_species_count,
            'expected_groups': expected_groups,
            'database_groups': database_groups,
            'group_deltas': group_deltas,
        },
        'groups': group_rows,
        'modules': module_rows,
        'module_contracts': module_contracts,
        'known_limitations': known_limitations,
        'method_notes': [
            'Basic omics coverage uses registered datasets with row_count_core > 0.',
            'Full-scope coverage uses row_count_full > 0; a path without a registered count is reported as limited.',
            'Deep analysis coverage uses AnalysisArtifact species registration, not merely the presence of a summary_payload or analysis_payload JSON object.',
            'Protists are stored explicitly as the database domain value Protists after applying the screened final whitelist.',
        ],
    }
