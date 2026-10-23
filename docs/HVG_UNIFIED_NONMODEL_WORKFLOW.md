# Unified HVG workflow

Full Expression/HVG jobs use `hvg_unified_nonmodel_v1`. HTTP automatic/manual configuration and the full-pipeline CLI share the same executor. A legacy `hvg_research.enabled=false` or `model_enabled=true` cannot restore the predictive branch.

1. Standardize the selected expression matrix/layer and validate input and metadata.
2. Identify all supported metadata modes. Compute official Scanpy global HVG labels, independently of sequence feature coverage.
3. Run the full Core audit, feature tests, covariate adjustment, matching, directional sets, baseline/subset/within-HVG enrichment, continuous feature-function and feature-ranked GSEA, within-function differences, interactions and technical sensitivity.
4. Run every available original group, condition, timecourse, sample-consensus and trajectory mode. Reuse the existing pattern/consensus rules; use the official configured HVG algorithm for each valid subset. Missing metadata and invalid subsets retain explicit reasons. The mode cache is task-local and indexed by actual cell and gene identities.
5. Run the original v2 multi-omics direct comparison on the same global standard labels. Preserve its original statistics, units and correction separately from the extended research analysis.
6. Correct the declared research families, integrate non-model candidate evidence, and test the research candidate union against source-specific annotated eligible backgrounds (family F9, global across declared research contexts). Save candidate functions and network availability separately.
7. Publish traceable tables, charts, source files and the complete archive in the existing ten result sections.

## Scope and statistical boundaries

Original metadata patterns and research contexts are separate outputs. All eligible original metadata modes run automatically. Extended research runs globally and for explicitly configured `hvg_research.contexts`; it does not invent donors, conditions, time labels or biological replicates. Pattern tables and consensus votes do not replace the frozen global standard HVG labels.

All Core fields remain in the audit. Unavailable, redundant, inapplicable and non-estimable fields are reported, not silently converted to zeros. Feature scaling, composition transforms, correction families and platform annotation limitations remain unchanged. Covariate-adjusted statistical tests are retained; these are not the removed prediction branch.

The original v2 comparison and extended research comparison use different preparation/adjustment contracts. Their q values and coefficients must not be pooled or presented as the same test.

## Removed branch

New jobs do not execute the old stoichiometric prediction/classification model, expected-versus-observed predictions, residual classes, model comparisons/CV, prediction-model bootstrap/permutation assessments, or residual-derived candidate scores and candidate-score GSEA. Candidate evidence now comes from standard HVG labels, significant Core relationships, function support and sensitivity results.

No validated PPI edge input/network inference was supplied by the original utility. The workflow explicitly reports `not_available`; feature tiers and former model classes are not network modules. The optional Seurat R bridge remains an unavailable/unimplemented historical capability; the official Python backend is used without algorithm fallback.

## Result interface

The ten section keys stay compatible. For unified runs, section 06 is **Feature & Function**, section 07 is **Evidence & Stability**. Model charts/tables are removed per run. Section 04 exposes actual original metadata mode outcomes. Section 05 embeds the complete original v2 comparison, including its filtering and feature drill-down, alongside the extended research plots. Section 08 includes research candidate enrichment. Tables and chart exports use the same selected run.

Historical curated model-organism case-study results remain readable as archival results. They are not newly executed models of a unified task. Legacy model functions remain in the library solely for source/archive compatibility; the full-job executor does not call them.

## Operation and reproducibility

Submit one **full** job from the existing workflow page. Supply an authoritative species, verified matrix value semantics and optional metadata; the platform uses its own annotation release. Advanced research settings still control declared contexts and statistical precision. Explicitly disabled research analyses and reduced test precision remain visible limitations.

Each run freezes input/source/config/code identities and publishes only completed output files. Restarting an old run after an execution-contract change requires a new run if its dependency fingerprint differs. A preanalysis-only job remains an input check, not a complete analysis.

The refreshed GSE123818 example reuses its prior validated platform-annotation research statistics and records that origin. Standard labels were independently recomputed and matched; newly connected non-model branches were calculated. The reuse provenance and separate historical/new code hashes are downloadable. New user jobs execute the whole pipeline from their own inputs.
