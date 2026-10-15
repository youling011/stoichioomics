from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from . import METHOD_VERSION


DNA_DINUCS = [a + b for a in "ACGT" for b in "ACGT"]
RNA_DINUCS = [a + b for a in "ACGU" for b in "ACGU"]
DNA_CODONS = [a + b + c for a in "ACGT" for b in "ACGT" for c in "ACGT"]
RNA_CODONS = [a + b + c for a in "ACGU" for b in "ACGU" for c in "ACGU"]
AA20 = list("ACDEFGHIKLMNPQRSTVWY")


@dataclass(frozen=True)
class ChartContract:
    chart_id: str
    omics: str
    module: str
    required_core_fields: tuple[str, ...] = ()
    optional_full_fields: tuple[str, ...] = ()
    row_filter: str = "all"
    compute_policy: str = "full_aggregate"
    display_policy: str = "aggregate"
    minimum_valid_n: int = 2
    evidence_level: str = "sequence-derived descriptive"
    method_version: str = METHOD_VERSION


GENOME_G1 = (
    "locus_gc_percent", "exon_gc_percent", "promoter_gc_percent",
    "locus_atoms_C_per_base", "locus_atoms_N_per_base", "locus_atoms_P_per_base",
    "exon_atoms_C_per_base", "exon_atoms_N_per_base", "exon_atoms_P_per_base",
    "promoter_atoms_C_per_base", "promoter_atoms_N_per_base", "promoter_atoms_P_per_base",
    "locus_shannon_entropy_acgt", "exon_shannon_entropy_acgt", "promoter_shannon_entropy_acgt",
    "locus_ratio_C_N", "locus_ratio_N_P", "exon_ratio_C_N", "exon_ratio_N_P",
    "promoter_ratio_C_N", "promoter_ratio_N_P",
)
GENOME_G2 = (
    "exon_gc_percent", "promoter_gc_percent", "promoter_exon_gc_delta",
    "gc_delta_promoter_minus_exon", "promoter_exon_N_delta", "promoter_exon_P_delta",
    "promoter_exon_entropy_delta", "exon_atoms_N_per_base", "gene_length_bp",
)
GENOME_G3_FULL = ("locus_gc_skew", "locus_at_skew")
GENOME_G4_FULL = tuple(f"locus_dinuc_{x}_freq" for x in DNA_DINUCS) + tuple(f"promoter_dinuc_{x}_freq" for x in DNA_DINUCS) + ("dinuc_distance_gene",)
GENOME_G5_FULL = ("gc1_percent", "gc2_percent", "gc3_percent", "codon_entropy_bits", "coding_valid") + tuple(f"codon_{x}_freq" for x in DNA_CODONS) + tuple(f"aa_{x}_freq" for x in AA20)
GENOME_G6 = ("start_1", "end_1", "stoich_island_score", "seqid")
GENOME_G7 = ("biotype", "gene_biotype", "gene_length_bp", "exon_gc_percent")

TRANSCRIPT_T1 = ("length_nt_acgu", "gc_content", "gc_percent_display", "nt_entropy", "frac_A", "frac_C", "frac_G", "frac_U")
TRANSCRIPT_T2 = ("atoms_per_nt_C", "atoms_per_nt_N", "atoms_per_nt_P", "C_N_ratio", "N_P_ratio", "mw_rna_nmp_per_nt_Da")
TRANSCRIPT_T3_FULL = ("gc_content", "nt_entropy", "max_run_any", "stability_proxy_score") + tuple(f"dinuc_{x}_freq" for x in RNA_DINUCS)
TRANSCRIPT_T4 = ("transcript_biotype", "gene_biotype", "length_nt_acgu")
TRANSCRIPT_T5 = ("length_nt_acgu", "orf_len_nt", "orf_len_aa", "coding_coverage", "coding_density_proxy", "orf_has_stop")
TRANSCRIPT_T6_FULL = ("derived_gc3", "codon_entropy_bits", "coding_valid", "orf_len_aa") + tuple(f"codon_{x}_freq" for x in RNA_CODONS)
TRANSCRIPT_T7 = ("rna_orf_coupling_score", "protein_gravy", "protein_gravy_proxy", "protein_instability_index") + tuple(f"aa_{x}_freq" for x in AA20)

