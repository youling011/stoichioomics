from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from backend.apps.common.json_safe import sanitize_for_json


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
        'description': 'Genome stoichiometric feature tables derived from exon, promoter and locus-level elemental composition fields.',
        'analysis_modules': ['Profile', 'Core features', 'Strategy clusters', 'Outliers', 'Stoich islands', 'Coupling network'],
    },
    'transcriptome': {
        'display_name': 'Transcriptome',
        'entity_label': 'Transcript',
        'primary_id': 'transcript_id',
        'fallback_id': 'entity_id',
        'description': 'Transcriptome feature tables derived from nucleotide composition, element-per-nt fields and ORF / coding proxy features.',
        'analysis_modules': ['Profile', 'Core features', 'Strategy clusters', 'Outliers', 'RNA-ORF coupling', 'Motif themes'],
    },
    'proteome': {
        'display_name': 'Proteome',
        'entity_label': 'Protein',
        'primary_id': 'protein_id',
        'fallback_id': 'entity_id',
        'description': 'Proteome feature tables derived from atom-per-aa, elemental ratio and physicochemical fields.',
        'analysis_modules': ['Profile', 'Core features', 'Strategy clusters', 'Outliers', 'Resource budgets', 'Trade-off front'],
    },
}

STAGE_NAMES = [
    'stage0_source_bundle',
    'stage1_standardized',
    'stage2_validation',
    'stage3_parquet',
    'stage4_catalog',
    'stage5_artifacts',
    'stage6_platform_registry',
]

DISPLAY_FALLBACK = {
    'Escherichia_coli_110957': 'Escherichia coli 110957',
    'Saccharomyces_cerevisiae.R64-1-1': 'Saccharomyces cerevisiae R64-1-1',
}

FEATURE_SCHEMA_PATH = Path(__file__).resolve().parent.parent / 'shared' / 'schemas' / 'stoich_feature_display_schema.json'


