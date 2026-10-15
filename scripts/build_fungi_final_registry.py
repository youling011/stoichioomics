from __future__ import annotations

import argparse
import csv
import gc
import json
import shutil
import sys
import time
import warnings
from pathlib import Path

import pandas as pd
from pandas.errors import DtypeWarning

warnings.filterwarnings('ignore', message='DataFrame columns are not unique.*', category=UserWarning)
warnings.filterwarnings('ignore', category=DtypeWarning)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_feature_table_case_pipeline import (
    candidate_numeric,
    derive_fingerprint,
    display_name_from_source,
    ensure_dir,
    field_meta_for_omics,
    hist_payload,
    infer_genome_features,
    infer_primary_id,
    infer_proteome_features,
    infer_transcriptome_features,
    kpi_from_df,
    safe_float,
    PROJECT_MODULES,
    OMICS_META,
    numeric_columns,
    percentile_summary,
    profile_payload,
    records,
    select_row_subset,
    short_name,
    write_json,
)


OMICS_LAYOUT = {
    'genome': ('基因组', '.genome_features.core.csv'),
    'transcriptome': ('转录组', '.transcriptome.core.v5.csv'),
    'proteome': ('蛋白质组', '.proteome_features.core.csv'),
}

INDEX_COLUMNS = {
    'genome': ['species_id', 'gene_id', 'gene_name', 'locus_tag', 'biotype', 'seqid', 'start_1', 'end_1', 'strand'],
    'transcriptome': ['species_id', 'transcript_id', 'gene_id', 'gene_symbol', 'transcript_biotype', 'seq_region', 'start', 'end', 'strand'],
    'proteome': ['species_id', 'protein_id', 'ensembl_gene_id', 'gene_id', 'gene_symbol', 'description', 'length_aa'],
}

INDEX_FILES = {
    'genome': 'gene_index.csv',
    'transcriptome': 'transcript_index.csv',
    'proteome': 'protein_index.csv',
}

PREFERRED_FEATURES = {
    'genome': ['exon_gc_percent', 'promoter_gc_percent', 'gc_delta_promoter_minus_exon', 'exon_atoms_N_per_base', 'gc3_percent', 'stoich_island_score'],
    'transcriptome': ['gc_percent_display', 'nt_entropy', 'atoms_per_nt_N', 'atoms_per_nt_P', 'rna_orf_coupling_score', 'protein_gravy_proxy'],
    'proteome': ['N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy', 'resource_budget_score', 'adaptation_score'],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Build fungi stage4/stage5/stage6 registry from the final screened species whitelist.'
    )
    parser.add_argument('--source-root', required=True, help='Fungi feature-data root directory.')
    parser.add_argument('--whitelist', required=True, help='Final screened Fungi species whitelist CSV.')
    parser.add_argument('--output-root', required=True, help='Output fungi pipeline directory.')
    parser.add_argument('--max-compare-pairs', type=int, default=250000, help='Maximum compare_pairs rows to write. Large taxa use capped neighbor pairs to avoid O(n^2) memory.')
    parser.add_argument('--max-compare-neighbors', type=int, default=8, help='Neighbor pairs per species when pairwise compare is capped.')
    parser.add_argument('--stage6-progress-step', type=int, default=25, help='Print Stage6 progress every N species and keep resume markers.')
    return parser.parse_args()


def resolve_core_path(source_root: Path, species_id: str, omics: str) -> Path:
    subdir, suffix = OMICS_LAYOUT[omics]
    base = source_root / subdir
    direct = base / f'{species_id}{suffix}'
    if direct.exists():
        return direct
    nested = base / species_id / f'{species_id}{suffix}'
    if nested.exists():
        return nested
    raise FileNotFoundError(f'Missing {omics} core feature table for {species_id}: {direct} or {nested}')


