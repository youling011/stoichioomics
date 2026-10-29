from __future__ import annotations
import sys as _corefull_sys
from pathlib import Path as _CoreFullPath
_corefull_sys.path.insert(0, str(_CoreFullPath(__file__).resolve().parents[1]))
from backend.apps.stoichdb.feature_sources import io as feature_io

import argparse
import json
from math import erfc, log, sqrt
from backend.apps.common.host_paths import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_MODULES = [
    'Gateway',
    'Overview',
    'Database',
    'Visualization',
    'Analysis',
    'Compare',
    'Workflows',
    'Guide',
    'Contact',
]

OMICS_META = {
    'genome': {
        'display_name': 'Genome',
        'entity_label': 'Gene',
        'primary_id': 'gene_id',
        'fallback_id': 'entity_id',
        'description': 'Genome stoichiometric feature table with promoter/exon composition, element densities, GC strata, skew, and coordinate-aware fields.',
    },
    'transcriptome': {
        'display_name': 'Transcriptome',
        'entity_label': 'Transcript',
        'primary_id': 'transcript_id',
        'fallback_id': 'entity_id',
        'description': 'Transcriptome stoichiometric feature table with nucleotide composition, element-per-nt metrics, motif bias, ORF coupling, and coding-proxy features.',
    },
    'proteome': {
        'display_name': 'Proteome',
        'entity_label': 'Protein',
        'primary_id': 'protein_id',
        'fallback_id': 'entity_id',
        'description': 'Proteome stoichiometric feature table with per-aa element densities, ratios, disulfide features, and physicochemical properties.',
    },
}

DEFAULT_FEATURE_PRIORITY = {
    'genome': ['exon_gc_percent', 'promoter_gc_percent', 'gc_delta_promoter_minus_exon', 'exon_atoms_N_per_base', 'gc3_percent', 'stoich_island_score'],
    'transcriptome': ['gc_percent_display', 'nt_entropy', 'atoms_per_nt_N', 'atoms_per_nt_P', 'rna_orf_coupling_score', 'protein_gravy_proxy'],
    'proteome': ['N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy', 'resource_budget_score', 'disulfide_density'],
}

FINGERPRINT_MAP = {
    'genome_gc': ['genome_gc', 'gc_mean', 'exon_gc_percent'],
    'promoter_gc': ['promoter_gc', 'promoter_gc_percent'],
    'genome_n_per_base': ['genome_n_per_base', 'exon_atoms_N_per_base', 'atoms_N_per_base'],
    'transcript_gc': ['transcript_gc', 'gc_content'],
    'transcript_entropy': ['transcript_entropy', 'nt_entropy'],
    'transcript_coupling': ['transcript_coupling', 'rna_orf_coupling_score'],
    'proteome_n_per_aa': ['proteome_n_per_aa', 'N_atoms_per_aa'],
    'proteome_s_per_aa': ['proteome_s_per_aa', 'S_atoms_per_aa'],
    'proteome_pi': ['proteome_pi', 'pI'],
    'proteome_gravy': ['proteome_gravy', 'gravy'],
}

FEATURE_SCHEMA_PATH = Path(__file__).resolve().parent.parent / 'shared' / 'schemas' / 'stoich_feature_display_schema.json'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a stoichdb-compatible registry from real feature tables and optional precomputed artifacts.')
    parser.add_argument('--metadata', required=True, help='CSV/TSV with one row per species. Must include species_id, display_name, short_name, domain, clade, habitat, genome_size_mb.')
    parser.add_argument('--input-root', required=True, help='Root directory containing <species_id>/<omics>/rows.(csv|json|parquet) and optional summary/analysis JSON files.')
    parser.add_argument('--output-root', required=True, help='Output registry directory to be consumed by the platform through STOICHDB_DATA_ROOT.')
    parser.add_argument('--format', choices=['auto', 'csv', 'tsv'], default='auto', help='Metadata file separator.')
    return parser.parse_args()


def read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == '.csv':
      return feature_io.read_csv(path)
    if suffix in {'.tsv', '.txt'}:
      return feature_io.read_csv(path, sep='\t')
    if suffix == '.json':
      return pd.read_json(path)
    if suffix == '.parquet':
      return pd.read_parquet(path)
    raise ValueError(f'Unsupported table format: {path}')


def read_metadata(path: Path, fmt: str) -> pd.DataFrame:
    if fmt == 'csv' or path.suffix.lower() == '.csv':
        return feature_io.read_csv(path)
    if fmt == 'tsv' or path.suffix.lower() in {'.tsv', '.txt'}:
        return feature_io.read_csv(path, sep='\t')
    return feature_io.read_csv(path)


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def numeric_columns(df: pd.DataFrame) -> list[str]:
    return [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]


def maybe_round(value: Any) -> Any:
    if isinstance(value, (np.floating, float)):
        return round(float(value), 4)
    if isinstance(value, (np.integer, int)):
        return int(value)
    return value


def hist_payload(series: pd.Series, bins: int = 18) -> dict[str, Any]:
    values = pd.to_numeric(series, errors='coerce').dropna().to_numpy(dtype=float)
    if not len(values):
        return {'centers': [], 'counts': []}
    counts, edges = np.histogram(values, bins=min(bins, max(6, int(sqrt(len(values)) * 2))))
    centers = ((edges[:-1] + edges[1:]) / 2).round(4).tolist()
    return {'centers': centers, 'counts': counts.astype(int).tolist()}


def load_feature_display_schema() -> dict[str, Any]:
    if FEATURE_SCHEMA_PATH.exists():
        try:
            payload = json.loads(FEATURE_SCHEMA_PATH.read_text(encoding='utf-8'))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {'version': 'fallback_v1', 'omics': {}}


