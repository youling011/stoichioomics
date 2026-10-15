# Visualization data contract

## Null policy

- Missing numeric observations are `null`.
- Empty binned coordinate windows return `counts[index] = null` and `bin_n[index] = 0`.
- Heatmap cells with missing values are emitted as missing cells and rendered neutral gray.

## X1 resource-shift contract

Primary visual fields:

- `dna_to_rna_n_shift_std`
- `rna_to_protein_n_shift_std`
- `resource_shift_score_std`

Method:

- robust-z delta within the matched reference cohort.
- `DNA_to_RNA_N_shift_std = z(transcriptome N/nt) - z(genome exon N/base)`.
- `RNA_to_Protein_N_shift_std = z(proteome N/aa) - z(transcriptome N/nt)`.

Legacy context fields:

- `dna_to_rna_n_shift_legacy_proxy`
- `rna_to_protein_n_shift_legacy_proxy`

Legacy raw differences are not primary visual axes because denominators differ.

## Species collection aggregate

Paginated species list responses now include `aggregate` when pagination is requested. `aggregate.domain_omics_matrix` powers filtered full-result coverage charts instead of current-page donuts.
