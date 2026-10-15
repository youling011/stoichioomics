from __future__ import annotations

from collections import defaultdict
import csv
from functools import lru_cache
import math
import re
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db.models import Q

from . import services
from . import function_annotations
from . import id_mapping
from .models import EntityRecord, OmicsDataset, Species


OMICS_ORDER = ('genome', 'transcriptome', 'proteome')

CORE_FIELDS: dict[str, list[dict[str, Any]]] = {
    'genome': [
        {'field': 'gene_length_bp', 'aliases': ['gene_length_bp', 'length_bp', 'gene_span_bp'], 'level': 'raw_feature'},
        {'field': 'exon_gc_percent', 'aliases': ['exon_gc_percent', 'gc_percent', 'gene_gc_percent'], 'level': 'raw_feature'},
        {'field': 'promoter_gc_percent', 'aliases': ['promoter_gc_percent'], 'level': 'raw_feature'},
        {'field': 'promoter_exon_gc_delta', 'aliases': ['promoter_exon_gc_delta', 'gc_delta_promoter_minus_exon'], 'level': 'derived_proxy'},
        {'field': 'gc3_percent', 'aliases': ['gc3_percent', 'GC3_percent', 'gc3'], 'level': 'raw_feature'},
        {'field': 'atoms_per_bp_C', 'aliases': ['atoms_per_bp_C', 'exon_atoms_C_per_base', 'C_atoms_per_bp'], 'level': 'raw_feature'},
        {'field': 'atoms_per_bp_N', 'aliases': ['atoms_per_bp_N', 'exon_atoms_N_per_base', 'N_atoms_per_bp'], 'level': 'raw_feature'},
        {'field': 'atoms_per_bp_P', 'aliases': ['atoms_per_bp_P', 'exon_atoms_P_per_base', 'P_atoms_per_bp'], 'level': 'raw_feature'},
        {'field': 'codon_usage_deviation', 'aliases': ['codon_usage_deviation', 'codon_bias_score', 'codon_entropy_bits'], 'level': 'derived_proxy'},
        {'field': 'stoich_island_score', 'aliases': ['stoich_island_score'], 'level': 'derived_proxy'},
        {'field': 'strategy_cluster', 'aliases': ['strategy_cluster'], 'level': 'candidate_label', 'numeric': False},
    ],
    'transcriptome': [
        {'field': 'length_nt', 'aliases': ['length_nt', 'transcript_length_nt', 'length'], 'level': 'raw_feature'},
        {'field': 'gc_content', 'aliases': ['gc_content', 'gc_percent_display', 'gc_percent'], 'level': 'raw_feature'},
        {'field': 'nt_entropy', 'aliases': ['nt_entropy', 'entropy'], 'level': 'derived_proxy'},
        {'field': 'atoms_per_nt_C', 'aliases': ['atoms_per_nt_C', 'C_atoms_per_nt'], 'level': 'raw_feature'},
        {'field': 'atoms_per_nt_N', 'aliases': ['atoms_per_nt_N', 'N_atoms_per_nt'], 'level': 'raw_feature'},
        {'field': 'atoms_per_nt_P', 'aliases': ['atoms_per_nt_P', 'P_atoms_per_nt'], 'level': 'raw_feature'},
        {'field': 'orf_len_nt', 'aliases': ['orf_len_nt', 'orf_length_nt'], 'level': 'derived_proxy'},
        {'field': 'orf_valid_flag', 'aliases': ['orf_valid_flag'], 'level': 'derived_proxy', 'numeric': False},
        {'field': 'codon_bias_score', 'aliases': ['codon_bias_score', 'codon_usage_deviation'], 'level': 'derived_proxy'},
        {'field': 'rna_orf_coupling_score', 'aliases': ['rna_orf_coupling_score', 'coding_density_proxy'], 'level': 'derived_proxy'},
        {'field': 'protein_proxy_gravy', 'aliases': ['protein_proxy_gravy', 'protein_gravy_proxy'], 'level': 'derived_proxy'},
        {'field': 'protein_proxy_instability', 'aliases': ['protein_proxy_instability', 'protein_instability_proxy'], 'level': 'derived_proxy'},
    ],
    'proteome': [
        {'field': 'length_aa', 'aliases': ['length_aa', 'protein_length', 'length'], 'level': 'raw_feature'},
        {'field': 'C_atoms_per_aa', 'aliases': ['C_atoms_per_aa', 'atoms_per_aa_C'], 'level': 'raw_feature'},
        {'field': 'N_atoms_per_aa', 'aliases': ['N_atoms_per_aa', 'atoms_per_aa_N'], 'level': 'raw_feature'},
        {'field': 'S_atoms_per_aa', 'aliases': ['S_atoms_per_aa', 'atoms_per_aa_S'], 'level': 'raw_feature'},
        {'field': 'N_S_ratio', 'aliases': ['N_S_ratio', 'N_to_S_ratio'], 'level': 'derived_proxy'},
        {'field': 'pI', 'aliases': ['pI', 'isoelectric_point'], 'level': 'derived_proxy'},
        {'field': 'net_charge_pH7', 'aliases': ['net_charge_pH7', 'net_charge'], 'level': 'derived_proxy'},
        {'field': 'gravy', 'aliases': ['gravy', 'GRAVY'], 'level': 'derived_proxy'},
        {'field': 'instability_index', 'aliases': ['instability_index'], 'level': 'derived_proxy'},
        {'field': 'aromaticity', 'aliases': ['aromaticity'], 'level': 'derived_proxy'},
        {'field': 'possible_disulfides', 'aliases': ['possible_disulfides', 'disulfide_proxy'], 'level': 'derived_proxy'},
        {'field': 'avg_oxidation_state_C', 'aliases': ['avg_oxidation_state_C', 'carbon_oxidation_state'], 'level': 'derived_proxy'},
        {'field': 'resource_budget_score', 'aliases': ['resource_budget_score'], 'level': 'derived_proxy'},
    ],
}

ID_KEYS = {
    'entity_id', 'gene_id', 'canonical_gene_id', 'gene_name', 'gene_symbol', 'symbol', 'locus_tag',
    'transcript_id', 'protein_id', 'ensembl_gene_id', 'secondary_id',
}

