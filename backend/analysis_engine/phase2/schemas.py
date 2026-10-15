
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List

CORE_MODEL_FEATURES = [
    'length_nt','gc_content','at_skew','gc_skew','nt_entropy','c_per_nt','n_per_nt','p_per_nt','C_N_ratio','C_P_ratio','N_P_ratio','orf_ratio_nt','protein_mw_da','protein_isoelectric_point','protein_gravy','protein_instability_index'
]
EXTENDED_MODEL_FEATURES = [
    'length_nt','gc_content','at_skew','gc_skew','nt_entropy','c_atoms','n_atoms','p_atoms','c_per_nt','n_per_nt','p_per_nt','C_N_ratio','C_P_ratio','N_P_ratio','orf_len_nt','orf_len_aa','orf_ratio_nt','protein_mw_da','protein_isoelectric_point','protein_gravy','protein_instability_index'
]
STOICH_CLASSES = ['canonical_hvg','stoich_explained_hvg','stoich_excess_hvg','stoich_constrained_stable','background_gene']
PLOT_FEATURES = ['gc_content','p_per_nt','n_per_nt','length_nt']

@dataclass
class ModelArtifacts:
    feature_columns: List[str]
    confounder_columns: List[str]
    baseline_feature_columns: List[str]
    augmented_feature_columns: List[str]
    numeric_summary: Dict[str, Any]
    model_metrics: Dict[str, Any]
    baseline_metrics: Dict[str, Any]
    delta_metrics: Dict[str, Any]
    feature_importance: List[Dict[str, Any]]
    permutation_importance: List[Dict[str, Any]] = field(default_factory=list)
    model_diagnostics: Dict[str, Any] = field(default_factory=dict)
    thresholds: Dict[str, Any] = field(default_factory=dict)
