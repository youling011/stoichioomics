# Feature-table case pipeline: from raw multi-omics CSVs to platform registry

This package now includes a complete worked example that starts from the real stoichiometric feature tables of two species:

- **Escherichia coli 110957**
- **Saccharomyces cerevisiae R64-1-1**

The example is meant to answer a practical engineering question:

> If you already have genome / transcriptome / proteome stoichiometric feature tables as CSV files, what files need to be generated at each stage before the data can become a working database platform?

The answer in this package is a staged pipeline under:

```text
/data/feature_table_case/pipeline_outputs/
```

## Stages included in the package

### Stage 0: source bundle
`stage0_source_bundle/`

Direct copies of the original feature tables plus a `source_inventory.csv` manifest.

Files:
- original `*.csv`
- `source_inventory.csv`

### Stage 1: standardized registry
`stage1_standardized/`

The raw bundle is reorganized into a future-proof species / omics directory layout.

Files:
- `metadata/species_metadata.auto.csv`
- `metadata/dataset_manifest.auto.csv`
- `schema/genome_schema.auto.csv`
- `schema/transcriptome_schema.auto.csv`
- `schema/proteome_schema.auto.csv`
- `species_registry/<species_id>/<omics>/full.csv`
- `species_registry/<species_id>/<omics>/core.csv`
- `import_manifest.json`

### Stage 2: validation
`stage2_validation/`

Basic quality-control reports derived directly from the feature tables.

Files:
- `validation_summary.csv`
- `cross_omics_join_summary.csv`
- `species_reports/<species_id>.validation.json`
- `validation_manifest.json`

### Stage 3: parquet conversion
`stage3_parquet/`

Parquet mirrors of the standardized full/core tables for faster future serving.

Files:
- `parquet/<species_id>/<omics>/full.parquet`
- `parquet/<species_id>/<omics>/core.parquet`
- `parquet_manifest.csv`
- `parquet_manifest.json`

### Stage 4: catalog / seed tables
`stage4_catalog/`

CSV seed tables that mirror the database tables you would later load into PostgreSQL.

Files:
- `db_seed/species.csv`
- `db_seed/omics_dataset.csv`
- `db_seed/feature_file.csv`
- `db_seed/gene_index.csv`
- `db_seed/transcript_index.csv`
- `db_seed/protein_index.csv`
- `catalog_manifest.json`

### Stage 5: artifacts
`stage5_artifacts/`

Analysis-ready artifacts generated from the feature tables without manual biological annotation.

Per species / omics:
- `profile.json`
- `core_features.json`
- `summary.json`
- `analysis.json`
- `derived_features.csv`
- `rows_for_platform.csv`

Per species:
- `cross_omics.json`
- `cross_omics_panel.csv`
- `browse_meta.json`

Global:
- `analysis_artifact.csv`
- `compare/species_fingerprints.csv`
- `compare/compare_pairs.csv`
- `artifact_manifest.json`

### Stage 6: platform registry
`stage6_platform_registry/`

The final JSON registry directly consumed by the current website.

Files:
- `index.json`
- `<species_id>/<omics>/rows.json`
- `<species_id>/<omics>/summary.json`
- `<species_id>/<omics>/analysis.json`
- `<species_id>/cross_omics.json`
- `registry_manifest.json`

The same registry is also copied into:

```text
/data/stoichdb_demo/
```

so the website loads this real two-species case by default.

## How the files are generated

The package includes the script:

```bash
python scripts/build_feature_table_case_pipeline.py \
  --source-root data/feature_table_case/pipeline_outputs/stage0_source_bundle \
  --output-root data/feature_table_case/pipeline_outputs_regenerated \
  --platform-data-root data/stoichdb_demo
```

What the script does:

1. scans raw feature-table filenames
2. infers `species_id`, `display_name`, `omics`, and `table_role`
3. reorganizes tables into a standardized species / omics layout
4. generates basic schema dictionaries and metadata manifests
5. validates row counts, duplicate IDs, missingness, constant numeric columns, and cross-omics key overlap
6. writes Parquet mirrors
7. exports future database seed tables
8. derives analysis features directly from the core feature tables
9. builds summary / analysis / cross-omics artifacts
10. assembles the final JSON registry for the current platform

## Which files are directly derived from the feature tables

These are generated purely from the uploaded feature tables and simple code rules:

- `species_metadata.auto.csv`
- `dataset_manifest.auto.csv`
- `*_schema.auto.csv`
- validation reports
- Parquet conversions
- `species.csv`, `omics_dataset.csv`, `feature_file.csv`
- `gene_index.csv`, `transcript_index.csv`, `protein_index.csv`
- `profile.json`
- `core_features.json`
- `summary.json`
- `analysis.json`
- `cross_omics.json`
- `species_fingerprints.csv`
- final platform `index.json`

No external annotation source is required for this example.

## How this maps to future large-scale species ingestion

For a much larger collection of species, the same pattern scales like this:

1. put every species bundle into the Stage 0 source layout
2. run the same pipeline script or its batch version
3. load Stage 4 seed tables into PostgreSQL
4. store Stage 3 Parquet and Stage 5 artifacts in file/object storage
5. point the backend to the Stage 6 registry or a database-backed artifact directory

The worked two-species case is therefore not just demo data. It is the exact template for future large-scale import runs.
