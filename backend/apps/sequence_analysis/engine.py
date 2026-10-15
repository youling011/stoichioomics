from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


NUCLEOTIDE_FORMULAS: dict[str, dict[str, int]] = {
    'A': {'C': 10, 'H': 12, 'N': 5, 'O': 5, 'P': 1},
    'C': {'C': 9, 'H': 12, 'N': 3, 'O': 6, 'P': 1},
    'G': {'C': 10, 'H': 12, 'N': 5, 'O': 6, 'P': 1},
    'T': {'C': 10, 'H': 13, 'N': 2, 'O': 7, 'P': 1},
    'U': {'C': 9, 'H': 11, 'N': 2, 'O': 8, 'P': 1},
}

AA_RESIDUE_FORMULAS: dict[str, dict[str, int]] = {
    'A': {'C': 3, 'H': 5, 'N': 1, 'O': 1},
    'R': {'C': 6, 'H': 12, 'N': 4, 'O': 1},
    'N': {'C': 4, 'H': 6, 'N': 2, 'O': 2},
    'D': {'C': 4, 'H': 5, 'N': 1, 'O': 3},
    'C': {'C': 3, 'H': 5, 'N': 1, 'O': 1, 'S': 1},
    'E': {'C': 5, 'H': 7, 'N': 1, 'O': 3},
    'Q': {'C': 5, 'H': 8, 'N': 2, 'O': 2},
    'G': {'C': 2, 'H': 3, 'N': 1, 'O': 1},
    'H': {'C': 6, 'H': 7, 'N': 3, 'O': 1},
    'I': {'C': 6, 'H': 11, 'N': 1, 'O': 1},
    'L': {'C': 6, 'H': 11, 'N': 1, 'O': 1},
    'K': {'C': 6, 'H': 12, 'N': 2, 'O': 1},
    'M': {'C': 5, 'H': 9, 'N': 1, 'O': 1, 'S': 1},
    'F': {'C': 9, 'H': 9, 'N': 1, 'O': 1},
    'P': {'C': 5, 'H': 7, 'N': 1, 'O': 1},
    'S': {'C': 3, 'H': 5, 'N': 1, 'O': 2},
    'T': {'C': 4, 'H': 7, 'N': 1, 'O': 2},
    'W': {'C': 11, 'H': 10, 'N': 2, 'O': 1},
    'Y': {'C': 9, 'H': 9, 'N': 1, 'O': 2},
    'V': {'C': 5, 'H': 9, 'N': 1, 'O': 1},
}

AA_GRAVY: dict[str, float] = {
    'A': 1.8, 'R': -4.5, 'N': -3.5, 'D': -3.5, 'C': 2.5,
    'Q': -3.5, 'E': -3.5, 'G': -0.4, 'H': -3.2, 'I': 4.5,
    'L': 3.8, 'K': -3.9, 'M': 1.9, 'F': 2.8, 'P': -1.6,
    'S': -0.8, 'T': -0.7, 'W': -0.9, 'Y': -1.3, 'V': 4.2,
}

METADATA_COLUMNS = {
    'entity_id',
    'entity_name',
    'record_id',
    'sample_id',
    'group',
    'species_id',
    'file_name',
    'seq_type',
}

DEFAULT_NUCLEOTIDE_FEATURES = [
    'gc_content',
    'at_content',
    'a_fraction',
    'c_fraction',
    'g_fraction',
    't_fraction',
    'gc_skew',
    'at_skew',
    'nt_entropy',
    'c_per_nt',
    'n_per_nt',
    'p_per_nt',
    'C_N_ratio',
    'C_P_ratio',
    'N_P_ratio',
]

DEFAULT_PROTEIN_FEATURES = [
    'hydrophobic_fraction',
    'polar_fraction',
    'charged_fraction',
    'acidic_fraction',
    'basic_fraction',
    'sulfur_fraction',
    'aromatic_fraction',
    'protein_gravy',
    'protein_charge_proxy',
    'protein_instability_proxy',
    'c_per_aa',
    'n_per_aa',
    's_per_aa',
    'C_N_ratio',
    'C_S_ratio',
    'N_S_ratio',
]