PROTEOME_P1 = ("length_aa", "canonical_fraction", "unknown_atom_ratio", "noncanonical_ratio")
PROTEOME_P1_FULL = (
    "length_canonical_aa", "known_residues_for_atoms", "unknown_residues_for_atoms",
    "noncanonical_aa", "X_count", "B_count", "Z_count", "J_count", "U_count", "O_count",
    "stop_asterisk_count", "seq_md5",
)
PROTEOME_P2 = ("C_atoms_per_aa", "N_atoms_per_aa", "S_atoms_per_aa", "C_N_ratio", "N_S_ratio")
PROTEOME_P2_FULL = ("C_mass_frac", "N_mass_frac", "S_mass_frac", "H_atoms_per_aa", "O_atoms_per_aa")
PROTEOME_P3_FULL = ("N_atoms_per_aa", "S_atoms_per_aa", "sulfur_aa_frac", "Se_atoms_per_aa", "Se_atoms", "disulfide_density")
PROTEOME_P4 = tuple(f"AA_{x}_pct" for x in AA20) + ("aa_entropy_bits", "aa_hydrophobic_frac", "aa_polar_frac", "aa_pos_frac", "aa_neg_frac", "aa_aromatic_frac")
PROTEOME_P5 = ("mw_da", "pI", "net_charge_pH7", "gravy", "instability_index", "aliphatic_index", "aromaticity")
PROTEOME_P6_FULL = ("ss_helix_frac", "ss_turn_frac", "ss_sheet_frac", "flex_mean", "surface_access_em_mean", "disulfide_density")
PROTEOME_P7_FULL = ("avg_oxidation_state_C", "O_C_ratio", "H_C_ratio", "a280_1mgml_reduced", "a280_1mgml_cystines", "extinction_reduced", "extinction_cystines", "aromaticity")


CONTRACTS: tuple[ChartContract, ...] = (
    ChartContract("genomeG1RegionChart", "genome", "G1", GENOME_G1),
    ChartContract("genomeG2DeltaChart", "genome", "G2", GENOME_G2),
    ChartContract("genomeG2ScatterChart", "genome", "G2", GENOME_G2, display_policy="deterministic_reservoir_5000"),
    ChartContract("genomeG3SkewChart", "genome", "G3", ("seqid",), GENOME_G3_FULL),
    ChartContract("genomeG4DinucHeatmap", "genome", "G4", ("seqid",), GENOME_G4_FULL),
    ChartContract("genomeG5CodonHeatmap", "genome", "G5", ("coding_valid",), GENOME_G5_FULL, row_filter="coding_valid"),
    ChartContract("genomeG6ProfileChart", "genome", "G6", GENOME_G6, display_policy="48_bins"),
    ChartContract("genomeG7BiotypeChart", "genome", "G7", GENOME_G7),
    ChartContract("transcriptomeT1BaseChart", "transcriptome", "T1", TRANSCRIPT_T1),
    ChartContract("transcriptomeT2ElementChart", "transcriptome", "T2", TRANSCRIPT_T2),
    ChartContract("transcriptomeT3DinucHeatmap", "transcriptome", "T3", ("gc_content", "nt_entropy", "max_run_any"), TRANSCRIPT_T3_FULL),
    ChartContract("transcriptomeT4BiotypeChart", "transcriptome", "T4", TRANSCRIPT_T4),
    ChartContract("transcriptomeT5OrfLengthChart", "transcriptome", "T5", TRANSCRIPT_T5, row_filter="orf_valid"),
    ChartContract("transcriptomeT6CodonHeatmap", "transcriptome", "T6", ("coding_valid",), TRANSCRIPT_T6_FULL, row_filter="coding_valid"),
    ChartContract("transcriptomeT7AaChart", "transcriptome", "T7", TRANSCRIPT_T7, row_filter="orf_valid", evidence_level="translated ORF proxy"),
    ChartContract("proteomeP1LengthChart", "proteome", "P1", PROTEOME_P1, PROTEOME_P1_FULL),
    ChartContract("proteomeP2ElementChart", "proteome", "P2", PROTEOME_P2, PROTEOME_P2_FULL),
    ChartContract("proteomeP3NsScatter", "proteome", "P3", ("N_atoms_per_aa", "S_atoms_per_aa"), PROTEOME_P3_FULL, display_policy="deterministic_reservoir_5000"),
    ChartContract("proteomeP4AaChart", "proteome", "P4", PROTEOME_P4),
    ChartContract("proteomeP5PiChart", "proteome", "P5", PROTEOME_P5),
    ChartContract("proteomeP6StructureChart", "proteome", "P6", ("length_aa",), PROTEOME_P6_FULL, evidence_level="sequence-derived proxy"),
    ChartContract("proteomeP7ZcChart", "proteome", "P7", ("length_aa",), PROTEOME_P7_FULL),
)


def contracts_for_omics(omics: str) -> tuple[ChartContract, ...]:
    return tuple(item for item in CONTRACTS if item.omics == omics)


def required_core_fields_for_omics(omics: str) -> tuple[str, ...]:
    return _dedupe(field for contract in contracts_for_omics(omics) for field in contract.required_core_fields)


def optional_full_fields_for_omics(omics: str) -> tuple[str, ...]:
    return _dedupe(field for contract in contracts_for_omics(omics) for field in contract.optional_full_fields)


def all_contract_fields_for_omics(omics: str) -> tuple[str, ...]:
    return _dedupe(
        field
        for contract in contracts_for_omics(omics)
        for field in [*contract.required_core_fields, *contract.optional_full_fields]
    )


def _dedupe(fields: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    for field in fields:
        if field and field not in out:
            out.append(field)
    return tuple(out)
