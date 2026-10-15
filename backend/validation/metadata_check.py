from __future__ import annotations
from typing import Dict, Any

from .schemas import StandardizedBundle
from .utils import RECOMMENDED_METADATA_FIELDS, fraction, non_null_fraction, top_value_counts


def build_metadata_check_report(bundle: StandardizedBundle) -> Dict[str, Any]:
    obs = bundle.obs.copy()
    n_cells = obs.shape[0]

    present = [c for c in RECOMMENDED_METADATA_FIELDS if c in obs.columns]
    missing = [c for c in RECOMMENDED_METADATA_FIELDS if c not in obs.columns]
    completeness = {c: non_null_fraction(obs[c]) for c in present}
    cardinality = {c: int(obs[c].nunique(dropna=True)) for c in present}

    supports = {
        'global_hvg': True,
        'group_aware_hvg': bool(any(c in obs.columns for c in ['cluster', 'cell_type'])),
        'condition_aware_hvg': 'condition' in obs.columns,
        'timecourse_hvg': 'timepoint' in obs.columns,
        'sample_consensus_hvg': any(c in obs.columns for c in ['sample_id', 'batch', 'donor']),
    }

    examples = {c: top_value_counts(obs[c], k=5) for c in present if cardinality.get(c, 0) <= 25}

    report = {
        'n_cells': int(n_cells),
        'required_cell_id_present': 'cell_id' in obs.columns,
        'cell_id_unique': bool(not obs.index.duplicated().any()),
        'recommended_fields_present': present,
        'recommended_fields_missing': missing,
        'field_completeness': completeness,
        'field_cardinality': cardinality,
        'example_value_counts': examples,
        'supports_analysis_modes': supports,
    }
    report['metadata_richness_score'] = round(fraction(len(present), len(RECOMMENDED_METADATA_FIELDS)), 4)
    return report