MODULE_LABELS = {
    'G1': 'Genome composition and stoichiometric profile',
    'G2': 'Promoter-gene body contrast',
    'G3': 'GC/AT skew asymmetry',
    'G4': 'Dinucleotide genomic signature and anomaly',
    'G5': 'CDS codon and GC3 strategy',
    'G6': 'Stoichiometric island / hotspot',
    'G7': 'Genome architecture context',
    'G8': 'Genome fingerprint / trade-off context',
    'T1': 'RNA composition overview',
    'T2': 'RNA elemental budget and resource outliers',
    'T3': 'RNA pattern, low-complexity and stability proxy',
    'T4': 'Transcript biotype context',
    'T5': 'ORF and coding-potential context',
    'T6': 'Codon strategy and anomaly',
    'T7': 'Derived protein-like transcript proxy',
    'T8': 'Transcriptome fingerprint and candidate summary',
    'P1': 'Protein identity and sequence quality',
    'P2': 'Elemental resource budget',
    'P3': 'Nitrogen/Sulfur/Se economy',
    'P4': 'Amino-acid composition atlas',
    'P5': 'Physicochemical property spectrum',
    'P6': 'Structure/accessibility proxy',
    'P7': 'Redox and detectability proxy',
    'P8': 'Proteome fingerprint and trade-off context',
    'X1': 'DNA-RNA-protein resource shift',
    'X2': 'Exon-transcript residual coupling',
    'X3': 'RNA GC and protein property coupling',
    'X4': 'Predicted/observed proteome status',
    'X5': 'Shared outlier propagation',
    'X6': 'Cross-omics coupling network',
    'X7': 'Cross-omics fingerprint atlas',
    'X8': 'Integrated cross-omics candidate workbench',
}

MODULE_PATH_RULES = {
    'genome': [
        ('stoich_islands', 'G6'),
        ('hotspot', 'G6'),
        ('promoter', 'G2'),
        ('delta', 'G2'),
        ('codon', 'G5'),
        ('gc3', 'G5'),
        ('dinuc', 'G4'),
        ('skew', 'G3'),
        ('architecture', 'G7'),
        ('biotype', 'G7'),
        ('tradeoff_front', 'G8'),
        ('fingerprint', 'G8'),
        ('outliers.high', 'G8'),
        ('outliers.low', 'G8'),
        ('outliers', 'G8'),
    ],
    'transcriptome': [
        ('resource_outliers', 'T2'),
        ('top_n_rich', 'T2'),
        ('top_p_rich', 'T2'),
        ('element', 'T2'),
        ('low_complexity', 'T3'),
        ('stability', 'T3'),
        ('dinuc', 'T3'),
        ('biotype', 'T4'),
        ('coding_potential', 'T5'),
        ('orf', 'T5'),
        ('codon_anomaly', 'T6'),
        ('codon', 'T6'),
        ('instability', 'T7'),
        ('protein_preview', 'T7'),
        ('candidate_summary', 'T8'),
        ('fingerprint', 'T8'),
        ('tradeoff_front', 'T8'),
        ('outliers', 'T8'),
    ],
    'proteome': [
        ('resource_budget', 'P2'),
        ('resource_outliers', 'P2'),
        ('low_n', 'P3'),
        ('s_rich', 'P3'),
        ('se_positive', 'P3'),
        ('ns', 'P3'),
        ('composition', 'P4'),
        ('aa_', 'P4'),
        ('hydrophobic', 'P5'),
        ('unstable', 'P5'),
        ('physchem', 'P5'),
        ('pi', 'P5'),
        ('gravy', 'P5'),
        ('disulfide', 'P6'),
        ('structure', 'P6'),
        ('redox', 'P7'),
        ('detectability', 'P7'),
        ('fingerprint', 'P8'),
        ('tradeoff_front', 'P8'),
        ('outliers.low', 'P2'),
        ('outliers.high', 'P2'),
        ('outliers', 'P8'),
    ],
    'cross_omics': [
        ('x1', 'X1'),
        ('dna_to_rna', 'X1'),
        ('rna_to_protein', 'X1'),
        ('top_transformations', 'X1'),
        ('x2', 'X2'),
        ('residual', 'X2'),
        ('x3', 'X3'),
        ('rna_gc', 'X3'),
        ('x4', 'X4'),
        ('predicted', 'X4'),
        ('observed', 'X4'),
        ('x5', 'X5'),
        ('shared', 'X5'),
        ('x6', 'X6'),
        ('edge', 'X6'),
        ('coupling', 'X6'),
        ('x7', 'X7'),
        ('fingerprint', 'X7'),
        ('x8', 'X8'),
        ('candidate_workbench', 'X8'),
        ('integrated', 'X8'),
    ],
}

SCORE_KEYS = (
    'score',
    'priority_score',
    'front_score',
    'outlier_score',
    'resource_outlier_score',
    'candidate_score',
    'residual',
    'abs_residual',
    'quadrant_score',
    'discordance_score',
    'shared_outlier_count',
    'resource_budget_score',
    'strategy_score',
    'adaptation_score',
    'codon_deviation',
    'dinuc_distance_transcript',
    'protein_instability_index',
    'value',
)


def _token(value: Any) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    return re.sub(r'\.\d+$', '', text).lower()


def _safe_num(value: Any) -> float | None:
    return services._safe_num(value)


def _row_from_record(record: EntityRecord) -> dict[str, Any]:
    row = dict(record.payload_json or {})
    row.setdefault('entity_id', record.entity_id)
    row.setdefault('gene_id', record.canonical_gene_id)
    row.setdefault('gene_name', record.gene_name)
    row.setdefault('description', record.description)
    row.setdefault('strategy_cluster', record.strategy_cluster)
    if record.secondary_id:
        row.setdefault('secondary_id', record.secondary_id)
    return row


def _value_from_row(row: dict[str, Any], aliases: list[str]) -> tuple[str, Any]:
    for alias in aliases:
        if alias in row and row.get(alias) not in (None, ''):
            return alias, row.get(alias)
    return aliases[0], None


def _record_tokens(record: EntityRecord) -> set[str]:
    row = _row_from_record(record)
    tokens = {
        _token(record.entity_id),
        _token(record.canonical_gene_id),
        _token(record.secondary_id),
        _token(record.gene_name),
    }
    for key in ID_KEYS:
        tokens.add(_token(row.get(key)))
    return {item for item in tokens if item}


def _exact_values(query: str) -> list[str]:
    q = str(query or '').strip()
    variants = [q, q.casefold(), q.upper()]
    seen: set[str] = set()
    values: list[str] = []
    for value in variants:
        if value and value not in seen:
            values.append(value)
            seen.add(value)
    return values


