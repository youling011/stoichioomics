from __future__ import annotations

from copy import deepcopy
from typing import Any


DNA_BASES = ["A", "C", "G", "T"]
RNA_BASES = ["A", "C", "G", "U"]
AA_CODES = ["A", "C", "D", "E", "F", "G", "H", "I", "K", "L", "M", "N", "P", "Q", "R", "S", "T", "V", "W", "Y"]


def _dna_dinuc(prefix: str = "locus_dinuc") -> list[str]:
    return [f"{prefix}_{a}{b}_freq" for a in DNA_BASES for b in DNA_BASES]


def _rna_dinuc(prefix: str = "dinuc") -> list[str]:
    return [f"{prefix}_{a}{b}_freq" for a in RNA_BASES for b in RNA_BASES]


def _codons() -> list[str]:
    return [f"codon_{a}{b}{c}_freq" for a in DNA_BASES for b in DNA_BASES for c in DNA_BASES]


def _aa_freq(prefix: str = "aa") -> list[str]:
    return [f"{prefix}_{aa}_freq" for aa in AA_CODES]


def _aa_pct() -> list[str]:
    return [f"AA_{aa}_pct" for aa in AA_CODES] + ["AA_other_pct"]


CORE_PANEL_REGISTRY: dict[str, list[dict[str, Any]]] = {
    "genome": [
        {
            "panel_id": "genome_annotation_overview",
            "title": "G0. 实体追踪与注释概览",
            "module": "annotation_overview",
            "region_options": ["gene", "transcript", "genome_location", "coding_status"],
            "metric_options": ["counts", "filters", "identity"],
            "default_chart": "categorical_bar",
            "unit": "metadata",
            "aggregation": "count",
            "fields": [
                "species_id", "gene_id", "source_gene_id", "gene_name", "locus_tag", "biotype", "seqid",
                "start_1", "end_1", "strand", "is_coding", "transcript_count",
                "chosen_transcript_source_id", "chosen_transcript_reason", "transl_table_used",
                "exon_seq_strategy", "upstream_intergenic_bp", "downstream_intergenic_bp", "coding_valid",
            ],
        },
        {
            "panel_id": "genome_region_quality",
            "title": "G1. 区域长度、GC 与序列质量",
            "module": "region_sequence_quality",
            "region_options": ["locus", "promoter", "exon", "CDS", "compare_regions"],
            "metric_options": ["length", "GC", "N_percent", "entropy"],
            "default_chart": "grouped_boxplot",
            "unit": "bp / percent / bits",
            "aggregation": "median/IQR",
            "fields": [
                "locus_length_bp", "locus_length_acgt_bp", "locus_gc_percent", "locus_n_percent",
                "promoter_length_bp", "promoter_length_acgt_bp", "promoter_gc_percent", "promoter_n_percent",
                "promoter_shannon_entropy_acgt", "exon_length_bp", "exon_length_acgt_bp",
                "exon_gc_percent", "exon_n_percent", "exon_shannon_entropy_acgt",
                "cds_length_bp", "cds_gc_percent",
            ],
        },
        {
            "panel_id": "genome_element_budget",
            "title": "G2. DNA 元素计量密度与元素比值",
            "module": "element_stoichiometry",
            "region_options": ["promoter", "exon"],
            "metric_options": ["atoms_per_base", "ratios"],
            "default_chart": "grouped_boxplot",
            "unit": "atoms per base / ratio",
            "aggregation": "median/IQR",
            "fields": [
                "promoter_atoms_C_per_base", "promoter_atoms_H_per_base", "promoter_atoms_O_per_base",
                "promoter_atoms_N_per_base", "promoter_atoms_P_per_base", "promoter_ratio_C_N",
                "promoter_ratio_C_P", "promoter_ratio_N_P", "exon_atoms_C_per_base",
                "exon_atoms_H_per_base", "exon_atoms_O_per_base", "exon_atoms_N_per_base",
                "exon_atoms_P_per_base", "exon_ratio_C_N", "exon_ratio_C_P", "exon_ratio_N_P",
            ],
        },
        {
            "panel_id": "genome_locus_dinucleotide",
            "title": "G3. locus 二核苷酸模式",
            "module": "dinucleotide_pattern",
            "region_options": ["locus"],
            "metric_options": ["frequency"],
            "default_chart": "composition_heatmap",
            "unit": "frequency",
            "aggregation": "median/IQR",
            "fields": ["locus_dinuc_total_valid", *_dna_dinuc()],
            "matrix": {"type": "dinucleotide", "alphabet": DNA_BASES, "field_prefix": "locus_dinuc"},
        },
        {
            "panel_id": "genome_cds_codon_usage",
            "title": "G4. CDS 密码子使用与编码偏好",
            "module": "codon_usage",
            "region_options": ["CDS"],
            "metric_options": ["codon_frequency", "GC_position", "codon_entropy"],
            "default_chart": "composition_heatmap",
            "unit": "frequency / percent / bits",
            "aggregation": "median/IQR",
            "fields": ["codon_total_valid", *_codons(), "gc1_percent", "gc2_percent", "gc3_percent", "codon_entropy_bits"],
            "matrix": {"type": "codon", "alphabet": DNA_BASES, "field_prefix": "codon"},
        },
        {
            "panel_id": "genome_cds_translated_aa",
            "title": "G5. CDS 翻译氨基酸组成代理",
            "module": "translated_aa_composition",
            "region_options": ["translated_CDS"],
            "metric_options": ["AA_frequency", "QC", "entropy"],
            "default_chart": "composition_heatmap",
            "unit": "frequency / count / bits",
            "aggregation": "median/IQR",
            "fields": ["aa_total_20", "aa_stop_count", *_aa_freq(), "aa_entropy_bits"],
            "matrix": {"type": "amino_acid", "alphabet": AA_CODES, "field_prefix": "aa"},
        },
    ],
    "transcriptome": [
        {
            "panel_id": "transcriptome_annotation_overview",
            "title": "T0. 实体追踪与注释概览",
            "module": "annotation_overview",
            "region_options": ["transcript", "gene", "genomic_coordinate", "biotype"],
            "metric_options": ["counts", "filters", "identity"],
            "default_chart": "categorical_bar",
            "unit": "metadata",
            "aggregation": "count",
            "fields": [
                "species_id", "omics", "element_rule", "transcript_id", "gene_id", "gene_symbol",
                "gene_biotype", "transcript_biotype", "assembly", "seq_region", "start", "end", "strand",
            ],
        },
        {
            "panel_id": "transcriptome_rna_base_complexity",
            "title": "T1. RNA 长度、碱基组成与复杂度",
            "module": "rna_base_composition",
            "region_options": ["whole_transcript"],
            "metric_options": ["length", "base_fraction", "GC_skew", "entropy"],
            "default_chart": "stacked_bar",
            "unit": "nt / proportion / entropy",
            "aggregation": "median/IQR",
            "fields": [
                "length_nt_total", "length_nt_acgu", "n_N", "frac_A", "frac_C", "frac_G", "frac_U",
                "gc_content", "at_skew", "gc_skew", "purine_frac", "nt_entropy",
            ],
        },
        {
            "panel_id": "transcriptome_rna_nmp_element_budget",
            "title": "T2. RNA_NMP 元素计量与资源比值",
            "module": "rna_element_stoichiometry",
            "region_options": ["whole_transcript"],
            "metric_options": ["total_atoms", "atoms_per_nt", "ratios", "molecular_weight"],
            "default_chart": "grouped_boxplot",
            "unit": "atoms / atoms per nt / ratio / Da",
            "aggregation": "median/IQR",
            "fields": [
                "C_atoms", "N_atoms", "P_atoms", "C_N_ratio", "C_P_ratio", "N_P_ratio",
                "atoms_per_nt_C", "atoms_per_nt_N", "atoms_per_nt_P", "mw_rna_nmp_per_nt_Da",
            ],
        },
        {
            "panel_id": "transcriptome_rna_dinucleotide",
            "title": "T3. RNA 二核苷酸模式",
            "module": "dinucleotide_pattern",
            "region_options": ["whole_transcript"],
            "metric_options": ["frequency"],
            "default_chart": "composition_heatmap",
            "unit": "frequency",
            "aggregation": "median/IQR",
            "fields": [*_rna_dinuc(), "dinuc_valid_pairs"],
            "matrix": {"type": "dinucleotide", "alphabet": RNA_BASES, "field_prefix": "dinuc"},
        },
        {
            "panel_id": "transcriptome_structure_repeats",
            "title": "T4. RNA 序列结构与重复模式",
            "module": "rna_structure_repeats",
            "region_options": ["whole_transcript"],
            "metric_options": ["spacing", "homopolymer", "clean_length"],
            "default_chart": "grouped_boxplot",
            "unit": "nt / count",
            "aggregation": "median/IQR",
            "fields": ["clean_rna_len", "avg_spacing_A", "avg_spacing_U", "max_run_A", "max_run_any"],
        },
        {
            "panel_id": "transcriptome_orf_coding_proxy",
            "title": "T5. ORF 编码潜力与翻译代理属性",
            "module": "orf_coding_potential",
            "region_options": ["longest_ORF"],
            "metric_options": ["ORF_size", "translated_property"],
            "default_chart": "scatter",
            "unit": "nt / aa / Da / property index",
            "aggregation": "median/IQR",
            "fields": [
                "orf_len_nt", "orf_len_aa", "orf_has_stop", "codon_valid_codons",
                "protein_mw_Da", "protein_instability_index", "protein_gravy", "protein_isoelectric_point",
            ],
        },
        {
            "panel_id": "transcriptome_orf_translated_aa",
            "title": "T6. ORF 翻译氨基酸组成",
            "module": "translated_aa_composition",
            "region_options": ["translated_ORF"],
            "metric_options": ["AA_frequency"],
            "default_chart": "composition_heatmap",
            "unit": "frequency / aa",
            "aggregation": "median/IQR",
            "fields": ["aa_len", *_aa_freq()],
            "matrix": {"type": "amino_acid", "alphabet": AA_CODES, "field_prefix": "aa"},
        },
    ],
    "proteome": [
        {
            "panel_id": "proteome_annotation_overview",
            "title": "P0. 实体追踪与注释概览",
            "module": "annotation_overview",
            "region_options": ["protein", "gene", "transcript", "source_database"],
            "metric_options": ["counts", "filters", "identity"],
            "default_chart": "categorical_bar",
            "unit": "metadata",
            "aggregation": "count",
            "fields": [
                "species_id", "protein_id", "gene_id", "gene_symbol", "transcript_id", "source_db",
                "source_protein_id", "ensembl_gene_id", "ensembl_transcript_id", "ensembl_protein_id", "description",
            ],
        },
        {
            "panel_id": "proteome_physicochemical",
            "title": "P1. 蛋白长度、分子量与基本理化性质",
            "module": "protein_physicochemical",
            "region_options": ["whole_protein"],
            "metric_options": ["size", "charge", "hydrophobic_stability"],
            "default_chart": "scatter",
            "unit": "aa / Da / property index",
            "aggregation": "median/IQR",
            "fields": [
                "length_aa", "mw_da", "pI", "net_charge_pH7", "gravy", "aromaticity",
                "instability_index", "aliphatic_index", "aa_entropy_bits",
            ],
        },
        {
            "panel_id": "proteome_aa_class_resource",
            "title": "P2. 氨基酸类别与资源属性摘要",
            "module": "aa_class_resource",
            "region_options": ["whole_protein"],
            "metric_options": ["AA_class_fraction", "sulfur_residues"],
            "default_chart": "stacked_bar",
            "unit": "fraction / count",
            "aggregation": "median/IQR",
            "fields": [
                "aa_hydrophobic_frac", "aa_polar_frac", "aa_pos_frac", "aa_neg_frac",
                "aa_aromatic_frac", "cys_count", "met_count", "sulfur_aa_frac",
            ],
        },
        {
            "panel_id": "proteome_element_budget",
            "title": "P3. 蛋白元素计量与元素资源比值",
            "module": "protein_element_stoichiometry",
            "region_options": ["whole_protein"],
            "metric_options": ["total_atoms", "atoms_per_aa", "ratios", "oxidation"],
            "default_chart": "grouped_boxplot",
            "unit": "atoms / atoms per aa / ratio",
            "aggregation": "median/IQR",
            "fields": [
                "C_atoms", "H_atoms", "N_atoms", "O_atoms", "S_atoms", "Se_atoms",
                "C_atoms_per_aa", "N_atoms_per_aa", "S_atoms_per_aa", "avg_oxidation_state_C",
                "C_N_ratio", "N_S_ratio", "O_C_ratio", "H_C_ratio",
            ],
        },
        {
            "panel_id": "proteome_aa_percentage",
            "title": "P4. 20AA 组成百分比",
            "module": "aa_composition_percentage",
            "region_options": ["whole_protein"],
            "metric_options": ["AA_percentage"],
            "default_chart": "composition_heatmap",
            "unit": "percent",
            "aggregation": "median/IQR",
            "fields": _aa_pct(),
            "matrix": {"type": "amino_acid", "alphabet": [*AA_CODES, "other"], "field_prefix": "AA", "suffix": "_pct"},
        },
    ],
}


def get_core_panel_registry(omics_type: str) -> list[dict[str, Any]]:
    return deepcopy(CORE_PANEL_REGISTRY.get(str(omics_type or "").lower(), []))


def get_core_fields(omics_type: str) -> list[str]:
    fields: list[str] = []
    for panel in CORE_PANEL_REGISTRY.get(str(omics_type or "").lower(), []):
        fields.extend(panel["fields"])
    return fields


def expected_core_field_count(omics_type: str) -> int:
    return len(get_core_fields(omics_type))
