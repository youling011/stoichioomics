from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from django.conf import settings
from backend.apps.common.histogram import finite_histogram
from scipy import stats
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    roc_curve,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import LabelEncoder, StandardScaler

from .feature_panels import build_core_feature_panels


METADATA_COLUMNS = {
    'entity_id', 'gene_id', 'gene_name', 'gene_symbol', 'transcript_id', 'protein_id',
    'sample_id', 'group', 'condition', 'species_id', 'file_name', 'gff_file',
    'omics_type', 'seq_type', 'analysis_type', 'strategy_cluster', 'source_db',
    'description', 'header_raw', 'raw_header', 'seq_md5',
}

OMICS_ALIASES = {
    'auto': 'transcriptome',
    'nucleotide': 'transcriptome',
    'rna': 'transcriptome',
    'cdna': 'transcriptome',
    'transcript': 'transcriptome',
    'transcriptome': 'transcriptome',
    'protein': 'proteome',
    'proteome': 'proteome',
    'peptide': 'proteome',
    'genome': 'genome',
    'dna': 'genome',
}

EXTRACTOR_FILES = {
    'genome': 'genome_stoich_feature_extractor_v3_3_2.py',
    'transcriptome': 'transcriptome_stoich_feature_extractor_v5_2.py',
    'proteome': 'proteome_stoich_feature_extractor_v4_fast.py',
}

EXTRACTOR_VERSION_EVIDENCE = {
    'genome': {
        'version': 'v3.3.2',
        'full_database_source_script': r'E:\A-new-stoichioomics\N-STOICHIOOMICS\数据\基因组\genome_stoich_feature_extractor_v3_3_2.py',
        'evidence': 'protists_genome_batch_manifest_strict_v3_3_2.csv and genome *.schema.json version=v3.3',
    },
    'transcriptome': {
        'version': 'v5.2',
        'full_database_source_script': r'E:\A-new-stoichioomics\N-STOICHIOOMICS\数据\转录组\transcriptome_stoich_feature_extractor_v5_2.py',
        'evidence': 'transcriptome *.core.v5.csv schema plus v5.2 single-pass core/full batch extractor',
    },
    'proteome': {
        'version': 'v4_fast',
        'full_database_source_script': r'E:\A-new-stoichioomics\N-STOICHIOOMICS\数据\蛋白质组\proteome_stoich_feature_extractor_v4_fast.py',
        'evidence': 'run_proteome_batch_from_manifest_v2_parallel.py requires v4_fast and full/core output fields match stored proteome tables',
    },
}

PREFERRED_FEATURES = {
    'genome': [
        'exon_gc_percent', 'promoter_gc_percent', 'gc_delta_promoter_minus_exon',
        'exon_atoms_N_per_base', 'exon_ratio_C_N', 'exon_ratio_N_P',
        'cds_gc_percent', 'gc3_percent', 'stoich_island_score',
    ],
    'transcriptome': [
        'gc_percent_display', 'gc_content', 'nt_entropy', 'atoms_per_nt_N',
        'atoms_per_nt_P', 'C_N_ratio', 'C_P_ratio', 'N_P_ratio',
        'coding_density_proxy', 'rna_orf_coupling_score', 'protein_gravy_proxy',
    ],
    'proteome': [
        'length_aa', 'N_atoms_per_aa', 'S_atoms_per_aa', 'C_N_ratio', 'N_S_ratio',
        'pI', 'gravy', 'instability_index', 'aliphatic_index',
        'resource_budget_score', 'adaptation_score',
    ],
}

BROWSE_COLUMNS = {
    'genome': [
        'entity_id', 'gene_id', 'gene_name', 'sample_id', 'group', 'species_id',
        'biotype', 'seqid', 'start_1', 'end_1', 'strand', 'strategy_cluster',
        'exon_gc_percent', 'promoter_gc_percent',
    ],
    'transcriptome': [
        'entity_id', 'transcript_id', 'gene_id', 'gene_symbol', 'sample_id',
        'group', 'species_id', 'transcript_biotype', 'strategy_cluster',
        'gc_content', 'nt_entropy', 'atoms_per_nt_N',
    ],
    'proteome': [
        'entity_id', 'protein_id', 'gene_id', 'gene_symbol', 'sample_id',
        'group', 'species_id', 'description', 'length_aa', 'strategy_cluster',
        'N_atoms_per_aa', 'S_atoms_per_aa', 'pI', 'gravy',
    ],
}

DIFFERENTIAL_FEATURE_COLUMNS = [
    'feature_name', 'comparison', 'reference_group', 'case_group', 'method',
    'statistic', 'p_value', 'welch_t_p_value', 'fdr', 'effect_size',
    'cliffs_delta', 'importance', 'importance_rank', 'reference_median',
    'case_median', 'reference_n', 'case_n',
]

DIFFERENTIAL_ENTITY_COLUMNS = [
    'gene_key', 'entity_id', 'gene_id', 'gene_name', 'comparison', 'group',
    'species_id', 'analysis_basis', 'score', 'top_feature', 'effect_size',
    'reference_median', 'case_median', 'p_value', 'fdr', 'supporting_feature_count',
]


@dataclass
class SampleInput:
    fasta_path: Path
    gff_path: Path | None
    sample_id: str
    group: str
    species_id: str
    condition: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    if isinstance(value, tuple):
        return [_safe_json(v) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if not isinstance(value, (str, bytes)):
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
    return value


def _normalize_omics(value: str) -> str:
    key = str(value or 'transcriptome').strip().lower()
    return OMICS_ALIASES.get(key, key if key in {'genome', 'transcriptome', 'proteome'} else 'transcriptome')


def _normalize_col(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(value).strip().lower()).strip('_')


def extractor_root() -> Path:
    env_root = os.environ.get('STOICH_FEATURE_EXTRACTOR_ROOT')
    if env_root:
        return Path(env_root)
    configured = getattr(settings, 'STOICH_FEATURE_EXTRACTOR_ROOT', None)
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR).parents[1] / '组学化学计量特征提取代码'


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def feature_extractor_contract() -> dict[str, Any]:
    root = extractor_root()
    contract = {}
    for omics, filename in EXTRACTOR_FILES.items():
        deployed_path = root / filename
        entry = dict(EXTRACTOR_VERSION_EVIDENCE.get(omics, {}))
        entry.update({
            'script_file': filename,
            'deployed_path': str(deployed_path),
            'deployed_sha256': _sha256_file(deployed_path),
        })
        contract[omics] = entry
    return contract