def field_meta_for_omics(omics: str, columns: list[str]) -> list[dict[str, Any]]:
    schema = load_feature_display_schema().get('omics') or {}
    rows = schema.get(omics) or []
    output = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        field = str(item.get('field') or '').strip()
        if field and field in columns:
            output.append(item)
    return output


def normalize_rows(df: pd.DataFrame, omics: str) -> pd.DataFrame:
    out = df.copy()
    if omics == 'genome' and {'promoter_gc_percent', 'exon_gc_percent'}.issubset(out.columns):
        promoter_gc = pd.to_numeric(out['promoter_gc_percent'], errors='coerce')
        exon_gc = pd.to_numeric(out['exon_gc_percent'], errors='coerce')
        out['gc_delta_promoter_minus_exon'] = promoter_gc - exon_gc
        out['promoter_exon_gc_delta'] = out['gc_delta_promoter_minus_exon']
    if omics == 'genome' and {'promoter_atoms_N_per_base', 'exon_atoms_N_per_base'}.issubset(out.columns):
        promoter_n = pd.to_numeric(out['promoter_atoms_N_per_base'], errors='coerce')
        exon_n = pd.to_numeric(out['exon_atoms_N_per_base'], errors='coerce')
        out['n_delta_promoter_minus_exon'] = promoter_n - exon_n
        out['promoter_exon_n_delta'] = out['n_delta_promoter_minus_exon']
    if omics == 'transcriptome' and 'gc_content' in out.columns:
        gc_raw = pd.to_numeric(out['gc_content'], errors='coerce')
        scale = 100.0 if (not gc_raw.dropna().empty and float(gc_raw.dropna().max()) <= 1.5) else 1.0
        out['gc_percent_display'] = gc_raw * scale
    return out


def percentile_summary(series: pd.Series) -> dict[str, float]:
    s = pd.to_numeric(series, errors='coerce').dropna()
    if s.empty:
        return {'mean': 0, 'std': 0, 'p05': 0, 'p25': 0, 'p50': 0, 'p75': 0, 'p95': 0}
    return {
        'mean': round(float(s.mean()), 4),
        'std': round(float(s.std(ddof=0)), 4),
        'p05': round(float(s.quantile(0.05)), 4),
        'p25': round(float(s.quantile(0.25)), 4),
        'p50': round(float(s.quantile(0.50)), 4),
        'p75': round(float(s.quantile(0.75)), 4),
        'p95': round(float(s.quantile(0.95)), 4),
    }


def first_present(columns: list[str], candidates: list[str]) -> str | None:
    lookup = {col.lower(): col for col in columns}
    for candidate in candidates:
        hit = lookup.get(candidate.lower())
        if hit:
            return hit
    return None


def safe_num(value: Any) -> float | None:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except Exception:
        return None


def fisher_pvalue_from_r(r: float, n: int) -> float:
    if n < 4:
        return 1.0
    r = max(min(float(r), 0.999999), -0.999999)
    z = 0.5 * log((1.0 + r) / (1.0 - r)) * sqrt(max(1.0, n - 3.0))
    return float(erfc(abs(z) / sqrt(2.0)))


def benjamini_hochberg_fdr(pvalues: list[float]) -> list[float]:
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
    return [min(1.0, max(0.0, float(v))) for v in adjusted]


def pareto_front_ranks(frame: pd.DataFrame, cost_col: str = 'cost_axis', adapt_col: str = 'adapt_axis') -> list[int]:
    if frame.empty or cost_col not in frame.columns or adapt_col not in frame.columns:
        return [0] * len(frame)
    costs = pd.to_numeric(frame[cost_col], errors='coerce').to_numpy(dtype=float)
    adapts = pd.to_numeric(frame[adapt_col], errors='coerce').to_numpy(dtype=float)
    n = len(frame)
    ranks = [0] * n
    remaining = set(range(n))
    current_rank = 1

    def dominates(i: int, j: int) -> bool:
        if not np.isfinite(costs[i]) or not np.isfinite(costs[j]) or not np.isfinite(adapts[i]) or not np.isfinite(adapts[j]):
            return False
        return (costs[i] <= costs[j] and adapts[i] >= adapts[j]) and (costs[i] < costs[j] or adapts[i] > adapts[j])

    while remaining:
        front = [idx for idx in remaining if not any(dominates(other, idx) for other in remaining if other != idx)]
        if not front:
            break
        for idx in front:
            ranks[idx] = current_rank
        remaining -= set(front)
        current_rank += 1
    return ranks


def top_entities(df: pd.DataFrame, id_col: str, label_cols: list[str], score_col: str, n: int = 8) -> dict[str, Any]:
    cols = []
    for col in [id_col] + [c for c in label_cols if c in df.columns] + [score_col]:
        if col in df.columns and col not in cols:
            cols.append(col)
    scored = df[cols].copy()
    scored[score_col] = pd.to_numeric(scored[score_col], errors='coerce')
    scored = scored.dropna(subset=[score_col])
    return {
        'top': scored.nlargest(min(n, len(scored)), score_col).to_dict(orient='records'),
        'bottom': scored.nsmallest(min(n, len(scored)), score_col).to_dict(orient='records'),
    }


