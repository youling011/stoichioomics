# HVG/non-HVG direct comparison v1

Schema: `hvg_nonhvg_v1`  
Evidence rules: `evidence_rule_v1`

This release adds an independent gene-level branch that compares reliably mapped Transcriptome and/or Proteome Core stoichiometric features between Phase 1 HVG and non-HVG labels. Genome and Full fields are outside the v1 comparison universe.

The primary continuous-feature analysis uses a two-sided Mann–Whitney U test, Cliff's delta, a reproducible stratified-bootstrap confidence interval, and one global Benjamini–Hochberg correction across every tested hypothesis in the job. Binary and nominal categorical fields retain their own effect definitions and conservative evidence rules. Gene-level adjusted logistic results use available expression, one detection/dropout measure, and an applicable length covariate; they are a separate multiple-testing family.

The comparison branch and existing Generic-M0/M1/M2/M3 model branch have independent status and failure handling. Existing `feature_associations.csv`, model artifacts, Case 5 B0/B1/B2/B3 evidence, Gene Explorer, and legacy APIs retain their original meanings. No permutation importance, Spearman correlation, or model importance is converted into a direct group effect.

Eight versioned artifacts are generated under `analysis_phase2`: feature audit, raw comparison, adjusted comparison, distribution quantiles, family summary, plot payload, summary, and run manifest. Historical results without these files return `legacy_not_generated`. Frozen Case 5 data can be migrated only through `backfill_hvg_nonhvg_comparison`, which calls the same comparison engine and records input hashes, backups, output hashes, and history.

The result page shows the direct-comparison tab separately from model evidence. Table filters do not recompute FDR or evidence levels. Overview payloads exclude all-feature distribution points; selected feature detail is loaded separately for ordinary jobs, while Case 5 uses its compact quantile data.