@lru_cache(maxsize=3)
def load_extractor_module(omics: str):
    omics = _normalize_omics(omics)
    script = extractor_root() / EXTRACTOR_FILES[omics]
    if not script.exists():
        raise RuntimeError(f'Missing {omics} stoichiometric extractor: {script}')
    spec = importlib.util.spec_from_file_location(f'stoich_{omics}_extractor_runtime', script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Cannot load extractor module: {script}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        missing = exc.name or str(exc)
        raise RuntimeError(
            f'{omics} extractor requires Python package "{missing}". '
            'Install project requirements again: pip install -r requirements.txt'
        ) from exc
    return module


def _read_sample_sheet(sample_sheet_path: Path | None) -> pd.DataFrame:
    if not sample_sheet_path:
        return pd.DataFrame()
    sheet = pd.read_csv(sample_sheet_path, sep=None, engine='python')
    sheet.columns = [_normalize_col(col) for col in sheet.columns]
    rename = {
        'file': 'file_name',
        'filename': 'file_name',
        'fasta': 'file_name',
        'fasta_file': 'file_name',
        'path': 'file_name',
        'sample': 'sample_id',
        'sample_name': 'sample_id',
        'species': 'species_id',
        'gff': 'gff_file',
        'gff3': 'gff_file',
        'annotation': 'gff_file',
        'annotation_file': 'gff_file',
    }
    return sheet.rename(columns={k: v for k, v in rename.items() if k in sheet.columns})


def _build_sample_inputs(
    input_files: list[Path],
    annotation_files: list[Path],
    sample_sheet_path: Path | None,
    analysis_type: str,
    group_field: str,
    omics: str,
) -> tuple[list[SampleInput], str]:
    sheet = _read_sample_sheet(sample_sheet_path)
    group_field_norm = _normalize_col(group_field or '')
    fallback_group_field = 'species_id' if analysis_type == 'multi_species' else 'condition'
    if analysis_type == 'single_sequence':
        fallback_group_field = 'group'
    if not group_field_norm:
        group_field_norm = fallback_group_field

    annotation_by_name = {path.name: path for path in annotation_files}
    annotation_by_stem = {path.stem.lower(): path for path in annotation_files}
    sheet_by_file: dict[str, pd.Series] = {}
    if not sheet.empty:
        if 'file_name' not in sheet.columns:
            raise ValueError('Sample sheet must contain file_name/fasta_file for uploaded FASTA files.')
        sheet['file_name'] = sheet['file_name'].map(lambda value: Path(str(value)).name)
        sheet_by_file = {str(row['file_name']): row for _, row in sheet.iterrows()}

    samples: list[SampleInput] = []
    for fasta_path in input_files:
        row = sheet_by_file.get(fasta_path.name)
        sample_id = str(row.get('sample_id')) if row is not None and 'sample_id' in row else fasta_path.stem
        condition = str(row.get('condition')) if row is not None and 'condition' in row else ('single' if analysis_type == 'single_sequence' else sample_id)
        species_id = str(row.get('species_id')) if row is not None and 'species_id' in row else (sample_id if analysis_type == 'multi_species' else 'uploaded_species')
        if analysis_type == 'single_sequence':
            group = 'single'
        elif row is not None and group_field_norm in row.index:
            group = str(row.get(group_field_norm))
        elif fallback_group_field == 'species_id':
            group = species_id
        else:
            group = condition

        gff_path = None
        if omics == 'genome':
            gff_name = str(row.get('gff_file')) if row is not None and 'gff_file' in row and pd.notna(row.get('gff_file')) else ''
            if gff_name:
                gff_path = annotation_by_name.get(Path(gff_name).name) or annotation_by_stem.get(Path(gff_name).stem.lower())
            if gff_path is None and len(annotation_files) == 1 and len(input_files) == 1:
                gff_path = annotation_files[0]
            if gff_path is None:
                fasta_stem = fasta_path.stem.lower()
                gff_path = next((path for stem, path in annotation_by_stem.items() if stem == fasta_stem or stem.startswith(fasta_stem)), None)
            if gff_path is None:
                raise ValueError(f'Genome analysis requires a matching GFF3 annotation file for {fasta_path.name}.')

        samples.append(SampleInput(
            fasta_path=fasta_path,
            gff_path=gff_path,
            sample_id=sample_id,
            group=group,
            species_id=species_id,
            condition=condition,
        ))
    return samples, group_field_norm


def _write_rows_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text('', encoding='utf-8')
        return
    colset = set()
    for row in rows:
        colset.update(row.keys())
    cols = columns or sorted(colset)
    for row in rows:
        for col in cols:
            row.setdefault(col, '')
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=cols, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def _extract_one_sample(sample: SampleInput, omics: str, feature_set: str, output_dir: Path, genetic_code: int) -> pd.DataFrame:
    raw_dir = output_dir / 'extractor_raw'
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_csv = raw_dir / f'{sample.sample_id}.{omics}.{feature_set}.csv'
    if omics == 'genome':
        module = load_extractor_module('genome')
        rows, _schema = module.process_one_species(
            fasta_path=str(sample.fasta_path),
            gff_path=str(sample.gff_path),
            species_id=sample.species_id,
            promoter_len=100,
            default_codon_table=int(genetic_code or 11),
            mito_table=1,
            plastid_table=11,
            mito_pattern=r'(mito|mt|chrm|mitochond)',
            plastid_pattern=r'(chloro|plastid|cpdna|chrpt|chloroplast)',
            transcript_strategy='auto',
            orient_to_transcription=True,
            respect_phase=False,
            include_exon=True,
            include_cds_dna=True,
            progress=False,
        )
        if feature_set == 'core':
            rows = module.build_core_rows(rows, fill_noncoding='zero')
            _write_rows_csv(out_csv, rows, columns=module.CORE_FEATURE_COLUMNS)
        else:
            module.write_csv(str(out_csv), rows)
    elif omics == 'transcriptome':
        module = load_extractor_module('transcriptome')
        if hasattr(module, 'extract_for_one_fasta'):
            module.extract_for_one_fasta(
                fasta_path=sample.fasta_path,
                out_csv=out_csv,
                species_id=sample.species_id,
                feature_set=feature_set,
                orf_mode='longest',
                genetic_code=int(genetic_code or 1),
                start_codons=None,
                show_progress=False,
            )
        elif hasattr(module, 'extract_one_fasta_to_targets'):
            module.extract_one_fasta_to_targets(
                fasta_path=Path(sample.fasta_path),
                species_id=sample.species_id,
                orf_mode='longest',
                genetic_code=int(genetic_code or 1),
                start_codons=None,
                targets={feature_set: out_csv},
                show_progress=False,
            )
        else:
            raise RuntimeError('Transcriptome extractor lacks a supported FASTA extraction entry point.')
    elif omics == 'proteome':
        module = load_extractor_module('proteome')
        module.write_features_for_fasta(
            fasta_path=str(sample.fasta_path),
            out_csv=str(out_csv),
            species_id=sample.species_id,
            feature_set=feature_set,
            append=False,
            progress=False,
        )
    else:
        raise ValueError(f'Unsupported omics_type: {omics}')

    df = pd.read_csv(out_csv).copy()
    df = df.assign(
        sample_id=sample.sample_id,
        group=sample.group,
        condition=sample.condition,
        species_id=sample.species_id,
        file_name=sample.fasta_path.name,
        gff_file=sample.gff_path.name if sample.gff_path else '',
        omics_type=omics,
    )
    return df


def _safe_num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _clean_id_value(value: Any) -> str:
    try:
        if pd.isna(value):
            return ''
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return '' if text.lower() in {'', 'nan', 'none', 'na', 'null', '<na>'} else text


def _id_series(df: pd.DataFrame, primary: str, fallback_prefix: str) -> pd.Series:
    if primary in df.columns:
        values = df[primary].map(_clean_id_value)
    else:
        values = pd.Series('', index=df.index, dtype=object)
    fallback = pd.Series([f'{fallback_prefix}_{idx + 1}' for idx in range(len(df))], index=df.index)
    return values.mask(values == '', fallback).astype(str)


def _filled_id_column(df: pd.DataFrame, primary: str, fallback: pd.Series) -> pd.Series:
    if primary in df.columns:
        values = df[primary].map(_clean_id_value)
    else:
        values = pd.Series('', index=df.index, dtype=object)
    fallback_values = fallback.map(_clean_id_value)
    return values.mask(values == '', fallback_values).astype(str)


def numeric_feature_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for col in df.columns:
        if col in METADATA_COLUMNS:
            continue
        lower = str(col).lower()
        if any(token in lower for token in ['_id', 'header', 'description', 'source_db', 'seq_md5']):
            continue
        series = pd.to_numeric(df[col], errors='coerce')
        if series.notna().sum() >= 2 and series.nunique(dropna=True) > 1:
            cols.append(col)
    return cols


def _zscore(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors='coerce')
    median = values.median(skipna=True)
    mad = (values - median).abs().median(skipna=True)
    scale = mad * 1.4826 if mad and math.isfinite(float(mad)) else values.std(skipna=True)
    if not scale or not math.isfinite(float(scale)):
        return pd.Series(0.0, index=series.index)
    return (values - median) / scale


def _normalize_feature_table(df: pd.DataFrame, omics: str) -> pd.DataFrame:
    data = df.copy()
    if omics == 'genome':
        data['entity_id'] = _id_series(data, 'gene_id', 'gene')
        data['gene_id'] = _filled_id_column(data, 'gene_id', data['entity_id'])
        if 'gene_name' not in data:
            data['gene_name'] = data['entity_id']
        data['gc_delta_promoter_minus_exon'] = pd.to_numeric(data.get('promoter_gc_percent'), errors='coerce') - pd.to_numeric(data.get('exon_gc_percent'), errors='coerce')
        data['promoter_exon_gc_delta'] = data['gc_delta_promoter_minus_exon']
        score_parts = []
        for col in ['exon_gc_percent', 'promoter_gc_percent', 'gc_delta_promoter_minus_exon', 'exon_atoms_N_per_base']:
            if col in data:
                score_parts.append(_zscore(data[col]).abs())
        data['stoich_island_score'] = pd.concat(score_parts, axis=1).mean(axis=1) if score_parts else 0.0
        data['strategy_score'] = data['stoich_island_score']
    elif omics == 'transcriptome':
        data['entity_id'] = _id_series(data, 'transcript_id', 'transcript')
        data['gene_id'] = _filled_id_column(data, 'gene_id', data['entity_id'])
        if 'gene_symbol' not in data:
            data['gene_symbol'] = ''
        gc = pd.to_numeric(data.get('gc_content'), errors='coerce')
        data['gc_percent_display'] = np.where(gc <= 1.5, gc * 100.0, gc)
        length = pd.to_numeric(data.get('length_nt_acgu'), errors='coerce').replace(0, np.nan)
        data['coding_density_proxy'] = pd.to_numeric(data.get('orf_len_nt'), errors='coerce') / length
        data['protein_gravy_proxy'] = pd.to_numeric(data.get('protein_gravy'), errors='coerce')
        score_parts = []
        for col in ['gc_percent_display', 'atoms_per_nt_N', 'nt_entropy', 'coding_density_proxy', 'protein_gravy_proxy']:
            if col in data:
                score_parts.append(_zscore(data[col]).abs())
        data['rna_orf_coupling_score'] = pd.concat(score_parts, axis=1).mean(axis=1) if score_parts else 0.0
        data['strategy_score'] = data['rna_orf_coupling_score']
    else:
        data['entity_id'] = _id_series(data, 'protein_id', 'protein')
        data['gene_id'] = _filled_id_column(data, 'gene_id', data['entity_id'])
        if 'gene_symbol' not in data:
            data['gene_symbol'] = data.get('gene_name', '')
        score_parts = []
        for col in ['N_atoms_per_aa', 'S_atoms_per_aa', 'C_N_ratio', 'N_S_ratio']:
            if col in data:
                score_parts.append(_zscore(data[col]).abs())
        data['resource_budget_score'] = pd.concat(score_parts, axis=1).mean(axis=1) if score_parts else 0.0
        instability = _zscore(data['instability_index']) if 'instability_index' in data else 0.0
        aliphatic = _zscore(data['aliphatic_index']) if 'aliphatic_index' in data else 0.0
        gravy = _zscore(data['gravy']) if 'gravy' in data else 0.0
        data['adaptation_score'] = pd.Series(aliphatic, index=data.index).fillna(0) + pd.Series(gravy, index=data.index).fillna(0) - pd.Series(instability, index=data.index).fillna(0).abs()
        data['strategy_score'] = data['resource_budget_score']

    score = pd.to_numeric(data.get('strategy_score'), errors='coerce')
    q_low = score.quantile(0.33) if score.notna().any() else 0
    q_high = score.quantile(0.66) if score.notna().any() else 0

    def cluster(value):
        value = _safe_num(value)
        if value is None:
            return 'unclassified'
        if value >= q_high:
            return 'high_stoich_shift'
        if value <= q_low:
            return 'low_stoich_shift'
        return 'balanced_stoich'

    data['strategy_cluster'] = score.map(cluster)
    data['gene_key'] = _filled_id_column(data, 'gene_id', data['entity_id'])
    for col in numeric_feature_columns(data):
        data[col] = pd.to_numeric(data[col], errors='coerce')
    return data


def _distribution_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {'min': 0, 'p25': 0, 'p50': 0, 'p75': 0, 'max': 0, 'mean': 0}
    arr = np.asarray(values, dtype=float)
    return {
        'min': float(np.nanmin(arr)),
        'p25': float(np.nanpercentile(arr, 25)),
        'p50': float(np.nanpercentile(arr, 50)),
        'p75': float(np.nanpercentile(arr, 75)),
        'max': float(np.nanmax(arr)),
        'mean': float(np.nanmean(arr)),
    }


def _histogram(values: list[float], bins: int = 32) -> dict[str, Any]:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not clean:
        return {'centers': [], 'counts': [], 'n': 0}
    counts, edges = finite_histogram(clean, bins=min(bins, max(8, len(set(clean)))))
    centers = ((edges[:-1] + edges[1:]) / 2).tolist()
    return {'centers': [float(v) for v in centers], 'counts': [int(v) for v in counts], 'n': int(len(clean))}


def _benjamini_hochberg(p_values: list[float | None]) -> list[float | None]:
    indexed = [(idx, p) for idx, p in enumerate(p_values) if p is not None and math.isfinite(float(p))]
    adjusted = [None for _ in p_values]
    if not indexed:
        return adjusted
    indexed.sort(key=lambda item: item[1])
    n = len(indexed)
    prev = 1.0
    for rank, (idx, p) in reversed(list(enumerate(indexed, start=1))):
        value = min(prev, float(p) * n / rank)
        adjusted[idx] = value
        prev = value
    return adjusted


def _cliffs_delta(x: pd.Series, y: pd.Series) -> float | None:
    xv = pd.to_numeric(x, errors='coerce').dropna().to_numpy()
    yv = pd.to_numeric(y, errors='coerce').dropna().to_numpy()
    if len(xv) == 0 or len(yv) == 0:
        return None
    if len(xv) * len(yv) > 200000:
        rng = np.random.default_rng(17)
        xv = rng.choice(xv, size=min(len(xv), 450), replace=False)
        yv = rng.choice(yv, size=min(len(yv), 450), replace=False)
    greater = sum(int(np.sum(value > yv)) for value in xv)
    lower = sum(int(np.sum(value < yv)) for value in xv)
    return float((greater - lower) / (len(xv) * len(yv)))


def _statistical_feature_tests(df: pd.DataFrame, reference_group: str, omics: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    groups = [str(item) for item in df['group'].dropna().astype(str).unique()]
    if len(groups) < 2:
        return pd.DataFrame(columns=DIFFERENTIAL_FEATURE_COLUMNS), {}
    reference = reference_group if reference_group in groups else groups[0]
    comparisons = [group for group in groups if group != reference]
    rows = []
    for feature in numeric_feature_columns(df):
        ref_values = pd.to_numeric(df.loc[df['group'].astype(str) == reference, feature], errors='coerce').dropna()
        if len(ref_values) < 1:
            continue
        for group in comparisons:
            case_values = pd.to_numeric(df.loc[df['group'].astype(str) == group, feature], errors='coerce').dropna()
            if len(case_values) < 1:
                continue
            p_mwu = None
            p_t = None
            statistic = None
            if len(ref_values) >= 2 and len(case_values) >= 2:
                try:
                    statistic, p_mwu = stats.mannwhitneyu(ref_values, case_values, alternative='two-sided')
                except ValueError:
                    pass
                try:
                    _, p_t = stats.ttest_ind(ref_values, case_values, equal_var=False, nan_policy='omit')
                except ValueError:
                    pass
            effect = float(case_values.median() - ref_values.median())
            rows.append({
                'feature_name': feature,
                'comparison': f'{reference} vs {group}',
                'reference_group': reference,
                'case_group': group,
                'method': 'mann_whitney_u_plus_welch_t',
                'statistic': None if statistic is None else float(statistic),
                'p_value': None if p_mwu is None else float(p_mwu),
                'welch_t_p_value': None if p_t is None or not math.isfinite(float(p_t)) else float(p_t),
                'effect_size': effect,
                'cliffs_delta': _cliffs_delta(ref_values, case_values),
                'reference_median': float(ref_values.median()),
                'case_median': float(case_values.median()),
                'reference_n': int(len(ref_values)),
                'case_n': int(len(case_values)),
                'importance': abs(effect),
            })
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=DIFFERENTIAL_FEATURE_COLUMNS), {'reference_group': reference, 'method': 'statistical_tests'}
    result['fdr'] = _benjamini_hochberg(result['p_value'].tolist())
    result = result.sort_values(['fdr', 'importance', 'feature_name'], ascending=[True, False, True], na_position='last').reset_index(drop=True)
    for col in DIFFERENTIAL_FEATURE_COLUMNS:
        if col not in result.columns:
            result[col] = None
    return result[DIFFERENTIAL_FEATURE_COLUMNS], {'reference_group': reference, 'method': 'mann_whitney_u_plus_welch_t', 'comparisons': comparisons}


def _random_forest_feature_importance(df: pd.DataFrame, reference_group: str) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    groups = df['group'].dropna().astype(str)
    if groups.nunique() < 2:
        return pd.DataFrame(columns=DIFFERENTIAL_FEATURE_COLUMNS), {}, []
    numeric_cols = numeric_feature_columns(df)
    numeric_cols = [col for col in numeric_cols if pd.to_numeric(df[col], errors='coerce').notna().sum() >= 2]
    if not numeric_cols:
        return pd.DataFrame(columns=DIFFERENTIAL_FEATURE_COLUMNS), {}, []
    X = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
    X = X.fillna(X.median(numeric_only=True)).fillna(0)
    variable = [col for col in numeric_cols if X[col].nunique() > 1]
    X = X[variable]
    if X.empty:
        return pd.DataFrame(columns=DIFFERENTIAL_FEATURE_COLUMNS), {}, []
    labeler = LabelEncoder()
    y = labeler.fit_transform(groups)
    model = RandomForestClassifier(
        n_estimators=300,
        random_state=17,
        class_weight='balanced',
        max_features='sqrt',
        min_samples_leaf=1,
    )
    model.fit(X, y)
    train_accuracy = accuracy_score(y, model.predict(X))
    cv_accuracy = None
    class_counts = pd.Series(y).value_counts()
    if len(df) >= 8 and class_counts.min() >= 2:
        n_splits = int(min(5, class_counts.min()))
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=17)
        cv_accuracy = float(cross_val_score(model, X, y, cv=cv, scoring='accuracy').mean())
    roc_auc = None
    if len(labeler.classes_) == 2 and len(df) >= 6 and class_counts.min() >= 2:
        try:
            proba = model.predict_proba(X)[:, 1]
            roc_auc = float(roc_auc_score(y, proba))
        except ValueError:
            roc_auc = None
    rows = []
    for rank, (feature, importance) in enumerate(sorted(zip(X.columns, model.feature_importances_), key=lambda item: item[1], reverse=True), start=1):
        rows.append({
            'feature_name': feature,
            'comparison': ' vs '.join([str(item) for item in labeler.classes_]),
            'reference_group': reference_group if reference_group in set(groups) else str(labeler.classes_[0]),
            'case_group': 'multi_species_rf',
            'method': 'random_forest_classifier',
            'statistic': None,
            'p_value': None,
            'fdr': None,
            'effect_size': None,
            'importance': float(importance),
            'importance_rank': rank,
            'reference_median': None,
            'case_median': None,
            'reference_n': int(class_counts.iloc[0]),
            'case_n': int(len(df) - class_counts.iloc[0]),
        })
    meta = {
        'method': 'random_forest_classifier',
        'n_estimators': 300,
        'classes': [str(item) for item in labeler.classes_],
        'train_accuracy': float(train_accuracy),
        'cv_accuracy': cv_accuracy,
        'roc_auc_train': roc_auc,
        'feature_count': int(X.shape[1]),
        'row_count': int(X.shape[0]),
    }
    result = pd.DataFrame(rows)
    for col in DIFFERENTIAL_FEATURE_COLUMNS:
        if col not in result.columns:
            result[col] = None
    return result[DIFFERENTIAL_FEATURE_COLUMNS], meta, list(X.columns)