def simple_clusters(df: pd.DataFrame, numeric_cols: list[str]) -> tuple[pd.Series, list[dict[str, Any]], list[dict[str, Any]]]:
    score_cols = numeric_cols[:4]
    if not score_cols:
        cluster = pd.Series(['Balanced'] * len(df), index=df.index)
        return cluster, [{'cluster': 'Balanced', 'count': int(len(df))}], [{'cluster': 'Balanced', 'count': int(len(df))}]

    scores = df[score_cols].apply(pd.to_numeric, errors='coerce').fillna(df[score_cols].mean()).sum(axis=1)
    q = min(4, max(1, scores.nunique()))
    if q == 1:
        cluster = pd.Series(['Balanced'] * len(df), index=df.index)
        counts = [{'cluster': 'Balanced', 'count': int(len(df))}]
        centroid = {col: round(float(pd.to_numeric(df[col], errors='coerce').mean()), 4) for col in score_cols}
        centroid.update({'cluster': 'Balanced', 'count': int(len(df))})
        return cluster, counts, [centroid]

    labels = ['Resource-lean', 'Balanced', 'Adaptive-shifted', 'Extreme-tail'][:q]
    bucket = pd.qcut(scores.rank(method='first'), q=q, labels=labels, duplicates='drop')
    cluster = pd.Series(bucket.astype(str), index=df.index)
    counts = cluster.value_counts().sort_index()
    breakdown = [{'cluster': name, 'count': int(counts[name])} for name in counts.index]
    centroids = []
    for name in counts.index:
        part = df[cluster == name]
        centroid = {col: round(float(pd.to_numeric(part[col], errors='coerce').mean()), 4) for col in score_cols}
        centroid.update({'cluster': name, 'count': int(len(part))})
        centroids.append(centroid)
    return cluster, breakdown, centroids


def correlation_payload(df: pd.DataFrame, numeric_cols: list[str]) -> tuple[dict[str, dict[str, dict[str, float]]], list[dict[str, Any]]]:
    cols = numeric_cols[:6]
    if len(cols) < 2:
        return {}, []
    source = df[cols].apply(pd.to_numeric, errors='coerce')
    corr_pearson = source.corr(method='pearson').fillna(0).round(4)
    corr_spearman = source.corr(method='spearman').fillna(0).round(4)
    all_edges = []
    for i, src in enumerate(cols):
        for dst in cols[i + 1:]:
            pair = source[[src, dst]].dropna()
            n = int(len(pair))
            weight = float(corr_spearman.loc[src, dst])
            all_edges.append({
                'source': src,
                'target': dst,
                'weight': round(weight, 4),
                'n': n,
                'p_value': round(float(fisher_pvalue_from_r(weight, n)), 8),
                'method': 'spearman',
            })
    fdr_values = benjamini_hochberg_fdr([float(item['p_value']) for item in all_edges])
    for idx, fdr in enumerate(fdr_values):
        all_edges[idx]['fdr'] = round(float(fdr), 8)
    edges = [item for item in all_edges if abs(float(item.get('weight', 0.0))) >= 0.28]
    edges.sort(key=lambda item: abs(item['weight']), reverse=True)
    return {'pearson': corr_pearson.to_dict(), 'spearman': corr_spearman.to_dict()}, edges[:20]


def scatter_payload(df: pd.DataFrame, numeric_cols: list[str], id_col: str) -> dict[str, Any]:
    if len(numeric_cols) < 2:
        return {}
    label_col = first_present(df.columns.tolist(), ['gene_name', 'display_name', id_col]) or id_col
    pairs = []
    for i in range(min(len(numeric_cols) - 1, 3)):
        pairs.append((numeric_cols[i], numeric_cols[i + 1]))
    payload = {}
    for x, y in pairs:
        key = f'{x}_vs_{y}'
        cols = [id_col, label_col, x, y]
        part = df[[c for c in cols if c in df.columns]].copy()
        if len(part) > 500:
            seed = sum(ord(ch) for ch in key) % (2**32 - 1)
            part = part.sample(n=500, random_state=seed)
        payload[key] = part.to_dict(orient='records')
    return payload


def build_summary(df: pd.DataFrame, omics: str, species_row: dict[str, Any]) -> dict[str, Any]:
    id_col = first_present(df.columns.tolist(), [OMICS_META[omics]['primary_id'], OMICS_META[omics]['fallback_id']]) or df.columns[0]
    label_cols = [c for c in ['gene_name', 'gene_id', 'transcript_id', 'protein_id', 'strategy_cluster'] if c in df.columns]
    numeric_cols = numeric_columns(df)
    feature_cols = [col for col in DEFAULT_FEATURE_PRIORITY[omics] if col in df.columns]
    if len(feature_cols) < 4:
        feature_cols = (feature_cols + [col for col in numeric_cols if col not in feature_cols])[:6]

    feature_cards = {col: percentile_summary(df[col]) for col in feature_cols}
    distributions = {col: hist_payload(df[col]) for col in feature_cols[:4]}
    cluster_labels, strategy_breakdown, centroids = simple_clusters(df, feature_cols or numeric_cols)
    if 'strategy_cluster' not in df.columns:
        df['strategy_cluster'] = cluster_labels
    corr_matrices, edges = correlation_payload(df, feature_cols or numeric_cols)
    scatter = scatter_payload(df, feature_cols or numeric_cols, id_col)
    score_col = (feature_cols or numeric_cols or [id_col])[0]
    tops = top_entities(df, id_col, label_cols, score_col) if score_col != id_col else {'top': [], 'bottom': []}
    field_meta = field_meta_for_omics(omics, df.columns.tolist())

    return {
        'scope': 'core',
        'available_scopes': ['core', 'full'],
        'field_meta': field_meta,
        'feature_cards': feature_cards,
        'distributions': distributions,
        'scatter': scatter,
        'correlation_matrix': corr_matrices.get('spearman', {}),
        'correlation_matrices': corr_matrices,
        'strategy_breakdown': strategy_breakdown,
        'cluster_centroids': centroids,
        'coupling_edges': edges,
        'preview_rows': df.head(12).replace({np.nan: None}).to_dict(orient='records'),
        'top_entities': tops,
        'browse_note': f"Auto-generated summary for {species_row['display_name']} {omics} from real feature rows.",
    }