def build_metadata(whitelist_df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for row in whitelist_df.to_dict(orient='records'):
        species_id = str(row['species']).strip()
        display_name = display_name_from_source(species_id)
        records.append({
            'species_id': species_id,
            'display_name': display_name,
            'short_name': short_name(display_name),
            'source_species_id': species_id,
            'domain': 'Fungi',
            'clade': str(row.get('qc_grade') or 'Final screened whitelist'),
            'habitat': 'Not provided',
            'genome_size_mb': 0.0,
            'has_genome': True,
            'has_transcriptome': True,
            'has_proteome': True,
        })
    return pd.DataFrame(records).sort_values('species_id')


def stream_stage4_catalog(
    metadata: pd.DataFrame,
    species_tables: dict[str, dict[str, dict[str, Path]]],
    stage4_dir: Path,
    chunk_size: int = 50000,
) -> None:
    ensure_dir(stage4_dir)
    db_seed = stage4_dir / 'db_seed'
    ensure_dir(db_seed)

    metadata.to_csv(db_seed / 'species.csv', index=False)
    for filename in INDEX_FILES.values():
        target = db_seed / filename
        if target.exists():
            target.unlink()

    dataset_rows = []
    feature_file_rows = []
    index_counts = {'genome': 0, 'transcriptome': 0, 'proteome': 0}
    for species_id in metadata['species_id'].astype(str):
        for omics in ['genome', 'transcriptome', 'proteome']:
            core_path = species_tables[species_id][omics]['core']
            row_count = 0
            target = db_seed / INDEX_FILES[omics]
            columns = INDEX_COLUMNS[omics]
            wrote_header = target.exists()
            for chunk in pd.read_csv(core_path, low_memory=False, chunksize=chunk_size):
                row_count += len(chunk)
                if 'species_id' not in chunk.columns:
                    chunk['species_id'] = species_id
                out = chunk.reindex(columns=columns)
                out.to_csv(target, mode='a', header=not wrote_header, index=False)
                wrote_header = True
            index_counts[omics] += row_count
            dataset_rows.append({
                'dataset_id': f'{species_id}__{omics}',
                'species_id': species_id,
                'omics_type': omics.upper(),
                'schema_version': 'auto_v1',
                'row_count_core': int(row_count),
                'row_count_full': 0,
                'core_csv_path': str(core_path),
                'full_csv_path': '',
                'status': 'ready',
            })
            feature_file_rows.append({
                'file_id': f'{species_id}__{omics}__core',
                'dataset_id': f'{species_id}__{omics}',
                'file_type': 'core',
                'path': str(core_path),
                'size_bytes': core_path.stat().st_size,
            })

    pd.DataFrame(dataset_rows).to_csv(db_seed / 'omics_dataset.csv', index=False)
    pd.DataFrame(feature_file_rows).to_csv(db_seed / 'feature_file.csv', index=False)
    write_json(stage4_dir / 'catalog_manifest.json', {
        'stage': 'stage4_catalog',
        'species_rows': int(len(metadata)),
        'dataset_rows': int(len(dataset_rows)),
        'gene_index_rows': int(index_counts['genome']),
        'transcript_index_rows': int(index_counts['transcriptome']),
        'protein_index_rows': int(index_counts['proteome']),
        'materialized_scope': 'core',
        'writer': 'streaming',
    })


def augment_rows(df: pd.DataFrame, omics: str) -> tuple[pd.DataFrame, list[str], list[str]]:
    if omics == 'genome':
        return infer_genome_features(df)
    if omics == 'transcriptome':
        return infer_transcriptome_features(df)
    return infer_proteome_features(df)


def light_summary(df: pd.DataFrame, omics: str, species_row: dict, core_cols: list[str]) -> dict:
    primary_id = infer_primary_id(omics, df.columns.tolist())
    field_meta = field_meta_for_omics(omics, df.columns.tolist())
    feature_cards = {col: percentile_summary(df[col]) for col in core_cols if col in df.columns}
    distributions = {col: hist_payload(df[col]) for col in core_cols[:4] if col in df.columns}
    preview_cols = [c for c in [primary_id, 'entity_id', 'gene_id', 'gene_name', 'strategy_cluster'] + core_cols[:5] if c in df.columns]
    return {
        'species_id': species_row['species_id'],
        'display_name': species_row['display_name'],
        'omics': omics,
        'scope': 'core',
        'available_scopes': ['core'],
        'row_count': int(len(df)),
        'primary_id': primary_id,
        'field_meta': field_meta,
        'kpis': kpi_from_df(df, omics),
        'feature_cards': feature_cards,
        'distributions': distributions,
        'scatter': {'x': core_cols[0] if core_cols else '', 'y': core_cols[1] if len(core_cols) > 1 else '', 'points': records(df[preview_cols].head(300)) if preview_cols else []},
        'preview_rows': records(df[preview_cols].head(20)) if preview_cols else [],
        'missingness': [
            {'field': col, 'missing_fraction': round(float(df[col].isna().mean()), 6)}
            for col in core_cols[:8]
            if col in df.columns
        ],
    }


def light_analysis(df: pd.DataFrame, omics: str, core_cols: list[str]) -> dict:
    primary_id = infer_primary_id(omics, df.columns.tolist())
    score_col = 'strategy_score' if 'strategy_score' in df.columns else (core_cols[0] if core_cols else '')
    outliers = {'high': [], 'low': []}
    if score_col:
        cols = [c for c in [primary_id, 'entity_id', 'gene_id', 'gene_name', score_col] + core_cols[:3] if c in df.columns]
        scored = df[cols].copy()
        scored[score_col] = pd.to_numeric(scored[score_col], errors='coerce')
        scored = scored.dropna(subset=[score_col])
        outliers = {
            'high': records(scored.nlargest(min(12, len(scored)), score_col)),
            'low': records(scored.nsmallest(min(12, len(scored)), score_col)),
        }
    return {
        'omics': omics,
        'feature_set': core_cols,
        'outliers': outliers,
        'tradeoff_front': [],
        'correlations': [],
        'method_metadata': {
            'summary': 'lightweight_final_whitelist_core_import',
            'materialized_scope': 'core',
        },
    }


def build_light_stage5(
    metadata: pd.DataFrame,
    species_tables: dict[str, dict[str, dict[str, Path]]],
    stage5_dir: Path,
    max_compare_pairs: int = 250000,
    max_compare_neighbors: int = 8,
) -> None:
    ensure_dir(stage5_dir)
    compare_dir = stage5_dir / 'compare'
    ensure_dir(compare_dir)

    manifest_path = stage5_dir / 'artifact_manifest.json'
    fingerprints_path = compare_dir / 'species_fingerprints.csv'
    compare_path = compare_dir / 'compare_pairs.csv'
    analysis_artifact_path = stage5_dir / 'analysis_artifact.csv'
    if manifest_path.exists() and fingerprints_path.exists() and compare_path.exists() and analysis_artifact_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if int(manifest.get('species_count') or 0) == int(len(metadata)):
                print(f'Stage5 already complete, skipping artifact rebuild: {stage5_dir}', flush=True)
                return
        except Exception:
            pass
    artifact_rows = []
    fingerprint_rows = []
    for idx, species_row in enumerate(metadata.to_dict(orient='records'), start=1):
        species_id = species_row['species_id']
        species_dir = stage5_dir / species_id
        ensure_dir(species_dir)
        expected_ready = (species_dir / 'cross_omics.json').exists() and (species_dir / 'browse_meta.json').exists()
        expected_ready = expected_ready and all(
            (species_dir / omics / 'rows_for_platform.csv').exists()
            and (species_dir / omics / 'summary.json').exists()
            and (species_dir / omics / 'analysis.json').exists()
            and (species_dir / omics / 'profile.json').exists()
            and (species_dir / omics / 'core_features.json').exists()
            for omics in ['genome', 'transcriptome', 'proteome']
        )
        if expected_ready:
            cross_payload = json.loads((species_dir / 'cross_omics.json').read_text(encoding='utf-8'))
            fingerprint_rows.append({'species_id': species_id, 'display_name': species_row['display_name'], **(cross_payload.get('fingerprint') or {})})
            for omics in ['genome', 'transcriptome', 'proteome']:
                omics_dir = species_dir / omics
                for artifact_name in ['profile.json', 'core_features.json', 'summary.json', 'analysis.json', 'rows_for_platform.csv']:
                    artifact_rows.append({
                        'species_id': species_id,
                        'omics_type': omics,
                        'artifact_type': artifact_name.replace('.json', '').replace('.csv', ''),
                        'path': str((omics_dir / artifact_name).relative_to(stage5_dir)),
                    })
            artifact_rows.append({
                'species_id': species_id,
                'omics_type': 'cross',
                'artifact_type': 'cross_omics',
                'path': str((species_dir / 'cross_omics.json').relative_to(stage5_dir)),
            })
            if idx == 1 or idx == len(metadata) or idx % 25 == 0:
                print(f'Stage5 fungi lightweight artifacts: {idx}/{len(metadata)} {species_id} (reused)', flush=True)
            continue
        transformed = {}
        browse_meta = {}
        for omics in ['genome', 'transcriptome', 'proteome']:
            source_path = species_tables[species_id][omics]['core']
            df = pd.read_csv(source_path, low_memory=False)
            if 'species_id' not in df.columns:
                df['species_id'] = species_id
            aug_df, inferred_cols, aux_cols = augment_rows(df, omics)
            core_cols = candidate_numeric(aug_df, PREFERRED_FEATURES[omics] + inferred_cols, max_cols=8)
            subset_rows, browse_columns, feature_options = select_row_subset(aug_df, omics)
            summary = light_summary(aug_df, omics, species_row, core_cols)
            analysis = light_analysis(aug_df, omics, core_cols)
            omics_dir = species_dir / omics
            ensure_dir(omics_dir)
            profile = profile_payload(
                aug_df,
                omics,
                core_cols,
                {'core_csv': str(source_path), 'full_csv': ''},
            )
            write_json(omics_dir / 'profile.json', profile)
            write_json(omics_dir / 'core_features.json', {'omics': omics, 'features': core_cols, 'auxiliary_features': aux_cols})
            subset_rows.to_csv(omics_dir / 'rows_for_platform.core.csv', index=False)
            write_json(omics_dir / 'summary.core.json', summary)
            write_json(omics_dir / 'analysis.core.json', analysis)
            subset_rows.to_csv(omics_dir / 'rows_for_platform.csv', index=False)
            write_json(omics_dir / 'summary.json', summary)
            write_json(omics_dir / 'analysis.json', analysis)
            browse_meta[omics] = {
                'browse_columns': browse_columns,
                'feature_options': feature_options,
                'primary_id': infer_primary_id(omics, aug_df.columns.tolist()),
                'available_scopes': ['core'],
            }
            transformed[omics] = aug_df
            for artifact_name in ['profile.json', 'core_features.json', 'summary.json', 'analysis.json', 'rows_for_platform.csv']:
                artifact_rows.append({
                    'species_id': species_id,
                    'omics_type': omics,
                    'artifact_type': artifact_name.replace('.json', '').replace('.csv', ''),
                    'path': str((omics_dir / artifact_name).relative_to(stage5_dir)),
                })
        fingerprint = derive_fingerprint(transformed.get('genome'), transformed.get('transcriptome'), transformed.get('proteome'))
        cross_payload = {
            'species_id': species_id,
            'fingerprint': fingerprint,
            'join_summary': {
                'genome_rows': int(len(transformed.get('genome', []))),
                'transcriptome_rows': int(len(transformed.get('transcriptome', []))),
                'proteome_rows': int(len(transformed.get('proteome', []))),
            },
            'method_metadata': {'materialized_scope': 'core', 'mode': 'lightweight_final_whitelist'},
        }
        write_json(species_dir / 'cross_omics.json', cross_payload)
        write_json(species_dir / 'browse_meta.json', browse_meta)
        artifact_rows.append({
            'species_id': species_id,
            'omics_type': 'cross',
            'artifact_type': 'cross_omics',
            'path': str((species_dir / 'cross_omics.json').relative_to(stage5_dir)),
        })
        fingerprint_rows.append({'species_id': species_id, 'display_name': species_row['display_name'], **fingerprint})
        if idx == 1 or idx == len(metadata) or idx % 25 == 0:
            print(f'Stage5 fungi lightweight artifacts: {idx}/{len(metadata)} {species_id}', flush=True)

    fingerprints_df = pd.DataFrame(fingerprint_rows)
    fingerprints_df.to_csv(compare_dir / 'species_fingerprints.csv', index=False)

    compare_columns = ['source', 'target', 'distance']
    compare_path = compare_dir / 'compare_pairs.csv'
    keys = [c for c in fingerprints_df.columns if c not in {'species_id', 'display_name'}]
    total_possible_pairs = int(len(fingerprints_df) * max(len(fingerprints_df) - 1, 0) // 2)
    compare_pair_count = 0
    compare_mode = 'empty'

    with compare_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=compare_columns)
        writer.writeheader()
        if len(fingerprints_df) > 1 and keys and max_compare_pairs > 0:
            numeric_df = fingerprints_df[keys].apply(pd.to_numeric, errors='coerce').fillna(0.0)
            matrix = numeric_df.to_numpy(dtype='float32', copy=True)
            mins = matrix.min(axis=0)
            maxs = matrix.max(axis=0)
            spans = maxs - mins
            spans[spans == 0] = 1
            scaled = (matrix - mins) / spans
            species_ids = fingerprints_df['species_id'].astype(str).tolist()

            def write_pair(i: int, j: int) -> None:
                nonlocal compare_pair_count
                distance = float(((scaled[i] - scaled[j]) ** 2).sum() ** 0.5)
                writer.writerow({
                    'source': species_ids[i],
                    'target': species_ids[j],
                    'distance': round(distance, 4),
                })
                compare_pair_count += 1

            if total_possible_pairs <= max_compare_pairs:
                compare_mode = 'full_pairwise'
                for i in range(len(fingerprints_df)):
                    for j in range(i + 1, len(fingerprints_df)):
                        write_pair(i, j)
            else:
                neighbor_count = max(1, min(int(max_compare_neighbors), len(fingerprints_df) - 1))
                compare_mode = f'neighbor_capped_{neighbor_count}'
                for i in range(len(fingerprints_df)):
                    upper = min(len(fingerprints_df), i + 1 + neighbor_count)
                    for j in range(i + 1, upper):
                        write_pair(i, j)
                        if compare_pair_count >= max_compare_pairs:
                            break
                    if compare_pair_count >= max_compare_pairs:
                        break

    pd.DataFrame(artifact_rows).to_csv(stage5_dir / 'analysis_artifact.csv', index=False)
    write_json(stage5_dir / 'artifact_manifest.json', {
        'stage': 'stage5_artifacts',
        'species_count': int(len(metadata)),
        'artifact_count': int(len(artifact_rows)),
        'compare_pairs': int(compare_pair_count),
        'compare_pairs_total_possible': int(total_possible_pairs),
        'compare_mode': compare_mode,
        'max_compare_pairs': int(max_compare_pairs),
        'max_compare_neighbors': int(max_compare_neighbors),
        'materialized_scope': 'core',
        'mode': 'lightweight_final_whitelist',
    })


def stage6_species_ready(species_out: Path) -> bool:
    if not (species_out / 'cross_omics.json').exists():
        return False
    for omics in ['genome', 'transcriptome', 'proteome']:
        omics_dir = species_out / omics
        if not all((omics_dir / name).exists() for name in ['rows.json', 'summary.json', 'analysis.json']):
            return False
    return True


def stage6_species_index_from_existing(species_row: dict, species_out: Path, fp_row: dict) -> dict:
    species_id = species_row['species_id']
    omics_index = {}
    for omics in ['genome', 'transcriptome', 'proteome']:
        omics_dir = species_out / omics
        summary_payload = json.loads((omics_dir / 'summary.json').read_text(encoding='utf-8'))
        core_summary_path = omics_dir / 'summary_core.json'
        available_scopes = ['core'] if core_summary_path.exists() else []
        omics_index[omics] = {
            'row_count': int(summary_payload.get('row_count') or 0),
            'scope_row_counts': {'core': int(summary_payload.get('row_count') or 0)} if 'core' in available_scopes else {},
            'available_scopes': available_scopes or ['core'],
            'kpis': summary_payload.get('kpis') or {},
        }
    payload = {
        'species_id': species_id,
        'display_name': species_row['display_name'],
        'short_name': species_row['short_name'],
        'domain': species_row['domain'],
        'clade': species_row['clade'],
        'habitat': species_row['habitat'],
        'genome_size_mb': safe_float(species_row['genome_size_mb']) or 0.0,
        'omics': omics_index,
        'fingerprint': {k: safe_float(v) or 0.0 for k, v in fp_row.items() if k not in {'species_id', 'display_name'}},
    }
    write_json(species_out / 'species_index.json', payload)
    return payload


def build_stage6_registry(
    metadata: pd.DataFrame,
    stage5_dir: Path,
    stage6_dir: Path,
    platform_data_root: Path | None = None,
    progress_step: int = 25,
) -> None:
    ensure_dir(stage6_dir)
    total = int(len(metadata))
    index_path = stage6_dir / 'index.json'
    if index_path.exists():
        try:
            existing_index = json.loads(index_path.read_text(encoding='utf-8'))
            existing_count = len(existing_index.get('species') or [])
            if existing_count == total:
                print(f'Stage6 registry already present, skipping: {stage6_dir} ({existing_count}/{total})', flush=True)
                return
        except Exception:
            pass

    fingerprints_df = pd.read_csv(stage5_dir / 'compare' / 'species_fingerprints.csv')
    fingerprint_by_species = {
        str(row.get('species_id')): row
        for row in fingerprints_df.to_dict(orient='records')
    }
    compare_path = stage5_dir / 'compare' / 'compare_pairs.csv'
    if compare_path.exists():
        compare_pairs = pd.read_csv(compare_path)
    else:
        compare_pairs = pd.DataFrame(columns=['source', 'target', 'distance'])
    if compare_pairs.empty:
        compare_pairs = pd.DataFrame(columns=['source', 'target', 'distance'])

    species_rows = []
    omics_meta_out = json.loads(json.dumps(OMICS_META))
    start = time.time()
    progress_step = max(1, int(progress_step or 25))
    reused_count = 0
    built_count = 0

    for idx, species_row in enumerate(metadata.to_dict(orient='records'), start=1):
        species_id = str(species_row['species_id'])
        species_art_dir = stage5_dir / species_id
        species_out = stage6_dir / species_id
        marker_path = species_out / 'species_index.json'
        fp_row = fingerprint_by_species.get(species_id, {'species_id': species_id, 'display_name': species_row.get('display_name', species_id)})
        status = 'built'

        if marker_path.exists() and stage6_species_ready(species_out):
            try:
                species_rows.append(json.loads(marker_path.read_text(encoding='utf-8')))
                reused_count += 1
                status = 'reused'
            except Exception:
                marker_path.unlink(missing_ok=True)

        if status != 'reused' and stage6_species_ready(species_out):
            species_rows.append(stage6_species_index_from_existing(species_row, species_out, fp_row))
            reused_count += 1
            status = 'indexed_existing'

        if status not in {'reused', 'indexed_existing'}:
            browse_meta = json.loads((species_art_dir / 'browse_meta.json').read_text(encoding='utf-8'))
            ensure_dir(species_out)
            omics_index = {}
            for omics in ['genome', 'transcriptome', 'proteome']:
                src_dir = species_art_dir / omics
                if not src_dir.exists():
                    continue
                dst_dir = species_out / omics
                ensure_dir(dst_dir)
                scope_row_counts = {}
                canonical_rows = None
                canonical_summary = None
                canonical_analysis = None
                for scope_name in ['core', 'full']:
                    rows_path = src_dir / f'rows_for_platform.{scope_name}.csv'
                    summary_path = src_dir / f'summary.{scope_name}.json'
                    analysis_path = src_dir / f'analysis.{scope_name}.json'
                    if not rows_path.exists() or not summary_path.exists() or not analysis_path.exists():
                        continue
                    rows_df = pd.read_csv(rows_path)
                    summary_payload = json.loads(summary_path.read_text(encoding='utf-8'))
                    analysis_payload = json.loads(analysis_path.read_text(encoding='utf-8'))
                    write_json(dst_dir / f'rows_{scope_name}.json', records(rows_df))
                    write_json(dst_dir / f'summary_{scope_name}.json', summary_payload)
                    write_json(dst_dir / f'analysis_{scope_name}.json', analysis_payload)
                    scope_row_counts[scope_name] = int(len(rows_df))
                    if canonical_rows is None or scope_name == 'core':
                        canonical_rows = rows_df
                        canonical_summary = summary_payload
                        canonical_analysis = analysis_payload
                    del rows_df

                if canonical_rows is None:
                    rows_df = pd.read_csv(src_dir / 'rows_for_platform.csv')
                    canonical_summary = json.loads((src_dir / 'summary.json').read_text(encoding='utf-8'))
                    canonical_analysis = json.loads((src_dir / 'analysis.json').read_text(encoding='utf-8'))
                    canonical_rows = rows_df

                write_json(dst_dir / 'rows.json', records(canonical_rows))
                write_json(dst_dir / 'summary.json', canonical_summary)
                write_json(dst_dir / 'analysis.json', canonical_analysis)

                omics_meta_out[omics]['browse_columns'] = browse_meta[omics]['browse_columns']
                omics_meta_out[omics]['feature_options'] = browse_meta[omics]['feature_options']
                omics_meta_out[omics]['primary_id'] = browse_meta[omics]['primary_id']
                omics_meta_out[omics]['available_scopes'] = browse_meta[omics].get('available_scopes', ['core'])
                if isinstance(canonical_summary, dict) and canonical_summary.get('field_meta'):
                    omics_meta_out[omics]['field_meta'] = canonical_summary.get('field_meta')

                omics_index[omics] = {
                    'row_count': int(len(canonical_rows)),
                    'scope_row_counts': scope_row_counts,
                    'available_scopes': browse_meta[omics].get('available_scopes', ['core']),
                    'kpis': canonical_summary.get('kpis') or {},
                }
                del canonical_rows

            shutil.copy2(species_art_dir / 'cross_omics.json', species_out / 'cross_omics.json')
            species_index = {
                'species_id': species_id,
                'display_name': species_row['display_name'],
                'short_name': species_row['short_name'],
                'domain': species_row['domain'],
                'clade': species_row['clade'],
                'habitat': species_row['habitat'],
                'genome_size_mb': safe_float(species_row['genome_size_mb']) or 0.0,
                'omics': omics_index,
                'fingerprint': {k: safe_float(v) or 0.0 for k, v in fp_row.items() if k not in {'species_id', 'display_name'}},
            }
            write_json(marker_path, species_index)
            species_rows.append(species_index)
            built_count += 1

        if idx == 1 or idx == total or idx % progress_step == 0:
            elapsed = time.time() - start
            rate = idx / elapsed if elapsed > 0 else 0.0
            remaining = (total - idx) / rate if rate > 0 else 0.0
            percent = (idx / max(total, 1)) * 100.0
            print(
                f'Stage6 registry [{percent:6.2f}%] {idx}/{total} {species_id} '
                f'status={status} reused={reused_count} built={built_count} '
                f'elapsed={elapsed/60:.1f}m eta={remaining/60:.1f}m',
                flush=True,
            )
        if idx % 100 == 0:
            gc.collect()

    project_payload = {
        'name': 'Stoichioomics Platform',
        'subtitle': f'Real multi-species registry built from {len(species_rows)} curated stoichiometric feature-table species',
        'description': 'This registry is generated directly from real stoichiometric feature tables and mirrors the staged files required for reproducible ORM / PostgreSQL imports at larger scale.',
        'species_count': int(len(species_rows)),
        'omics_types': ['genome', 'transcriptome', 'proteome'],
        'modules': PROJECT_MODULES,
    }
    index_payload = {
        'project': project_payload,
        'species': species_rows,
        'omics_meta': omics_meta_out,
        'compare_pairs': records(compare_pairs),
    }
    write_json(index_path, index_payload)
    write_json(stage6_dir / 'registry_manifest.json', {
        'stage': 'stage6_platform_registry',
        'species_count': len(species_rows),
        'compare_pairs': len(compare_pairs),
        'reused_species': reused_count,
        'built_species': built_count,
        'resume_mode': True,
    })
    print(f'Stage6 registry completed: {len(species_rows)}/{total}; reused={reused_count}; built={built_count}; index={index_path}', flush=True)

    if platform_data_root is not None:
        if platform_data_root.exists():
            shutil.rmtree(platform_data_root)
        shutil.copytree(stage6_dir, platform_data_root)
def main() -> None:
    args = parse_args()
    source_root = Path(args.source_root)
    whitelist_path = Path(args.whitelist)
    output_root = Path(args.output_root)

    whitelist = pd.read_csv(whitelist_path)
    if 'species' not in whitelist.columns:
        raise SystemExit(f'Whitelist missing required species column: {whitelist_path}')

    metadata = build_metadata(whitelist)
    species_tables: dict[str, dict[str, dict[str, Path]]] = {}
    inventory_rows = []
    dataset_rows = []
    for species_id in metadata['species_id'].astype(str):
        for omics in ['genome', 'transcriptome', 'proteome']:
            core_path = resolve_core_path(source_root, species_id, omics)
            species_tables.setdefault(species_id, {}).setdefault(omics, {})['core'] = core_path
            inventory_rows.append({
                'species_id': species_id,
                'omics': omics,
                'table_role': 'core',
                'source_path': str(core_path),
                'file_size_bytes': core_path.stat().st_size,
            })
            dataset_rows.append({
                'species_id': species_id,
                'omics': omics,
                'table_role': 'core',
                'path': str(core_path),
            })

    stage0 = output_root / 'stage0_source_bundle'
    stage1 = output_root / 'stage1_standardized'
    stage4 = output_root / 'stage4_catalog'
    stage5 = output_root / 'stage5_artifacts'
    stage6 = output_root / 'stage6_platform_registry'
    for path in [stage0, stage1 / 'metadata', stage4, stage5, stage6]:
        ensure_dir(path)

    pd.DataFrame(inventory_rows).to_csv(stage0 / 'source_inventory.csv', index=False)
    metadata.to_csv(stage1 / 'metadata' / 'species_metadata.auto.csv', index=False)
    pd.DataFrame(dataset_rows).to_csv(stage1 / 'metadata' / 'dataset_manifest.auto.csv', index=False)
    write_json(stage1 / 'import_manifest.json', {
        'stage': 'stage1_standardized',
        'species_count': int(len(metadata)),
        'omics_types': ['genome', 'proteome', 'transcriptome'],
        'dataset_count': int(len(dataset_rows)),
        'whitelist': str(whitelist_path),
        'materialized_scope': 'core',
    })

    stage4_ready = all((stage4 / 'db_seed' / name).exists() for name in [
        'species.csv',
        'omics_dataset.csv',
        'feature_file.csv',
        'gene_index.csv',
        'transcript_index.csv',
        'protein_index.csv',
    ]) and (stage4 / 'catalog_manifest.json').exists()
    if stage4_ready:
        print(f'Stage4 already present, skipping: {stage4}', flush=True)
    else:
        stream_stage4_catalog(metadata, species_tables, stage4)
    build_light_stage5(metadata, species_tables, stage5, max_compare_pairs=args.max_compare_pairs, max_compare_neighbors=args.max_compare_neighbors)
    build_stage6_registry(metadata, stage5, stage6, progress_step=args.stage6_progress_step)

    write_json(output_root / 'pipeline_manifest.json', {
        'project': 'Stoichioomics fungi final-whitelist feature registry',
        'source_root': str(source_root),
        'whitelist': str(whitelist_path),
        'stages': [
            {'stage0_source_bundle': str(stage0)},
            {'stage1_standardized': str(stage1)},
            {'stage4_catalog': str(stage4)},
            {'stage5_artifacts': str(stage5)},
            {'stage6_platform_registry': str(stage6)},
        ],
        'species_count': int(len(metadata)),
        'dataset_count': int(len(dataset_rows)),
        'platform_registry': str(stage6),
        'materialized_scope': 'core',
    })
    print(f'Built fungi registry at: {output_root}')
    print(f'Species indexed: {len(metadata)}')
    print(f'Dataset files indexed: {len(dataset_rows)}')


if __name__ == '__main__':
    main()