@dataclass
class FastaRecord:
    record_id: str
    description: str
    sequence: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_col(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(value).strip().lower()).strip('_')


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_json(v) for v in value]
    if isinstance(value, tuple):
        return [_safe_json(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
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


def _safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator is None or denominator == 0:
        return None
    value = numerator / denominator
    return float(value) if math.isfinite(value) else None


def _shannon_entropy(counts: dict[str, int], total: int) -> float | None:
    if total <= 0:
        return None
    entropy = 0.0
    for count in counts.values():
        if count <= 0:
            continue
        p = count / total
        entropy -= p * math.log2(p)
    return entropy


def parse_fasta(path: Path) -> list[FastaRecord]:
    records: list[FastaRecord] = []
    current_header: str | None = None
    chunks: list[str] = []

    def flush() -> None:
        nonlocal current_header, chunks
        if current_header is None:
            return
        sequence = ''.join(chunks).upper()
        sequence = re.sub(r'[^A-Z*.-]', '', sequence)
        sequence = sequence.replace('-', '').replace('.', '')
        record_id = current_header.split()[0] if current_header.strip() else f'record_{len(records) + 1}'
        records.append(FastaRecord(record_id=record_id, description=current_header, sequence=sequence))
        chunks = []

    with path.open('r', encoding='utf-8', errors='replace') as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith('>'):
                flush()
                current_header = line[1:].strip() or f'record_{len(records) + 1}'
            else:
                if current_header is None:
                    raise ValueError(f'{path.name} is not a valid FASTA file: first non-empty line must start with ">".')
                chunks.append(line)
    flush()
    if not records:
        raise ValueError(f'{path.name} does not contain FASTA records.')
    return records


def guess_sequence_type(sequence: str, requested: str = 'auto') -> str:
    requested = (requested or 'auto').lower()
    if requested in {'nucleotide', 'dna', 'rna', 'genome', 'transcriptome'}:
        return 'nucleotide'
    if requested in {'protein', 'proteome', 'peptide'}:
        return 'proteome'
    seq = sequence.upper().replace('*', '')
    if not seq:
        return 'nucleotide'
    nucleotide_symbols = set('ACGTUNRYKMSWBDHV')
    nucleotide_like = sum(1 for char in seq if char in nucleotide_symbols)
    return 'nucleotide' if nucleotide_like / len(seq) >= 0.9 else 'proteome'


def _apply_formulas(sequence: str, formulas: dict[str, dict[str, int]], atoms: list[str]) -> dict[str, int]:
    totals = {atom: 0 for atom in atoms}
    for char in sequence:
        formula = formulas.get(char)
        if not formula:
            continue
        for atom, count in formula.items():
            totals[atom] = totals.get(atom, 0) + count
    return totals


def _ratio_features(row: dict[str, Any], denominator: str) -> dict[str, Any]:
    values = {}
    denom_value = row.get(denominator) or 0
    for atom in ['C', 'H', 'N', 'O', 'P', 'S']:
        total_key = f'{atom.lower()}_atoms'
        if total_key in row:
            values[f'{atom.lower()}_per_{denominator.replace("length_", "")}'] = _safe_divide(row[total_key], denom_value)
    if row.get('n_atoms'):
        values['C_N_ratio'] = _safe_divide(row.get('c_atoms', 0), row.get('n_atoms', 0))
    if row.get('p_atoms'):
        values['C_P_ratio'] = _safe_divide(row.get('c_atoms', 0), row.get('p_atoms', 0))
        values['N_P_ratio'] = _safe_divide(row.get('n_atoms', 0), row.get('p_atoms', 0))
    if row.get('s_atoms'):
        values['C_S_ratio'] = _safe_divide(row.get('c_atoms', 0), row.get('s_atoms', 0))
        values['N_S_ratio'] = _safe_divide(row.get('n_atoms', 0), row.get('s_atoms', 0))
    return values


def nucleotide_features(sequence: str) -> dict[str, Any]:
    seq = sequence.upper().replace('U', 'T')
    length = len(seq)
    counts = Counter(seq)
    a = counts.get('A', 0)
    c = counts.get('C', 0)
    g = counts.get('G', 0)
    t = counts.get('T', 0)
    n = length - a - c - g - t
    known = a + c + g + t
    atom_totals = _apply_formulas(seq, NUCLEOTIDE_FORMULAS, ['C', 'H', 'N', 'O', 'P'])
    row: dict[str, Any] = {
        'length_nt': length,
        'known_nt': known,
        'ambiguous_nt': n,
        'gc_content': _safe_divide(g + c, known),
        'at_content': _safe_divide(a + t, known),
        'a_fraction': _safe_divide(a, known),
        'c_fraction': _safe_divide(c, known),
        'g_fraction': _safe_divide(g, known),
        't_fraction': _safe_divide(t, known),
        'n_fraction': _safe_divide(n, length),
        'gc_skew': _safe_divide(g - c, g + c),
        'at_skew': _safe_divide(a - t, a + t),
        'nt_entropy': _shannon_entropy({'A': a, 'C': c, 'G': g, 'T': t}, known),
        'c_atoms': atom_totals['C'],
        'h_atoms': atom_totals['H'],
        'n_atoms': atom_totals['N'],
        'o_atoms': atom_totals['O'],
        'p_atoms': atom_totals['P'],
    }
    row.update(_ratio_features(row, 'length_nt'))
    return row


def protein_features(sequence: str) -> dict[str, Any]:
    seq = sequence.upper().replace('*', '')
    valid = ''.join(char for char in seq if char in AA_RESIDUE_FORMULAS)
    length = len(valid)
    counts = Counter(valid)
    atom_totals = _apply_formulas(valid, AA_RESIDUE_FORMULAS, ['C', 'H', 'N', 'O', 'S'])
    hydrophobic = sum(counts.get(aa, 0) for aa in 'AVILMFWY')
    polar = sum(counts.get(aa, 0) for aa in 'STNQC')
    charged = sum(counts.get(aa, 0) for aa in 'DEKRH')
    acidic = sum(counts.get(aa, 0) for aa in 'DE')
    basic = sum(counts.get(aa, 0) for aa in 'KRH')
    sulfur = sum(counts.get(aa, 0) for aa in 'CM')
    aromatic = sum(counts.get(aa, 0) for aa in 'FWY')
    gravy = _safe_divide(sum(AA_GRAVY.get(aa, 0.0) * count for aa, count in counts.items()), length)
    charge_proxy = _safe_divide(basic - acidic, length)
    instability_proxy = _safe_divide(40.0 + 80.0 * counts.get('P', 0) + 35.0 * counts.get('G', 0) - 25.0 * sum(counts.get(aa, 0) for aa in 'IVL'), max(length, 1))
    row: dict[str, Any] = {
        'length_aa': length,
        'invalid_aa': len(seq) - length,
        'hydrophobic_fraction': _safe_divide(hydrophobic, length),
        'polar_fraction': _safe_divide(polar, length),
        'charged_fraction': _safe_divide(charged, length),
        'acidic_fraction': _safe_divide(acidic, length),
        'basic_fraction': _safe_divide(basic, length),
        'sulfur_fraction': _safe_divide(sulfur, length),
        'aromatic_fraction': _safe_divide(aromatic, length),
        'protein_gravy': gravy,
        'protein_charge_proxy': charge_proxy,
        'protein_instability_proxy': instability_proxy,
        'c_atoms': atom_totals['C'],
        'h_atoms': atom_totals['H'],
        'n_atoms': atom_totals['N'],
        'o_atoms': atom_totals['O'],
        's_atoms': atom_totals['S'],
    }
    for aa in sorted(AA_RESIDUE_FORMULAS):
        row[f'aa_{aa.lower()}_fraction'] = _safe_divide(counts.get(aa, 0), length)
    row.update(_ratio_features(row, 'length_aa'))
    return row


def load_sample_sheet(sample_sheet_path: Path | None, file_names: list[str], analysis_type: str, group_field: str) -> pd.DataFrame:
    if sample_sheet_path:
        sheet = pd.read_csv(sample_sheet_path, sep=None, engine='python')
        sheet.columns = [_normalize_col(col) for col in sheet.columns]
        rename_map = {
            'filename': 'file_name',
            'file': 'file_name',
            'sample': 'sample_id',
            'sample_name': 'sample_id',
            'condition_name': 'condition',
            'species': 'species_id',
        }
        sheet = sheet.rename(columns={key: value for key, value in rename_map.items() if key in sheet.columns})
    else:
        default_group_field = 'species_id' if analysis_type == 'multi_species' else 'condition'
        rows = []
        for file_name in file_names:
            sample_id = Path(file_name).stem
            rows.append({
                'file_name': file_name,
                'sample_id': sample_id,
                'condition': sample_id if analysis_type != 'single_sequence' else 'single',
                'species_id': sample_id if analysis_type == 'multi_species' else 'uploaded',
                default_group_field: sample_id if analysis_type != 'single_sequence' else 'single',
            })
        sheet = pd.DataFrame(rows)

    if 'file_name' not in sheet.columns:
        raise ValueError('Sample sheet must contain file_name or file column.')
    if 'sample_id' not in sheet.columns:
        sheet['sample_id'] = sheet['file_name'].map(lambda value: Path(str(value)).stem)
    if 'condition' not in sheet.columns:
        sheet['condition'] = sheet['sample_id']
    if 'species_id' not in sheet.columns:
        sheet['species_id'] = 'uploaded'

    normalized_group = _normalize_col(group_field or '')
    fallback_group = 'species_id' if analysis_type == 'multi_species' else 'condition'
    if analysis_type == 'single_sequence':
        normalized_group = 'group'
        sheet['group'] = 'single'
    elif normalized_group and normalized_group in sheet.columns:
        sheet['group'] = sheet[normalized_group].astype(str)
    elif fallback_group in sheet.columns:
        normalized_group = fallback_group
        sheet['group'] = sheet[fallback_group].astype(str)
    else:
        normalized_group = 'sample_id'
        sheet['group'] = sheet['sample_id'].astype(str)

    sheet['file_name'] = sheet['file_name'].map(lambda value: Path(str(value)).name)
    sheet['sample_id'] = sheet['sample_id'].astype(str)
    sheet['species_id'] = sheet['species_id'].astype(str)
    sheet['group'] = sheet['group'].astype(str)
    sheet.attrs['resolved_group_field'] = normalized_group
    return sheet


def build_feature_table(
    input_files: list[Path],
    sample_sheet_path: Path | None,
    analysis_type: str,
    omics_type: str,
    group_field: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    file_names = [path.name for path in input_files]
    sheet = load_sample_sheet(sample_sheet_path, file_names, analysis_type, group_field)
    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    sheet_by_file = {str(row['file_name']): row for _, row in sheet.iterrows()}

    for input_file in input_files:
        metadata = sheet_by_file.get(input_file.name)
        if metadata is None:
            sample_id = input_file.stem
            metadata = pd.Series({
                'sample_id': sample_id,
                'condition': sample_id,
                'species_id': sample_id if analysis_type == 'multi_species' else 'uploaded',
                'group': sample_id if analysis_type != 'single_sequence' else 'single',
            })
            warnings.append(f'{input_file.name} was not in the sample sheet; metadata inferred from file name.')
        fasta_records = parse_fasta(input_file)
        for record in fasta_records:
            seq_type = guess_sequence_type(record.sequence, omics_type)
            feature_values = nucleotide_features(record.sequence) if seq_type == 'nucleotide' else protein_features(record.sequence)
            entity_id = record.record_id
            row: dict[str, Any] = {
                'entity_id': entity_id,
                'entity_name': record.description,
                'record_id': record.record_id,
                'sample_id': str(metadata.get('sample_id', input_file.stem)),
                'group': str(metadata.get('group', 'single')),
                'species_id': str(metadata.get('species_id', 'uploaded')),
                'file_name': input_file.name,
                'seq_type': seq_type,
            }
            row.update(feature_values)
            records.append(row)

    if not records:
        raise ValueError('No sequence records were parsed from uploaded FASTA files.')

    df = pd.DataFrame(records)
    summary = {
        'analysis_type': analysis_type,
        'omics_type': omics_type,
        'group_field': sheet.attrs.get('resolved_group_field', group_field),
        'input_file_count': len(input_files),
        'record_count': int(len(df)),
        'sample_count': int(df['sample_id'].nunique()),
        'group_count': int(df['group'].nunique()),
        'species_count': int(df['species_id'].nunique()),
        'sequence_type_counts': {str(k): int(v) for k, v in df['seq_type'].value_counts().to_dict().items()},
        'warnings': warnings,
        'created_at': _now_iso(),
    }
    return df, summary


def numeric_feature_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for col in df.columns:
        if col in METADATA_COLUMNS:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            if df[col].notna().sum() >= 1:
                cols.append(col)
    return cols


def benjamini_hochberg(p_values: list[float | None]) -> list[float | None]:
    indexed = [(idx, p) for idx, p in enumerate(p_values) if p is not None and math.isfinite(float(p))]
    if not indexed:
        return [None for _ in p_values]
    indexed.sort(key=lambda item: item[1])
    n = len(indexed)
    adjusted = [None for _ in p_values]
    prev = 1.0
    for rank, (idx, p) in reversed(list(enumerate(indexed, start=1))):
        value = min(prev, float(p) * n / rank)
        adjusted[idx] = value
        prev = value
    return adjusted


def cliffs_delta(x: pd.Series, y: pd.Series) -> float | None:
    x_values = x.dropna().astype(float).to_numpy()
    y_values = y.dropna().astype(float).to_numpy()
    if len(x_values) == 0 or len(y_values) == 0:
        return None
    if len(x_values) * len(y_values) > 200000:
        rng = np.random.default_rng(17)
        x_values = rng.choice(x_values, size=min(len(x_values), 450), replace=False)
        y_values = rng.choice(y_values, size=min(len(y_values), 450), replace=False)
    greater = 0
    lower = 0
    for value in x_values:
        greater += int(np.sum(value > y_values))
        lower += int(np.sum(value < y_values))
    return (greater - lower) / (len(x_values) * len(y_values))


def differential_features(df: pd.DataFrame, analysis_type: str) -> pd.DataFrame:
    output_cols = [
        'feature_name', 'method', 'statistic', 'p_value', 'fdr', 'effect_size',
        'top_group', 'low_group', 'group_summary'
    ]
    if analysis_type == 'single_sequence' or df['group'].nunique() < 2:
        return pd.DataFrame(columns=output_cols)

    rows: list[dict[str, Any]] = []
    groups = [group for group, part in df.groupby('group') if len(part) > 0]
    for feature in numeric_feature_columns(df):
        series_by_group = [df.loc[df['group'] == group, feature].dropna().astype(float) for group in groups]
        if sum(len(series) > 0 for series in series_by_group) < 2:
            continue
        group_summary: dict[str, dict[str, Any]] = {}
        medians: dict[str, float] = {}
        for group, series in zip(groups, series_by_group):
            if len(series) == 0:
                continue
            medians[str(group)] = float(series.median())
            group_summary[str(group)] = {
                'n': int(len(series)),
                'mean': float(series.mean()),
                'median': float(series.median()),
                'q1': float(series.quantile(0.25)),
                'q3': float(series.quantile(0.75)),
            }
        if len(medians) < 2:
            continue
        top_group = max(medians, key=medians.get)
        low_group = min(medians, key=medians.get)
        effect_size = medians[top_group] - medians[low_group]
        method = 'kruskal_wallis'
        statistic = None
        p_value = None
        if len(groups) == 2:
            x, y = series_by_group[0], series_by_group[1]
            if len(x) > 0 and len(y) > 0:
                try:
                    statistic, p_value = stats.mannwhitneyu(x, y, alternative='two-sided')
                    method = 'mann_whitney_u'
                    delta = cliffs_delta(x, y)
                    if delta is not None:
                        effect_size = delta
                except ValueError:
                    statistic, p_value = None, None
        else:
            usable = [series for series in series_by_group if len(series) > 0]
            try:
                statistic, p_value = stats.kruskal(*usable)
            except ValueError:
                statistic, p_value = None, None
        rows.append({
            'feature_name': feature,
            'method': method,
            'statistic': None if statistic is None else float(statistic),
            'p_value': None if p_value is None else float(p_value),
            'effect_size': None if effect_size is None else float(effect_size),
            'top_group': top_group,
            'low_group': low_group,
            'group_summary': json.dumps(_safe_json(group_summary), ensure_ascii=False),
        })

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=output_cols)
    result['fdr'] = benjamini_hochberg(result['p_value'].tolist())
    result = result.sort_values(['fdr', 'p_value', 'feature_name'], na_position='last').reset_index(drop=True)
    return result[output_cols]


def differential_entities(df: pd.DataFrame, analysis_type: str) -> pd.DataFrame:
    return differential_entities_with_reference(df, analysis_type, '')


def differential_entities_with_reference(df: pd.DataFrame, analysis_type: str, reference_group: str = '') -> pd.DataFrame:
    numeric_cols = numeric_feature_columns(df)
    if not numeric_cols:
        return pd.DataFrame(columns=[
            'entity_id', 'entity_name', 'sample_id', 'group', 'species_id',
            'analysis_basis', 'score', 'top_feature', 'top_feature_value', 'top_feature_delta'
        ])

    z_frame = pd.DataFrame(index=df.index)
    for col in numeric_cols:
        values = df[col].astype(float)
        median = values.median(skipna=True)
        mad = (values - median).abs().median(skipna=True)
        scale = mad * 1.4826 if mad and math.isfinite(float(mad)) else values.std(skipna=True)
        if not scale or not math.isfinite(float(scale)):
            continue
        z_frame[col] = (values - median) / scale

    rows: list[dict[str, Any]] = []
    if not z_frame.empty:
        abs_z = z_frame.abs()
        for idx in abs_z.index:
            top_feature = abs_z.loc[idx].idxmax()
            score = abs_z.loc[idx, top_feature]
            if pd.isna(score):
                continue
            source = df.loc[idx]
            rows.append({
                'entity_id': source.get('entity_id'),
                'entity_name': source.get('entity_name'),
                'sample_id': source.get('sample_id'),
                'group': source.get('group'),
                'species_id': source.get('species_id'),
                'analysis_basis': 'within_dataset_outlier',
                'score': float(score),
                'top_feature': top_feature,
                'top_feature_value': _safe_json(source.get(top_feature)),
                'top_feature_delta': _safe_json(z_frame.loc[idx, top_feature]),
            })

    if analysis_type != 'single_sequence' and df['group'].nunique() >= 2:
        groups = list(df['group'].dropna().astype(str).unique())
        reference = str(reference_group).strip()
        if reference not in groups:
            reference = groups[0]
        comparison_groups = [group for group in groups if group != reference]
        grouped = df.groupby(['entity_id', 'group'])[numeric_cols].median(numeric_only=True)
        global_scale = df[numeric_cols].astype(float).std(skipna=True).replace(0, np.nan)
        for compare_group in comparison_groups:
            for entity_id in df['entity_id'].dropna().unique():
                try:
                    left = grouped.loc[(entity_id, reference)]
                    right = grouped.loc[(entity_id, compare_group)]
                except KeyError:
                    continue
                delta = (right - left) / global_scale
                delta = delta.replace([np.inf, -np.inf], np.nan).dropna()
                if delta.empty:
                    continue
                top_feature = delta.abs().idxmax()
                representative = df[df['entity_id'] == entity_id].iloc[0]
                rows.append({
                    'entity_id': representative.get('entity_id'),
                    'entity_name': representative.get('entity_name'),
                    'sample_id': 'matched_across_groups',
                    'group': f'{reference} vs {compare_group}',
                    'species_id': representative.get('species_id'),
                    'analysis_basis': 'between_group_delta',
                    'score': float(abs(delta[top_feature])),
                    'top_feature': top_feature,
                    'top_feature_value': _safe_json(grouped.loc[(entity_id, compare_group), top_feature]),
                    'top_feature_delta': float(delta[top_feature]),
                })

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result = result.sort_values('score', ascending=False).reset_index(drop=True)
    return result.head(1000)


def _feature_boxplots(df: pd.DataFrame, feature_names: list[str]) -> list[dict[str, Any]]:
    rows = []
    for feature in feature_names:
        if feature not in df.columns:
            continue
        for group, part in df.groupby('group'):
            values = part[feature].dropna().astype(float)
            if values.empty:
                continue
            rows.append({
                'feature_name': feature,
                'group': str(group),
                'n': int(len(values)),
                'min': float(values.min()),
                'q1': float(values.quantile(0.25)),
                'median': float(values.median()),
                'q3': float(values.quantile(0.75)),
                'max': float(values.max()),
            })
    return rows


def _pca_payload(df: pd.DataFrame, numeric_cols: list[str]) -> list[dict[str, Any]]:
    usable = df[numeric_cols].replace([np.inf, -np.inf], np.nan).dropna(axis=1, how='all')
    usable = usable.fillna(usable.median(numeric_only=True))
    usable = usable.loc[:, usable.nunique(dropna=True) > 1]
    if len(usable) < 2 or usable.shape[1] < 2:
        return []
    scaled = StandardScaler().fit_transform(usable)
    coords = PCA(n_components=2).fit_transform(scaled)
    rows = []
    for idx, source_idx in enumerate(usable.index):
        source = df.loc[source_idx]
        rows.append({
            'entity_id': source.get('entity_id'),
            'sample_id': source.get('sample_id'),
            'group': source.get('group'),
            'species_id': source.get('species_id'),
            'pc1': float(coords[idx, 0]),
            'pc2': float(coords[idx, 1]),
        })
    return rows


def build_plots_payload(df: pd.DataFrame, diff_features: pd.DataFrame, diff_entities: pd.DataFrame) -> dict[str, Any]:
    numeric_cols = numeric_feature_columns(df)
    seq_types = set(df['seq_type'].dropna().astype(str).tolist())
    default_features = DEFAULT_NUCLEOTIDE_FEATURES if seq_types == {'nucleotide'} else DEFAULT_PROTEIN_FEATURES
    ranked_features = diff_features['feature_name'].head(8).tolist() if not diff_features.empty else []
    selected_features = [name for name in ranked_features + default_features if name in numeric_cols]
    selected_features = list(dict.fromkeys(selected_features))[:10]
    sample_means = []
    for (sample_id, group), part in df.groupby(['sample_id', 'group']):
        means = part[selected_features].mean(numeric_only=True).to_dict() if selected_features else {}
        sample_means.append({
            'sample_id': str(sample_id),
            'group': str(group),
            'feature_means': _safe_json(means),
            'record_count': int(len(part)),
        })
    feature_profile = {}
    for feature in selected_features:
        values = df[feature].dropna().astype(float)
        if values.empty:
            continue
        feature_profile[feature] = {
            'mean': float(values.mean()),
            'median': float(values.median()),
            'min': float(values.min()),
            'max': float(values.max()),
        }
    return _safe_json({
        'selected_features': selected_features,
        'feature_profile': feature_profile,
        'feature_boxplots': _feature_boxplots(df, selected_features),
        'sample_feature_means': sample_means,
        'pca_scatter': _pca_payload(df, numeric_cols),
        'top_differential_features': diff_features.head(20).to_dict(orient='records') if not diff_features.empty else [],
        'top_differential_entities': diff_entities.head(30).to_dict(orient='records') if not diff_entities.empty else [],
    })


def run_sequence_analysis(
    input_files: list[Path],
    sample_sheet_path: Path | None,
    output_dir: Path,
    analysis_type: str,
    omics_type: str = 'auto',
    group_field: str = '',
    reference_group: str = '',
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis_type = analysis_type or 'single_sequence'
    if analysis_type not in {'single_sequence', 'multi_sample', 'multi_species'}:
        raise ValueError('analysis_type must be one of single_sequence, multi_sample, multi_species.')
    df, summary = build_feature_table(input_files, sample_sheet_path, analysis_type, omics_type, group_field)
    diff_feature_df = differential_features(df, analysis_type)
    diff_entity_df = differential_entities_with_reference(df, analysis_type, reference_group)
    plots_payload = build_plots_payload(df, diff_feature_df, diff_entity_df)

    feature_path = output_dir / 'sequence_features.csv'
    diff_feature_path = output_dir / 'differential_features.csv'
    diff_entity_path = output_dir / 'differential_entities.csv'
    plot_path = output_dir / 'plots_payload.json'
    summary_path = output_dir / 'summary.json'
    log_path = output_dir / 'run_log.json'

    df.to_csv(feature_path, index=False)
    diff_feature_df.to_csv(diff_feature_path, index=False)
    diff_entity_df.to_csv(diff_entity_path, index=False)
    plot_path.write_text(json.dumps(plots_payload, ensure_ascii=False, indent=2), encoding='utf-8')

    summary.update({
        'feature_count': int(len(numeric_feature_columns(df))),
        'reference_group': reference_group or None,
        'differential_feature_count': int(len(diff_feature_df)),
        'differential_entity_count': int(len(diff_entity_df)),
        'significant_feature_count': int((diff_feature_df['fdr'].fillna(1.0) <= 0.05).sum()) if not diff_feature_df.empty and 'fdr' in diff_feature_df else 0,
        'outputs': {
            'features': 'sequence_features.csv',
            'differential_features': 'differential_features.csv',
            'differential_entities': 'differential_entities.csv',
            'plots': 'plots_payload.json',
            'summary': 'summary.json',
            'run_log': 'run_log.json',
        },
    })
    summary_path.write_text(json.dumps(_safe_json(summary), ensure_ascii=False, indent=2), encoding='utf-8')
    log_path.write_text(json.dumps(_safe_json({
        'started_at': summary['created_at'],
        'finished_at': _now_iso(),
        'input_files': [path.name for path in input_files],
        'sample_sheet': sample_sheet_path.name if sample_sheet_path else None,
        'analysis_type': analysis_type,
        'omics_type': omics_type,
        'group_field': summary.get('group_field'),
    }), ensure_ascii=False, indent=2), encoding='utf-8')
    return _safe_json(summary)