def _match_query(query: str) -> Q:
    q = str(query or '').strip()
    values = _exact_values(q)
    return (
        Q(entity_id__in=values)
        | Q(canonical_gene_id__in=values)
        | Q(secondary_id__in=values)
        | Q(gene_name__in=values)
    )


def _match_type(record: EntityRecord, query: str) -> str:
    target = _token(query)
    if not target:
        return 'empty'
    row = _row_from_record(record)
    checks = [
        ('entity_id', record.entity_id),
        ('gene_id', record.canonical_gene_id or row.get('gene_id')),
        ('protein_id', row.get('protein_id')),
        ('transcript_id', row.get('transcript_id')),
        ('gene_name', record.gene_name or row.get('gene_name') or row.get('gene_symbol')),
        ('secondary_id', record.secondary_id or row.get('secondary_id')),
    ]
    for label, value in checks:
        if _token(value) == target:
            return label
    return 'searchable_text'


def _identity_payload(record: EntityRecord) -> dict[str, Any]:
    row = _row_from_record(record)
    return {
        'species_id': record.species.species_id,
        'species_name': record.species.display_name,
        'omics': record.omics_type,
        'entity_id': record.entity_id,
        'gene_id': record.canonical_gene_id or row.get('gene_id') or row.get('ensembl_gene_id') or '',
        'gene_name': record.gene_name or row.get('gene_name') or row.get('gene_symbol') or '',
        'transcript_id': row.get('transcript_id') or '',
        'protein_id': row.get('protein_id') or '',
        'description': record.description or row.get('description') or '',
        'strategy_cluster': record.strategy_cluster or row.get('strategy_cluster') or '',
    }


def search_entities(
    *,
    q: str,
    species_id: str = '',
    omics: str = '',
    id_type: str = '',
    limit: int = 30,
    include_synonyms: bool = True,
) -> dict[str, Any]:
    q = str(q or '').strip()
    limit = services._safe_int(limit, 30, minimum=1, maximum=100)
    if not q:
        return {'query': q, 'matches': [], 'total': 0, 'limit': limit}
    if omics:
        services.validate_omics(omics)

    if not services.db_mode():
        return _file_search_entities(q=q, species_id=species_id, omics=omics, limit=limit)

    base_qs = EntityRecord.objects.select_related('species', 'dataset')
    if species_id:
        base_qs = base_qs.filter(species__species_id=species_id)
    if omics:
        base_qs = base_qs.filter(omics_type=omics)
    values = _exact_values(q)
    indexed_fields = ['entity_id', 'canonical_gene_id', 'gene_name']
    fields = indexed_fields + (['secondary_id'] if species_id else [])
    rows = []
    seen = set()
    for field in fields:
        if len(rows) >= limit:
            break
        field_qs = base_qs.filter(**{f'{field}__in': values}).order_by('omics_type', 'entity_id')
        for rec in field_qs[: max(limit * 2, 10)]:
            payload = _identity_payload(rec)
            key = (payload['species_id'], payload['omics'], payload['entity_id'])
            if key in seen:
                continue
            seen.add(key)
            match_type = _match_type(rec, q)
            if id_type and match_type != id_type:
                continue
            gene_key = payload.get('gene_id') or payload.get('entity_id')
            payload.update({
                'entity_key': gene_key or payload['entity_id'],
                'match_type': match_type,
                'match_confidence': 'high',
                'canonical_flag': rec.entity_id == gene_key or rec.omics_type == 'genome',
                'report_url': f"/species/{payload['species_id']}/entity/{gene_key or payload['entity_id']}",
            })
            rows.append(payload)
            if len(rows) >= limit:
                break
    return {
        'query': q,
        'species_id': species_id,
        'omics': omics,
        'matches': rows,
        'total': len(rows),
        'limit': limit,
        'search_mode': 'species_scoped_exact_id' if species_id else 'global_exact_id',
        'fallback_policy': 'EntityRecord fallback uses exact indexed ID fields only; broad text scans are disabled for interactive search.',
    }


def _file_search_entities(*, q: str, species_id: str = '', omics: str = '', limit: int = 30) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    species_ids = [species_id] if species_id else list(services.file_species_map().keys())
    target = _token(q)
    for sid in species_ids:
        for omics_key in ([omics] if omics else OMICS_ORDER):
            try:
                rows = services._file_rows_for_scope(sid, omics_key, 'core')
            except Exception:
                continue
            for row in rows:
                tokens = {_token(row.get(key)) for key in ID_KEYS}
                if target not in tokens and target not in _token(row.get('description')):
                    continue
                gene_key = row.get('gene_id') or row.get('ensembl_gene_id') or row.get('entity_id')
                matches.append({
                    'species_id': sid,
                    'species_name': sid.replace('_', ' '),
                    'omics': omics_key,
                    'entity_id': row.get('entity_id') or row.get(services.omics_meta()[omics_key].get('primary_id')),
                    'entity_key': gene_key,
                    'gene_id': row.get('gene_id') or row.get('ensembl_gene_id') or '',
                    'gene_name': row.get('gene_name') or row.get('gene_symbol') or '',
                    'transcript_id': row.get('transcript_id') or '',
                    'protein_id': row.get('protein_id') or '',
                    'match_type': 'file_row',
                    'match_confidence': 'medium',
                    'report_url': f"/species/{sid}/entity/{gene_key}",
                })
                if len(matches) >= limit:
                    return {'query': q, 'matches': matches, 'total': len(matches), 'limit': limit}
    return {'query': q, 'matches': matches, 'total': len(matches), 'limit': limit}


def _seed_records(species_id: str, entity_key: str) -> list[EntityRecord]:
    query = str(entity_key or '').strip()
    qs = EntityRecord.objects.select_related('species', 'dataset').filter(species__species_id=species_id)
    exact = list(qs.filter(_match_query(query)).order_by('omics_type', 'entity_id')[:20])
    if exact:
        return exact
    return list(qs.filter(searchable_text__icontains=query).order_by('omics_type', 'entity_id')[:20])