def _differential_features(df: pd.DataFrame, analysis_type: str, reference_group: str, omics: str) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    if analysis_type == 'multi_species':
        rf_df, meta, model_features = _random_forest_feature_importance(df, reference_group)
        return rf_df, meta, model_features
    if analysis_type == 'multi_sample':
        stat_df, meta = _statistical_feature_tests(df, reference_group, omics)
        return stat_df, meta, []
    return pd.DataFrame(columns=DIFFERENTIAL_FEATURE_COLUMNS), {}, []


def _selected_diff_features(diff_features: pd.DataFrame, omics: str) -> list[str]:
    if not diff_features.empty and 'feature_name' in diff_features:
        rows = diff_features.copy()
        if 'fdr' in rows:
            sig = rows[pd.to_numeric(rows['fdr'], errors='coerce').fillna(1) <= 0.1]
            if not sig.empty:
                return list(dict.fromkeys(sig['feature_name'].head(30).astype(str).tolist()))
        sort_key = 'importance' if 'importance' in rows else 'effect_size'
        if sort_key in rows:
            rows['_rank_abs'] = pd.to_numeric(rows[sort_key], errors='coerce').abs()
            rows = rows.sort_values('_rank_abs', ascending=False)
        return list(dict.fromkeys(rows['feature_name'].head(30).astype(str).tolist()))
    return PREFERRED_FEATURES.get(omics, [])[:12]


def _differential_entities(
    df: pd.DataFrame,
    analysis_type: str,
    reference_group: str,
    diff_features: pd.DataFrame,
    rf_model_features: list[str],
    omics: str,
) -> pd.DataFrame:
    groups = [str(item) for item in df['group'].dropna().astype(str).unique()]
    if len(groups) < 2:
        return pd.DataFrame(columns=DIFFERENTIAL_ENTITY_COLUMNS)
    reference = reference_group if reference_group in groups else groups[0]
    features = rf_model_features[:30] if analysis_type == 'multi_species' and rf_model_features else _selected_diff_features(diff_features, omics)
    features = [feature for feature in features if feature in df.columns]
    if not features:
        features = numeric_feature_columns(df)[:20]
    if not features:
        return pd.DataFrame(columns=DIFFERENTIAL_ENTITY_COLUMNS)
    numeric_values = df[features].apply(pd.to_numeric, errors='coerce')
    scale = numeric_values.std(skipna=True).replace(0, np.nan).fillna(1.0)
    rows = []
    if analysis_type == 'multi_sample':
        meta_cols = ['gene_key', 'entity_id', 'gene_id', 'gene_name', 'gene_symbol', 'species_id']
        available_meta_cols = [col for col in meta_cols if col in df.columns]
        group_cols = ['gene_key', 'sample_id', 'group']
        work_cols = list(dict.fromkeys([*available_meta_cols, 'sample_id', 'group', *features]))
        work = df[work_cols].copy()
        for feature in features:
            work[feature] = pd.to_numeric(work[feature], errors='coerce')
        per_sample = work.groupby(group_cols, dropna=False)[features].median().reset_index()
        meta_value_cols = [col for col in available_meta_cols if col != 'gene_key']
        if meta_value_cols:
            meta_by_gene = work.groupby('gene_key', dropna=False)[meta_value_cols].first()
        else:
            meta_by_gene = pd.DataFrame(index=per_sample['gene_key'].drop_duplicates())

        for compare_group in [group for group in groups if group != reference]:
            for gene_key, part in per_sample.groupby('gene_key', dropna=False):
                ref_part = part[part['group'].astype(str) == reference]
                case_part = part[part['group'].astype(str) == compare_group]
                if ref_part.empty or case_part.empty:
                    continue
                ref_med = ref_part[features].apply(pd.to_numeric, errors='coerce').median(numeric_only=True)
                case_med = case_part[features].apply(pd.to_numeric, errors='coerce').median(numeric_only=True)
                delta = ((case_med - ref_med) / scale).replace([np.inf, -np.inf], np.nan).dropna()
                if delta.empty:
                    continue
                top_feature = delta.abs().idxmax()
                p_value = None
                p_values = []
                for feature in delta.index:
                    ref_values = pd.to_numeric(ref_part[feature], errors='coerce').dropna()
                    case_values = pd.to_numeric(case_part[feature], errors='coerce').dropna()
                    if len(ref_values) < 2 or len(case_values) < 2:
                        continue
                    try:
                        _, feature_p = stats.mannwhitneyu(ref_values, case_values, alternative='two-sided')
                    except ValueError:
                        continue
                    if feature_p is not None and math.isfinite(float(feature_p)):
                        p_values.append(float(feature_p))
                if p_values:
                    try:
                        _, p_value = stats.combine_pvalues(p_values, method='fisher')
                    except ValueError:
                        p_value = min(p_values)
                    p_value = None if p_value is None or not math.isfinite(float(p_value)) else float(p_value)
                rep = meta_by_gene.loc[gene_key] if gene_key in meta_by_gene.index else pd.Series(dtype=object)
                entity_id = rep.get('entity_id') or gene_key
                rows.append({
                    'gene_key': gene_key,
                    'entity_id': entity_id,
                    'gene_id': rep.get('gene_id') or entity_id,
                    'gene_name': rep.get('gene_name') or rep.get('gene_symbol') or '',
                    'comparison': f'{reference} vs {compare_group}',
                    'group': compare_group,
                    'species_id': rep.get('species_id', ''),
                    'analysis_basis': 'reference_group_feature_delta',
                    'score': float(abs(delta[top_feature])),
                    'top_feature': top_feature,
                    'effect_size': float(case_med[top_feature] - ref_med[top_feature]),
                    'reference_median': _safe_json(ref_med[top_feature]),
                    'case_median': _safe_json(case_med[top_feature]),
                    'p_value': None if p_value is None else float(p_value),
                    'supporting_feature_count': int(len(delta)),
                })
    else:
        importances = {}
        if not diff_features.empty and {'feature_name', 'importance'}.issubset(diff_features.columns):
            for _, row in diff_features.iterrows():
                importances[str(row['feature_name'])] = float(row.get('importance') or 0)
        weights = pd.Series({feature: importances.get(feature, 1.0) for feature in features})
        ref_df = df[df['group'].astype(str) == reference]
        center = ref_df[features].apply(pd.to_numeric, errors='coerce').median(numeric_only=True) if not ref_df.empty else df[features].apply(pd.to_numeric, errors='coerce').median(numeric_only=True)
        for _, row in df.iterrows():
            values = pd.to_numeric(row[features], errors='coerce')
            delta = ((values - center) / scale).replace([np.inf, -np.inf], np.nan).dropna()
            if delta.empty:
                continue
            weighted = (delta.abs() * weights.reindex(delta.index).fillna(1.0))
            top_feature = weighted.idxmax()
            gene_key = row.get('gene_key') or row.get('gene_id') or row.get('entity_id')
            rows.append({
                'gene_key': gene_key,
                'entity_id': row.get('entity_id'),
                'gene_id': row.get('gene_id') or row.get('entity_id'),
                'gene_name': row.get('gene_name') or row.get('gene_symbol') or '',
                'comparison': 'multi_species_rf_reference_deviation',
                'group': row.get('group'),
                'species_id': row.get('species_id', ''),
                'analysis_basis': 'rf_weighted_feature_outlier',
                'score': float(weighted[top_feature]),
                'top_feature': top_feature,
                'effect_size': float(values[top_feature] - center[top_feature]),
                'reference_median': _safe_json(center[top_feature]),
                'case_median': _safe_json(values[top_feature]),
                'p_value': None,
                'supporting_feature_count': int(len(delta)),
            })
    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=DIFFERENTIAL_ENTITY_COLUMNS)
    result['fdr'] = _benjamini_hochberg(result['p_value'].tolist()) if 'p_value' in result else None
    for col in DIFFERENTIAL_ENTITY_COLUMNS:
        if col not in result.columns:
            result[col] = None
    return result.sort_values('score', ascending=False).head(1000).reset_index(drop=True)[DIFFERENTIAL_ENTITY_COLUMNS]