def progress_bar(current: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return '[' + ('-' * width) + ']'
    ratio = max(0.0, min(1.0, current / total))
    filled = int(round(width * ratio))
    return '[' + ('#' * filled) + ('-' * (width - filled)) + ']'


def stage_message(stage_index: int, stage_total: int, label: str) -> str:
    percent = 100.0 if stage_total <= 0 else (stage_index / stage_total) * 100.0
    return f'Build {progress_bar(stage_index, stage_total)} {percent:6.2f}% | Stage {stage_index}/{stage_total} | {label}'


@dataclass
class DatasetRef:
    source_name: str
    source_path: Path
    species_source_id: str
    species_id: str
    display_name: str
    short_name: str
    omics: str
    table_role: str  # full/core


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a complete staged pipeline from multi-omics stoichiometric feature tables.')
    parser.add_argument('--source-root', required=True, help='Directory containing feature-table CSVs. Nested per-omics subdirectories are supported.')
    parser.add_argument('--output-root', required=True, help='Root directory for all generated stages.')
    parser.add_argument('--platform-data-root', default='', help='Optional path to also refresh the frontend/backend registry folder consumed by the platform.')
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def clean_slug(text: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')
    slug = re.sub(r'_+', '_', slug)
    return slug


def display_name_from_source(source_id: str) -> str:
    if source_id in DISPLAY_FALLBACK:
        return DISPLAY_FALLBACK[source_id]
    text = source_id.replace('_', ' ').replace('.', ' ').replace('-', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    parts = text.split()
    if not parts:
        return text
    normalized = []
    uppercase_tokens = {'gca', 'atcc', 'ccmp', 'rn66', 'ip1'}
    for idx, token in enumerate(parts):
        lower = token.lower()
        if idx == 0:
            normalized.append(token.capitalize())
        elif lower in uppercase_tokens:
            normalized.append(token.upper())
        else:
            normalized.append(token)
    return ' '.join(normalized)


def short_name(display_name: str) -> str:
    parts = display_name.split()
    if len(parts) >= 2:
        return f'{parts[0][0]}. {" ".join(parts[1:])}'
    return display_name


def split_stem(name: str, marker: str) -> str:
    lower_name = name.lower()
    idx = lower_name.find(marker)
    if idx < 0:
        raise ValueError(f'Cannot find marker {marker!r} in filename: {name}')
    return name[:idx]


def parse_filename(path: Path) -> DatasetRef:
    name = path.name
    lower = name.lower()
    if '.genome_features' in lower:
        omics = 'genome'
        marker = '.genome_features'
    elif '.transcriptome' in lower:
        omics = 'transcriptome'
        marker = '.transcriptome'
    elif '.proteome_features' in lower:
        omics = 'proteome'
        marker = '.proteome_features'
    else:
        raise ValueError(f'Cannot infer omics from filename: {name}')

    if '.core.' in lower:
        role = 'core'
    elif '.full.' in lower or lower.endswith('.csv'):
        role = 'full'
    else:
        role = 'full'

    source_species = split_stem(name, marker)
    species_id = clean_slug(source_species)
    display_name = display_name_from_source(source_species)
    return DatasetRef(
        source_name=name,
        source_path=path,
        species_source_id=source_species,
        species_id=species_id,
        display_name=display_name,
        short_name=short_name(display_name),
        omics=omics,
        table_role=role,
    )


def scan_bundle(source_root: Path) -> list[DatasetRef]:
    refs = []
    seen_keys: dict[tuple[str, str, str], Path] = {}
    for path in sorted(source_root.rglob('*.csv')):
        lower = path.name.lower()
        if '.genome_features' not in lower and '.transcriptome.' not in lower and '.proteome_features' not in lower:
            continue
        ref = parse_filename(path)
        key = (ref.species_id, ref.omics, ref.table_role)
        existing = seen_keys.get(key)
        if existing is not None and existing != path:
            raise ValueError(
                f'Duplicate table detected for {ref.species_id}/{ref.omics}/{ref.table_role}: '
                f'{existing} and {path}'
            )
        seen_keys[key] = path
        refs.append(ref)
    return refs


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False)


def read_csv_sample(path: Path, nrows: int = 200) -> pd.DataFrame:
    return pd.read_csv(path, low_memory=False, nrows=nrows)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(sanitize_for_json(payload), indent=2, ensure_ascii=False, allow_nan=False),
        encoding='utf-8',
    )


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
    candidates = schema.get(omics) or []
    present = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        field = str(item.get('field') or '').strip()
        if not field or field not in columns:
            continue
        present.append(item)
    return present


def safe_float(value: Any, digits: int = 4) -> float | None:
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    try:
        num = float(value)
    except Exception:
        return None
    if not math.isfinite(num):
        return None
    return round(num, digits)


def numeric_columns(df: pd.DataFrame) -> list[str]:
    return [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]


def materialize_file(src: Path, dst: Path) -> None:
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def count_csv_rows(path: Path) -> int:
    newline_count = 0
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            newline_count += chunk.count(b'\n')
    return max(newline_count - 1, 0)


def make_species_metadata(refs: list[DatasetRef], species_tables: dict[str, dict[str, dict[str, Path]]]) -> pd.DataFrame:
    species_ref_map: dict[str, DatasetRef] = {}
    for ref in refs:
        species_ref_map.setdefault(ref.species_id, ref)
    records: list[dict[str, Any]] = []
    for species_id, omics_tables in species_tables.items():
        species_ref = species_ref_map.get(species_id)
        source_species_id = species_ref.species_source_id if species_ref else species_id
        display_name = species_ref.display_name if species_ref else display_name_from_source(source_species_id)
        short = species_ref.short_name if species_ref else short_name(display_name)
        genome_full_path = omics_tables.get('genome', {}).get('core') or omics_tables.get('genome', {}).get('full')
        genome_size_mb = None
        if genome_full_path and genome_full_path.exists():
            genome_df = read_csv(genome_full_path)
            seq_col = next((c for c in ['seqid', 'seq_region', 'chromosome'] if c in genome_df.columns), None)
            end_col = next((c for c in ['end_1', 'end', 'stop', 'gene_end'] if c in genome_df.columns), None)
            if seq_col and end_col:
                part = genome_df[[seq_col, end_col]].copy()
                part[end_col] = pd.to_numeric(part[end_col], errors='coerce')
                genome_size_mb = safe_float(part.groupby(seq_col)[end_col].max().sum() / 1_000_000.0)
        records.append({
            'species_id': species_id,
            'display_name': display_name,
            'short_name': short,
            'source_species_id': source_species_id,
            'domain': 'Unknown',
            'clade': 'Unclassified',
            'habitat': 'Not provided',
            'genome_size_mb': genome_size_mb or 0.0,
            'has_genome': 'genome' in omics_tables,
            'has_transcriptome': 'transcriptome' in omics_tables,
            'has_proteome': 'proteome' in omics_tables,
        })
    return pd.DataFrame(records).sort_values('species_id')


def copy_stage0(refs: list[DatasetRef], stage0_dir: Path, materialize_sources: bool = True) -> pd.DataFrame:
    ensure_dir(stage0_dir)
    inventory = []
    for ref in refs:
        dst = stage0_dir / ref.source_name
        if materialize_sources:
            materialize_file(ref.source_path, dst)
        else:
            dst = ref.source_path
        inventory.append({
            'source_name': ref.source_name,
            'species_source_id': ref.species_source_id,
            'species_id': ref.species_id,
            'display_name': ref.display_name,
            'omics': ref.omics,
            'table_role': ref.table_role,
            'copied_path': str(dst if not materialize_sources else dst.relative_to(stage0_dir.parent)),
            'file_size_bytes': dst.stat().st_size,
        })
    df = pd.DataFrame(inventory).sort_values(['species_id', 'omics', 'table_role'])
    df.to_csv(stage0_dir / 'source_inventory.csv', index=False)
    return df


def build_stage1_standardized(
    refs: list[DatasetRef],
    stage1_dir: Path,
    materialize_sources: bool = True,
) -> tuple[pd.DataFrame, dict[str, dict[str, dict[str, Path]]]]:
    ensure_dir(stage1_dir)
    registry_dir = stage1_dir / 'species_registry'
    schema_dir = stage1_dir / 'schema'
    meta_dir = stage1_dir / 'metadata'
    ensure_dir(registry_dir)
    ensure_dir(schema_dir)
    ensure_dir(meta_dir)

    species_tables: dict[str, dict[str, dict[str, Path]]] = {}
    dataset_manifest = []
    per_omics_frames: dict[str, list[pd.DataFrame]] = {'genome': [], 'transcriptome': [], 'proteome': []}

    for ref in refs:
        species_tables.setdefault(ref.species_id, {}).setdefault(ref.omics, {})
        dst_dir = registry_dir / ref.species_id / ref.omics
        ensure_dir(dst_dir)
        dst = dst_dir / f'{ref.table_role}.csv'
        if materialize_sources:
            materialize_file(ref.source_path, dst)
            table_path = dst
            relative_path = str(dst.relative_to(stage1_dir))
        else:
            table_path = ref.source_path
            relative_path = str(ref.source_path)
        species_tables[ref.species_id][ref.omics][ref.table_role] = table_path

        sample = read_csv_sample(table_path)
        col_count = int(len(sample.columns))
        dataset_manifest.append({
            'species_id': ref.species_id,
            'display_name': ref.display_name,
            'omics': ref.omics,
            'table_role': ref.table_role,
            'path': relative_path,
            'row_count': None,
            'column_count': col_count,
            'primary_id': infer_primary_id(ref.omics, sample.columns.tolist()),
            'numeric_column_count': len(numeric_columns(sample)),
        })
        tagged = pd.DataFrame({
            'field_name': sample.columns,
            'dtype': [str(sample[col].dtype) for col in sample.columns],
            'source_species_id': ref.species_id,
            'table_role': ref.table_role,
        })
        per_omics_frames[ref.omics].append(tagged)

    metadata = make_species_metadata(refs, species_tables)
    metadata.to_csv(meta_dir / 'species_metadata.auto.csv', index=False)
    pd.DataFrame(dataset_manifest).sort_values(['species_id', 'omics', 'table_role']).to_csv(meta_dir / 'dataset_manifest.auto.csv', index=False)

    for omics, frames in per_omics_frames.items():
        if not frames:
            continue
        merged = pd.concat(frames, ignore_index=True)
        grouped = merged.groupby('field_name', dropna=False)
        rows = []
        for field_name, part in grouped:
            dtypes = sorted(set(part['dtype'].astype(str)))
            table_roles = sorted(set(part['table_role'].astype(str)))
            rows.append({
                'field_name': field_name,
                'dtype_examples': '|'.join(dtypes),
                'seen_in_tables': int(len(part)),
                'table_roles': '|'.join(table_roles),
                'required_in_all_tables': int(part['source_species_id'].nunique() == len(metadata) and set(table_roles) == {'core', 'full'}),
                'numeric_hint': int(any('int' in d or 'float' in d for d in dtypes)),
                'used_in_filter_auto': int(any(token in field_name for token in ['id', 'name', 'biotype', 'strand', 'seqid', 'seq_region'])),
                'used_in_visualization_auto': int(any('int' in d or 'float' in d for d in dtypes)),
            })
        pd.DataFrame(rows).sort_values(['required_in_all_tables', 'field_name'], ascending=[False, True]).to_csv(schema_dir / f'{omics}_schema.auto.csv', index=False)

    write_json(stage1_dir / 'import_manifest.json', {
        'stage': 'stage1_standardized',
        'species_count': int(len(metadata)),
        'omics_types': sorted({ref.omics for ref in refs}),
        'dataset_count': int(len(dataset_manifest)),
    })
    return metadata, species_tables


def infer_primary_id(omics: str, columns: list[str]) -> str:
    candidates = {
        'genome': ['gene_id', 'entity_id'],
        'transcriptome': ['transcript_id', 'gene_id', 'entity_id'],
        'proteome': ['protein_id', 'ensembl_protein_id', 'gene_id', 'entity_id'],
    }[omics]
    lookup = {col.lower(): col for col in columns}
    for candidate in candidates:
        hit = lookup.get(candidate.lower())
        if hit:
            return hit
    return columns[0]


def join_key_columns(omics: str, columns: list[str]) -> list[str]:
    if omics == 'genome':
        return [c for c in ['gene_id'] if c in columns]
    if omics == 'transcriptome':
        return [c for c in ['gene_id', 'transcript_id'] if c in columns]
    return [c for c in ['ensembl_gene_id', 'gene_id', 'protein_id'] if c in columns]


def build_stage2_validation(metadata: pd.DataFrame, species_tables: dict[str, dict[str, dict[str, Path]]], stage2_dir: Path) -> None:
    ensure_dir(stage2_dir)
    species_report_dir = stage2_dir / 'species_reports'
    ensure_dir(species_report_dir)
    summary_rows = []
    join_rows = []

    for species_row in metadata.to_dict(orient='records'):
        species_id = species_row['species_id']
        omics_tables = species_tables[species_id]
        species_report = {'species_id': species_id, 'datasets': {}, 'cross_omics_join': {}}
        omics_dfs = {}
        for omics, table_paths in omics_tables.items():
            dataset_entry = {}
            for role, path in table_paths.items():
                df = read_csv(path)
                primary_id = infer_primary_id(omics, df.columns.tolist())
                numeric_cols = numeric_columns(df)
                constant_numeric = [col for col in numeric_cols[:150] if pd.to_numeric(df[col], errors='coerce').nunique(dropna=True) <= 1]
                duplicate_id_count = int(df[primary_id].duplicated().sum()) if primary_id in df.columns else -1
                missing_fraction = round(float(df.isna().mean().mean()), 6)
                record = {
                    'species_id': species_id,
                    'omics': omics,
                    'table_role': role,
                    'row_count': int(len(df)),
                    'column_count': int(len(df.columns)),
                    'primary_id': primary_id,
                    'duplicate_primary_id_count': duplicate_id_count,
                    'missing_fraction_mean': missing_fraction,
                    'numeric_column_count': int(len(numeric_cols)),
                    'constant_numeric_column_count': int(len(constant_numeric)),
                    'first_constant_numeric_columns': '|'.join(constant_numeric[:12]),
                }
                dataset_entry[role] = record
                summary_rows.append(record)
                if role == 'core':
                    omics_dfs[omics] = df
            species_report['datasets'][omics] = dataset_entry

        genome = omics_dfs.get('genome')
        transcriptome = omics_dfs.get('transcriptome')
        proteome = omics_dfs.get('proteome')
        if genome is not None and transcriptome is not None:
            gk = infer_primary_id('genome', genome.columns.tolist())
            tk = 'gene_id' if 'gene_id' in transcriptome.columns else infer_primary_id('transcriptome', transcriptome.columns.tolist())
            genome_keys = set(genome[gk].dropna().astype(str))
            rna_keys = set(transcriptome[tk].dropna().astype(str))
            overlap = sorted(genome_keys & rna_keys)
            coverage = round(len(overlap) / max(1, len(genome_keys)), 6)
            species_report['cross_omics_join']['genome_to_transcriptome'] = {
                'left_key': gk,
                'right_key': tk,
                'left_count': len(genome_keys),
                'right_count': len(rna_keys),
                'overlap_count': len(overlap),
                'coverage_vs_genome': coverage,
            }
            join_rows.append({
                'species_id': species_id,
                'join_name': 'genome_to_transcriptome',
                'left_key': gk,
                'right_key': tk,
                'left_count': len(genome_keys),
                'right_count': len(rna_keys),
                'overlap_count': len(overlap),
                'coverage_vs_left': coverage,
            })
        if genome is not None and proteome is not None:
            gk = 'gene_id' if 'gene_id' in genome.columns else infer_primary_id('genome', genome.columns.tolist())
            pk = 'ensembl_gene_id' if 'ensembl_gene_id' in proteome.columns else ('gene_id' if 'gene_id' in proteome.columns else infer_primary_id('proteome', proteome.columns.tolist()))
            genome_keys = set(genome[gk].dropna().astype(str))
            prot_keys = set(proteome[pk].dropna().astype(str))
            overlap = sorted(genome_keys & prot_keys)
            coverage = round(len(overlap) / max(1, len(prot_keys)), 6)
            species_report['cross_omics_join']['genome_to_proteome'] = {
                'left_key': gk,
                'right_key': pk,
                'left_count': len(genome_keys),
                'right_count': len(prot_keys),
                'overlap_count': len(overlap),
                'coverage_vs_proteome': coverage,
            }
            join_rows.append({
                'species_id': species_id,
                'join_name': 'genome_to_proteome',
                'left_key': gk,
                'right_key': pk,
                'left_count': len(genome_keys),
                'right_count': len(prot_keys),
                'overlap_count': len(overlap),
                'coverage_vs_left': coverage,
            })

        write_json(species_report_dir / f'{species_id}.validation.json', species_report)

    pd.DataFrame(summary_rows).sort_values(['species_id', 'omics', 'table_role']).to_csv(stage2_dir / 'validation_summary.csv', index=False)
    pd.DataFrame(join_rows).sort_values(['species_id', 'join_name']).to_csv(stage2_dir / 'cross_omics_join_summary.csv', index=False)
    write_json(stage2_dir / 'validation_manifest.json', {
        'stage': 'stage2_validation',
        'species_count': int(len(metadata)),
        'dataset_reports': int(len(summary_rows)),
        'join_reports': int(len(join_rows)),
    })


def build_stage3_parquet(species_tables: dict[str, dict[str, dict[str, Path]]], stage3_dir: Path) -> None:
    ensure_dir(stage3_dir)
    manifest_rows = []
    for species_id, omics_tables in species_tables.items():
        for omics, table_paths in omics_tables.items():
            out_dir = stage3_dir / 'parquet' / species_id / omics
            ensure_dir(out_dir)
            for role, csv_path in table_paths.items():
                df = read_csv(csv_path)
                pq_path = out_dir / f'{role}.parquet'
                df.to_parquet(pq_path, index=False)
                manifest_rows.append({
                    'species_id': species_id,
                    'omics': omics,
                    'table_role': role,
                    'csv_path': str(csv_path),
                    'parquet_path': str(pq_path.relative_to(stage3_dir)),
                    'row_count': int(len(df)),
                    'column_count': int(len(df.columns)),
                })
    pd.DataFrame(manifest_rows).sort_values(['species_id', 'omics', 'table_role']).to_csv(stage3_dir / 'parquet_manifest.csv', index=False)
    write_json(stage3_dir / 'parquet_manifest.json', {
        'stage': 'stage3_parquet',
        'dataset_count': len(manifest_rows),
    })


def build_stage4_catalog(metadata: pd.DataFrame, species_tables: dict[str, dict[str, dict[str, Path]]], stage4_dir: Path) -> None:
    ensure_dir(stage4_dir)
    db_seed = stage4_dir / 'db_seed'
    ensure_dir(db_seed)

    species_df = metadata.copy()
    species_df.to_csv(db_seed / 'species.csv', index=False)

    datasets_rows = []
    feature_file_rows = []
    gene_rows = []
    transcript_rows = []
    protein_rows = []
    for species_row in metadata.to_dict(orient='records'):
        species_id = species_row['species_id']
        for omics, table_paths in species_tables[species_id].items():
            core_path = table_paths.get('core')
            full_path = table_paths.get('full')
            core_df = read_csv(core_path) if core_path else None
            datasets_rows.append({
                'dataset_id': f'{species_id}__{omics}',
                'species_id': species_id,
                'omics_type': omics.upper(),
                'schema_version': 'auto_v1',
                'row_count_core': int(len(core_df)) if core_df is not None else 0,
                'row_count_full': count_csv_rows(full_path) if full_path else 0,
                'core_csv_path': str(core_path) if core_path else '',
                'full_csv_path': str(full_path) if full_path else '',
                'status': 'ready',
            })
            for role, path in table_paths.items():
                feature_file_rows.append({
                    'file_id': f'{species_id}__{omics}__{role}',
                    'dataset_id': f'{species_id}__{omics}',
                    'file_type': role,
                    'path': str(path),
                    'size_bytes': path.stat().st_size,
                })
            if omics == 'genome' and core_df is not None:
                cols = [c for c in ['species_id', 'gene_id', 'gene_name', 'locus_tag', 'biotype', 'seqid', 'start_1', 'end_1', 'strand'] if c in core_df.columns]
                gene_rows.extend(core_df[cols].replace({np.nan: None}).to_dict(orient='records'))
            if omics == 'transcriptome' and core_df is not None:
                cols = [c for c in ['species_id', 'transcript_id', 'gene_id', 'gene_symbol', 'transcript_biotype', 'seq_region', 'start', 'end', 'strand'] if c in core_df.columns]
                transcript_rows.extend(core_df[cols].replace({np.nan: None}).to_dict(orient='records'))
            if omics == 'proteome' and core_df is not None:
                cols = [c for c in ['species_id', 'protein_id', 'ensembl_gene_id', 'gene_id', 'gene_symbol', 'description', 'length_aa'] if c in core_df.columns]
                protein_rows.extend(core_df[cols].replace({np.nan: None}).to_dict(orient='records'))

    pd.DataFrame(datasets_rows).to_csv(db_seed / 'omics_dataset.csv', index=False)
    pd.DataFrame(feature_file_rows).to_csv(db_seed / 'feature_file.csv', index=False)
    pd.DataFrame(gene_rows).to_csv(db_seed / 'gene_index.csv', index=False)
    pd.DataFrame(transcript_rows).to_csv(db_seed / 'transcript_index.csv', index=False)
    pd.DataFrame(protein_rows).to_csv(db_seed / 'protein_index.csv', index=False)
    write_json(stage4_dir / 'catalog_manifest.json', {
        'stage': 'stage4_catalog',
        'species_rows': int(len(species_df)),
        'dataset_rows': int(len(datasets_rows)),
        'gene_index_rows': int(len(gene_rows)),
        'transcript_index_rows': int(len(transcript_rows)),
        'protein_index_rows': int(len(protein_rows)),
    })


def zscore_series(series: pd.Series) -> pd.Series:
    arr = pd.to_numeric(series, errors='coerce')
    mean = arr.mean()
    std = arr.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(np.zeros(len(series)), index=series.index)
    return (arr - mean) / std


def hist_payload(series: pd.Series, bins: int = 24) -> dict[str, Any]:
    values = pd.to_numeric(series, errors='coerce').dropna().to_numpy(dtype=float)
    if len(values) == 0:
        return {'centers': [], 'counts': []}
    n_bins = min(max(8, int(math.sqrt(len(values)) * 2)), bins)
    counts, edges = np.histogram(values, bins=n_bins)
    centers = ((edges[:-1] + edges[1:]) / 2).round(4).tolist()
    return {'centers': centers, 'counts': counts.astype(int).tolist()}


def percentile_summary(series: pd.Series) -> dict[str, float]:
    values = pd.to_numeric(series, errors='coerce').dropna()
    if len(values) == 0:
        return {'mean': 0.0, 'std': 0.0, 'p05': 0.0, 'p25': 0.0, 'p50': 0.0, 'p75': 0.0, 'p95': 0.0}
    return {
        'mean': round(float(values.mean()), 4),
        'std': round(float(values.std(ddof=0)), 4),
        'p05': round(float(values.quantile(0.05)), 4),
        'p25': round(float(values.quantile(0.25)), 4),
        'p50': round(float(values.quantile(0.50)), 4),
        'p75': round(float(values.quantile(0.75)), 4),
        'p95': round(float(values.quantile(0.95)), 4),
    }


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    clean = df.replace({np.nan: None}).to_dict(orient='records')
    out = []
    for row in clean:
        out.append({
            k: (round(float(v), 4) if isinstance(v, (float, np.floating)) and math.isfinite(float(v)) else (int(v) if isinstance(v, (np.integer,)) else v))
            for k, v in row.items()
        })
    return out


def candidate_numeric(df: pd.DataFrame, preferred: list[str], max_cols: int = 8) -> list[str]:
    cols = [col for col in preferred if col in df.columns]
    for col in numeric_columns(df):
        if col not in cols:
            cols.append(col)
        if len(cols) >= max_cols:
            break
    return cols[:max_cols]


def infer_genome_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    out = df.copy()
    if 'entity_id' not in out.columns:
        out['entity_id'] = out['gene_id']
    if {'promoter_gc_percent', 'exon_gc_percent'}.issubset(out.columns):
        promoter_gc = pd.to_numeric(out['promoter_gc_percent'], errors='coerce')
        exon_gc = pd.to_numeric(out['exon_gc_percent'], errors='coerce')
        out['gc_delta_promoter_minus_exon'] = promoter_gc - exon_gc
        # Keep legacy alias for backward compatibility.
        out['promoter_exon_gc_delta'] = out['gc_delta_promoter_minus_exon']
    if {'promoter_atoms_N_per_base', 'exon_atoms_N_per_base'}.issubset(out.columns):
        promoter_n = pd.to_numeric(out['promoter_atoms_N_per_base'], errors='coerce')
        exon_n = pd.to_numeric(out['exon_atoms_N_per_base'], errors='coerce')
        out['n_delta_promoter_minus_exon'] = promoter_n - exon_n
        # Keep legacy alias for backward compatibility.
        out['promoter_exon_n_delta'] = out['n_delta_promoter_minus_exon']
    island_source = candidate_numeric(out, ['gc_delta_promoter_minus_exon', 'n_delta_promoter_minus_exon', 'gc3_percent', 'exon_atoms_N_per_base'], max_cols=4)
    if island_source:
        out['stoich_island_score'] = sum(zscore_series(out[col]) for col in island_source) / len(island_source)
    else:
        out['stoich_island_score'] = 0.0
    cluster_basis = candidate_numeric(out, ['gc_delta_promoter_minus_exon', 'stoich_island_score', 'gc3_percent', 'exon_atoms_N_per_base'], max_cols=4)
    out['strategy_score'] = sum(zscore_series(out[col]) for col in cluster_basis) / max(1, len(cluster_basis))
    return out, cluster_basis, island_source


def infer_transcriptome_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    out = df.copy()
    if 'entity_id' not in out.columns:
        out['entity_id'] = out['transcript_id']
    if 'coding_density_proxy' not in out.columns and {'orf_len_nt', 'length_nt_total'}.issubset(out.columns):
        total = pd.to_numeric(out['length_nt_total'], errors='coerce').replace(0, np.nan)
        out['coding_density_proxy'] = (pd.to_numeric(out['orf_len_nt'], errors='coerce') / total).fillna(0)
    if 'protein_gravy_proxy' not in out.columns and 'protein_gravy' in out.columns:
        out['protein_gravy_proxy'] = pd.to_numeric(out['protein_gravy'], errors='coerce').fillna(0)
    elif 'protein_gravy_proxy' not in out.columns:
        out['protein_gravy_proxy'] = 0.0
    if 'gc_content' in out.columns and 'gc_percent_display' not in out.columns:
        gc_raw = pd.to_numeric(out['gc_content'], errors='coerce')
        scale = 100.0 if (not gc_raw.dropna().empty and float(gc_raw.dropna().max()) <= 1.5) else 1.0
        out['gc_percent_display'] = gc_raw * scale
    coupling_terms = candidate_numeric(out, ['atoms_per_nt_N', 'gc_percent_display', 'coding_density_proxy', 'protein_gravy_proxy'], max_cols=4)
    out['rna_orf_coupling_score'] = sum(zscore_series(out[col]) for col in coupling_terms) / max(1, len(coupling_terms))
    cluster_basis = candidate_numeric(out, ['rna_orf_coupling_score', 'nt_entropy', 'atoms_per_nt_N', 'gc_percent_display'], max_cols=4)
    out['strategy_score'] = sum(zscore_series(out[col]) for col in cluster_basis) / max(1, len(cluster_basis))
    return out, cluster_basis, coupling_terms


def infer_proteome_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    out = df.copy()
    if 'entity_id' not in out.columns:
        out['entity_id'] = out['protein_id']
    resource_terms = candidate_numeric(out, ['N_atoms_per_aa', 'S_atoms_per_aa', 'C_N_ratio', 'sulfur_aa_frac'], max_cols=4)
    if resource_terms:
        out['resource_budget_score'] = sum(zscore_series(out[col]) for col in resource_terms) / len(resource_terms)
    else:
        out['resource_budget_score'] = 0.0
    adaptation_terms = candidate_numeric(out, ['pI', 'gravy', 'instability_index', 'aromaticity'], max_cols=4)
    out['adaptation_score'] = sum(zscore_series(out[col]) for col in adaptation_terms) / max(1, len(adaptation_terms))
    cluster_basis = candidate_numeric(out, ['resource_budget_score', 'adaptation_score', 'N_atoms_per_aa', 'pI'], max_cols=4)
    out['strategy_score'] = sum(zscore_series(out[col]) for col in cluster_basis) / max(1, len(cluster_basis))
    return out, cluster_basis, resource_terms


def assign_clusters(score: pd.Series) -> pd.Series:
    score = pd.to_numeric(score, errors='coerce').fillna(0)
    if score.nunique() <= 1:
        return pd.Series(['Balanced'] * len(score), index=score.index)
    labels = ['Resource-lean', 'Balanced', 'Adaptive-shifted', 'Extreme-tail']
    quantiled = pd.qcut(score.rank(method='first'), q=min(4, score.nunique()), labels=labels[:min(4, score.nunique())], duplicates='drop')
    return pd.Series(quantiled.astype(str), index=score.index).fillna('Balanced')


def top_bottom(df: pd.DataFrame, score_col: str, id_cols: list[str], n: int = 12) -> dict[str, list[dict[str, Any]]]:
    cols = [c for c in id_cols + [score_col] if c in df.columns]
    scored = df[cols].copy()
    scored[score_col] = pd.to_numeric(scored[score_col], errors='coerce')
    scored = scored.dropna(subset=[score_col])
    return {
        'high': records(scored.nlargest(min(n, len(scored)), score_col)),
        'low': records(scored.nsmallest(min(n, len(scored)), score_col)),
    }


def fisher_pvalue_from_r(r: float, n: int) -> float:
    if n < 4:
        return 1.0
    r = max(min(float(r), 0.999999), -0.999999)
    z = 0.5 * math.log((1.0 + r) / (1.0 - r)) * math.sqrt(max(1.0, n - 3.0))
    return float(math.erfc(abs(z) / math.sqrt(2.0)))


def benjamini_hochberg_fdr(pvalues: list[float]) -> list[float]:
    if not pvalues:
        return []
    m = len(pvalues)
    ranked = sorted(enumerate(pvalues), key=lambda item: item[1])
    adjusted = [1.0] * m
    prev = 1.0
    for reverse_rank, (idx, p) in enumerate(reversed(ranked), start=1):
        rank = m - reverse_rank + 1
        value = min(prev, (p * m) / max(1, rank))
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


def build_feature_cards(df: pd.DataFrame, cols: list[str]) -> dict[str, Any]:
    return {col: percentile_summary(df[col]) for col in cols if col in df.columns}


def build_correlation_matrix(df: pd.DataFrame, cols: list[str]) -> tuple[dict[str, dict[str, dict[str, float]]], list[dict[str, Any]]]:
    use = [c for c in cols if c in df.columns]
    if len(use) < 2:
        return {}, []
    source = df[use].apply(pd.to_numeric, errors='coerce')
    pearson = source.corr(method='pearson').fillna(0).round(4)
    spearman = source.corr(method='spearman').fillna(0).round(4)
    edge_all = []
    for i, src in enumerate(use):
        for dst in use[i + 1:]:
            pair = source[[src, dst]].dropna()
            n = int(len(pair))
            val = float(spearman.loc[src, dst])
            p_value = fisher_pvalue_from_r(val, n)
            edge_all.append({
                'source': src,
                'target': dst,
                'weight': round(val, 4),
                'n': n,
                'p_value': round(float(p_value), 8),
                'method': 'spearman',
            })
    fdr_values = benjamini_hochberg_fdr([float(item['p_value']) for item in edge_all])
    for idx, fdr in enumerate(fdr_values):
        edge_all[idx]['fdr'] = round(float(fdr), 8)
    edges = [item for item in edge_all if abs(float(item.get('weight', 0.0))) >= 0.35]
    edges.sort(key=lambda row: abs(float(row.get('weight', 0.0))), reverse=True)
    return {'pearson': pearson.to_dict(), 'spearman': spearman.to_dict()}, edges[:24]


def make_scatter_payload(df: pd.DataFrame, mappings: list[tuple[str, str, str]], id_col: str, name_col: str) -> dict[str, Any]:
    out = {}
    for key, x_col, y_col in mappings:
        if x_col in df.columns and y_col in df.columns:
            cols = [c for c in [id_col, name_col, x_col, y_col] if c in df.columns]
            part = df[cols]
            if len(part) > 1200:
                seed = sum(ord(ch) for ch in f'{key}:{x_col}:{y_col}') % (2**32 - 1)
                part = part.sample(n=1200, random_state=seed)
            out[key] = records(part)
    return out


def choose_name_col(df: pd.DataFrame, fallback: str) -> str:
    for col in ['gene_name', 'gene_symbol', 'description', fallback]:
        if col in df.columns:
            return col
    return fallback


def kpi_from_df(df: pd.DataFrame, omics: str) -> list[dict[str, Any]]:
    if omics == 'genome':
        items = [
            ('Rows', len(df)),
            ('Mean exon GC%', safe_float(pd.to_numeric(df.get('exon_gc_percent'), errors='coerce').mean())),
            ('Mean promoter-minus-exon ΔGC', safe_float(pd.to_numeric(df.get('gc_delta_promoter_minus_exon'), errors='coerce').mean())),
            ('Mean N / base', safe_float(pd.to_numeric(df.get('exon_atoms_N_per_base'), errors='coerce').mean())),
        ]
    elif omics == 'transcriptome':
        items = [
            ('Rows', len(df)),
            ('Mean RNA GC%', safe_float(pd.to_numeric(df.get('gc_percent_display'), errors='coerce').mean())),
            ('Mean nt entropy', safe_float(pd.to_numeric(df.get('nt_entropy'), errors='coerce').mean())),
            ('RNA-ORF coupling', safe_float(pd.to_numeric(df.get('rna_orf_coupling_score'), errors='coerce').mean())),
        ]
    else:
        items = [
            ('Rows', len(df)),
            ('Mean N / aa', safe_float(pd.to_numeric(df.get('N_atoms_per_aa'), errors='coerce').mean())),
            ('Mean S / aa', safe_float(pd.to_numeric(df.get('S_atoms_per_aa'), errors='coerce').mean())),
            ('Mean pI', safe_float(pd.to_numeric(df.get('pI'), errors='coerce').mean())),
        ]
    return [{'label': label, 'value': value} for label, value in items if value is not None]


def select_row_subset(df: pd.DataFrame, omics: str) -> tuple[pd.DataFrame, list[str], list[str]]:
    browse_map = {
        'genome': ['entity_id', 'gene_id', 'gene_name', 'biotype', 'seqid', 'start_1', 'end_1', 'strand', 'strategy_cluster', 'exon_gc_percent', 'promoter_gc_percent', 'gc_delta_promoter_minus_exon', 'exon_atoms_N_per_base', 'stoich_island_score'],
        'transcriptome': ['entity_id', 'transcript_id', 'gene_id', 'gene_symbol', 'transcript_biotype', 'seq_region', 'start', 'end', 'strand', 'strategy_cluster', 'gc_percent_display', 'gc_content', 'nt_entropy', 'atoms_per_nt_N', 'coding_density_proxy', 'rna_orf_coupling_score', 'protein_gravy_proxy'],
        'proteome': ['entity_id', 'protein_id', 'ensembl_gene_id', 'gene_id', 'gene_symbol', 'description', 'length_aa', 'strategy_cluster', 'N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy', 'resource_budget_score', 'adaptation_score'],
    }
    feature_options = [c for c in browse_map[omics] if c in df.columns and c not in {'entity_id', 'gene_id', 'protein_id', 'transcript_id', 'gene_name', 'gene_symbol', 'description'}]
    browse_columns = [c for c in browse_map[omics] if c in df.columns][:10]
    kept = [c for c in browse_map[omics] if c in df.columns]
    subset = df[kept].copy()
    return subset, browse_columns, feature_options[:8]


def profile_payload(df: pd.DataFrame, omics: str, core_cols: list[str], stage_paths: dict[str, str]) -> dict[str, Any]:
    num_cols = numeric_columns(df)
    return {
        'omics': omics,
        'row_count': int(len(df)),
        'column_count': int(len(df.columns)),
        'numeric_column_count': int(len(num_cols)),
        'core_feature_count': int(len(core_cols)),
        'core_features': core_cols,
        'primary_id': infer_primary_id(omics, df.columns.tolist()),
        'source_files': stage_paths,
    }


def build_summary_payload(df: pd.DataFrame, omics: str, species_row: dict[str, Any], core_cols: list[str]) -> dict[str, Any]:
    primary_id = infer_primary_id(omics, df.columns.tolist())
    name_col = choose_name_col(df, primary_id)
    field_meta = field_meta_for_omics(omics, df.columns.tolist())
    feature_cards = build_feature_cards(df, core_cols)
    distributions = {col: hist_payload(df[col]) for col in core_cols[:4] if col in df.columns}
    corr_matrices, edges = build_correlation_matrix(df, core_cols)
    cluster_counts = df['strategy_cluster'].astype(str).value_counts().sort_index().to_dict() if 'strategy_cluster' in df.columns else {}
    cluster_centroids = []
    if 'strategy_cluster' in df.columns:
        for cluster_name, part in df.groupby('strategy_cluster'):
            row = {'cluster': str(cluster_name), 'count': int(len(part))}
            for col in core_cols[:4]:
                if col in part.columns:
                    row[col] = safe_float(pd.to_numeric(part[col], errors='coerce').mean())
            cluster_centroids.append(row)
    scatter_map = {
        'genome': [('promoter_vs_exon_gc', 'exon_gc_percent', 'promoter_gc_percent'), ('gc_delta_vs_n', 'gc_delta_promoter_minus_exon', 'exon_atoms_N_per_base')],
        'transcriptome': [('gc_vs_entropy', 'gc_percent_display', 'nt_entropy'), ('coupling_vs_gravy', 'rna_orf_coupling_score', 'protein_gravy_proxy')],
        'proteome': [('n_vs_pi', 'N_atoms_per_aa', 'pI'), ('s_vs_disulfide', 'S_atoms_per_aa', 'disulfide_density')],
    }[omics]
    scatter = make_scatter_payload(df, scatter_map, primary_id, name_col)
    top_field = core_cols[0] if core_cols else 'strategy_score'
    ranked = top_bottom(df, top_field, [primary_id, name_col])
    top_entities = {'top': ranked.get('high', []), 'bottom': ranked.get('low', [])}
    preview_cols = [c for c in [primary_id, name_col, 'strategy_cluster'] + core_cols[:5] if c in df.columns]
    missingness_fields = [item.get('field') for item in field_meta if item.get('field')] or core_cols[:8]
    missingness = []
    for field in missingness_fields:
        if field not in df.columns:
            continue
        valid_n = int(df[field].notna().sum())
        total_n = int(len(df))
        miss_n = max(0, total_n - valid_n)
        missingness.append({
            'field': field,
            'valid_n': valid_n,
            'missing_n': miss_n,
            'missing_rate': round(float(miss_n / max(1, total_n)), 6),
        })

    composition = []
    category_cols = {
        'genome': ['biotype', 'strand', 'seqid'],
        'transcriptome': ['transcript_biotype', 'biotype', 'strand', 'seq_region'],
        'proteome': ['strategy_cluster'],
    }.get(omics, [])
    for col in category_cols:
        if col not in df.columns:
            continue
        counts = df[col].astype(str).value_counts().head(12)
        composition.append({
            'field': col,
            'counts': [{'label': key, 'count': int(value)} for key, value in counts.items()],
        })
    return {
        'display_name': OMICS_META[omics]['display_name'],
        'description': OMICS_META[omics]['description'],
        'field_meta': field_meta,
        'kpis': kpi_from_df(df, omics),
        'feature_cards': feature_cards,
        'distributions': distributions,
        'scatter': scatter,
        'correlation_matrix': corr_matrices.get('spearman', {}),
        'correlation_matrices': corr_matrices,
        'strategy_breakdown': [{'cluster': k, 'count': int(v)} for k, v in cluster_counts.items()],
        'cluster_centroids': cluster_centroids,
        'coupling_edges': edges,
        'preview_rows': records(df[preview_cols].head(12)),
        'top_entities': top_entities,
        'missingness': missingness,
        'categorical_composition': composition,
        'browse_note': f'Auto-generated from {species_row["display_name"]} {omics} feature tables without manual biological annotation.',
    }


def build_analysis_payload(df: pd.DataFrame, omics: str, core_cols: list[str]) -> dict[str, Any]:
    primary_id = infer_primary_id(omics, df.columns.tolist())
    name_col = choose_name_col(df, primary_id)
    outliers = {
        'high': [],
        'low': [],
        'multivariate': [],
        'feature_contributions': {},
    }
    score_col = 'strategy_score' if 'strategy_score' in df.columns else (core_cols[0] if core_cols else '')
    robust_center = 0.0
    robust_scale = 1.0
    robust_n = 0
    if score_col:
        keep_cols = [c for c in [primary_id, name_col, score_col, *core_cols[:2]] if c in df.columns]
        scored = df[keep_cols].copy()
        score_series = pd.to_numeric(scored.get(score_col), errors='coerce')
        valid = score_series.dropna()
        if not valid.empty:
            robust_n = int(len(valid))
            robust_center = float(valid.median())
            mad = float((valid - robust_center).abs().median())
            std = float(valid.std(ddof=0))
            robust_scale = (1.4826 * mad) if mad > 0 else (std if std > 0 else 1.0)
            scored['robust_z'] = (score_series - robust_center) / robust_scale
            scored['outlier_score'] = scored['robust_z'].abs()
            high = scored[scored['robust_z'] >= 2.5].copy()
            low = scored[scored['robust_z'] <= -2.5].copy()
            if high.empty and low.empty:
                high = scored.nlargest(min(12, len(scored)), 'robust_z')
                low = scored.nsmallest(min(12, len(scored)), 'robust_z')
            else:
                high = high.sort_values('robust_z', ascending=False).head(24)
                low = low.sort_values('robust_z', ascending=True).head(24)
            for idx, row in enumerate(records(high), start=1):
                item = dict(row)
                item['outlier_rank'] = idx
                item['outlier_label'] = 'candidate'
                outliers['high'].append(item)
            for idx, row in enumerate(records(low), start=1):
                item = dict(row)
                item['outlier_rank'] = idx
                item['outlier_label'] = 'candidate'
                outliers['low'].append(item)

    analysis: dict[str, Any] = {
        'evidence_level': 'exploratory',
        'result_type': 'hypothesis_generating',
        'outliers': outliers,
        'tradeoff_front': [],
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
        },
    }
    if len(core_cols) >= 2:
        x_col, y_col = core_cols[:2]
        part = df[[c for c in [primary_id, name_col, x_col, y_col] if c in df.columns]].copy()
        part = part.rename(columns={x_col: 'cost_axis', y_col: 'adapt_axis'})
        part['front_score'] = (
            pd.to_numeric(part['cost_axis'], errors='coerce').rank(pct=True)
            + pd.to_numeric(part['adapt_axis'], errors='coerce').rank(pct=True)
        ) / 2
        part['front_rank'] = pareto_front_ranks(part, 'cost_axis', 'adapt_axis')
        part = part.sort_values(['front_rank', 'front_score'], ascending=[True, False])
        analysis['tradeoff_front'] = records(part.head(800))
    if omics == 'genome':
        sort_cols = [c for c in ['seqid', 'start_1', 'end_1'] if c in df.columns]
        ordered = df.sort_values(sort_cols) if sort_cols else df
        block_size = max(120, len(ordered) // 12)
        values = pd.to_numeric(ordered['stoich_island_score'], errors='coerce').fillna(0)
        islands = []
        for i, (_, part) in enumerate(ordered.groupby(np.arange(len(ordered)) // block_size), start=1):
            score = pd.to_numeric(part.get('stoich_island_score'), errors='coerce').fillna(0)
            islands.append({
                'segment': f'Window {i}',
                'seqid': str(part.get('seqid').iloc[0]) if 'seqid' in part.columns and len(part) else '',
                'start': int(pd.to_numeric(part.get('start_1'), errors='coerce').min()) if 'start_1' in part.columns else None,
                'end': int(pd.to_numeric(part.get('end_1'), errors='coerce').max()) if 'end_1' in part.columns else None,
                'gene_count': int(len(part)),
                'mean_island_score': round(float(score.mean()), 4),
            })
        analysis['stoich_islands'] = islands
        analysis['display_labels']['stoich_islands'] = 'Stoichiometric island candidates'
    elif omics == 'transcriptome':
        motif_col = None
        for candidate in ['transcript_biotype', 'gene_biotype', 'strategy_cluster']:
            if candidate in df.columns:
                motif_col = candidate
                break
        counts = df[motif_col].astype(str).value_counts().head(8) if motif_col else pd.Series(dtype=int)
        themes = [{'theme': k, 'count': int(v)} for k, v in counts.items()]
        analysis['motif_themes'] = themes
        analysis['composition_themes'] = themes
        analysis['display_labels']['motif_themes'] = 'Compositional themes'
    else:
        means = []
        for col in core_cols[:6]:
            if col in df.columns:
                means.append({'feature': col, 'mean': safe_float(pd.to_numeric(df[col], errors='coerce').mean())})
        analysis['resource_budget'] = means
        analysis['sequence_intrinsic_resource_profile'] = means
        analysis['display_labels']['resource_budget'] = 'Sequence-intrinsic resource profile'
    return analysis


def derive_fingerprint(genome_df: pd.DataFrame | None, transcript_df: pd.DataFrame | None, proteome_df: pd.DataFrame | None) -> dict[str, float]:
    def mean_of(df: pd.DataFrame | None, col: str) -> float:
        if df is None or col not in df.columns:
            return 0.0
        return round(float(pd.to_numeric(df[col], errors='coerce').mean()), 4)

    return {
        'genome_gc': mean_of(genome_df, 'exon_gc_percent'),
        'promoter_gc': mean_of(genome_df, 'promoter_gc_percent'),
        'genome_n_per_base': mean_of(genome_df, 'exon_atoms_N_per_base'),
        'transcript_gc': mean_of(transcript_df, 'gc_content'),
        'transcript_entropy': mean_of(transcript_df, 'nt_entropy'),
        'transcript_coupling': mean_of(transcript_df, 'rna_orf_coupling_score'),
        'proteome_n_per_aa': mean_of(proteome_df, 'N_atoms_per_aa'),
        'proteome_s_per_aa': mean_of(proteome_df, 'S_atoms_per_aa'),
        'proteome_pi': mean_of(proteome_df, 'pI'),
        'proteome_gravy': mean_of(proteome_df, 'gravy'),
    }


def correlation_dict_from_df(df: pd.DataFrame, cols: list[str]) -> dict[str, dict[str, float]]:
    use = [c for c in cols if c in df.columns]
    if len(use) < 2:
        return {}
    return df[use].apply(pd.to_numeric, errors='coerce').corr().fillna(0).round(4).to_dict()


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


def outlier_gene_set_from_analysis(
    analysis_payload: dict[str, Any] | None,
    df: pd.DataFrame | None,
    omics: str,
) -> set[str]:
    if not isinstance(analysis_payload, dict):
        return set()
    outliers = analysis_payload.get('outliers')
    if not isinstance(outliers, dict):
        return set()

    candidates: list[dict[str, Any]] = []
    for rows in outliers.values():
        if isinstance(rows, list):
            candidates.extend([row for row in rows if isinstance(row, dict)])
    if not candidates:
        return set()

    genes: set[str] = set()
    pending_ids: set[str] = set()
    for row in candidates:
        for gene_key in ['gene_id', 'ensembl_gene_id']:
            gene = str(row.get(gene_key) or '').strip()
            if gene:
                genes.add(gene)
        for id_key in ['entity_id', 'transcript_id', 'protein_id']:
            entity = str(row.get(id_key) or '').strip()
            if entity:
                pending_ids.add(entity)

    if genes or df is None or df.empty or not pending_ids:
        return genes

    primary_id = infer_primary_id(omics, df.columns.tolist())
    id_cols = [col for col in ['entity_id', primary_id, 'transcript_id', 'protein_id'] if col and col in df.columns]
    gene_cols = [col for col in ['gene_id', 'ensembl_gene_id'] if col in df.columns]
    if not id_cols or not gene_cols:
        return genes

    for _, row in df[id_cols + gene_cols].iterrows():
        gene = ''
        for gene_col in gene_cols:
            value = str(row.get(gene_col) or '').strip()
            if value:
                gene = value
                break
        if not gene:
            continue
        for id_col in id_cols:
            entity = str(row.get(id_col) or '').strip()
            if entity and entity in pending_ids:
                genes.add(gene)
                break
    return genes


def build_cross_omics_payload(
    species_id: str,
    genome_df: pd.DataFrame | None,
    transcript_df: pd.DataFrame | None,
    proteome_df: pd.DataFrame | None,
    fingerprint: dict[str, float],
    outlier_gene_sets: dict[str, set[str]] | None = None,
) -> tuple[dict[str, Any], pd.DataFrame]:
    merged = pd.DataFrame()
    if genome_df is not None and transcript_df is not None:
        g = genome_df.copy()
        r = transcript_df.copy()
        gkey = 'gene_id' if 'gene_id' in g.columns else infer_primary_id('genome', g.columns.tolist())
        rkey = 'gene_id' if 'gene_id' in r.columns else infer_primary_id('transcriptome', r.columns.tolist())
        merged = g.merge(r, left_on=gkey, right_on=rkey, suffixes=('_genome', '_rna'))
        if proteome_df is not None:
            p = proteome_df.copy()
            pkey = 'ensembl_gene_id' if 'ensembl_gene_id' in p.columns else ('gene_id' if 'gene_id' in p.columns else infer_primary_id('proteome', p.columns.tolist()))
            merged = merged.merge(p, left_on=gkey, right_on=pkey, suffixes=('', '_protein'))

    genome_rows = int(len(genome_df)) if genome_df is not None else 0
    transcript_rows = int(len(transcript_df)) if transcript_df is not None else 0
    proteome_rows = int(len(proteome_df)) if proteome_df is not None else 0
    genome_genes = set(genome_df['gene_id'].astype(str)) if genome_df is not None and 'gene_id' in genome_df.columns else set()
    transcript_genes = set(transcript_df['gene_id'].astype(str)) if transcript_df is not None and 'gene_id' in transcript_df.columns else set()
    proteome_genes = (
        set(proteome_df['ensembl_gene_id'].astype(str))
        if proteome_df is not None and 'ensembl_gene_id' in proteome_df.columns
        else (set(proteome_df['gene_id'].astype(str)) if proteome_df is not None and 'gene_id' in proteome_df.columns else set())
    )
    matched_gt = len(genome_genes & transcript_genes)
    matched_tp = len(transcript_genes & proteome_genes)
    matched_all = len(genome_genes & transcript_genes & proteome_genes)

    cross_panel = pd.DataFrame()
    if not merged.empty:
        label_col = 'gene_name'
        if label_col not in merged.columns:
            label_col = choose_name_col(merged, 'gene_id')
        transcript_gc = pd.to_numeric(merged.get('gc_content'), errors='coerce')
        transcript_gc_scale = 100.0 if (not transcript_gc.dropna().empty and float(transcript_gc.dropna().max()) <= 1.5) else 1.0
        cross_panel = pd.DataFrame({
            'gene_id': merged.get('gene_id', merged.get('gene_id_genome', pd.Series([None] * len(merged)))).astype(str),
            'gene_name': merged.get(label_col, merged.get('gene_symbol', pd.Series([None] * len(merged)))),
            'exon_gc_percent': pd.to_numeric(merged.get('exon_gc_percent'), errors='coerce'),
            'transcript_gc': transcript_gc,
            'transcript_gc_percent': transcript_gc * transcript_gc_scale,
            'proteome_n_per_aa': pd.to_numeric(merged.get('N_atoms_per_aa'), errors='coerce'),
            'dna_to_rna_n_shift': pd.to_numeric(merged.get('atoms_per_nt_N'), errors='coerce') - pd.to_numeric(merged.get('exon_atoms_N_per_base'), errors='coerce'),
            'rna_to_protein_n_shift': pd.to_numeric(merged.get('N_atoms_per_aa'), errors='coerce') - pd.to_numeric(merged.get('atoms_per_nt_N'), errors='coerce'),
            'dna_to_rna_n_delta': pd.to_numeric(merged.get('atoms_per_nt_N'), errors='coerce') - pd.to_numeric(merged.get('exon_atoms_N_per_base'), errors='coerce'),
            'rna_to_protein_n_delta': pd.to_numeric(merged.get('N_atoms_per_aa'), errors='coerce') - pd.to_numeric(merged.get('atoms_per_nt_N'), errors='coerce'),
            'dna_to_rna_gc_delta': transcript_gc * transcript_gc_scale - pd.to_numeric(merged.get('exon_gc_percent'), errors='coerce'),
            'pI': pd.to_numeric(merged.get('pI'), errors='coerce'),
            'gravy': pd.to_numeric(merged.get('gravy'), errors='coerce'),
        }).dropna(subset=['gene_id']).head(1500)
        cross_panel['discordance_score'] = (
            pd.to_numeric(cross_panel['dna_to_rna_n_delta'], errors='coerce').abs().fillna(0)
            + pd.to_numeric(cross_panel['rna_to_protein_n_delta'], errors='coerce').abs().fillna(0)
            + (
                pd.to_numeric(cross_panel['dna_to_rna_n_delta'], errors='coerce').fillna(0)
                - pd.to_numeric(cross_panel['rna_to_protein_n_delta'], errors='coerce').fillna(0)
            ).abs()
        ).round(6)
        cross_panel['main_driver'] = np.where(
            cross_panel['dna_to_rna_n_delta'].abs() >= cross_panel['rna_to_protein_n_delta'].abs(),
            'DNA_to_RNA_shift',
            'RNA_to_protein_shift',
        )

    corr_matrices: dict[str, dict[str, dict[str, float]]] = {}
    corr_details: list[dict[str, Any]] = []
    if not cross_panel.empty:
        corr_frame = cross_panel[['exon_gc_percent', 'transcript_gc', 'proteome_n_per_aa']].rename(columns={'exon_gc_percent': 'genome_gc'})
        corr_frame = corr_frame.dropna()
        if len(corr_frame) >= 2:
            corr_matrices = {
                'pearson': corr_frame.corr(method='pearson').fillna(0).round(4).to_dict(),
                'spearman': corr_frame.corr(method='spearman').fillna(0).round(4).to_dict(),
            }
            pvals = []
            pairs = []
            cols = corr_frame.columns.tolist()
            for i, src in enumerate(cols):
                for dst in cols[i + 1:]:
                    r = float(corr_frame.corr(method='spearman').loc[src, dst])
                    pval = fisher_pvalue_from_r(r, int(len(corr_frame)))
                    pvals.append(pval)
                    pairs.append((src, dst, r, pval))
            fdrs = benjamini_hochberg_fdr(pvals)
            for idx, (src, dst, r, pval) in enumerate(pairs):
                corr_details.append({
                    'method': 'spearman',
                    'feature_a': src,
                    'feature_b': dst,
                    'r': round(float(r), 6),
                    'n': int(len(corr_frame)),
                    'p_value': round(float(pval), 8),
                    'fdr': round(float(fdrs[idx]), 8),
                })
    if not corr_matrices:
        fallback = {
            'genome_gc': {'genome_gc': 1.0, 'transcript_gc': 0.0, 'proteome_n_per_aa': 0.0},
            'transcript_gc': {'genome_gc': 0.0, 'transcript_gc': 1.0, 'proteome_n_per_aa': 0.0},
            'proteome_n_per_aa': {'genome_gc': 0.0, 'transcript_gc': 0.0, 'proteome_n_per_aa': 1.0},
        }
        corr_matrices = {'pearson': fallback, 'spearman': fallback}
    points = cross_panel[['gene_name', 'exon_gc_percent', 'proteome_n_per_aa']].dropna() if not cross_panel.empty else pd.DataFrame()
    if len(points) > 500:
        points = points.sample(n=500, random_state=17)
    transformations = records(cross_panel.sort_values('discordance_score', ascending=False).head(500)) if not cross_panel.empty else []
    top_transformations = records(cross_panel.sort_values('discordance_score', ascending=False).head(24)) if not cross_panel.empty else []
    shared_outliers = shared_outlier_summary(outlier_gene_sets or {})
    payload = {
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
        'transformations': transformations,
        'cross_points': records(points.rename(columns={'gene_name': 'gene_name'})) if not cross_panel.empty else [],
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
    return payload, cross_panel


def build_stage5_artifacts(
    metadata: pd.DataFrame,
    species_tables: dict[str, dict[str, dict[str, Path]]],
    stage5_dir: Path,
    progress: Callable[[str], None] | None = None,
    stage_index: int = 5,
    stage_total: int = 6,
) -> None:
    ensure_dir(stage5_dir)
    compare_dir = stage5_dir / 'compare'
    ensure_dir(compare_dir)
    artifact_manifest_rows = []
    fingerprint_rows = []

    total_species = int(len(metadata))
    for idx, species_row in enumerate(metadata.to_dict(orient='records'), start=1):
        species_id = species_row['species_id']
        if progress is not None:
            stage5_percent = 100.0 if total_species <= 0 else (idx / total_species) * 100.0
            progress(
                f'{stage_message(stage_index, stage_total, "Deriving summaries and analysis artifacts")} '
                f'| Species {progress_bar(idx, total_species, width=20)} {stage5_percent:6.2f}% ({idx}/{total_species}) | {species_id}'
            )
        omics_paths = species_tables[species_id]
        out_species = stage5_dir / species_id
        ensure_dir(out_species)
        transformed = {}
        canonical_analysis: dict[str, dict[str, Any]] = {}
        browse_meta = {}
        for omics, table_paths in omics_paths.items():
            scope_sources = {
                'core': table_paths.get('core') or table_paths.get('full'),
                'full': table_paths.get('full') or table_paths.get('core'),
            }
            scope_payloads: dict[str, dict[str, Any]] = {}
            first_core_cols: list[str] = []
            first_aux_cols: list[str] = []
            for scope_name, source_path in scope_sources.items():
                if not source_path or not Path(source_path).exists():
                    continue
                source_df = read_csv(source_path).copy()
                if omics == 'genome':
                    aug_df, core_cols, aux_cols = infer_genome_features(source_df)
                elif omics == 'transcriptome':
                    aug_df, core_cols, aux_cols = infer_transcriptome_features(source_df)
                else:
                    aug_df, core_cols, aux_cols = infer_proteome_features(source_df)
                if not first_core_cols:
                    first_core_cols = core_cols
                    first_aux_cols = aux_cols
                aug_df['strategy_cluster'] = assign_clusters(aug_df['strategy_score'])
                subset_rows, browse_columns, feature_options = select_row_subset(aug_df, omics)
                summary = build_summary_payload(aug_df, omics, species_row, core_cols)
                summary['scope'] = scope_name
                summary['available_scopes'] = sorted(set(scope_sources.keys()))
                analysis = build_analysis_payload(aug_df, omics, core_cols)
                analysis['scope'] = scope_name
                scope_payloads[scope_name] = {
                    'aug_df': aug_df,
                    'subset_rows': subset_rows,
                    'browse_columns': browse_columns,
                    'feature_options': feature_options,
                    'primary_id': infer_primary_id(omics, aug_df.columns.tolist()),
                    'summary': summary,
                    'analysis': analysis,
                }

            if not scope_payloads:
                continue

            canonical_scope = 'core' if 'core' in scope_payloads else next(iter(scope_payloads.keys()))
            canonical = scope_payloads[canonical_scope]
            omics_out = out_species / omics
            ensure_dir(omics_out)

            profile = profile_payload(
                canonical['aug_df'],
                omics,
                first_core_cols or [],
                {'core_csv': str(table_paths.get('core', '')), 'full_csv': str(table_paths.get('full', ''))},
            )
            write_json(omics_out / 'profile.json', profile)
            write_json(omics_out / 'core_features.json', {'omics': omics, 'features': first_core_cols, 'auxiliary_features': first_aux_cols})

            for scope_name, payload in scope_payloads.items():
                payload['subset_rows'].to_csv(omics_out / f'rows_for_platform.{scope_name}.csv', index=False)
                payload['aug_df'].to_csv(omics_out / f'derived_features.{scope_name}.csv', index=False)
                write_json(omics_out / f'summary.{scope_name}.json', payload['summary'])
                write_json(omics_out / f'analysis.{scope_name}.json', payload['analysis'])
                for artifact_name in [
                    f'summary.{scope_name}.json',
                    f'analysis.{scope_name}.json',
                    f'derived_features.{scope_name}.csv',
                    f'rows_for_platform.{scope_name}.csv',
                ]:
                    artifact_manifest_rows.append({
                        'species_id': species_id,
                        'omics_type': omics,
                        'artifact_type': artifact_name.replace('.json', '').replace('.csv', '').replace('.', '_'),
                        'path': str((omics_out / artifact_name).relative_to(stage5_dir)),
                    })

            # Compatibility outputs keep old readers unchanged.
            canonical['subset_rows'].to_csv(omics_out / 'rows_for_platform.csv', index=False)
            canonical['aug_df'].to_csv(omics_out / 'derived_features.csv', index=False)
            write_json(omics_out / 'summary.json', canonical['summary'])
            write_json(omics_out / 'analysis.json', canonical['analysis'])

            transformed[omics] = canonical['aug_df']
            canonical_analysis[omics] = canonical['analysis']
            browse_meta[omics] = {
                'browse_columns': canonical['browse_columns'],
                'feature_options': canonical['feature_options'],
                'primary_id': canonical['primary_id'],
                'available_scopes': sorted(scope_payloads.keys()),
            }

            for artifact_name in ['profile.json', 'core_features.json', 'summary.json', 'analysis.json', 'derived_features.csv', 'rows_for_platform.csv']:
                artifact_manifest_rows.append({
                    'species_id': species_id,
                    'omics_type': omics,
                    'artifact_type': artifact_name.replace('.json', '').replace('.csv', ''),
                    'path': str((omics_out / artifact_name).relative_to(stage5_dir)),
                })

        fingerprint = derive_fingerprint(transformed.get('genome'), transformed.get('transcriptome'), transformed.get('proteome'))
        outlier_gene_sets = {
            omics: outlier_gene_set_from_analysis(canonical_analysis.get(omics), transformed.get(omics), omics)
            for omics in ['genome', 'transcriptome', 'proteome']
        }
        cross_payload, cross_panel = build_cross_omics_payload(
            species_id,
            transformed.get('genome'),
            transformed.get('transcriptome'),
            transformed.get('proteome'),
            fingerprint,
            outlier_gene_sets=outlier_gene_sets,
        )
        write_json(out_species / 'cross_omics.json', cross_payload)
        if not cross_panel.empty:
            cross_panel.to_csv(out_species / 'cross_omics_panel.csv', index=False)
            artifact_manifest_rows.append({
                'species_id': species_id,
                'omics_type': 'cross',
                'artifact_type': 'cross_omics_panel',
                'path': str((out_species / 'cross_omics_panel.csv').relative_to(stage5_dir)),
            })
        artifact_manifest_rows.append({
            'species_id': species_id,
            'omics_type': 'cross',
            'artifact_type': 'cross_omics',
            'path': str((out_species / 'cross_omics.json').relative_to(stage5_dir)),
        })
        fingerprint_rows.append({'species_id': species_id, 'display_name': species_row['display_name'], **fingerprint})

        write_json(out_species / 'browse_meta.json', browse_meta)

    fingerprints_df = pd.DataFrame(fingerprint_rows)
    fingerprints_df.to_csv(compare_dir / 'species_fingerprints.csv', index=False)
    pairs = []
    if len(fingerprints_df) > 1:
        keys = [c for c in fingerprints_df.columns if c not in {'species_id', 'display_name'}]
        matrix = fingerprints_df[keys].astype(float).to_numpy()
        mins = matrix.min(axis=0)
        maxs = matrix.max(axis=0)
        spans = np.where((maxs - mins) == 0, 1, maxs - mins)
        scaled = (matrix - mins) / spans
        for i, src in fingerprints_df.iterrows():
            for j in range(i + 1, len(fingerprints_df)):
                dst = fingerprints_df.iloc[j]
                dist = float(np.linalg.norm(scaled[i] - scaled[j]))
                pairs.append({'source': src['species_id'], 'target': dst['species_id'], 'distance': round(dist, 4)})
    pd.DataFrame(pairs).to_csv(compare_dir / 'compare_pairs.csv', index=False)
    pd.DataFrame(artifact_manifest_rows).to_csv(stage5_dir / 'analysis_artifact.csv', index=False)
    write_json(stage5_dir / 'artifact_manifest.json', {
        'stage': 'stage5_artifacts',
        'species_count': int(len(metadata)),
        'artifact_count': int(len(artifact_manifest_rows)),
        'compare_pairs': int(len(pairs)),
    })


def build_stage6_registry(metadata: pd.DataFrame, stage5_dir: Path, stage6_dir: Path, platform_data_root: Path | None = None) -> None:
    ensure_dir(stage6_dir)
    artifacts = pd.read_csv(stage5_dir / 'analysis_artifact.csv')
    fingerprints = pd.read_csv(stage5_dir / 'compare' / 'species_fingerprints.csv')
    compare_pairs = pd.read_csv(stage5_dir / 'compare' / 'compare_pairs.csv') if (stage5_dir / 'compare' / 'compare_pairs.csv').exists() else pd.DataFrame(columns=['source', 'target', 'distance'])

    species_rows = []
    omics_meta_out = json.loads(json.dumps(OMICS_META))
    for species_row in metadata.to_dict(orient='records'):
        species_id = species_row['species_id']
        species_art_dir = stage5_dir / species_id
        browse_meta = json.loads((species_art_dir / 'browse_meta.json').read_text(encoding='utf-8'))
        species_out = stage6_dir / species_id
        ensure_dir(species_out)
        omics_index = {}
        for omics in ['genome', 'transcriptome', 'proteome']:
            src_dir = species_art_dir / omics
            if not src_dir.exists():
                continue
            dst_dir = species_out / omics
            ensure_dir(dst_dir)
            scope_rows: dict[str, pd.DataFrame] = {}
            scope_summaries: dict[str, dict[str, Any]] = {}
            scope_analyses: dict[str, dict[str, Any]] = {}
            for scope_name in ['core', 'full']:
                rows_path = src_dir / f'rows_for_platform.{scope_name}.csv'
                summary_path = src_dir / f'summary.{scope_name}.json'
                analysis_path = src_dir / f'analysis.{scope_name}.json'
                if not rows_path.exists() or not summary_path.exists() or not analysis_path.exists():
                    continue
                scope_rows[scope_name] = pd.read_csv(rows_path)
                scope_summaries[scope_name] = json.loads(summary_path.read_text(encoding='utf-8'))
                scope_analyses[scope_name] = json.loads(analysis_path.read_text(encoding='utf-8'))
                write_json(dst_dir / f'rows_{scope_name}.json', records(scope_rows[scope_name]))
                write_json(dst_dir / f'summary_{scope_name}.json', scope_summaries[scope_name])
                write_json(dst_dir / f'analysis_{scope_name}.json', scope_analyses[scope_name])

            canonical_scope = 'core' if 'core' in scope_rows else (next(iter(scope_rows.keys())) if scope_rows else '')
            if not canonical_scope:
                rows_df = pd.read_csv(src_dir / 'rows_for_platform.csv')
                summary_payload = json.loads((src_dir / 'summary.json').read_text(encoding='utf-8'))
                analysis_payload = json.loads((src_dir / 'analysis.json').read_text(encoding='utf-8'))
            else:
                rows_df = scope_rows[canonical_scope]
                summary_payload = scope_summaries[canonical_scope]
                analysis_payload = scope_analyses[canonical_scope]

            write_json(dst_dir / 'rows.json', records(rows_df))
            write_json(dst_dir / 'summary.json', summary_payload)
            write_json(dst_dir / 'analysis.json', analysis_payload)

            omics_meta_out[omics]['browse_columns'] = browse_meta[omics]['browse_columns']
            omics_meta_out[omics]['feature_options'] = browse_meta[omics]['feature_options']
            omics_meta_out[omics]['primary_id'] = browse_meta[omics]['primary_id']
            omics_meta_out[omics]['available_scopes'] = browse_meta[omics].get('available_scopes', ['core'])
            if isinstance(summary_payload, dict) and summary_payload.get('field_meta'):
                omics_meta_out[omics]['field_meta'] = summary_payload.get('field_meta')

            omics_index[omics] = {
                'row_count': int(len(rows_df)),
                'scope_row_counts': {scope_name: int(len(df_scope)) for scope_name, df_scope in scope_rows.items()},
                'available_scopes': browse_meta[omics].get('available_scopes', ['core']),
                'kpis': summary_payload['kpis'],
            }

        shutil.copy2(species_art_dir / 'cross_omics.json', species_out / 'cross_omics.json')
        fp_row = fingerprints.loc[fingerprints['species_id'] == species_id].iloc[0].to_dict()
        species_rows.append({
            'species_id': species_id,
            'display_name': species_row['display_name'],
            'short_name': species_row['short_name'],
            'domain': species_row['domain'],
            'clade': species_row['clade'],
            'habitat': species_row['habitat'],
            'genome_size_mb': safe_float(species_row['genome_size_mb']) or 0.0,
            'omics': omics_index,
            'fingerprint': {k: safe_float(v) or 0.0 for k, v in fp_row.items() if k not in {'species_id', 'display_name'}},
        })

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
    write_json(stage6_dir / 'index.json', index_payload)
    write_json(stage6_dir / 'registry_manifest.json', {
        'stage': 'stage6_platform_registry',
        'species_count': len(species_rows),
        'compare_pairs': len(compare_pairs),
    })

    if platform_data_root is not None:
        if platform_data_root.exists():
            shutil.rmtree(platform_data_root)
        shutil.copytree(stage6_dir, platform_data_root)


def run_pipeline(
    source_root: Path,
    output_root: Path,
    platform_data_root: Path | None = None,
    fast_mode: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    def emit(message: str) -> None:
        if progress is not None:
            progress(message)

    stage_total = 6 if fast_mode else 8

    if output_root.exists():
        emit(f'Removing existing pipeline output: {output_root}')
        shutil.rmtree(output_root)
    ensure_dir(output_root)

    emit(stage_message(1, stage_total, f'Scanning source bundle: {source_root}'))
    refs = scan_bundle(source_root)
    if not refs:
        raise SystemExit(f'No CSV feature tables found in {source_root}')
    emit(f'Indexed {len(refs)} dataset files')

    stage0_dir = output_root / 'stage0_source_bundle'
    stage1_dir = output_root / 'stage1_standardized'
    stage2_dir = output_root / 'stage2_validation'
    stage3_dir = output_root / 'stage3_parquet'
    stage4_dir = output_root / 'stage4_catalog'
    stage5_dir = output_root / 'stage5_artifacts'
    stage6_dir = output_root / 'stage6_platform_registry'

    emit(stage_message(2, stage_total, 'Stage 0: recording source inventory'))
    copy_stage0(refs, stage0_dir, materialize_sources=not fast_mode)
    emit(stage_message(3, stage_total, 'Stage 1: building standardized registry'))
    metadata, species_tables = build_stage1_standardized(refs, stage1_dir, materialize_sources=not fast_mode)
    if not fast_mode:
        emit(stage_message(4, stage_total, 'Stage 2: validating datasets'))
        build_stage2_validation(metadata, species_tables, stage2_dir)
        emit(stage_message(5, stage_total, 'Stage 3: writing parquet mirrors'))
        build_stage3_parquet(species_tables, stage3_dir)
    stage4_index = 4 if fast_mode else 6
    stage5_index = 5 if fast_mode else 7
    stage6_index = 6 if fast_mode else 8

    emit(stage_message(stage4_index, stage_total, 'Stage 4: building database seed catalog'))
    build_stage4_catalog(metadata, species_tables, stage4_dir)
    emit(stage_message(stage5_index, stage_total, 'Stage 5: deriving summaries and analysis artifacts'))
    build_stage5_artifacts(
        metadata,
        species_tables,
        stage5_dir,
        progress=progress,
        stage_index=stage5_index,
        stage_total=stage_total,
    )
    emit(stage_message(stage6_index, stage_total, 'Stage 6: building platform registry'))
    build_stage6_registry(metadata, stage5_dir, stage6_dir, platform_data_root=platform_data_root)
    emit(f'Build {progress_bar(stage_total, stage_total)} 100.00% | Writing pipeline manifest')

    write_json(output_root / 'pipeline_manifest.json', {
        'project': 'Stoichioomics feature-table case pipeline',
        'source_root': str(source_root),
        'stages': [{name: str(output_root / name)} for name in STAGE_NAMES],
        'species_count': int(len(metadata)),
        'platform_registry': str(stage6_dir),
        'platform_data_root_refreshed': str(platform_data_root) if platform_data_root else None,
        'fast_mode': bool(fast_mode),
    })
    return {
        'source_root': source_root,
        'output_root': output_root,
        'platform_data_root': platform_data_root,
        'species_count': int(len(metadata)),
        'dataset_count': int(len(refs)),
        'platform_registry': stage6_dir,
    }


def main() -> None:
    args = parse_args()
    source_root = Path(args.source_root)
    output_root = Path(args.output_root)
    platform_data_root = Path(args.platform_data_root) if args.platform_data_root else None

    result = run_pipeline(source_root, output_root, platform_data_root=platform_data_root)
    print('Pipeline build finished.')
    print(f'Output root: {result["output_root"]}')
    print(f'Species indexed: {result["species_count"]}')
    print(f'Dataset files indexed: {result["dataset_count"]}')
    if platform_data_root is not None:
        print(f'Platform registry refreshed at: {platform_data_root}')


if __name__ == '__main__':
    main()