def _linked_records(species_id: str, entity_key: str) -> list[EntityRecord]:
    seeds = _seed_records(species_id, entity_key)
    if not seeds:
        raise services.NotFoundError(f'Unknown entity for {species_id}: {entity_key}')
    tokens: set[str] = {_token(entity_key)}
    gene_ids: set[str] = set()
    for rec in seeds:
        row = _row_from_record(rec)
        for key in ('canonical_gene_id', 'gene_id', 'ensembl_gene_id'):
            value = getattr(rec, key, None) if hasattr(rec, key) else row.get(key)
            token = _token(value)
            if token:
                gene_ids.add(str(value).strip())
                tokens.add(token)
        tokens.update(_record_tokens(rec))

    qs = EntityRecord.objects.select_related('species', 'dataset').filter(species__species_id=species_id)
    linked_q = Q(pk__in=[rec.pk for rec in seeds])
    for gene_id in gene_ids:
        linked_q |= Q(canonical_gene_id__iexact=gene_id)
        linked_q |= Q(searchable_text__icontains=gene_id)
    for token in list(tokens)[:8]:
        linked_q |= Q(entity_id__iexact=token)
        linked_q |= Q(secondary_id__iexact=token)
    records = list(qs.filter(linked_q).order_by('omics_type', 'entity_id')[:120])
    dedup: dict[tuple[str, str], EntityRecord] = {}
    for rec in records + seeds:
        dedup[(rec.omics_type, rec.entity_id)] = rec
    return list(dedup.values())


def _canonical_record(records: list[EntityRecord], omics: str) -> EntityRecord | None:
    candidates = [rec for rec in records if rec.omics_type == omics]
    if not candidates:
        return None
    if omics == 'genome':
        return candidates[0]
    length_keys = ['length_aa'] if omics == 'proteome' else ['length_nt', 'transcript_length_nt', 'length']
    def score(rec: EntityRecord) -> float:
        row = _row_from_record(rec)
        for key in length_keys:
            value = _safe_num(row.get(key))
            if value is not None:
                return value
        return 0.0
    return sorted(candidates, key=score, reverse=True)[0]


def _stats_from_values(values: list[float], total: int) -> dict[str, Any]:
    values.sort()
    if not values:
        return {'n_total': total, 'valid_n': 0, 'missing_rate': 1.0, 'values': []}
    median = services._percentile(values, 0.5)
    abs_dev = sorted(abs(v - median) for v in values)
    mad = services._percentile(abs_dev, 0.5)
    return {
        'n_total': total,
        'valid_n': len(values),
        'missing_rate': round(1 - services._safe_div(len(values), total), 6) if total else 1.0,
        'median': round(median, 6),
        'q05': round(services._percentile(values, 0.05), 6),
        'q25': round(services._percentile(values, 0.25), 6),
        'q75': round(services._percentile(values, 0.75), 6),
        'q95': round(services._percentile(values, 0.95), 6),
        'mad': round(mad, 6),
        'values': values,
    }


@lru_cache(maxsize=256)
def _bulk_stats_for_omics_cached(species_id: str, omics: str) -> dict[tuple[str, ...], dict[str, Any]]:
    return _bulk_stats_for_omics_uncached(species_id, omics, tuple(tuple(cfg['aliases']) for cfg in CORE_FIELDS.get(omics, []) if cfg.get('numeric', True)))


def _bulk_stats_for_omics_uncached(species_id: str, omics: str, numeric_aliases: tuple[tuple[str, ...], ...]) -> dict[tuple[str, ...], dict[str, Any]]:
    values_by_aliases: dict[tuple[str, ...], list[float]] = {aliases: [] for aliases in numeric_aliases}
    total = 0
    qs = (
        EntityRecord.objects
        .filter(species__species_id=species_id, omics_type=omics)
        .only('payload_json', 'numeric_summary')
        .iterator(chunk_size=2000)
    )
    for rec in qs:
        total += 1
        source = rec.numeric_summary or {}
        raw = rec.payload_json or {}
        for aliases in numeric_aliases:
            value = None
            for alias in aliases:
                value = source.get(alias)
                if value is None:
                    value = raw.get(alias)
                if value not in (None, ''):
                    break
            num = _safe_num(value)
            if num is not None:
                values_by_aliases[aliases].append(float(num))
    return {aliases: _stats_from_values(values, total) for aliases, values in values_by_aliases.items()}


