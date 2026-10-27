"""Versioned presentation contracts. No analysis or inference is performed here."""
import json
from pathlib import Path

DESIGN_REVISION=3
REGISTRY=json.loads((Path(__file__).parent/'design_registry.json').read_text(encoding='utf-8'))
DESIGNS={r['code']:r for r in REGISTRY}
SEQUENCE_PROFILES={'S01':{'audit'},'S05':{'coordinates'},'S06':{'codons'},'S07':{'amino_acids'},
 'S08':{'elements'},'S09':{'bases','regions'},'S15':{'sample_deltas','unpaired','paired'},'S18':{'roc_curve','pr_curve'}}
HVG_PROFILES={
 'H01':{'universe','annotation_coverage','context_coverage'},'H02':{'core_disposition','core_omics'},
 'H03':{'hvg_scatter','original_mean_score'},'H04':{'original_top_hvg'},
 'H05':{'original_workflow','original_pattern_counts','original_subset_counts'},'H06':{'context_effects'},
 'H07':{'feature_volcano'},'H08':{'adjusted_forest','adjusted_evidence'},'H09':{'matching'},'H10':{'distribution'},'H11':{'sets'},
 'H12':{'baseline'},'H13':{'subset','within_hvg'},'H14':{'feature_function'},'H15':{'gsea'},
 'H16':{'detail'},'H17':{'interactions'},'H18':{'within_raw','within_adjusted'},
 'H19':{'replication','feature_stability','set_stability','threshold_stability','candidate_frequency'},
 'H20':{'baseline_stability','feature_sensitivity'},'H21':{'candidate_frequency','candidate_priority','candidate_tiers'},
 'H22':{'candidate_ora'},'H23':{'gene'},'H24':{'original_expected_observed','original_residuals','original_classes'},
 'H25':{'original_model_associations','original_model_comparison','original_bootstrap','original_candidate_enrichment'},
 'H26':{'hvg_histogram','original_dropout'},'H27':{'eligibility','core_missingness','mapping_coverage'},
 'H28':{'feature_forest','adjusted_forest'},
 'H29':{'original_forest','original_omics_effect','original_family_heatmap','original_raw_adjusted','original_quantiles'},
 'H30':{'original_mean_score','original_top_hvg','original_dropout'},'H31':{'mapping','original_mapping_quality'},
 'H32':{'original_candidate_bubble'}}

def validate_profile(chart,params,source_kind):
    profile=params.get('panel_profile')
    if not profile:return
    allowed=(SEQUENCE_PROFILES if source_kind=='sequence' else HVG_PROFILES).get(chart,set())
    if profile not in allowed:raise ValueError('Unsupported presentation profile for '+chart+': '+str(profile))