def _field_meta(df: pd.DataFrame, omics: str) -> list[dict[str, Any]]:
    preferred = [feature for feature in PREFERRED_FEATURES.get(omics, []) if feature in df.columns]
    rest = [feature for feature in numeric_feature_columns(df) if feature not in preferred]
    fields = preferred + rest[:80]
    output = []
    for field in fields:
        output.append({
            'field': field,
            'label': field.replace('_', ' '),
            'unit': '',
            'family': 'uploaded_sequence_stoichiometry',
            'value_type': 'numeric',
            'display_transform': 'none',
            'default_chart': 'histogram',
            'allowed_chart_types': ['histogram', 'boxplot', 'scatter', 'heatmap'],
            'allow_in_basic': True,
            'allow_pairwise': True,
            'is_derived': field in {'strategy_score', 'stoich_island_score', 'resource_budget_score', 'adaptation_score', 'rna_orf_coupling_score'},
            'evidence_level': 'computed_from_uploaded_sequence',
            'description_short': 'Computed from uploaded sequence by the platform stoichiometric extractor.',
        })
    return output


def _pca_payload(df: pd.DataFrame, features: list[str]) -> list[dict[str, Any]]:
    usable = df[features].apply(pd.to_numeric, errors='coerce')
    usable = usable.dropna(axis=1, how='all').fillna(usable.median(numeric_only=True)).fillna(0)
    usable = usable.loc[:, usable.nunique(dropna=True) > 1]
    if len(usable) < 2 or usable.shape[1] < 2:
        return []
    coords = PCA(n_components=2, random_state=17).fit_transform(StandardScaler().fit_transform(usable))
    rows = []
    for idx, source_idx in enumerate(usable.index):
        source = df.loc[source_idx]
        rows.append({
            'entity_id': source.get('entity_id'),
            'gene_id': source.get('gene_id'),
            'sample_id': source.get('sample_id'),
            'group': source.get('group'),
            'species_id': source.get('species_id'),
            'pc1': float(coords[idx, 0]),
            'pc2': float(coords[idx, 1]),
        })
    return rows


def _embedding_payload(df: pd.DataFrame, features: list[str], label_field: str) -> dict[str, Any]:
    usable = df[features].apply(pd.to_numeric, errors='coerce')
    usable = usable.dropna(axis=1, how='all').fillna(usable.median(numeric_only=True)).fillna(0)
    usable = usable.loc[:, usable.nunique(dropna=True) > 1]
    if len(usable) < 2 or usable.shape[1] < 2:
        return {
            'available': False,
            'reason': 'At least two rows and two variable features are required for embedding.',
            'method': 'none',
            'points': [],
        }
    matrix = StandardScaler().fit_transform(usable)
    method = 'pca_fallback'
    coords = None
    try:
        if os.environ.get('SEQUENCE_ANALYSIS_ENABLE_UMAP', '').strip().lower() not in {'1', 'true', 'yes'}:
            raise RuntimeError('optional UMAP disabled by default')
        import umap  # type: ignore

        n_neighbors = max(2, min(15, len(usable) - 1))
        coords = umap.UMAP(n_components=2, n_neighbors=n_neighbors, min_dist=0.1, random_state=17).fit_transform(matrix)
        method = 'umap'
    except Exception:
        coords = PCA(n_components=2, random_state=17).fit_transform(matrix)
    points = []
    for idx, source_idx in enumerate(usable.index):
        source = df.loc[source_idx]
        points.append({
            'entity_id': source.get('entity_id'),
            'gene_id': source.get('gene_id'),
            'sample_id': source.get('sample_id'),
            'group': source.get('group'),
            'species_id': source.get('species_id'),
            'label': source.get(label_field),
            'x': float(coords[idx, 0]),
            'y': float(coords[idx, 1]),
        })
    return _safe_json({
        'available': True,
        'method': method,
        'label_field': label_field,
        'points': points,
        'method_metadata': {
            'umap_dependency': 'used when the optional umap package is importable; otherwise PCA fallback is returned',
            'standardization': 'StandardScaler',
            'evidence_level': 'exploratory',
        },
    })


def _coupling_edges(df: pd.DataFrame, features: list[str]) -> list[dict[str, Any]]:
    usable = df[features].apply(pd.to_numeric, errors='coerce')
    corr = usable.corr(method='spearman', min_periods=4)
    rows = []
    pvalues = []
    for i, src in enumerate(corr.columns):
        for dst in corr.columns[i + 1:]:
            value = corr.loc[src, dst]
            if pd.isna(value) or abs(float(value)) < 0.35:
                continue
            clean = usable[[src, dst]].dropna()
            p_value = None
            if len(clean) >= 4:
                try:
                    _, p_value = stats.spearmanr(clean[src], clean[dst])
                except ValueError:
                    p_value = None
            pvalues.append(p_value)
            rows.append({
                'source': src,
                'target': dst,
                'weight': float(value),
                'n': int(len(clean)),
                'p_value': None if p_value is None else float(p_value),
                'method': 'spearman',
            })
    fdr = _benjamini_hochberg(pvalues)
    for idx, value in enumerate(fdr):
        rows[idx]['fdr'] = value
    rows.sort(key=lambda item: abs(float(item['weight'])), reverse=True)
    return rows[:50]


