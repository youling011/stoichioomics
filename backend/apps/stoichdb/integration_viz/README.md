# Integration visualizations

Overview and Cross-omics use complete registered Core CSV populations. Genome
Full contributes only three explicitly named, one-to-one-aligned supplemental
fields. Source CSVs and curated database tables are never modified.

## Run and inspect

From the project root, using its Python environment:

```powershell
.\.venv\Scripts\python.exe manage.py materialize_integration_visuals --species-file data\proteome_visuals\common_species_20261020.txt --resume --publish --with-default-cohort --max-workers 1
.\.venv\Scripts\python.exe manage.py materialize_integration_visuals --species-file data\proteome_visuals\common_species_20261020.txt --audit-only --with-default-cohort
```

The list contains 691 unique registry IDs, including strains/assemblies. Other
species are materialized on demand. A capability audit is separate from result
precomputation; it reads complete identifiers and necessary numeric columns and
publishes only capability reports:

```powershell
.\.venv\Scripts\python.exe manage.py materialize_integration_visuals --scan-capabilities --all-registered --resume --max-workers 4 --output-root runtime\integration_capability_audit_20261022
```

One, two or four bounded read-only audit processes are allowed; low physical memory reduces concurrency. Datasets with 100,000 or more
registered Core rows run alone. Scientific materialization uses one worker and
recycles a separate process for large datasets. All BLAS thread pools use one
thread. No selection means a command error; all-registered is audit-only.

## Identity and publication

`runtime/integration_visuals_v1` is an independent namespace. Registry IDs remain
literal inside artifacts and exports. Directory components use SHA surrogates
to stay below Windows path limits. Species versions are immutable, staged,
audited and atomically published. Explicit missing versions return HTTP 410;
changed sources/methods return HTTP 409. Failed builds retain the last good
pointer. `storage_version=2` adds all native island component evidence without
changing the approved numerical methods or repeating unchanged correlations.

`cohorts.py` contains numerical methods. `cohort_artifacts.py` independently
publishes content-addressed cohorts: all actual Core content hashes, selected
species/order, release and implementation enter the final key. A cheap request
signature index keeps GET/ensure free of source scanning. Descriptor caches can
read full original Core snapshot columns; they never use matched gene means.

API prefix: `/api/stoichdb/species/<id>/integration/visualizations/`.
Responses use the platform `ok/data` envelope. Manifest GET does not calculate
results. `ensure` enqueues one task, and `requests/<id>/` reports actual stages
and heartbeat. Cohorts are separate tasks, preventing single-consumer deadlock.
The hidden consumer exits after 45 idle seconds. Admin-only prepare accepts
`force:true`; ordinary ensure cannot overwrite existing publications.

## UI and rollback

The original navigation, metadata, ID QC, GO/KEGG, three-omics workspaces and old
APIs remain. New content uses scoped `.integration-*` styles, a shared lifecycle
context, at most three chart requests, full field directories, server paging,
native member lookup and backend complete exports. Coordinates use paged
tracks; viewing a range never refits global scores or thresholds. Figures export
actual SVG or 4× PNG via a disposable offscreen ECharts instance. Large exact
JSON/CSV responses receive compression only in this namespace.

Flags: `INTEGRATION_VIZ_ENABLED`, `INTEGRATION_VIZ_ON_DEMAND`,
`INTEGRATION_VIZ_ROOT`, and front-end `VITE_INTEGRATION_OVERVIEW_ENABLED` /
`VITE_INTEGRATION_CROSS_ENABLED`. Setting both front-end flags to `0` and
rebuilding restores the retained legacy branches. Disable on-demand to stop new
consumers. Keep existing artifacts as evidence; do not restore the entire repo
or delete shared runtime directories. Test overrides use independent roots and
the disposable database `test_stoich_integration_viz_acceptance_20261022`.

Storage version 3 keeps lossless gzipped original Core CSV snapshots and all 272 per-gene finite support counts, in addition to native score components and the unchanged scientific results. Snapshot bytes are checked against the original full-file SHA. Immutable storage upgrades inherit the passed numerical audit and separately check all added evidence.

The exact before/after fingerprints in implementation_compatibility.json permit reuse only of previously audited immutable artifacts across the all-null rho ordering-key fix. No scientific coefficients, masks, source values or scores changed. Future/unlisted fingerprints still invalidate normally; API manifests and the publication inventory show both fingerprints.

Cohort CLI/consumer processes use cohort_metadata.registry_snapshot to avoid repeated loading of large registry JSON. It reads only real dataset identity/path/count fields, validates registry identity before/after, keeps file checks unchanged, restores readers on every exit, and is never entered by HTTP handlers.