def build_analysis(df: pd.DataFrame, omics: str) -> dict[str, Any]:
    numeric_cols = numeric_columns(df)
    feature_cols = [col for col in DEFAULT_FEATURE_PRIORITY[omics] if col in df.columns] or numeric_cols[:6]
    score_col = 'strategy_score' if 'strategy_score' in df.columns else (feature_cols[0] if feature_cols else None)
    id_col = first_present(df.columns.tolist(), [OMICS_META[omics]['primary_id'], OMICS_META[omics]['fallback_id']]) or df.columns[0]
    label_cols = [c for c in ['gene_name', id_col] if c in df.columns]

    outliers = {
        'high': [],
        'low': [],
        'multivariate': [],
        'feature_contributions': {},
    }
    tradeoff_front = []
    robust_n = 0
    if score_col:
        cols = []
        for col in [id_col] + label_cols + feature_cols[:2] + [score_col]:
            if col in df.columns and col not in cols:
                cols.append(col)
        scored = df[cols].copy()
        series = pd.to_numeric(df[score_col], errors='coerce')
        valid = series.dropna()
        center = float(valid.median()) if not valid.empty else 0.0
        mad = float((valid - center).abs().median()) if not valid.empty else 0.0
        std = float(valid.std(ddof=0)) if not valid.empty else 0.0
        scale = (1.4826 * mad) if mad > 0 else (std if std > 0 else 1.0)
        robust_n = int(len(valid))
        scored['robust_z'] = (pd.to_numeric(scored[score_col], errors='coerce') - center) / scale
        scored['outlier_score'] = scored['robust_z'].abs()
        high_df = scored[scored['robust_z'] >= 2.5].copy()
        low_df = scored[scored['robust_z'] <= -2.5].copy()
        if high_df.empty and low_df.empty:
            high_df = scored.nlargest(min(12, len(scored)), 'robust_z')
            low_df = scored.nsmallest(min(12, len(scored)), 'robust_z')
        else:
            high_df = high_df.sort_values('robust_z', ascending=False).head(24)
            low_df = low_df.sort_values('robust_z', ascending=True).head(24)
        high_rows = high_df.replace({np.nan: None}).to_dict(orient='records')
        low_rows = low_df.replace({np.nan: None}).to_dict(orient='records')
        for idx, row in enumerate(high_rows, start=1):
            row['outlier_rank'] = idx
            row['outlier_label'] = 'candidate'
        for idx, row in enumerate(low_rows, start=1):
            row['outlier_rank'] = idx
            row['outlier_label'] = 'candidate'
        outliers['high'] = high_rows
        outliers['low'] = low_rows

    if len(feature_cols) >= 2:
        x_col, y_col = feature_cols[:2]
        part = df[[c for c in [id_col, 'gene_name', x_col, y_col] if c in df.columns]].copy().head(240)
        part = part.rename(columns={x_col: 'cost_axis', y_col: 'adapt_axis'})
        part['front_score'] = (pd.to_numeric(part['cost_axis'], errors='coerce').rank(pct=True) + pd.to_numeric(part['adapt_axis'], errors='coerce').rank(pct=True)) / 2
        part['front_rank'] = pareto_front_ranks(part, 'cost_axis', 'adapt_axis')
        part = part.sort_values(['front_rank', 'front_score'], ascending=[True, False])
        tradeoff_front = part.replace({np.nan: None}).to_dict(orient='records')

    payload: dict[str, Any] = {
        'scope': 'core',
        'evidence_level': 'exploratory',
        'result_type': 'hypothesis_generating',
        'outliers': outliers,
        'tradeoff_front': tradeoff_front,
        'method_metadata': {
            'outliers': {
                'method': 'robust_zscore_mad',
                'scale': score_col or 'strategy_score',
                'thresholds': {'high': 2.5, 'low': -2.5},
                'n_entities': robust_n,
                'center': 'median',
                'scale_detail': '1.4826_mad_fallback_std',
                'missing_policy': 'pairwise_complete',
                'evidence_level': 'exploratory',
            },
            'tradeoff_front': {
                'method': 'non_dominated_sorting',
                'axes': {'cost_axis': 'minimize', 'adapt_axis': 'maximize'},
                'evidence_level': 'exploratory',
            },
            'coupling_network': {
                'method': 'spearman_association',
                'multiple_testing': 'benjamini_hochberg_fdr',
                'evidence_level': 'exploratory',
            },
        },
        'display_labels': {
            'outliers': 'Candidate outliers',
            'tradeoff_front': 'Trade-off landscape',
            'coupling_edges': 'Feature coupling network',
            'strategy_breakdown': 'Exploratory strategy groups',
        },
    }
    if omics == 'genome':
        sort_cols = [c for c in ['seqid', 'start_1', 'end_1'] if c in df.columns]
        ordered = df.sort_values(sort_cols) if sort_cols else df
        block_size = max(120, len(ordered) // 12)
        islands = []
        for idx, (_, part) in enumerate(ordered.groupby(np.arange(len(ordered)) // block_size), start=1):
            score = pd.to_numeric(part.get('stoich_island_score'), errors='coerce').fillna(0)
            islands.append({
                'segment': f'Window {idx}',
                'seqid': str(part.get('seqid').iloc[0]) if 'seqid' in part.columns and len(part) else '',
                'start': int(pd.to_numeric(part.get('start_1'), errors='coerce').min()) if 'start_1' in part.columns else None,
                'end': int(pd.to_numeric(part.get('end_1'), errors='coerce').max()) if 'end_1' in part.columns else None,
                'gene_count': int(len(part)),
                'mean_island_score': round(float(score.mean()), 4),
            })
        payload['stoich_islands'] = islands
        payload['display_labels']['stoich_islands'] = 'Stoichiometric island candidates'
    elif omics == 'transcriptome':
        theme_col = first_present(df.columns.tolist(), ['motif_theme', 'strategy_cluster'])
        if theme_col:
            counts = df[theme_col].astype(str).value_counts().head(6)
            themes = [{'theme': k, 'count': int(v)} for k, v in counts.items()]
            payload['motif_themes'] = themes
            payload['composition_themes'] = themes
        else:
            payload['motif_themes'] = []
            payload['composition_themes'] = []
        payload['display_labels']['motif_themes'] = 'Compositional themes'
    else:
        means = [
            {'feature': col, 'mean': round(float(pd.to_numeric(df[col], errors='coerce').mean()), 4)}
            for col in feature_cols[:6]
        ]
        payload['resource_budget'] = means
        payload['sequence_intrinsic_resource_profile'] = means
        payload['display_labels']['resource_budget'] = 'Sequence-intrinsic resource profile'
    return payload


def derive_kpis(df: pd.DataFrame, omics: str) -> dict[str, Any]:
    numeric_cols = numeric_columns(df)
    feature_cols = [col for col in DEFAULT_FEATURE_PRIORITY[omics] if col in df.columns] or numeric_cols[:3]
    kpis = {'row_count': int(len(df))}
    for col in feature_cols[:3]:
        kpis[col] = round(float(pd.to_numeric(df[col], errors='coerce').mean()), 4)
    return kpis


def derive_fingerprint(species_row: dict[str, Any], omics_summaries: dict[str, dict[str, Any]], omics_rows: dict[str, pd.DataFrame]) -> dict[str, float]:
    result = {}
    for out_key, candidates in FINGERPRINT_MAP.items():
        value = None
        for candidate in candidates:
            if candidate in species_row and pd.notna(species_row[candidate]):
                value = species_row[candidate]
                break
            for omics, df in omics_rows.items():
                if candidate in df.columns:
                    value = round(float(pd.to_numeric(df[candidate], errors='coerce').mean()), 4)
                    break
            if value is not None:
                break
        result[out_key] = round(float(value), 4) if value is not None else 0.0
    return result


def merge_payload(default_payload: dict[str, Any], override_payload: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(default_payload)
    if not isinstance(override_payload, dict):
        return merged
    for key, value in override_payload.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged.get(key) or {})
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def enhance_analysis_payload(payload: dict[str, Any] | None, defaults: dict[str, Any]) -> dict[str, Any]:
    merged = merge_payload(defaults, payload or {})
    merged.setdefault('evidence_level', 'exploratory')
    merged.setdefault('result_type', 'hypothesis_generating')
    merged.setdefault('scope', 'core')

    outliers = merged.get('outliers') if isinstance(merged.get('outliers'), dict) else {}
    for side in ['high', 'low']:
        rows = outliers.get(side)
        if not isinstance(rows, list):
            continue
        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            row.setdefault('outlier_rank', idx)
            row.setdefault('outlier_label', 'candidate')
    merged['outliers'] = outliers

    tradeoff = merged.get('tradeoff_front')
    if isinstance(tradeoff, list) and tradeoff:
        frame = pd.DataFrame([row if isinstance(row, dict) else {} for row in tradeoff])
        if not frame.empty and {'cost_axis', 'adapt_axis'}.issubset(frame.columns):
            ranks = pareto_front_ranks(frame, 'cost_axis', 'adapt_axis')
            for idx, row in enumerate(tradeoff):
                if isinstance(row, dict):
                    row.setdefault('front_rank', int(ranks[idx]) if idx < len(ranks) else 0)
            merged['tradeoff_front'] = tradeoff

    if 'composition_themes' not in merged and isinstance(merged.get('motif_themes'), list):
        merged['composition_themes'] = merged.get('motif_themes')
    if 'sequence_intrinsic_resource_profile' not in merged and isinstance(merged.get('resource_budget'), list):
        merged['sequence_intrinsic_resource_profile'] = merged.get('resource_budget')
    return merged


def outlier_gene_set_from_analysis(analysis_payload: dict[str, Any] | None, df: pd.DataFrame | None, omics: str) -> set[str]:
    if not isinstance(analysis_payload, dict):
        return set()
    outliers = analysis_payload.get('outliers')
    if not isinstance(outliers, dict):
        return set()

    rows: list[dict[str, Any]] = []
    for bucket in outliers.values():
        if isinstance(bucket, list):
            rows.extend([item for item in bucket if isinstance(item, dict)])
    if not rows:
        return set()

    genes: set[str] = set()
    pending_ids: set[str] = set()
    for row in rows:
        for gene_key in ['gene_id', 'ensembl_gene_id']:
            gene = str(row.get(gene_key) or '').strip()
            if gene:
                genes.add(gene)
        for id_key in ['entity_id', 'transcript_id', 'protein_id']:
            value = str(row.get(id_key) or '').strip()
            if value:
                pending_ids.add(value)

    if genes or df is None or df.empty or not pending_ids:
        return genes

    id_col = first_present(df.columns.tolist(), [OMICS_META[omics]['primary_id'], OMICS_META[omics]['fallback_id']])
    id_cols = [col for col in ['entity_id', id_col, 'transcript_id', 'protein_id'] if col and col in df.columns]
    gene_cols = [col for col in ['gene_id', 'ensembl_gene_id'] if col in df.columns]
    if not id_cols or not gene_cols:
        return genes

    subset = df[id_cols + gene_cols]
    for _, row in subset.iterrows():
        gene = ''
        for gene_col in gene_cols:
            gene_value = str(row.get(gene_col) or '').strip()
            if gene_value:
                gene = gene_value
                break
        if not gene:
            continue
        for entity_col in id_cols:
            entity = str(row.get(entity_col) or '').strip()
            if entity and entity in pending_ids:
                genes.add(gene)
                break
    return genes


def shared_outlier_summary(gene_sets: dict[str, set[str]]) -> dict[str, Any]:
    genome = set(gene_sets.get('genome') or set())
    transcriptome = set(gene_sets.get('transcriptome') or set())
    proteome = set(gene_sets.get('proteome') or set())
    all_three = sorted(genome & transcriptome & proteome)
    return {
        'genome_only': sorted(genome - transcriptome - proteome)[:200],
        'transcriptome_only': sorted(transcriptome - genome - proteome)[:200],
        'proteome_only': sorted(proteome - genome - transcriptome)[:200],
        'shared_all_three': all_three[:200],
        'counts': {
            'genome_only': int(len(genome - transcriptome - proteome)),
            'transcriptome_only': int(len(transcriptome - genome - proteome)),
            'proteome_only': int(len(proteome - genome - transcriptome)),
            'shared_all_three': int(len(all_three)),
        },
    }


def build_cross_omics(
    species_id: str,
    omics_rows: dict[str, pd.DataFrame],
    fingerprint: dict[str, float],
    outlier_gene_sets: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    genome = omics_rows.get('genome', pd.DataFrame())
    transcriptome = omics_rows.get('transcriptome', pd.DataFrame())
    proteome = omics_rows.get('proteome', pd.DataFrame())

    join_key = first_present(genome.columns.tolist(), ['gene_id', 'entity_id'])
    transcript_key = first_present(transcriptome.columns.tolist(), ['gene_id', 'entity_id'])
    proteome_key = first_present(proteome.columns.tolist(), ['ensembl_gene_id', 'gene_id', 'entity_id'])

    merged = pd.DataFrame()
    if not genome.empty and not transcriptome.empty and join_key and transcript_key:
        merged = genome.merge(transcriptome, left_on=join_key, right_on=transcript_key, suffixes=('_genome', '_rna'))
        if not proteome.empty and proteome_key:
            merged = merged.merge(proteome, left_on=join_key, right_on=proteome_key, suffixes=('', '_protein'))

    genome_rows = int(len(genome))
    transcript_rows = int(len(transcriptome))
    proteome_rows = int(len(proteome))
    genome_genes = set(genome['gene_id'].astype(str)) if 'gene_id' in genome.columns else set()
    transcript_genes = set(transcriptome['gene_id'].astype(str)) if 'gene_id' in transcriptome.columns else set()
    proteome_genes = (
        set(proteome['ensembl_gene_id'].astype(str))
        if 'ensembl_gene_id' in proteome.columns
        else (set(proteome['gene_id'].astype(str)) if 'gene_id' in proteome.columns else set())
    )
    matched_gt = len(genome_genes & transcript_genes)
    matched_tp = len(transcript_genes & proteome_genes)
    matched_all = len(genome_genes & transcript_genes & proteome_genes)

    corr_matrices: dict[str, dict[str, dict[str, float]]] = {}
    corr_details: list[dict[str, Any]] = []
    cross_points = []
    transformations: list[dict[str, Any]] = []
    if not merged.empty:
        gcol = first_present(merged.columns.tolist(), ['exon_gc_percent', 'gc_mean', 'exon_gc_percent_genome'])
        gncol = first_present(merged.columns.tolist(), ['exon_atoms_N_per_base', 'genome_n_per_base'])
        pcol = first_present(merged.columns.tolist(), ['N_atoms_per_aa', 'proteome_n_per_aa'])
        tncol = first_present(merged.columns.tolist(), ['atoms_per_nt_N', 'transcript_n_per_nt'])
        rcol = first_present(merged.columns.tolist(), ['gc_content', 'transcript_gc', 'gc_percent_display'])
        label = first_present(merged.columns.tolist(), ['gene_name', 'gene_symbol', join_key]) or join_key

        if gcol and pcol:
            points = merged[[c for c in [label, gcol, pcol] if c in merged.columns]].copy()
            if len(points) > 500:
                points = points.sample(n=500, random_state=19)
            cross_points = points.rename(columns={label: 'gene_name', gcol: 'exon_gc_percent', pcol: 'proteome_n_per_aa'}).replace({np.nan: None}).to_dict(orient='records')

        if gncol and tncol and pcol:
            part = merged.copy()
            transcript_gc = pd.to_numeric(part.get(rcol), errors='coerce') if rcol else pd.Series([np.nan] * len(part))
            gc_scale = 100.0 if (not transcript_gc.dropna().empty and float(transcript_gc.dropna().max()) <= 1.5) else 1.0
            part['dna_to_rna_n_shift'] = pd.to_numeric(part.get(tncol), errors='coerce') - pd.to_numeric(part.get(gncol), errors='coerce')
            part['rna_to_protein_n_shift'] = pd.to_numeric(part.get(pcol), errors='coerce') - pd.to_numeric(part.get(tncol), errors='coerce')
            part['dna_to_rna_n_delta'] = part['dna_to_rna_n_shift']
            part['rna_to_protein_n_delta'] = part['rna_to_protein_n_shift']
            part['dna_to_rna_gc_delta'] = (transcript_gc * gc_scale) - pd.to_numeric(part.get(gcol), errors='coerce') if gcol else np.nan
            part['discordance_score'] = (
                part['dna_to_rna_n_delta'].abs().fillna(0)
                + part['rna_to_protein_n_delta'].abs().fillna(0)
                + (part['dna_to_rna_n_delta'].fillna(0) - part['rna_to_protein_n_delta'].fillna(0)).abs()
            ).round(6)
            part['main_driver'] = np.where(
                part['dna_to_rna_n_delta'].abs() >= part['rna_to_protein_n_delta'].abs(),
                'DNA_to_RNA_shift',
                'RNA_to_protein_shift',
            )
            gene_col = first_present(part.columns.tolist(), ['gene_id', 'gene_id_genome', join_key]) or join_key
            part_out = pd.DataFrame({
                'entity_id': part.get(join_key, part.get(gene_col)),
                'gene_id': part.get(gene_col),
                'gene_name': part.get(label, part.get('gene_symbol')),
                'dna_to_rna_n_shift': part.get('dna_to_rna_n_shift'),
                'rna_to_protein_n_shift': part.get('rna_to_protein_n_shift'),
                'dna_to_rna_n_delta': part.get('dna_to_rna_n_delta'),
                'rna_to_protein_n_delta': part.get('rna_to_protein_n_delta'),
                'dna_to_rna_gc_delta': part.get('dna_to_rna_gc_delta'),
                'discordance_score': part.get('discordance_score'),
                'main_driver': part.get('main_driver'),
                'pI': pd.to_numeric(part.get('pI'), errors='coerce'),
                'gravy': pd.to_numeric(part.get('gravy'), errors='coerce'),
            }).dropna(subset=['gene_id'])
            part_out = part_out.sort_values('discordance_score', ascending=False)
            transformations = part_out.head(500).replace({np.nan: None}).to_dict(orient='records')

        if gcol and rcol and pcol:
            corr_frame = merged[[gcol, rcol, pcol]].apply(pd.to_numeric, errors='coerce')
            corr_frame.columns = ['genome_gc', 'transcript_gc', 'proteome_n_per_aa']
            corr_frame = corr_frame.dropna()
            if len(corr_frame) >= 2:
                corr_matrices = {
                    'pearson': corr_frame.corr(method='pearson').fillna(0).round(4).to_dict(),
                    'spearman': corr_frame.corr(method='spearman').fillna(0).round(4).to_dict(),
                }
                pvals = []
                pairs = []
                cols = corr_frame.columns.tolist()
                spearman_matrix = corr_frame.corr(method='spearman')
                for i, src in enumerate(cols):
                    for dst in cols[i + 1:]:
                        r_value = float(spearman_matrix.loc[src, dst])
                        pval = fisher_pvalue_from_r(r_value, int(len(corr_frame)))
                        pvals.append(pval)
                        pairs.append((src, dst, r_value, pval))
                fdr_values = benjamini_hochberg_fdr(pvals)
                for idx, (src, dst, r_value, pval) in enumerate(pairs):
                    corr_details.append({
                        'method': 'spearman',
                        'feature_a': src,
                        'feature_b': dst,
                        'r': round(float(r_value), 6),
                        'n': int(len(corr_frame)),
                        'p_value': round(float(pval), 8),
                        'fdr': round(float(fdr_values[idx]), 8),
                    })

    if not corr_matrices:
        fallback = {
            'genome_gc': {'genome_gc': 1.0, 'transcript_gc': 0.0, 'proteome_n_per_aa': 0.0},
            'transcript_gc': {'genome_gc': 0.0, 'transcript_gc': 1.0, 'proteome_n_per_aa': 0.0},
            'proteome_n_per_aa': {'genome_gc': 0.0, 'transcript_gc': 0.0, 'proteome_n_per_aa': 1.0},
        }
        corr_matrices = {'pearson': fallback, 'spearman': fallback}

    top_transformations = transformations[:24]
    shared_outliers = shared_outlier_summary(outlier_gene_sets or {})
    return {
        'species_id': species_id,
        'fingerprint': fingerprint,
        'correlation_matrix': corr_matrices.get('spearman', {}),
        'correlation_matrices': corr_matrices,
        'correlation_details': corr_details,
        'join_summary': {
            'genome_rows': genome_rows,
            'transcriptome_rows': transcript_rows,
            'proteome_rows': proteome_rows,
            'matched_genome_transcriptome': int(matched_gt),
            'matched_transcriptome_proteome': int(matched_tp),
            'matched_all_three': int(matched_all),
            'match_rate_genome_transcriptome': round(float(matched_gt / max(1, min(len(genome_genes), len(transcript_genes)))) if genome_genes and transcript_genes else 0.0, 6),
            'match_rate_transcriptome_proteome': round(float(matched_tp / max(1, min(len(transcript_genes), len(proteome_genes)))) if transcript_genes and proteome_genes else 0.0, 6),
            'match_rate_all_three': round(float(matched_all / max(1, min(len(genome_genes), len(transcript_genes), len(proteome_genes)))) if genome_genes and transcript_genes and proteome_genes else 0.0, 6),
        },
        'cross_points': cross_points,
        'transformations': transformations,
        'top_transformations': top_transformations,
        'shared_outliers': shared_outliers,
        'method_metadata': {
            'join_panel': {'method': 'gene_level_id_mapping', 'evidence_level': 'exploratory'},
            'correlation': {'method': 'spearman', 'multiple_testing': 'benjamini_hochberg_fdr', 'evidence_level': 'exploratory'},
            'transformations': {'method': 'explicit_delta_and_discordance', 'direction': 'DNA_to_RNA_to_Protein', 'evidence_level': 'exploratory'},
            'shared_outliers': {'method': 'set_overlap_of_candidate_outliers', 'evidence_level': 'exploratory'},
        },
        'evidence_level': 'exploratory',
    }


def merge_cross_payload(existing_payload: dict[str, Any] | None, computed_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(existing_payload, dict):
        return computed_payload
    merged = dict(existing_payload)
    for key in [
        'species_id',
        'fingerprint',
        'correlation_matrix',
        'correlation_matrices',
        'correlation_details',
        'join_summary',
        'cross_points',
        'transformations',
        'top_transformations',
        'shared_outliers',
        'method_metadata',
        'evidence_level',
    ]:
        merged[key] = computed_payload.get(key)
    return merged


def compare_pairs(species_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = list(FINGERPRINT_MAP.keys())
    pairs = []
    if not species_rows:
        return pairs
    matrix = np.array([[float(row['fingerprint'].get(key, 0)) for key in keys] for row in species_rows], dtype=float)
    medians = np.median(matrix, axis=0)
    mad = np.median(np.abs(matrix - medians), axis=0)
    robust_scale = 1.4826 * mad
    std = np.std(matrix, axis=0)
    scales = np.where(robust_scale > 0, robust_scale, np.where(std > 0, std, 1.0))
    scaled = (matrix - medians) / scales
    for i, src in enumerate(species_rows):
        for j in range(i + 1, len(species_rows)):
            dst = species_rows[j]
            distance = float(np.linalg.norm(scaled[i] - scaled[j]))
            pairs.append({
                'source': src['species_id'],
                'target': dst['species_id'],
                'distance': round(distance, 4),
                'method': 'euclidean',
                'normalization': 'robust_zscore',
                'n_features': len(keys),
            })
    return sorted(pairs, key=lambda item: item['distance'])


def to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{k: maybe_round(v) for k, v in row.items()} for row in df.replace({np.nan: None}).to_dict(orient='records')]


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def main() -> None:
    args = parse_args()
    metadata = read_metadata(Path(args.metadata), args.format)
    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    ensure_dir(output_root)

    required_cols = ['species_id', 'display_name', 'short_name', 'domain', 'clade', 'habitat', 'genome_size_mb']
    missing = [col for col in required_cols if col not in metadata.columns]
    if missing:
        raise SystemExit(f'Metadata missing required columns: {missing}')

    species_index = []
    for meta_row in metadata.to_dict(orient='records'):
        species_id = str(meta_row['species_id'])
        species_dir = output_root / species_id
        ensure_dir(species_dir)
        omics_index = {}
        omics_rows: dict[str, pd.DataFrame] = {}
        omics_analysis: dict[str, dict[str, Any]] = {}

        for omics, info in OMICS_META.items():
            omics_input = input_root / species_id / omics
            if not omics_input.exists():
                continue
            table_path = None
            for candidate in ['rows.parquet', 'rows.csv', 'rows.tsv', 'rows.json']:
                path = omics_input / candidate
                if feature_io.source_exists(path):
                    table_path = path
                    break
            if table_path is None:
                continue

            df = normalize_rows(read_table(table_path).copy(), omics)
            primary_id = first_present(df.columns.tolist(), [info['primary_id'], info['fallback_id']])
            if primary_id is None:
                raise SystemExit(f'{species_id}/{omics} is missing primary identifier columns {info["primary_id"]}/{info["fallback_id"]}')
            if 'entity_id' not in df.columns:
                df['entity_id'] = df[primary_id]

            summary_path = omics_input / 'summary.json'
            analysis_path = omics_input / 'analysis.json'
            summary = json.loads(summary_path.read_text(encoding='utf-8')) if feature_io.source_exists(summary_path) else build_summary(df, omics, meta_row)
            analysis_default = build_analysis(df, omics)
            analysis_source = json.loads(analysis_path.read_text(encoding='utf-8')) if feature_io.source_exists(analysis_path) else {}
            analysis = enhance_analysis_payload(analysis_source, analysis_default)

            omics_out = species_dir / omics
            ensure_dir(omics_out)
            write_json(omics_out / 'rows.json', to_records(df))
            write_json(omics_out / 'summary.json', summary)
            write_json(omics_out / 'analysis.json', analysis)

            meta = DEFAULT_FEATURE_PRIORITY[omics]
            browse_columns = [col for col in [primary_id, 'gene_name', 'biotype', 'strand', 'length_aa', *meta] if col in df.columns][:8]
            omics_index[omics] = {
                'row_count': int(len(df)),
                'kpis': derive_kpis(df, omics),
            }
            OMICS_META[omics]['browse_columns'] = browse_columns
            OMICS_META[omics]['feature_options'] = [col for col in meta if col in df.columns] or numeric_columns(df)[:8]
            omics_rows[omics] = df
            omics_analysis[omics] = analysis

        if not omics_rows:
            continue

        fingerprint = derive_fingerprint(meta_row, {}, omics_rows)
        cross_input = input_root / species_id / 'cross_omics.json'
        outlier_gene_sets = {
            omics: outlier_gene_set_from_analysis(omics_analysis.get(omics), omics_rows.get(omics), omics)
            for omics in ['genome', 'transcriptome', 'proteome']
        }
        computed_cross = build_cross_omics(species_id, omics_rows, fingerprint, outlier_gene_sets=outlier_gene_sets)
        cross_source = json.loads(cross_input.read_text(encoding='utf-8')) if cross_input.exists() else {}
        cross_payload = merge_cross_payload(cross_source, computed_cross)
        write_json(species_dir / 'cross_omics.json', cross_payload)

        species_index.append({
            'species_id': species_id,
            'display_name': meta_row['display_name'],
            'short_name': meta_row['short_name'],
            'domain': meta_row['domain'],
            'clade': meta_row['clade'],
            'habitat': meta_row['habitat'],
            'genome_size_mb': round(float(meta_row['genome_size_mb']), 4),
            'fingerprint': fingerprint,
            'omics': omics_index,
        })

    index_payload = {
        'project': {
            'species_count': len(species_index),
            'omics_types': list(OMICS_META.keys()),
            'modules': PROJECT_MODULES,
        },
        'species': species_index,
        'omics_meta': OMICS_META,
        'compare_pairs': compare_pairs(species_index),
    }
    write_json(output_root / 'index.json', index_payload)
    print(f'Built stoichdb registry at: {output_root}')
    print('Point the backend to it with: STOICHDB_DATA_ROOT=' + str(output_root))


if __name__ == '__main__':
    main()