def _build_summary_analysis(df: pd.DataFrame, omics: str, feature_set: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    features = [feature for feature in PREFERRED_FEATURES.get(omics, []) if feature in df.columns]
    if len(features) < 3:
        features = numeric_feature_columns(df)[:12]
    distributions = []
    feature_rank = []
    for feature in features:
        values = pd.to_numeric(df[feature], errors='coerce').dropna().astype(float).tolist()
        distributions.append({'field': feature, 'distribution': _histogram(values), 'summary': _distribution_stats(values)})
        feature_rank.append({'feature': feature, 'mean': _distribution_stats(values)['mean'], 'median': _distribution_stats(values)['p50']})
    feature_rank.sort(key=lambda item: abs(float(item['mean'] or 0)), reverse=True)
    strategy_counts = [
        {'strategy_cluster': str(cluster), 'count': int(count)}
        for cluster, count in df['strategy_cluster'].value_counts().items()
    ]
    outlier_rows = []
    score = pd.to_numeric(df.get('strategy_score'), errors='coerce')
    if score.notna().any():
        z = _zscore(score)
        for idx in z.abs().sort_values(ascending=False).head(24).index:
            source = df.loc[idx]
            outlier_rows.append({
                'entity_id': source.get('entity_id'),
                'gene_id': source.get('gene_id'),
                'gene_name': source.get('gene_name') or source.get('gene_symbol') or '',
                'strategy_cluster': source.get('strategy_cluster'),
                'strategy_score': _safe_json(source.get('strategy_score')),
                'outlier_score': float(abs(z.loc[idx])),
                'robust_z': float(z.loc[idx]),
                'sample_id': source.get('sample_id'),
                'group': source.get('group'),
            })
    high = [row for row in outlier_rows if row['robust_z'] >= 0][:12]
    low = [row for row in outlier_rows if row['robust_z'] < 0][:12]
    analysis = {
        'scope': feature_set,
        'evidence_level': 'exploratory',
        'result_type': 'uploaded_sequence_runtime_result',
        'strategy_breakdown': strategy_counts,
        'feature_rank': feature_rank[:24],
        'outliers': {'high': high, 'low': low, 'multivariate': outlier_rows[:24], 'feature_contributions': {}},
        'tradeoff_front': outlier_rows[:24],
        'coupling_edges': _coupling_edges(df, features[:16]),
        'method_metadata': {
            'feature_extraction': {
                'method': 'project_builtin_omics_stoichiometric_extractors',
                'source_folder': str(extractor_root()),
                'feature_set': feature_set,
                'full_database_feature_extractor_contract': feature_extractor_contract(),
            },
            'outliers': {
                'method': 'robust_zscore_mad_on_strategy_score',
                'evidence_level': 'exploratory',
            },
            'coupling_network': {
                'method': 'spearman_association',
                'multiple_testing': 'benjamini_hochberg_fdr',
            },
        },
    }
    summary = {
        'scope': feature_set,
        'available_scopes': [feature_set],
        'row_count': int(len(df)),
        'sample_count': int(df['sample_id'].nunique()),
        'group_count': int(df['group'].nunique()),
        'species_count': int(df['species_id'].nunique()),
        'kpis': [
            {'label': 'Rows', 'value': int(len(df))},
            {'label': 'Samples', 'value': int(df['sample_id'].nunique())},
            {'label': 'Groups', 'value': int(df['group'].nunique())},
            {'label': 'Numeric features', 'value': int(len(numeric_feature_columns(df)))},
        ],
        'field_meta': _field_meta(df, omics),
        'distributions': distributions,
        'strategy_breakdown': strategy_counts,
        'correlation_matrices': {'spearman': df[features].apply(pd.to_numeric, errors='coerce').corr(method='spearman').fillna(0).to_dict() if features else {}},
        'coupling_edges': analysis['coupling_edges'],
    }
    platform = {
        'species_id': 'uploaded_runtime_result',
        'display_name': 'Uploaded runtime result',
        'omics': omics,
        'omics_cards': [{
            'omics': omics,
            'display_name': omics.title(),
            'description': 'Runtime uploaded sequence result generated by built-in stoichiometric feature extractors.',
            'row_count': int(len(df)),
            'kpis': summary['kpis'],
            'analysis_modules': ['Profile', 'Core features', 'Strategy clusters', 'Outliers', 'Coupling network', 'Feature explorer'],
            'status': 'runtime_ephemeral',
        }],
        'summary': summary,
        'analysis': analysis,
        'browse_columns': [col for col in BROWSE_COLUMNS.get(omics, []) if col in df.columns],
    }
    return summary, analysis, platform


def _plots_payload(df: pd.DataFrame, diff_features: pd.DataFrame, diff_entities: pd.DataFrame, platform: dict[str, Any], omics: str) -> dict[str, Any]:
    features = _selected_diff_features(diff_features, omics)
    features = [feature for feature in features if feature in df.columns]
    if not features:
        features = [feature for feature in PREFERRED_FEATURES.get(omics, []) if feature in df.columns]
    features = features[:12]
    boxplots = []
    for feature in features:
        for group, part in df.groupby('group'):
            values = pd.to_numeric(part[feature], errors='coerce').dropna()
            if values.empty:
                continue
            boxplots.append({
                'feature_name': feature,
                'group': str(group),
                'n': int(len(values)),
                'min': float(values.min()),
                'q1': float(values.quantile(0.25)),
                'median': float(values.median()),
                'q3': float(values.quantile(0.75)),
                'max': float(values.max()),
            })
    profile = {}
    for feature in features:
        values = pd.to_numeric(df[feature], errors='coerce').dropna().astype(float).tolist()
        profile[feature] = _distribution_stats(values)
    return _safe_json({
        'selected_features': features,
        'feature_profile': profile,
        'feature_boxplots': boxplots,
        'pca_scatter': _pca_payload(df, features if len(features) >= 2 else numeric_feature_columns(df)[:20]),
        'top_differential_features': diff_features.head(30).to_dict(orient='records') if not diff_features.empty else [],
        'top_differential_entities': diff_entities.head(50).to_dict(orient='records') if not diff_entities.empty else [],
        'platform_visualization': platform,
        'comparison_capabilities': {
            'features': numeric_feature_columns(df)[:200],
            'entities': df[['entity_id', 'gene_id']].head(300).to_dict(orient='records') if {'entity_id', 'gene_id'}.issubset(df.columns) else [],
        },
    })


def _feature_family(feature: str, omics: str) -> str:
    name = str(feature).lower()
    if any(token in name for token in ['atom', 'atoms', 'ratio_c', 'ratio_n', 'c_n', 'c_p', 'n_p', 'n_s', 'per_nt', 'per_aa', 'budget']):
        return 'Element'
    if any(token in name for token in ['gc', 'at_', 'a_fraction', 'c_fraction', 'g_fraction', 't_fraction', 'u_fraction', 'base']):
        return 'Base'
    if name.startswith('codon_') or 'codon' in name or name in {'gc1_percent', 'gc2_percent', 'gc3_percent'}:
        return 'Codon'
    if name.startswith('aa_') or 'amino' in name or 'aa_' in name:
        return 'AA composition'
    if 'dinuc' in name or 'entropy' in name or 'complexity' in name or 'skew' in name:
        return 'Dinucleotide/complexity'
    if any(token in name for token in ['promoter', 'exon', 'locus', 'intergenic', 'island']):
        return 'Promoter/Exon'
    if any(token in name for token in ['orf', 'cds', 'coding', 'rna_orf']):
        return 'ORF/CDS'
    if any(token in name for token in ['pi', 'gravy', 'instability', 'aliphatic', 'molecular', 'weight', 'hydro', 'flex', 'aromatic']):
        return 'Protein property'
    if any(token in name for token in ['strategy', 'stoich', 'resource', 'adaptation', 'coupling']):
        return 'Stoich index'
    return f'{omics.title()} other'


def _feature_unit(feature: str, family: str) -> str:
    name = str(feature).lower()
    if 'percent' in name or name.endswith('_pct'):
        return 'percent'
    if 'fraction' in name or 'freq' in name or 'content' in name or 'rate' in name:
        return 'proportion'
    if 'length' in name or name.endswith('_len') or '_len_' in name:
        return 'count'
    if 'score' in name or 'index' in name or 'entropy' in name or 'ratio' in name:
        return 'unitless'
    if family == 'Element':
        return 'atom count or normalized atom cost'
    return 'raw computed unit'


def _feature_description(feature: str, family: str, omics: str) -> str:
    return (
        f'{feature} is a {family.lower()} feature computed from uploaded {omics} sequence data. '
        'Interpret it as descriptive/exploratory sequence-derived evidence unless external validation is added.'
    )


def _build_feature_catalog(df: pd.DataFrame, omics: str) -> dict[str, Any]:
    preferred = [feature for feature in PREFERRED_FEATURES.get(omics, []) if feature in df.columns]
    all_numeric = numeric_feature_columns(df)
    ordered = list(dict.fromkeys([*preferred, *all_numeric]))
    features = []
    families: dict[str, dict[str, Any]] = {}
    for feature in ordered:
        family = _feature_family(feature, omics)
        unit = _feature_unit(feature, family)
        valid_n = int(pd.to_numeric(df[feature], errors='coerce').notna().sum())
        missing_rate = float(1 - valid_n / max(1, len(df)))
        item = {
            'feature_name': feature,
            'field': feature,
            'label': feature.replace('_', ' '),
            'feature_family': family,
            'unit': unit,
            'omics_type': omics,
            'is_core_feature': feature in preferred,
            'is_modelable': valid_n >= 2 and missing_rate <= 0.8,
            'allow_top_low': valid_n > 0,
            'recommended_chart': 'boxplot' if df['group'].nunique() > 1 else 'histogram',
            'allowed_chart_types': ['histogram', 'boxplot', 'scatter', 'heatmap', 'ranked_bar'],
            'missing_rate': missing_rate,
            'evidence_level': 'computed_from_uploaded_sequence',
            'description': _feature_description(feature, family, omics),
        }
        features.append(item)
        bucket = families.setdefault(family, {'feature_family': family, 'feature_count': 0, 'features': []})
        bucket['feature_count'] += 1
        bucket['features'].append(feature)
    return {
        'omics_type': omics,
        'row_count': int(len(df)),
        'feature_count': int(len(features)),
        'families': list(families.values()),
        'features': features,
        'method_metadata': {
            'method': 'automatic_feature_catalog_from_sequence_feature_table',
            'evidence_level': 'descriptive',
            'notes': 'Feature families are assigned from stable field-name rules and current omics type.',
        },
    }


def _build_feature_summary(df: pd.DataFrame, catalog: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    meta = {item['feature_name']: item for item in catalog.get('features', [])}
    rows = []
    for feature in [item['feature_name'] for item in catalog.get('features', [])]:
        values = pd.to_numeric(df[feature], errors='coerce')
        valid = values.dropna()
        stats_payload = _distribution_stats(valid.astype(float).tolist())
        rows.append({
            'feature_name': feature,
            'feature_family': meta.get(feature, {}).get('feature_family', 'Other'),
            'unit': meta.get(feature, {}).get('unit', ''),
            'n': int(len(df)),
            'valid_n': int(valid.shape[0]),
            'missing_n': int(len(df) - valid.shape[0]),
            'missing_rate': float(1 - valid.shape[0] / max(1, len(df))),
            'zero_rate': float((valid == 0).sum() / max(1, valid.shape[0])) if valid.shape[0] else 0.0,
            'mean': stats_payload['mean'],
            'median': stats_payload['p50'],
            'std': None if valid.shape[0] < 2 else float(valid.std()),
            'iqr': float(stats_payload['p75'] - stats_payload['p25']),
            'min': stats_payload['min'],
            'max': stats_payload['max'],
            'is_core_feature': bool(meta.get(feature, {}).get('is_core_feature', False)),
            'is_modelable': bool(meta.get(feature, {}).get('is_modelable', False)),
        })
    table = pd.DataFrame(rows)
    payload = {
        'rows': table.to_dict(orient='records'),
        'columns': list(table.columns),
        'method_metadata': {
            'method': 'per_numeric_feature_descriptive_statistics',
            'missing_policy': 'non-numeric values are treated as missing',
            'evidence_level': 'descriptive',
        },
    }
    return table, _safe_json(payload)


def _group_summary(df: pd.DataFrame, features: list[str]) -> list[dict[str, Any]]:
    rows = []
    for group, part in df.groupby('group', dropna=False):
        row = {
            'group': str(group),
            'record_count': int(len(part)),
            'sample_count': int(part['sample_id'].nunique()) if 'sample_id' in part else 0,
            'species_count': int(part['species_id'].nunique()) if 'species_id' in part else 0,
            'strategy_clusters': [
                {'strategy_cluster': str(k), 'count': int(v)}
                for k, v in part.get('strategy_cluster', pd.Series(dtype=object)).value_counts().items()
            ],
            'feature_medians': {},
        }
        for feature in features[:24]:
            values = pd.to_numeric(part[feature], errors='coerce').dropna()
            row['feature_medians'][feature] = None if values.empty else float(values.median())
        rows.append(row)
    return rows


def _build_basic_visualization_payload(df: pd.DataFrame, catalog: dict[str, Any], feature_summary: pd.DataFrame, omics: str) -> dict[str, Any]:
    core_features = [item['feature_name'] for item in catalog.get('features', []) if item.get('is_core_feature')]
    if not core_features:
        core_features = [item['feature_name'] for item in catalog.get('features', [])][:12]
    family_panels = []
    for family in catalog.get('families', []):
        fields = [feature for feature in family.get('features', []) if feature in df.columns][:10]
        distributions = []
        boxplots = []
        for feature in fields:
            values = pd.to_numeric(df[feature], errors='coerce').dropna().astype(float).tolist()
            distributions.append({'feature_name': feature, 'distribution': _histogram(values), 'summary': _distribution_stats(values)})
            for group, part in df.groupby('group', dropna=False):
                group_values = pd.to_numeric(part[feature], errors='coerce').dropna()
                if group_values.empty:
                    continue
                boxplots.append({
                    'feature_name': feature,
                    'group': str(group),
                    'n': int(len(group_values)),
                    'missing_rate': float(1 - len(group_values) / max(1, len(part))),
                    'min': float(group_values.min()),
                    'q1': float(group_values.quantile(0.25)),
                    'median': float(group_values.median()),
                    'q3': float(group_values.quantile(0.75)),
                    'max': float(group_values.max()),
                })
        family_panels.append({
            'feature_family': family.get('feature_family'),
            'feature_count': family.get('feature_count'),
            'recommended_chart': 'boxplot' if df['group'].nunique() > 1 else 'histogram',
            'distributions': distributions,
            'boxplots': boxplots,
        })
    corr_features = [feature for feature in core_features if feature in df.columns][:16]
    corr = df[corr_features].apply(pd.to_numeric, errors='coerce').corr(method='spearman').fillna(0).to_dict() if corr_features else {}
    return _safe_json({
        'kpis': [
            {'label': 'Rows', 'value': int(len(df))},
            {'label': 'Samples', 'value': int(df['sample_id'].nunique())},
            {'label': 'Groups', 'value': int(df['group'].nunique())},
            {'label': 'Species', 'value': int(df['species_id'].nunique())},
            {'label': 'Numeric features', 'value': int(len(catalog.get('features', [])))},
            {'label': 'Mean missing rate', 'value': float(feature_summary['missing_rate'].mean()) if not feature_summary.empty else 0.0},
        ],
        'feature_family_coverage': [
            {'feature_family': family.get('feature_family'), 'feature_count': family.get('feature_count')}
            for family in catalog.get('families', [])
        ],
        'group_summary': _group_summary(df, core_features),
        'family_panels': family_panels,
        'correlation_matrix': {'method': 'spearman', 'features': corr_features, 'values': corr},
        'scatter_defaults': corr_features[:2],
        'method_metadata': {
            'method': 'descriptive_feature_family_visualization_payload',
            'evidence_level': 'descriptive',
            'chart_policy': 'Charts are derived from uploaded sequence features and do not imply functional causality.',
        },
    })


TOP_LOW_COLUMNS = [
    'feature_name', 'rank_type', 'rank', 'entity_id', 'gene_id', 'gene_name',
    'feature_value', 'sample_id', 'group', 'species_id', 'strategy_cluster',
]


def _top_low_rows_for_feature(df: pd.DataFrame, feature: str, n: int = 10) -> list[dict[str, Any]]:
    if feature not in df.columns:
        return []
    work = df.copy()
    work['_feature_value'] = pd.to_numeric(work[feature], errors='coerce')
    work = work.dropna(subset=['_feature_value'])
    if work.empty:
        return []

    def build_rows(part: pd.DataFrame, rank_type: str) -> list[dict[str, Any]]:
        rows = []
        for rank, (_, row) in enumerate(part.iterrows(), start=1):
            rows.append({
                'feature_name': feature,
                'rank_type': rank_type,
                'rank': rank,
                'entity_id': row.get('entity_id'),
                'gene_id': row.get('gene_id') or row.get('entity_id'),
                'gene_name': row.get('gene_name') or row.get('gene_symbol') or '',
                'feature_value': float(row['_feature_value']),
                'sample_id': row.get('sample_id', ''),
                'group': row.get('group', ''),
                'species_id': row.get('species_id', ''),
                'strategy_cluster': row.get('strategy_cluster', ''),
            })
        return rows

    low = work.sort_values('_feature_value', ascending=True).head(n)
    high = work.sort_values('_feature_value', ascending=False).head(n)
    return build_rows(low, 'Low10') + build_rows(high, 'Top10')


def _build_top_low_entities(df: pd.DataFrame, catalog: dict[str, Any], n: int = 10) -> tuple[pd.DataFrame, dict[str, Any]]:
    features = [item['feature_name'] for item in catalog.get('features', []) if item.get('is_core_feature') and item.get('allow_top_low')]
    if not features:
        features = [item['feature_name'] for item in catalog.get('features', []) if item.get('allow_top_low')][:24]
    rows = []
    by_feature = {}
    for feature in features:
        feature_rows = _top_low_rows_for_feature(df, feature, n=n)
        by_feature[feature] = feature_rows
        rows.extend(feature_rows)
    table = pd.DataFrame(rows, columns=TOP_LOW_COLUMNS)
    payload = {
        'n_per_direction': n,
        'features': features,
        'by_feature': by_feature,
        'rows': table.to_dict(orient='records'),
        'columns': TOP_LOW_COLUMNS,
        'method_metadata': {
            'method': 'numeric_feature_rank_top_low',
            'rank_policy': 'Top10 is descending feature value; Low10 is ascending feature value.',
            'evidence_level': 'descriptive',
        },
    }
    return table, _safe_json(payload)


def top_low_entities_from_rows(df: pd.DataFrame, feature: str | None = None, n: int = 10) -> dict[str, Any]:
    if feature:
        rows = _top_low_rows_for_feature(df, feature, n=n)
        return _safe_json({'n_per_direction': n, 'features': [feature], 'by_feature': {feature: rows}, 'rows': rows, 'columns': TOP_LOW_COLUMNS})
    catalog = _build_feature_catalog(df, str(df.get('omics_type', pd.Series(['transcriptome'])).iloc[0]))
    _table, payload = _build_top_low_entities(df, catalog, n=n)
    return payload


def _paired_scatter_payload(df: pd.DataFrame, reference: str, case: str, features: list[str]) -> list[dict[str, Any]]:
    rows = []
    if 'gene_key' not in df.columns or not features:
        return rows
    ref = df[df['group'].astype(str) == reference]
    cur = df[df['group'].astype(str) == case]
    if ref.empty or cur.empty:
        return rows
    for feature in features[:8]:
        ref_med = ref.groupby('gene_key')[feature].median(numeric_only=True)
        case_med = cur.groupby('gene_key')[feature].median(numeric_only=True)
        common = ref_med.index.intersection(case_med.index)
        for gene_key in common[:1000]:
            rows.append({
                'feature_name': feature,
                'gene_key': gene_key,
                'reference_group': reference,
                'case_group': case,
                'reference_value': _safe_json(ref_med.loc[gene_key]),
                'case_value': _safe_json(case_med.loc[gene_key]),
                'delta': _safe_json(case_med.loc[gene_key] - ref_med.loc[gene_key]),
            })
    return rows


def _build_sample_comparison_payload(
    df: pd.DataFrame,
    diff_features: pd.DataFrame,
    diff_entities: pd.DataFrame,
    reference_group: str,
    omics: str,
) -> dict[str, Any]:
    groups = [str(item) for item in df['group'].dropna().astype(str).unique()]
    if len(groups) < 2:
        return {
            'available': False,
            'reason': 'Fewer than two groups are available; sample comparison requires multi-sample or multi-species input.',
            'method_metadata': {'evidence_level': 'descriptive'},
        }
    reference = reference_group if reference_group in groups else groups[0]
    cases = [group for group in groups if group != reference]
    selected = _selected_diff_features(diff_features, omics)
    selected = [feature for feature in selected if feature in df.columns][:24]
    if not selected:
        selected = numeric_feature_columns(df)[:24]
    feature_boxplots = []
    for feature in selected:
        for group, part in df.groupby('group', dropna=False):
            values = pd.to_numeric(part[feature], errors='coerce').dropna()
            if values.empty:
                continue
            feature_boxplots.append({
                'feature_name': feature,
                'group': str(group),
                'n': int(len(values)),
                'missing_rate': float(1 - len(values) / max(1, len(part))),
                **_distribution_stats(values.astype(float).tolist()),
            })
    delta_heatmap = []
    ref_df = df[df['group'].astype(str) == reference]
    ref_center = ref_df[selected].apply(pd.to_numeric, errors='coerce').median(numeric_only=True)
    scale = df[selected].apply(pd.to_numeric, errors='coerce').std(skipna=True).replace(0, np.nan).fillna(1.0)
    for case in cases:
        case_df = df[df['group'].astype(str) == case]
        case_center = case_df[selected].apply(pd.to_numeric, errors='coerce').median(numeric_only=True)
        for feature in selected:
            delta = case_center.get(feature, np.nan) - ref_center.get(feature, np.nan)
            delta_heatmap.append({
                'feature_name': feature,
                'comparison': f'{reference} vs {case}',
                'reference_group': reference,
                'case_group': case,
                'standardized_delta': _safe_json(delta / scale.get(feature, 1.0)),
                'raw_delta': _safe_json(delta),
            })
    paired = []
    for case in cases:
        paired.extend(_paired_scatter_payload(df, reference, case, selected[:8]))
    return _safe_json({
        'available': True,
        'reference_group': reference,
        'case_groups': cases,
        'group_overview': _group_summary(df, selected),
        'differential_features': diff_features.head(100).to_dict(orient='records') if not diff_features.empty else [],
        'differential_entities': diff_entities.head(100).to_dict(orient='records') if not diff_entities.empty else [],
        'feature_boxplots': feature_boxplots,
        'feature_delta_heatmap': delta_heatmap,
        'feature_volcano': diff_features.to_dict(orient='records') if not diff_features.empty else [],
        'paired_scatter': paired,
        'matched_n': len({row['gene_key'] for row in paired}) if paired else 0,
        'comparison_mode': 'paired_and_unpaired' if paired else 'unpaired_distribution_only',
        'method_metadata': {
            'method': 'reference_vs_case_feature_comparison',
            'reference_group': reference,
            'multiple_testing': 'benjamini_hochberg_fdr',
            'warning': 'If group replicate counts are small, prioritize effect sizes and descriptive differences over p-values.',
            'evidence_level': 'descriptive/exploratory',
        },
    })


def _prepare_ml_matrix(df: pd.DataFrame, label_field: str) -> tuple[pd.DataFrame, pd.Series, list[str], dict[str, Any]]:
    if label_field not in df.columns:
        raise KeyError(label_field)
    features = []
    dropped = []
    for feature in numeric_feature_columns(df):
        values = pd.to_numeric(df[feature], errors='coerce')
        missing_rate = float(values.isna().sum() / max(1, len(values)))
        if missing_rate > 0.8 or values.nunique(dropna=True) < 2:
            dropped.append({'feature_name': feature, 'reason': 'high_missing_or_near_zero_variance', 'missing_rate': missing_rate})
            continue
        features.append(feature)
    if not features:
        raise ValueError('No modelable numeric features are available.')
    y = df[label_field].astype(str)
    valid_mask = y.notna() & (y.str.strip() != '')
    X = df.loc[valid_mask, features].apply(pd.to_numeric, errors='coerce')
    X = X.fillna(X.median(numeric_only=True)).fillna(0)
    variable = [feature for feature in features if X[feature].nunique(dropna=True) > 1]
    X = X[variable]
    y = y.loc[valid_mask]
    if X.shape[1] == 0:
        raise ValueError('No variable modelable numeric features remain after preprocessing.')
    if y.nunique() < 2:
        raise ValueError('ML discrimination requires at least two label classes.')
    meta = {'dropped_features': dropped, 'row_count': int(len(X)), 'feature_count': int(X.shape[1]), 'label_field': label_field}
    return X, y, list(X.columns), meta


def _roc_pr_payload(y: np.ndarray, classes: list[str], proba: np.ndarray) -> dict[str, Any]:
    if len(classes) != 2:
        return {
            'available': False,
            'reason': 'ROC/PR payload is emitted only for binary classification.',
        }
    try:
        fpr, tpr, roc_thresholds = roc_curve(y, proba[:, 1])
        precision, recall, pr_thresholds = precision_recall_curve(y, proba[:, 1])
    except ValueError as exc:
        return {'available': False, 'reason': str(exc)}
    return _safe_json({
        'available': True,
        'positive_class': classes[1],
        'roc_curve': [
            {'fpr': float(x), 'tpr': float(yv), 'threshold': None if idx >= len(roc_thresholds) else float(roc_thresholds[idx])}
            for idx, (x, yv) in enumerate(zip(fpr, tpr))
        ],
        'pr_curve': [
            {'precision': float(p), 'recall': float(r), 'threshold': None if idx >= len(pr_thresholds) else float(pr_thresholds[idx])}
            for idx, (p, r) in enumerate(zip(precision, recall))
        ],
    })


def _feature_redundancy_groups(X: pd.DataFrame, ranked_features: list[str]) -> dict[str, Any]:
    top = [feature for feature in ranked_features[:30] if feature in X.columns]
    if len(top) < 2:
        return {'available': False, 'reason': 'Fewer than two top features are available.', 'groups': [], 'correlation_matrix': {}}
    corr = X[top].corr(method='spearman').fillna(0)
    used: set[str] = set()
    groups = []
    for feature in top:
        if feature in used:
            continue
        members = [feature]
        used.add(feature)
        for other in top:
            if other in used:
                continue
            if abs(float(corr.loc[feature, other])) >= 0.85:
                members.append(other)
                used.add(other)
        groups.append({
            'representative_feature': feature,
            'members': members,
            'member_count': len(members),
            'max_abs_spearman_to_representative': max([abs(float(corr.loc[feature, item])) for item in members] or [1.0]),
        })
    return _safe_json({
        'available': True,
        'threshold_abs_spearman': 0.85,
        'groups': groups,
        'correlation_matrix': corr.to_dict(),
    })


def _top_feature_distributions(df: pd.DataFrame, label_field: str, feature_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for item in feature_rows[:12]:
        feature = item.get('feature_name')
        if feature not in df.columns:
            continue
        groups = []
        for label, part in df.groupby(label_field, dropna=False):
            values = pd.to_numeric(part[feature], errors='coerce').dropna().astype(float).tolist()
            groups.append({
                'feature_name': feature,
                'label': str(label),
                'n': len(values),
                'missing_rate': float(1 - len(values) / max(1, len(part))),
                **_distribution_stats(values),
            })
        output.append({'feature_name': feature, 'groups': groups})
    return _safe_json(output)


def _entity_contribution_rows(
    df: pd.DataFrame,
    X: pd.DataFrame,
    y_raw: pd.Series,
    classes: list[str],
    feature_rows: list[dict[str, Any]],
    rf_pred: np.ndarray,
    rf_proba: np.ndarray,
) -> list[dict[str, Any]]:
    top_features = [row['feature_name'] for row in feature_rows[:12] if row.get('feature_name') in X.columns]
    if not top_features:
        return []
    centers = X[top_features].median(numeric_only=True)
    scale = X[top_features].std(skipna=True).replace(0, np.nan).fillna(1.0)
    rows = []
    for idx, source_idx in enumerate(X.index):
        source = df.loc[source_idx]
        z = ((X.loc[source_idx, top_features] - centers) / scale).replace([np.inf, -np.inf], np.nan).fillna(0)
        top_feature = str(z.abs().idxmax())
        rows.append({
            'entity_id': source.get('entity_id'),
            'gene_id': source.get('gene_id'),
            'gene_name': source.get('gene_name') or source.get('gene_symbol') or '',
            'sample_id': source.get('sample_id'),
            'species_id': source.get('species_id'),
            'true_label': y_raw.loc[source_idx],
            'predicted_label': classes[int(rf_pred[idx])],
            'confidence': float(np.max(rf_proba[idx])),
            'top_contribution_feature': top_feature,
            'top_contribution_z': float(z[top_feature]),
            'mean_abs_top_feature_z': float(z.abs().mean()),
        })
    rows.sort(key=lambda row: (row['confidence'], abs(row['top_contribution_z'])), reverse=True)
    return _safe_json(rows[:500])


def _label_view_status(df: pd.DataFrame) -> list[dict[str, Any]]:
    candidates = ['group', 'sample_id', 'species_id', 'condition']
    rows = []
    if {'species_id', 'condition'}.issubset(df.columns):
        combo = df['species_id'].astype(str) + ':' + df['condition'].astype(str)
        rows.append({
            'label_field': 'species_condition',
            'available': bool(combo.nunique(dropna=True) >= 2),
            'class_count': int(combo.nunique(dropna=True)),
            'row_count': int(combo.notna().sum()),
            'recommended_view': 'interaction_view',
            'notes': 'Synthetic label formed as species_id:condition for interaction-style exploration.',
        })
    for field in candidates:
        if field not in df.columns:
            rows.append({'label_field': field, 'available': False, 'reason': 'field_not_present'})
            continue
        counts = df[field].astype(str).replace('', np.nan).dropna().value_counts()
        rows.append({
            'label_field': field,
            'available': bool(len(counts) >= 2),
            'class_count': int(len(counts)),
            'row_count': int(counts.sum()),
            'min_class_n': int(counts.min()) if len(counts) else 0,
            'recommended_view': 'species_view' if field == 'species_id' else ('condition_view' if field == 'condition' else 'general_view'),
        })
    return rows


def ml_discrimination_from_rows(df: pd.DataFrame, label_field: str = 'group') -> dict[str, Any]:
    df = df.copy()
    if label_field == 'species_condition' and {'species_id', 'condition'}.issubset(df.columns):
        df['species_condition'] = df['species_id'].astype(str) + ':' + df['condition'].astype(str)
    try:
        X, y_raw, features, prep_meta = _prepare_ml_matrix(df, label_field)
    except (KeyError, ValueError) as exc:
        return {
            'available': False,
            'reason': str(exc),
            'label_field': label_field,
            'label_view_status': _label_view_status(df),
            'method_metadata': {'evidence_level': 'exploratory'},
        }
    labeler = LabelEncoder()
    y = labeler.fit_transform(y_raw)
    classes = [str(item) for item in labeler.classes_]
    class_counts = {classes[int(cls)]: int(count) for cls, count in pd.Series(y).value_counts().sort_index().items()}
    low_sample_warning = bool(len(y) < 12 or min(class_counts.values()) < 2)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    logistic = LogisticRegression(max_iter=1000, class_weight='balanced', random_state=17)
    logistic.fit(X_scaled, y)
    logistic_pred = logistic.predict(X_scaled)
    logistic_metrics = {
        'train_accuracy': float(accuracy_score(y, logistic_pred)),
        'balanced_accuracy': float(balanced_accuracy_score(y, logistic_pred)),
        'macro_f1': float(f1_score(y, logistic_pred, average='macro')),
    }
    if len(classes) == 2:
        try:
            proba = logistic.predict_proba(X_scaled)[:, 1]
            logistic_metrics['auroc_train'] = float(roc_auc_score(y, proba))
            logistic_metrics['auprc_train'] = float(average_precision_score(y, proba))
        except ValueError:
            pass

    rf = RandomForestClassifier(n_estimators=120, random_state=17, class_weight='balanced', max_features='sqrt')
    rf.fit(X, y)
    rf_pred = rf.predict(X)
    rf_proba = rf.predict_proba(X)
    rf_metrics = {
        'train_accuracy': float(accuracy_score(y, rf_pred)),
        'balanced_accuracy': float(balanced_accuracy_score(y, rf_pred)),
        'macro_f1': float(f1_score(y, rf_pred, average='macro')),
    }
    cv_meta: dict[str, Any] = {'validation_method': 'training_only_exploratory', 'low_sample_warning': low_sample_warning}
    class_series = pd.Series(y).value_counts()
    if len(y) >= 8 and class_series.min() >= 2:
        n_splits = int(min(5, class_series.min()))
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=17)
        cv_meta = {
            'validation_method': 'stratified_kfold',
            'n_splits': n_splits,
            'logistic_balanced_accuracy_cv_mean': float(cross_val_score(logistic, X_scaled, y, cv=cv, scoring='balanced_accuracy').mean()),
            'rf_balanced_accuracy_cv_mean': float(cross_val_score(rf, X, y, cv=cv, scoring='balanced_accuracy').mean()),
            'low_sample_warning': low_sample_warning,
        }

    try:
        perm = permutation_importance(rf, X, y, n_repeats=5, random_state=17, scoring='balanced_accuracy')
        perm_mean = dict(zip(features, perm.importances_mean))
        perm_std = dict(zip(features, perm.importances_std))
    except Exception:
        perm_mean = {feature: None for feature in features}
        perm_std = {feature: None for feature in features}

    coef_importance: dict[str, float] = {}
    if logistic.coef_.ndim == 2:
        for idx, feature in enumerate(features):
            coef_importance[feature] = float(np.mean(np.abs(logistic.coef_[:, idx])))
    rf_importance = dict(zip(features, rf.feature_importances_))
    feature_rows = []
    for feature in features:
        medians = {}
        for cls in classes:
            medians[cls] = _safe_json(pd.to_numeric(df.loc[df[label_field].astype(str) == cls, feature], errors='coerce').median())
        sorted_medians = sorted([(k, v) for k, v in medians.items() if v is not None], key=lambda item: item[1])
        direction = ''
        if len(sorted_medians) >= 2:
            direction = f'{sorted_medians[-1][0]} higher than {sorted_medians[0][0]}'
        feature_rows.append({
            'feature_name': feature,
            'rf_importance': float(rf_importance.get(feature, 0.0)),
            'logistic_abs_coef': float(coef_importance.get(feature, 0.0)),
            'permutation_importance_mean': None if perm_mean.get(feature) is None else float(perm_mean[feature]),
            'permutation_importance_std': None if perm_std.get(feature) is None else float(perm_std[feature]),
            'direction': direction,
            'class_medians': medians,
        })
    feature_rows.sort(key=lambda row: (row['permutation_importance_mean'] or 0, row['rf_importance'], row['logistic_abs_coef']), reverse=True)
    for rank, row in enumerate(feature_rows, start=1):
        row['rank'] = rank

    predictions = []
    for idx, source_idx in enumerate(X.index):
        source = df.loc[source_idx]
        probabilities = {classes[class_idx]: float(rf_proba[idx][class_idx]) for class_idx in range(len(classes))}
        predictions.append({
            'entity_id': source.get('entity_id'),
            'gene_id': source.get('gene_id'),
            'sample_id': source.get('sample_id'),
            'species_id': source.get('species_id'),
            'true_label': y_raw.loc[source_idx],
            'rf_predicted_label': classes[int(rf_pred[idx])],
            'rf_confidence': float(np.max(rf_proba[idx])),
            'rf_probabilities': probabilities,
        })
    cm = confusion_matrix(y, rf_pred).tolist()
    pca_rows = _pca_payload(df.loc[X.index].assign(_ml_label=y_raw.loc[X.index].values), features[:30])
    ranked_features = [row['feature_name'] for row in feature_rows]
    roc_pr = _roc_pr_payload(y, classes, rf_proba)
    embedding = _embedding_payload(df.loc[X.index].assign(**{label_field: y_raw.loc[X.index].values}), features[:30], label_field)
    redundancy = _feature_redundancy_groups(X, ranked_features)
    feature_distributions = _top_feature_distributions(df.loc[X.index], label_field, feature_rows)
    entity_contributions = _entity_contribution_rows(df, X, y_raw, classes, feature_rows, rf_pred, rf_proba)
    return _safe_json({
        'available': True,
        'label_field': label_field,
        'classes': classes,
        'class_counts': class_counts,
        'feature_count': len(features),
        'row_count': int(len(X)),
        'models': {
            'logistic_regression': {'metrics': logistic_metrics, 'parameters': {'class_weight': 'balanced', 'max_iter': 1000, 'standardized': True}},
            'random_forest': {'metrics': rf_metrics, 'parameters': {'n_estimators': 120, 'class_weight': 'balanced', 'max_features': 'sqrt'}},
        },
        'validation': cv_meta,
        'confusion_matrix': {'labels': classes, 'values': cm, 'model': 'random_forest'},
        'roc_pr': roc_pr,
        'feature_importance': feature_rows[:80],
        'predictions': predictions,
        'class_separation_pca': pca_rows,
        'class_separation_embedding': embedding,
        'top_feature_distributions': feature_distributions,
        'feature_redundancy': redundancy,
        'entity_contributions': entity_contributions,
        'label_view_status': _label_view_status(df),
        'advanced_explainability': {
            'shap': {
                'available': False,
                'reason': 'The optional shap package is not required by this project; permutation importance and z-score entity contribution are used as stable built-in explainability.',
                'fallback': 'permutation_importance_plus_entity_z_contribution',
            },
            'umap': {
                'available': embedding.get('method') == 'umap',
                'fallback': 'pca_fallback' if embedding.get('method') != 'umap' else None,
            },
        },
        'preprocessing': prep_meta,
        'method_metadata': {
            'method': 'standardized_logistic_regression_plus_random_forest',
            'missing_policy': 'median imputation then zero fallback',
            'feature_filter': 'numeric, <=80% missing, non-zero variance',
            'label_field': label_field,
            'supported_label_views': ['group', 'sample_id', 'species_id', 'condition', 'species_condition'],
            'evidence_level': 'exploratory',
            'warning': 'Training metrics can be optimistic for small uploaded datasets; use validation and class counts when interpreting.',
        },
    })


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(_safe_json(payload), ensure_ascii=False, indent=2), encoding='utf-8')


def _build_method_metadata(
    *,
    analysis_type: str,
    omics: str,
    feature_set: str,
    resolved_group_field: str,
    reference_group: str,
    feature_catalog: dict[str, Any],
    basic_visualization: dict[str, Any],
    sample_comparison: dict[str, Any],
    ml_discrimination: dict[str, Any],
) -> dict[str, Any]:
    return _safe_json({
        'result_type': 'uploaded_sequence_runtime_result',
        'analysis_type': analysis_type,
        'omics_type': omics,
        'feature_set': feature_set,
        'group_field': resolved_group_field,
        'reference_group': reference_group or None,
        'evidence_level': 'descriptive/exploratory',
        'feature_extraction': {
            'method': 'project_builtin_omics_stoichiometric_extractors',
            'extractor_root': str(extractor_root()),
            'extractor_files': EXTRACTOR_FILES,
            'full_database_feature_extractor_contract': feature_extractor_contract(),
            'raw_input_policy': 'raw uploads deleted after runtime computation',
        },
        'feature_catalog': feature_catalog.get('method_metadata', {}),
        'basic_visualization': basic_visualization.get('method_metadata', {}),
        'sample_comparison': sample_comparison.get('method_metadata', {}),
        'ml_discrimination': ml_discrimination.get('method_metadata', {}),
        'limitations': [
            'Uploaded sequence results are not imported into the curated public species registry.',
            'Descriptive statistics, PCA, correlations, outlier rankings, and ML models are exploratory unless externally validated.',
            'Small group sizes can make p-values, FDR, and training metrics unstable; effect sizes and class counts should be inspected.',
        ],
    })


def run_sequence_analysis(
    input_files: list[Path],
    annotation_files: list[Path] | None,
    sample_sheet_path: Path | None,
    output_dir: Path,
    analysis_type: str,
    omics_type: str = 'transcriptome',
    group_field: str = '',
    reference_group: str = '',
    feature_set: str = 'core',
    genetic_code: int = 1,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    omics = _normalize_omics(omics_type)
    feature_set = 'core' if str(feature_set or 'core').lower() not in {'core', 'full'} else str(feature_set).lower()
    analysis_type = analysis_type if analysis_type in {'single_sequence', 'multi_sample', 'multi_species'} else 'single_sequence'
    samples, resolved_group_field = _build_sample_inputs(
        input_files=input_files,
        annotation_files=annotation_files or [],
        sample_sheet_path=sample_sheet_path,
        analysis_type=analysis_type,
        group_field=group_field,
        omics=omics,
    )
    frames = [
        _extract_one_sample(sample, omics=omics, feature_set=feature_set, output_dir=output_dir, genetic_code=genetic_code)
        for sample in samples
    ]
    feature_df = _normalize_feature_table(pd.concat(frames, ignore_index=True), omics)
    diff_features, diff_meta, rf_model_features = _differential_features(feature_df, analysis_type, reference_group, omics)
    diff_entities = _differential_entities(feature_df, analysis_type, reference_group, diff_features, rf_model_features, omics)
    summary_payload, analysis_payload, platform_bundle = _build_summary_analysis(feature_df, omics, feature_set)
    feature_catalog = _build_feature_catalog(feature_df, omics)
    feature_summary_table, feature_summary_payload = _build_feature_summary(feature_df, feature_catalog)
    basic_visualization = _build_basic_visualization_payload(feature_df, feature_catalog, feature_summary_table, omics)
    core_feature_panels = build_core_feature_panels(feature_df, omics)
    top_low_table, top_low_payload = _build_top_low_entities(feature_df, feature_catalog, n=10)
    sample_comparison = _build_sample_comparison_payload(feature_df, diff_features, diff_entities, reference_group, omics)
    ml_discrimination = ml_discrimination_from_rows(feature_df, label_field='group')
    method_metadata = _build_method_metadata(
        analysis_type=analysis_type,
        omics=omics,
        feature_set=feature_set,
        resolved_group_field=resolved_group_field,
        reference_group=reference_group,
        feature_catalog=feature_catalog,
        basic_visualization=basic_visualization,
        sample_comparison=sample_comparison,
        ml_discrimination=ml_discrimination,
    )
    plots = _plots_payload(feature_df, diff_features, diff_entities, platform_bundle, omics)

    feature_path = output_dir / 'sequence_features.csv'
    rows_path = output_dir / 'rows_for_platform.csv'
    diff_feature_path = output_dir / 'differential_features.csv'
    diff_entity_path = output_dir / 'differential_entities.csv'
    feature_catalog_path = output_dir / 'feature_catalog.json'
    feature_summary_csv_path = output_dir / 'feature_summary.csv'
    feature_summary_json_path = output_dir / 'feature_summary.json'
    basic_visualization_path = output_dir / 'basic_visualization_payload.json'
    core_feature_panels_path = output_dir / 'core_feature_panels.json'
    top_low_csv_path = output_dir / 'top_low_entities.csv'
    top_low_json_path = output_dir / 'top_low_entities.json'
    sample_comparison_path = output_dir / 'sample_comparison_payload.json'
    sample_comparison_features_csv_path = output_dir / 'sample_comparison_features.csv'
    sample_comparison_features_json_path = output_dir / 'sample_comparison_features.json'
    sample_comparison_entities_csv_path = output_dir / 'sample_comparison_entities.csv'
    sample_comparison_entities_json_path = output_dir / 'sample_comparison_entities.json'
    ml_discrimination_path = output_dir / 'ml_discrimination_payload.json'
    ml_feature_importance_path = output_dir / 'ml_feature_importance.csv'
    ml_feature_importance_json_path = output_dir / 'ml_feature_importance.json'
    ml_predictions_path = output_dir / 'ml_predictions.csv'
    ml_predictions_json_path = output_dir / 'ml_predictions.json'
    method_metadata_path = output_dir / 'method_metadata.json'
    summary_path = output_dir / 'summary.json'
    analysis_path = output_dir / 'analysis_payload.json'
    platform_path = output_dir / 'platform_bundle.json'
    plots_path = output_dir / 'plots_payload.json'
    log_path = output_dir / 'run_log.json'

    feature_df.to_csv(feature_path, index=False)
    feature_df.to_csv(rows_path, index=False)
    diff_features.to_csv(diff_feature_path, index=False)
    diff_entities.to_csv(diff_entity_path, index=False)
    feature_summary_table.to_csv(feature_summary_csv_path, index=False)
    top_low_table.to_csv(top_low_csv_path, index=False)
    pd.DataFrame(sample_comparison.get('differential_features', [])).to_csv(sample_comparison_features_csv_path, index=False)
    pd.DataFrame(sample_comparison.get('differential_entities', [])).to_csv(sample_comparison_entities_csv_path, index=False)
    pd.DataFrame(ml_discrimination.get('feature_importance', [])).to_csv(ml_feature_importance_path, index=False)
    pd.DataFrame(ml_discrimination.get('predictions', [])).to_csv(ml_predictions_path, index=False)
    summary = {
        'analysis_type': analysis_type,
        'omics_type': omics,
        'feature_set': feature_set,
        'group_field': resolved_group_field,
        'reference_group': reference_group or None,
        'input_file_count': len(input_files),
        'annotation_file_count': len(annotation_files or []),
        'record_count': int(len(feature_df)),
        'sample_count': int(feature_df['sample_id'].nunique()),
        'group_count': int(feature_df['group'].nunique()),
        'species_count': int(feature_df['species_id'].nunique()),
        'feature_count': int(len(numeric_feature_columns(feature_df))),
        'differential_feature_count': int(len(diff_features)),
        'differential_entity_count': int(len(diff_entities)),
        'significant_feature_count': int((pd.to_numeric(diff_features.get('fdr'), errors='coerce').fillna(1.0) <= 0.05).sum()) if not diff_features.empty and 'fdr' in diff_features else 0,
        'extractor_root': str(extractor_root()),
        'differential_method': diff_meta,
        'platform_summary': summary_payload,
        'feature_catalog': {
            'feature_count': feature_catalog.get('feature_count', 0),
            'families': feature_catalog.get('families', []),
        },
        'artifact_contract': {
            'evidence_level': 'descriptive/exploratory',
            'new_optimization_artifacts': [
                'feature_catalog', 'feature_summary', 'basic_visualization',
                'top_low_entities', 'sample_comparison', 'ml_discrimination',
            ],
        },
        'created_at': _now_iso(),
        'outputs': {
            'features': 'sequence_features.csv',
            'platform_rows': 'rows_for_platform.csv',
            'differential_features': 'differential_features.csv',
            'differential_entities': 'differential_entities.csv',
            'feature_catalog': 'feature_catalog.json',
            'feature_summary_csv': 'feature_summary.csv',
            'feature_summary': 'feature_summary.json',
            'basic_visualization': 'basic_visualization_payload.json',
            'core_feature_panels': 'core_feature_panels.json',
            'top_low_entities_csv': 'top_low_entities.csv',
            'top_low_entities': 'top_low_entities.json',
            'sample_comparison': 'sample_comparison_payload.json',
            'sample_comparison_features_csv': 'sample_comparison_features.csv',
            'sample_comparison_features': 'sample_comparison_features.json',
            'sample_comparison_entities_csv': 'sample_comparison_entities.csv',
            'sample_comparison_entities': 'sample_comparison_entities.json',
            'ml_discrimination': 'ml_discrimination_payload.json',
            'ml_feature_importance': 'ml_feature_importance.csv',
            'ml_feature_importance_json': 'ml_feature_importance.json',
            'ml_predictions': 'ml_predictions.csv',
            'ml_predictions_json': 'ml_predictions.json',
            'method_metadata': 'method_metadata.json',
            'summary': 'summary.json',
            'analysis': 'analysis_payload.json',
            'platform_bundle': 'platform_bundle.json',
            'plots': 'plots_payload.json',
            'run_log': 'run_log.json',
        },
    }
    _write_json(feature_catalog_path, feature_catalog)
    _write_json(feature_summary_json_path, feature_summary_payload)
    _write_json(basic_visualization_path, basic_visualization)
    _write_json(core_feature_panels_path, core_feature_panels)
    _write_json(top_low_json_path, top_low_payload)
    _write_json(sample_comparison_path, sample_comparison)
    _write_json(sample_comparison_features_json_path, {'rows': sample_comparison.get('differential_features', []), 'method_metadata': sample_comparison.get('method_metadata', {})})
    _write_json(sample_comparison_entities_json_path, {'rows': sample_comparison.get('differential_entities', []), 'method_metadata': sample_comparison.get('method_metadata', {})})
    _write_json(ml_discrimination_path, ml_discrimination)
    _write_json(ml_feature_importance_json_path, {'rows': ml_discrimination.get('feature_importance', []), 'method_metadata': ml_discrimination.get('method_metadata', {})})
    _write_json(ml_predictions_json_path, {'rows': ml_discrimination.get('predictions', []), 'method_metadata': ml_discrimination.get('method_metadata', {})})
    _write_json(method_metadata_path, method_metadata)
    _write_json(summary_path, summary)
    _write_json(analysis_path, analysis_payload)
    _write_json(platform_path, platform_bundle)
    _write_json(plots_path, plots)
    _write_json(log_path, {
        'started_at': summary['created_at'],
        'finished_at': _now_iso(),
        'raw_inputs_deleted_after_run': True,
        'extractors': EXTRACTOR_FILES,
        'full_database_feature_extractor_contract': feature_extractor_contract(),
        'artifacts': summary['outputs'],
        'samples': [
            {
                'sample_id': sample.sample_id,
                'group': sample.group,
                'species_id': sample.species_id,
                'file_name': sample.fasta_path.name,
                'gff_file': sample.gff_path.name if sample.gff_path else None,
            }
            for sample in samples
        ],
    })
    return _safe_json(summary)


def field_summary_from_rows(df: pd.DataFrame, field: str) -> dict[str, Any]:
    if field not in df.columns:
        raise KeyError(field)
    values_raw = df[field].tolist()
    values = [_safe_num(value) for value in values_raw]
    numeric = [float(value) for value in values if value is not None]
    ranked = df.assign(_target=pd.to_numeric(df[field], errors='coerce')).dropna(subset=['_target']).sort_values('_target', ascending=False)
    return _safe_json({
        'field': field,
        'n_total': int(len(df)),
        'valid_n': int(len(numeric)),
        'missing_n': int(len(df) - len(numeric)),
        'summary': _distribution_stats(numeric),
        'distribution': _histogram(numeric),
        'top_rows': ranked.head(12).drop(columns=['_target']).to_dict(orient='records'),
        'bottom_rows': ranked.tail(12).drop(columns=['_target']).to_dict(orient='records'),
    })


def scatter_from_rows(df: pd.DataFrame, x_field: str, y_field: str, sample: int = 1200) -> dict[str, Any]:
    if x_field not in df.columns or y_field not in df.columns:
        raise KeyError(f'{x_field}/{y_field}')
    points = []
    for _, row in df.iterrows():
        x = _safe_num(row.get(x_field))
        y = _safe_num(row.get(y_field))
        if x is None or y is None:
            continue
        points.append({
            'entity_id': row.get('entity_id'),
            'gene_id': row.get('gene_id'),
            'gene_name': row.get('gene_name') or row.get('gene_symbol') or '',
            'sample_id': row.get('sample_id'),
            'group': row.get('group'),
            x_field: x,
            y_field: y,
        })
    if len(points) > sample:
        stride = max(1, len(points) // sample)
        points = points[::stride][:sample]
    return {'x_field': x_field, 'y_field': y_field, 'n_points': len(points), 'points': _safe_json(points)}


def feature_comparison_from_rows(df: pd.DataFrame, feature: str) -> dict[str, Any]:
    if feature not in df.columns:
        raise KeyError(feature)
    rows = []
    for group, part in df.groupby('group'):
        values = pd.to_numeric(part[feature], errors='coerce').dropna()
        if values.empty:
            continue
        rows.append({
            'group': str(group),
            'n': int(len(values)),
            **_distribution_stats(values.astype(float).tolist()),
            'points': [
                {
                    'entity_id': row.get('entity_id'),
                    'gene_id': row.get('gene_id'),
                    'sample_id': row.get('sample_id'),
                    'value': _safe_num(row.get(feature)),
                }
                for _, row in part.head(500).iterrows()
                if _safe_num(row.get(feature)) is not None
            ],
        })
    return {'feature': feature, 'groups': _safe_json(rows)}


def entity_comparison_from_rows(df: pd.DataFrame, entities: list[str], features: list[str]) -> dict[str, Any]:
    entity_set = {str(item).strip() for item in entities if str(item).strip()}
    features = [feature for feature in features if feature in df.columns]
    if not entity_set or not features:
        raise KeyError('entities/features')
    mask = df['entity_id'].astype(str).isin(entity_set)
    if 'gene_id' in df.columns:
        mask = mask | df['gene_id'].astype(str).isin(entity_set)
    if 'gene_key' in df.columns:
        mask = mask | df['gene_key'].astype(str).isin(entity_set)
    subset = df[mask].copy()
    rows = []
    entity_col = 'gene_key' if 'gene_key' in subset.columns else 'entity_id'
    for (entity_id, group), part in subset.groupby([entity_col, 'group']):
        rep = part.iloc[0]
        item = {
            'entity_id': str(entity_id),
            'gene_id': rep.get('gene_id') or str(entity_id),
            'gene_name': rep.get('gene_name') or rep.get('gene_symbol') or '',
            'group': str(group),
            'sample_count': int(part['sample_id'].nunique()),
        }
        for feature in features:
            values = pd.to_numeric(part[feature], errors='coerce').dropna()
            item[feature] = None if values.empty else float(values.median())
        rows.append(item)
    return {'entities': list(entity_set), 'features': features, 'rows': _safe_json(rows)}
