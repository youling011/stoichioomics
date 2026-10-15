# Model-8 Case 1-5 Platform Release Contract

## Purpose

This document records the platform-level landing contract for Model-8 Case 1-5. The full database remains the broad coverage layer; the fixed eight-model-organism cases are the reproducible deep-case layer. Web summaries, paper-facing numbers, figure mappings, and downloads must be read from the same `release_id`.

## Build

Run from the project root:

```powershell
.\.venv\Scripts\python.exe -u .\scripts\build_model8_platform_release.py
```

The script does not recalculate database-wide stoichiometric features. It reads rebuilt Case 1-5 artifacts under `data/case_studies/model8` and the frozen `feature_extractor_contract.json`, validates the Model-8 protein files and case summaries against `model8-protein-elemental-v2`, then writes a platform release directory. Release generation is blocked if any Case 1-5 summary lacks the contract or if a protein feature row violates it.

## Protein elemental semantics

Model-8 protein C, N, and S values are atom totals derived from polymerized amino-acid residue formulas. Their normalized fields are named `c_atoms_per_aa`, `n_atoms_per_aa`, and `s_atoms_per_aa`. Residue identities are kept separately as `cys_count`, `ser_count`, `asn_count`, and `met_count`; one-letter residue symbols must never be interpreted directly as elemental atoms. In particular, serine contains no sulfur, while both cysteine and methionine contribute one sulfur atom per residue.

Artifacts from the earlier ambiguous schema (`c_count`, `s_count`, `n_count`, `c_per_aa`, `s_per_aa`, `n_per_aa` in protein tables) are incompatible with the v2 contract and must not be mixed with a v2 release.

## Output Directory

`data/case_studies/model8/platform_release`

Required files:

- `model8_platform_release_manifest.json`
- `case_artifact_registry.csv`
- `figure_mapping.csv`
- `claims.json`
- `elemental_semantics_validation.json`
- `model8_case1_5_platform_bundle.zip`

## CaseArtifact-Style Registry

`case_artifact_registry.csv` carries the fields required by the optimization plan:

- `case_id`
- `case_version`
- `species_id`
- `expression_accession`
- `artifact_kind`
- `path`
- `format`
- `sha256`
- `method_version`
- `status`
- `generated_at`
- `release_id`

Allowed status values are `generated`, `skipped`, `blocked`, and `unavailable`.

## Paper-Platform Consistency

`figure_mapping.csv` carries:

- `figure_id`
- `panel`
- `case_id`
- `species_or_dataset`
- `source_file`
- `filter_or_query`
- `script`
- `checksum`
- `release_id`

Any paper figure or number using Model-8 cases should trace back to one row in this file and one registered artifact in `case_artifact_registry.csv`.

## API

- `GET /api/stoichdb/case-studies/model8/platform-release/`
- `GET /api/stoichdb/case-studies/model8/download-bundle/`
- `GET /api/stoichdb/case-studies/model8/download/<relative_path>`

The direct file download endpoint is restricted to files under `data/case_studies/model8`.

## Frontend

`frontend/src/views/CaseStudiesView.vue` displays a Platform release contract panel above the individual cases. It shows:

- full database coverage vs fixed Model-8 deep-case scope
- `release_id`
- artifact count
- figure mapping count
- claims count
- bundle, registry, figure mapping, claims, and manifest downloads

## Claim Rules

Allowed terms:

- `stoich_associated`
- `stoich_predictive_feature`
- `candidate_priority`

Forbidden terms:

- `stoich_driver`
- causal driver
- regulator

Blocked or unavailable datasets must display the reason and must not be rendered as empty plots or zero-filled results.