def _bulk_stats_for_omics(species_id: str, omics: str, configs: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
    if configs == CORE_FIELDS.get(omics, []):
        return _bulk_stats_for_omics_cached(species_id, omics)
    numeric_aliases = [tuple(cfg['aliases']) for cfg in configs if cfg.get('numeric', True)]
    return _bulk_stats_for_omics_uncached(species_id, omics, tuple(numeric_aliases))


def _feature_context(species_id: str, omics: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    configs = CORE_FIELDS.get(omics, [])
    stats_map = _bulk_stats_for_omics(species_id, omics, configs)
    for cfg in configs:
        aliases = cfg['aliases']
        source_field, value = _value_from_row(row, aliases)
        item = {
            'feature': cfg['field'],
            'source_field': source_field,
            'value': value,
            'evidence_level': cfg.get('level', 'raw_feature'),
            'description': 'Direct table field' if cfg.get('level') == 'raw_feature' else 'Computed proxy or candidate label; interpret as hypothesis-generating evidence.',
        }
        if cfg.get('numeric', True):
            num = _safe_num(value)
            stats = stats_map.get(tuple(aliases), {})
            item.update({key: stats.get(key) for key in ('median', 'q05', 'q25', 'q75', 'q95', 'valid_n', 'n_total', 'missing_rate')})
            if num is not None and stats.get('values'):
                values = stats['values']
                le_count = sum(1 for v in values if v <= num)
                percentile = 100 * services._safe_div(le_count, len(values))
                scale = 1.4826 * float(stats.get('mad') or 0.0)
                robust_z = (num - float(stats.get('median') or 0.0)) / scale if scale else 0.0
                item.update({
                    'value': round(num, 6),
                    'percentile': round(percentile, 2),
                    'robust_z': round(robust_z, 4),
                    'tail_label': _tail_label(percentile),
                    'rank_desc': max(1, len(values) - le_count + 1),
                })
        output.append(item)
    return output


def _tail_label(percentile: float) -> str:
    if percentile <= 1:
        return 'P01_low'
    if percentile <= 5:
        return 'P05_low'
    if percentile >= 99:
        return 'P99_high'
    if percentile >= 95:
        return 'P95_high'
    return 'normal'


def _iter_dicts(payload: Any, path: str = ''):
    if isinstance(payload, dict):
        yield path, payload
        for key, value in payload.items():
            next_path = f'{path}.{key}' if path else str(key)
            yield from _iter_dicts(value, next_path)
    elif isinstance(payload, list):
        for idx, value in enumerate(payload):
            yield from _iter_dicts(value, f'{path}[{idx}]')


def _module_id_from_path(path: str, omics: str, row: dict[str, Any] | None = None) -> str:
    row = row or {}
    explicit = row.get('module_id') or row.get('module') or row.get('source_module')
    if explicit and re.fullmatch(r'[GTPX][0-9]', str(explicit).upper()):
        return str(explicit).upper()
    match = re.search(r'\b([GTPX][0-9])\b', path.upper())
    if match:
        return match.group(1)
    target = path.lower().replace('modules[', 'modules.')
    rules = MODULE_PATH_RULES.get(omics, MODULE_PATH_RULES.get('cross_omics', []))
    for needle, module_id in rules:
        if needle in target:
            return module_id
    candidate_text = ' '.join(str(row.get(key) or '').lower() for key in ('candidate_type', 'class', 'label', 'source_path', 'method'))
    for needle, module_id in rules:
        if needle in candidate_text:
            return module_id
    prefix = {'genome': 'G', 'transcriptome': 'T', 'proteome': 'P'}.get(omics, 'X')
    return f'{prefix}?'


def _evidence_score(row: dict[str, Any]) -> tuple[float, str]:
    for key in SCORE_KEYS:
        value = _safe_num(row.get(key))
        if value is not None:
            return float(value), key
    shift_values = []
    for key, value in row.items():
        if any(token in str(key).lower() for token in ('shift', 'residual', 'delta', 'distance', 'score')):
            num = _safe_num(value)
            if num is not None:
                shift_values.append((abs(float(num)), float(num), str(key)))
    if shift_values:
        _, value, key = sorted(shift_values, reverse=True)[0]
        return value, key
    return 0.0, ''


def _severity(score: float, row: dict[str, Any]) -> str:
    tail = str(row.get('tail_label') or '').lower()
    if 'p99' in tail or abs(score) >= 4:
        return 'extreme'
    if 'p95' in tail or abs(score) >= 3:
        return 'high'
    if abs(score) >= 2:
        return 'medium'
    return 'low'


def _evidence_explanation(module_id: str, candidate_type: str, score: float, score_field: str) -> str:
    label = MODULE_LABELS.get(module_id, f'{module_id} candidate module')
    score_text = f'{score_field}={round(score, 4)}' if score_field else 'no explicit numeric score in the source row'
    return (
        f'This entity is linked to {module_id} ({label}) as {candidate_type}; {score_text}. '
        'Interpret this as module-derived candidate evidence unless an external validation layer is available.'
    )


def _candidate_evidence(species_id: str, records: list[EntityRecord]) -> list[dict[str, Any]]:
    target_tokens = set()
    for rec in records:
        target_tokens.update(_record_tokens(rec))
    target_tokens = {t for t in target_tokens if t}
    evidence: list[dict[str, Any]] = []
    sources: list[tuple[str, str, dict[str, Any]]] = []
    if services.db_mode():
        datasets = OmicsDataset.objects.filter(species__species_id=species_id, omics_type__in=OMICS_ORDER).only('omics_type', 'analysis_payload')
        for ds in datasets:
            if isinstance(ds.analysis_payload, dict):
                sources.append((ds.omics_type, 'analysis_payload', ds.analysis_payload))
        try:
            species = Species.objects.only('cross_omics_payload').get(species_id=species_id)
            if isinstance(species.cross_omics_payload, dict):
                sources.append(('cross_omics', 'cross_omics_payload', species.cross_omics_payload))
        except Species.DoesNotExist:
            pass
    else:
        for omics in OMICS_ORDER:
            try:
                sources.append((omics, 'analysis', services.get_analysis(species_id, omics)))
            except Exception:
                pass
        try:
            sources.append(('cross_omics', 'cross_omics', services.get_cross_omics(species_id)))
        except Exception:
            pass

    seen = set()
    for omics, source_name, payload in sources:
        for path, row in _iter_dicts(payload):
            row_tokens = {_token(row.get(key)) for key in ID_KEYS if row.get(key) not in (None, '')}
            if not row_tokens.intersection(target_tokens):
                continue
            module_id = _module_id_from_path(path, omics, row)
            score, score_field = _evidence_score(row)
            key = (module_id, path, tuple(sorted(row_tokens.intersection(target_tokens))))
            if key in seen:
                continue
            seen.add(key)
            candidate_type = str(row.get('candidate_type') or row.get('class') or row.get('label') or path.split('.')[-1] or 'candidate')
            module_name = MODULE_LABELS.get(module_id, path.replace('.', ' / ')[:180])
            evidence.append({
                'module_id': module_id,
                'module_name': module_name,
                'omics_scope': omics,
                'candidate_type': candidate_type,
                'score': round(score, 6),
                'score_field': score_field,
                'rank': row.get('rank') or row.get('rank_desc') or '',
                'severity_level': _severity(score, row),
                'evidence_level': 'cross_omics' if omics == 'cross_omics' else 'candidate_label',
                'explanation': _evidence_explanation(module_id, candidate_type, score, score_field),
                'source_artifact_id': source_name,
                'source_path': path,
                'matched_ids': sorted(row_tokens.intersection(target_tokens)),
            })
            if len(evidence) >= 120:
                return evidence
    return evidence


def _annotation_candidate_paths(species_id: str) -> list[Path]:
    base_dirs = [
        Path(settings.BASE_DIR) / 'data' / 'external_annotations',
        Path(settings.BASE_DIR) / 'workspace' / 'external_annotations',
    ]
    names = [
        f'{species_id}.json',
        f'{species_id}.csv',
        f'{species_id}_annotations.json',
        f'{species_id}_annotations.csv',
    ]
    return [base / name for base in base_dirs for name in names]


def _load_external_annotations(species_id: str, records: list[EntityRecord]) -> dict[str, Any]:
    tokens = set()
    for record in records:
        tokens.update(_record_tokens(record))
    tokens = {token for token in tokens if token}
    matches: list[dict[str, Any]] = []
    loaded_sources: list[str] = []
    for path in _annotation_candidate_paths(species_id):
        if not path.exists():
            continue
        loaded_sources.append(str(path))
        try:
            if path.suffix.lower() == '.json':
                payload = services.load_json(str(path.relative_to(services.DATA_ROOT))) if str(path).startswith(str(services.DATA_ROOT)) else None
                if payload is None:
                    import json
                    payload = json.loads(path.read_text(encoding='utf-8'))
                rows = payload if isinstance(payload, list) else payload.get('annotations') or payload.get('rows') or []
            else:
                with path.open('r', encoding='utf-8-sig', newline='') as fh:
                    rows = list(csv.DictReader(fh))
        except Exception as exc:
            matches.append({'source': str(path), 'error': f'failed_to_read: {exc}'})
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_tokens = {_token(row.get(key)) for key in ID_KEYS.union({'id', 'accession', 'uniprot_id', 'go_id', 'pfam_id'}) if row.get(key) not in (None, '')}
            if row_tokens.intersection(tokens):
                matches.append({
                    'source': str(path),
                    'matched_ids': sorted(row_tokens.intersection(tokens)),
                    'evidence_level': 'external_annotation',
                    'annotation': row,
                })
    required_sources = [
        'GO / KEGG functional annotation table keyed by gene_id or protein_id',
        'Pfam / InterPro domain table keyed by protein_id',
        'UniProt mapping table keyed by protein_id or accession',
        'AlphaFold / structure-quality table keyed by protein_id',
        'Expression or proteomics abundance table keyed by gene_id/protein_id and sample/group',
    ]
    return {
        'available': bool(matches),
        'annotations': matches,
        'loaded_sources': loaded_sources,
        'required_sources': required_sources,
        'note': (
            'External annotations are loaded only when matching local JSON/CSV files exist under '
            'data/external_annotations or workspace/external_annotations. They remain separate from core stoichiometric evidence.'
        ),
    }


def _neighbor_rows(species_id: str, record: EntityRecord | None, features: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    if not record:
        return []
    numeric_features = [f for f in features if _safe_num(f.get('value')) is not None][:6]
    if not numeric_features:
        return []
    fields = [f['source_field'] for f in numeric_features]
    target = [float(f['value']) for f in numeric_features]
    rows = []
    for rec in EntityRecord.objects.filter(species__species_id=species_id, omics_type=record.omics_type).only('entity_id', 'canonical_gene_id', 'gene_name', 'numeric_summary')[:800]:
        source = rec.numeric_summary or {}
        vec = [_safe_num(source.get(field)) for field in fields]
        if any(v is None for v in vec):
            continue
        distance = math.sqrt(sum((float(v) - target[idx]) ** 2 for idx, v in enumerate(vec)))
        if rec.entity_id == record.entity_id:
            continue
        rows.append({
            'omics': record.omics_type,
            'entity_id': rec.entity_id,
            'gene_id': rec.canonical_gene_id,
            'gene_name': rec.gene_name,
            'distance': round(distance, 6),
            'method': 'Euclidean distance in available core feature space',
        })
    rows.sort(key=lambda item: item['distance'])
    return rows[:limit]


def get_entity_report(
    species_id: str,
    entity_key: str,
    *,
    prefer_canonical: bool = True,
    include_raw: bool = False,
    include_charts: bool = True,
    include_neighbors: bool = True,
) -> dict[str, Any]:
    if not services.db_mode():
        return _file_entity_report(species_id, entity_key, include_raw=include_raw)
    try:
        species = Species.objects.get(species_id=species_id)
    except Species.DoesNotExist:
        raise services.NotFoundError(f'Unknown species: {species_id}')
    records = _linked_records(species_id, entity_key)
    primary = records[0]
    canonical_by_omics = {omics: _canonical_record(records, omics) for omics in OMICS_ORDER}
    identity = _identity_payload(primary)
    gene_key = identity.get('gene_id') or entity_key
    link_count = sum(1 for rec in canonical_by_omics.values() if rec)
    link_confidence = 'high' if link_count >= 2 and gene_key else ('medium' if link_count else 'low')
    mapping_summary = services.cross_omics_mapping_summary(species_id, entity_key=gene_key or entity_key)

    omics_sections: dict[str, Any] = {}
    neighbors: list[dict[str, Any]] = []
    for omics, rec in canonical_by_omics.items():
        if not rec:
            omics_sections[omics] = {'available': False, 'features': [], 'entities': []}
            continue
        row = _row_from_record(rec)
        features = _feature_context(species_id, omics, row)
        omics_sections[omics] = {
            'available': True,
            'identity': _identity_payload(rec),
            'features': features,
            'entities': [_identity_payload(item) for item in records if item.omics_type == omics],
            'canonical_rule': 'annotation canonical if present, otherwise longest transcript/protein, otherwise first linked entity',
        }
        if include_neighbors:
            neighbors.extend(_neighbor_rows(species_id, rec, features, limit=4))

    evidence = _candidate_evidence(species_id, records)
    mapping_evidence = _mapping_evidence_payload(omics_sections, mapping_summary, link_confidence)
    try:
        id_mapping_evidence = id_mapping.get_entity_mapping_chain(species_id, gene_key or entity_key)
    except Exception:
        id_mapping_evidence = {'available': False, 'query': gene_key or entity_key, 'matches': []}
    functional_evidence = function_annotations.entity_function_payload(species_id, gene_key or entity_key)
    external_annotations = _load_external_annotations(species_id, records)
    overview_cards = _overview_cards(omics_sections, evidence, link_confidence, mapping_evidence)
    chart_contexts = _chart_contexts(evidence, omics_sections) if include_charts else []
    raw = {}
    if include_raw:
        raw = {f'{rec.omics_type}:{rec.entity_id}': _row_from_record(rec) for rec in records}

    return {
        'query': {'input': entity_key, 'species_id': species_id},
        'entity_identity': {
            **identity,
            'species_name': species.display_name,
            'entity_key': gene_key or entity_key,
            'canonical_flag': True,
            'link_confidence': link_confidence,
        },
        'id_chain': {
            'gene_id': gene_key,
            'link_confidence': link_confidence,
            'complete_chain': mapping_evidence['complete_chain'],
            'evidence_grade': mapping_evidence['evidence_grade'],
            'mapping_confidence': mapping_evidence['mapping_confidence'],
            'missing_layers': mapping_evidence['missing_layers'],
            'mapping_conflict_count': mapping_summary.get('conflict_count', 0),
            'isoform_rule': 'canonical annotation if present; otherwise longest available transcript/protein; all isoforms are retained in each omics section.',
            'genome_entity_id': canonical_by_omics['genome'].entity_id if canonical_by_omics.get('genome') else '',
            'transcript_entities': [_identity_payload(rec) for rec in records if rec.omics_type == 'transcriptome'],
            'protein_entities': [_identity_payload(rec) for rec in records if rec.omics_type == 'proteome'],
        },
        'overview_cards': overview_cards,
        'omics_sections': omics_sections,
        'cross_omics': _cross_omics_summary(omics_sections, evidence, link_confidence, mapping_summary),
        'mapping_summary': mapping_summary,
        'mapping_evidence': mapping_evidence,
        'id_mapping_evidence': id_mapping_evidence,
        'functional_evidence': functional_evidence,
        'evidence_summary': {
            'hit_module_count': len({item['module_id'] for item in evidence}),
            'max_severity': _max_severity(evidence),
            'evidence': evidence,
        },
        'chart_contexts': chart_contexts,
        'nearest_neighbors': neighbors[:12],
        'external_annotations': external_annotations,
        'raw_payload_refs': raw,
        'data_quality': _quality_notes(records, omics_sections, link_confidence, mapping_evidence),
        'download_links': {
            'json': f'/api/stoichdb/species/{species_id}/entities/{entity_key}/report/?include_raw=1',
            'raw': f'/api/stoichdb/species/{species_id}/entities/{entity_key}/raw/',
            'evidence': f'/api/stoichdb/species/{species_id}/entities/{entity_key}/evidence/',
            'function': f'/api/stoichdb/species/{species_id}/entities/{entity_key}/function/',
        },
    }


def _file_entity_report(species_id: str, entity_key: str, *, include_raw: bool = False) -> dict[str, Any]:
    matches = _file_search_entities(q=entity_key, species_id=species_id, limit=30).get('matches', [])
    if not matches:
        raise services.NotFoundError(f'Unknown entity for {species_id}: {entity_key}')
    return {
        'query': {'input': entity_key, 'species_id': species_id},
        'entity_identity': {**matches[0], 'link_confidence': 'medium'},
        'id_chain': {'gene_id': matches[0].get('gene_id') or entity_key, 'link_confidence': 'medium', 'transcript_entities': [], 'protein_entities': []},
        'overview_cards': [{'label': 'File mode entity match', 'value': len(matches), 'note': 'The platform is running in file mode; report uses scoped JSON rows.'}],
        'omics_sections': {},
        'cross_omics': {'available': False},
        'evidence_summary': {'hit_module_count': 0, 'max_severity': 'none', 'evidence': []},
        'chart_contexts': [],
        'nearest_neighbors': [],
        'external_annotations': {'available': False},
        'functional_evidence': function_annotations.entity_function_payload(species_id, matches[0].get('gene_id') or entity_key),
        'raw_payload_refs': {'matches': matches} if include_raw else {},
        'data_quality': {'flags': ['file_mode_limited_report'], 'notes': ['Database-backed entity statistics are unavailable in file mode.']},
        'download_links': {},
    }


def _overview_cards(sections: dict[str, Any], evidence: list[dict[str, Any]], link_confidence: str, mapping_evidence: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    available = [omics for omics, section in sections.items() if section.get('available')]
    tail_hits = []
    for section in sections.values():
        for item in section.get('features') or []:
            if item.get('tail_label') and item.get('tail_label') != 'normal':
                tail_hits.append(item)
    return [
        {'label': 'Omics coverage', 'value': f'{len(available)}/3', 'note': ', '.join(available) or 'No omics linked'},
        {'label': 'Link confidence', 'value': link_confidence, 'note': 'Based on shared gene/entity IDs across omics layers.'},
        {'label': 'Evidence chain', 'value': (mapping_evidence or {}).get('evidence_grade', '-'), 'note': (mapping_evidence or {}).get('chain_status', 'Mapping evidence was not evaluated.')},
        {'label': 'Tail features', 'value': len(tail_hits), 'note': 'Features outside P05/P95 within the current species background.'},
        {'label': 'Candidate modules', 'value': len({item['module_id'] for item in evidence}), 'note': 'G/T/P/X module evidence aggregated from current artifacts.'},
    ]


def _max_severity(evidence: list[dict[str, Any]]) -> str:
    order = {'none': 0, 'low': 1, 'medium': 2, 'high': 3, 'extreme': 4}
    current = 'none'
    for item in evidence:
        sev = item.get('severity_level') or 'low'
        if order.get(sev, 0) > order.get(current, 0):
            current = sev
    return current


def _mapping_evidence_payload(sections: dict[str, Any], mapping_summary: dict[str, Any], link_confidence: str) -> dict[str, Any]:
    available = [omics for omics, section in sections.items() if section.get('available')]
    missing = [omics for omics in OMICS_ORDER if omics not in available]
    complete_chain = len(available) == 3
    conflict_count = int(mapping_summary.get('conflict_count') or 0)
    if complete_chain and link_confidence == 'high':
        grade = 'A' if conflict_count == 0 else 'B'
    elif len(available) >= 2:
        grade = 'C'
    elif len(available) == 1:
        grade = 'D'
    else:
        grade = 'Fail'
    mapping_confidence = 'high' if grade == 'A' else ('medium' if grade in {'B', 'C'} else 'low')
    return {
        'complete_chain': complete_chain,
        'evidence_grade': grade,
        'mapping_confidence': mapping_confidence,
        'available_layers': available,
        'missing_layers': missing,
        'coverage': mapping_summary.get('coverage') or {},
        'conflict_count': conflict_count,
        'multi_mapping': mapping_summary.get('multi_mapping') or {},
        'chain_status': (
            'Complete genome-transcript-protein evidence chain.'
            if complete_chain else
            f"Missing layer(s): {', '.join(missing)}."
        ),
        'method': 'Entity-level canonical links plus species-level mapping coverage summary.',
    }


def _cross_omics_summary(sections: dict[str, Any], evidence: list[dict[str, Any]], link_confidence: str, mapping_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    available = [omics for omics, section in sections.items() if section.get('available')]
    cross_hits = [item for item in evidence if item.get('omics_scope') == 'cross_omics']
    mapping_summary = mapping_summary or {}
    return {
        'available': len(available) >= 2,
        'omics_available': available,
        'link_confidence': link_confidence,
        'mapping_coverage': mapping_summary.get('coverage') or {},
        'mapping_conflict_count': int(mapping_summary.get('conflict_count') or 0),
        'multi_mapping': mapping_summary.get('multi_mapping') or {},
        'cross_omics_hit_count': len(cross_hits),
        'direction_class': 'available_in_multiple_layers' if len(available) >= 2 else 'single_layer_only',
        'note': 'Cross-omics shifts are interpreted only when at least two omics layers are linked with non-low confidence; mapping coverage and conflicts are shown as interpretation preconditions.',
    }


def _chart_contexts(evidence: list[dict[str, Any]], sections: dict[str, Any]) -> list[dict[str, Any]]:
    contexts = []
    for omics, section in sections.items():
        if section.get('available'):
            contexts.append({
                'module_id': f'{omics}_feature_context',
                'chart_id': f'{omics}_feature_distribution',
                'omics': omics,
                'method': 'Species-background percentile and robust z-score',
                'why_flagged': 'Shows where the entity sits relative to the current species feature distribution.',
                'highlight_supported': True,
            })
    for item in evidence[:30]:
        contexts.append({
            'module_id': item.get('module_id'),
            'chart_id': item.get('source_path'),
            'omics': item.get('omics_scope'),
            'method': 'Candidate artifact lookup',
            'why_flagged': item.get('explanation'),
            'highlight_supported': False,
        })
    return contexts


def _quality_notes(records: list[EntityRecord], sections: dict[str, Any], link_confidence: str, mapping_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    flags = []
    if link_confidence == 'low':
        flags.append('low_link_confidence')
    for omics, section in sections.items():
        if not section.get('available'):
            flags.append(f'missing_{omics}')
        for feature in section.get('features') or []:
            if (feature.get('missing_rate') or 0) > 0.5:
                flags.append(f'high_missing_rate:{omics}:{feature.get("feature")}')
    if len(records) > 20:
        flags.append('many_linked_isoforms')
    if mapping_evidence:
        if not mapping_evidence.get('complete_chain'):
            flags.append('incomplete_cross_omics_chain')
        if (mapping_evidence.get('conflict_count') or 0) > 0:
            flags.append('mapping_conflicts_present')
    return {
        'flags': sorted(set(flags)),
        'notes': [
            'Proxy indicators are hypothesis-generating and should not be read as direct experimental validation.',
            'Percentile and robust z-score are computed against the current species and omics background.',
            'External annotations are displayed separately when available and are not mixed into core stoichiometric evidence.',
        ],
    }


def get_entity_evidence(species_id: str, entity_key: str, *, scope: str = '', min_severity: str = '', module_ids: str = '') -> dict[str, Any]:
    report = get_entity_report(species_id, entity_key, include_raw=False, include_charts=False, include_neighbors=False)
    evidence = report['evidence_summary']['evidence']
    if module_ids:
        allowed = {item.strip().upper() for item in module_ids.split(',') if item.strip()}
        evidence = [item for item in evidence if str(item.get('module_id', '')).upper() in allowed]
    if min_severity:
        order = {'low': 1, 'medium': 2, 'high': 3, 'extreme': 4}
        threshold = order.get(min_severity.lower(), 1)
        evidence = [item for item in evidence if order.get(str(item.get('severity_level', 'low')).lower(), 1) >= threshold]
    return {'species_id': species_id, 'entity_key': entity_key, 'evidence': evidence, 'total': len(evidence)}


def get_entity_chart_context(species_id: str, entity_key: str, *, module_id: str = '', chart_id: str = '', nearest_neighbors: bool = True) -> dict[str, Any]:
    report = get_entity_report(species_id, entity_key, include_raw=False, include_charts=True, include_neighbors=nearest_neighbors)
    contexts = report.get('chart_contexts') or []
    if module_id:
        contexts = [item for item in contexts if str(item.get('module_id', '')).lower() == module_id.lower()]
    if chart_id:
        contexts = [item for item in contexts if str(item.get('chart_id', '')).lower() == chart_id.lower()]
    return {'species_id': species_id, 'entity_key': entity_key, 'chart_contexts': contexts, 'nearest_neighbors': report.get('nearest_neighbors') or []}


def get_entity_raw(species_id: str, entity_key: str, *, omics: str = '', feature_set: str = 'core') -> dict[str, Any]:
    records = _linked_records(species_id, entity_key) if services.db_mode() else []
    rows = []
    for rec in records:
        if omics and rec.omics_type != omics:
            continue
        rows.append({'omics': rec.omics_type, 'entity_id': rec.entity_id, 'row': _row_from_record(rec), 'feature_set': feature_set})
    if not rows:
        report = get_entity_report(species_id, entity_key, include_raw=True)
        return {'species_id': species_id, 'entity_key': entity_key, 'rows': report.get('raw_payload_refs') or {}}
    return {'species_id': species_id, 'entity_key': entity_key, 'rows': rows, 'total': len(rows)}


def batch_entity_report(payload: dict[str, Any]) -> dict[str, Any]:
    species_id = str(payload.get('species_id') or '').strip()
    raw_ids = payload.get('ids') or []
    if isinstance(raw_ids, str):
        raw_ids = [line.strip() for line in raw_ids.replace(',', '\n').splitlines() if line.strip()]
    ids = [str(item).strip() for item in raw_ids if str(item).strip()][:200]
    rows = []
    unmatched = []
    for input_id in ids:
        try:
            if species_id:
                report = get_entity_report(species_id, input_id, include_raw=False, include_charts=False, include_neighbors=False)
                identity = report['entity_identity']
            else:
                matches = search_entities(q=input_id, limit=1).get('matches') or []
                if not matches:
                    raise services.NotFoundError(input_id)
                match = matches[0]
                report = get_entity_report(match['species_id'], match['entity_key'], include_raw=False, include_charts=False, include_neighbors=False)
                identity = report['entity_identity']
            evidence = report.get('evidence_summary') or {}
            tail_count = sum(
                1
                for section in (report.get('omics_sections') or {}).values()
                for feature in section.get('features') or []
                if feature.get('tail_label') and feature.get('tail_label') != 'normal'
            )
            priority = min(1.0, 0.18 * tail_count + 0.15 * evidence.get('hit_module_count', 0) + (0.2 if identity.get('link_confidence') == 'high' else 0.05))
            rows.append({
                'input_id': input_id,
                'matched_id': identity.get('entity_key') or identity.get('entity_id'),
                'species_id': identity.get('species_id'),
                'gene_id': identity.get('gene_id'),
                'gene_name': identity.get('gene_name'),
                'omics_available': ','.join(report.get('cross_omics', {}).get('omics_available') or []),
                'hit_module_count': evidence.get('hit_module_count', 0),
                'max_severity': evidence.get('max_severity', 'none'),
                'tail_feature_count': tail_count,
                'link_confidence': identity.get('link_confidence'),
                'priority_score': round(priority, 4),
                'report_url': f"/species/{identity.get('species_id')}/entity/{identity.get('entity_key') or identity.get('entity_id')}",
                'match_confidence': 'high',
            })
        except Exception:
            unmatched.append({'input_id': input_id, 'reason': 'No entity match in current EntityRecord index'})
    rows.sort(key=lambda item: item['priority_score'], reverse=True)
    for idx, row in enumerate(rows, 1):
        row['priority_rank'] = idx
    return {'species_id': species_id, 'rows': rows, 'unmatched': unmatched, 'total': len(rows), 'limit': 200}
