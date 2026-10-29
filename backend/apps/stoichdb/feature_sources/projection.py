"""Pure, versioned Core projection rules independent of ORM and filesystem paths.

These primitives do not resolve sources or activate any database binding.  A caller
must first establish the correct per-release recipe and verify its Full source.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
import math
from typing import Mapping, Sequence

GENOME_ZERO_FIELDS = (
    'cds_length_bp', 'cds_gc_percent', 'gc1_percent', 'gc2_percent', 'gc3_percent',
    'codon_total_valid', 'codon_entropy_bits', 'aa_total_20', 'aa_entropy_bits', 'aa_stop_count',
) + tuple('codon_' + ''.join(codon) + '_freq' for codon in product('ACGT', repeat=3)) + tuple(
    'aa_' + amino_acid + '_freq' for amino_acid in 'ACDEFGHIKLMNPQRSTVWY'
)
GENOME_DEPENDENCIES = ('is_coding', 'codon_total_valid', 'aa_total_20')


class ProjectionError(ValueError):
    """The source cannot be projected under the requested recipe."""


def _to_int_safe(value: object) -> int:
    # Preserve the extractor's behavior, including float-like strings and NaN.
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return 0
        return int(value)
    value = str(value).strip()
    if not value or value.lower() == 'nan':
        return 0
    try:
        return int(float(value))
    except Exception:
        return 0


@dataclass(frozen=True)
class CoreRecipe:
    omics: str
    columns: tuple[str, ...]
    fill_noncoding: str = 'zero'
    version: str = 'extractor-projection-v1'

    def __post_init__(self) -> None:
        if self.omics not in {'genome', 'transcriptome', 'proteome'}:
            raise ProjectionError('unsupported omics')
        if not self.columns or any(not isinstance(c, str) or not c for c in self.columns):
            raise ProjectionError('Core columns must be nonempty names')
        if len(set(self.columns)) != len(self.columns):
            raise ProjectionError('duplicate Core column')
        if self.version != 'extractor-projection-v1':
            raise ProjectionError('unknown recipe version')
        if self.fill_noncoding not in {'zero', 'nan'}:
            raise ProjectionError('unknown noncoding strategy')

    def required_columns(self, requested: Sequence[str] | None = None) -> tuple[str, ...]:
        selected = self.columns if requested is None else tuple(requested)
        if len(set(selected)) != len(selected) or any(c not in self.columns for c in selected):
            raise ProjectionError('invalid requested Core fields')
        required = [c for c in selected if not (self.omics == 'genome' and c == 'coding_valid')]
        if self.omics == 'genome' and (
            'coding_valid' in selected or
            (self.fill_noncoding == 'zero' and bool(set(selected) & set(GENOME_ZERO_FIELDS)))
        ):
            required.extend(GENOME_DEPENDENCIES)
        return tuple(dict.fromkeys(required))

    def validate_full_header(self, header: Sequence[str], requested: Sequence[str] | None = None) -> None:
        if not header or any(not c for c in header) or len(set(header)) != len(header):
            raise ProjectionError('empty or duplicate Full column')
        missing = [c for c in self.required_columns(requested) if c not in header]
        if missing:
            raise ProjectionError('missing Full columns: ' + ', '.join(missing))

    def project(self, row: Mapping[str, object], requested: Sequence[str] | None = None) -> dict[str, object]:
        selected = self.columns if requested is None else tuple(requested)
        required = self.required_columns(selected)
        missing = [c for c in required if c not in row]
        if missing:
            raise ProjectionError('missing Full fields: ' + ', '.join(missing))
        valid = None
        if self.omics == 'genome' and any(c in GENOME_DEPENDENCIES for c in required):
            if all(c in row for c in GENOME_DEPENDENCIES):
                valid = int(_to_int_safe(row['is_coding']) == 1 and
                            _to_int_safe(row['codon_total_valid']) > 0 and
                            _to_int_safe(row['aa_total_20']) > 0)
        result = {}
        for col in selected:
            if self.omics == 'genome' and col == 'coding_valid':
                if valid is None:
                    raise ProjectionError('missing coding dependencies')
                result[col] = valid
            elif (self.omics == 'genome' and self.fill_noncoding == 'zero'
                  and col in GENOME_ZERO_FIELDS and valid == 0):
                result[col] = 0
            else:
                result[col] = row[col]
        return result

