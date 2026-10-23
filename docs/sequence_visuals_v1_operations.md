# Genome / Transcriptome visualization operations

This implementation adds an isolated `sequence_viz` channel. Existing Overview, Cross, Table, Compare, EntityReport and Proteome channels retain their original routes. No database schema migration is required.

## Runtime and rollback

The backend settings are `SEQUENCE_VIZ_GENOME_ENABLED`, `SEQUENCE_VIZ_TRANSCRIPTOME_ENABLED`, `SEQUENCE_VIZ_ROOT`, `SEQUENCE_VIZ_ON_DEMAND` and `SEQUENCE_VIZ_COHORT_LIMIT` (maximum 32). Frontend overrides are `VITE_SEQUENCE_VIZ_GENOME_ENABLED` and `VITE_SEQUENCE_VIZ_TRANSCRIPTOME_ENABLED`. Set the relevant frontend and backend enable flags to `0`, then rebuild/restart the normal application to restore the legacy rendering path. Do not delete the existing Proteome artifact namespace.

Artifacts live in `runtime/sequence_visuals_v1`. Published pointers refer to immutable versions. Each version records the source file hashes, original columns, actual row counts, scope, release and implementation hash. Source/schema/implementation changes invalidate the published identity. Do not manually edit a published version. Unknown versions return HTTP 410; mismatched source identity returns HTTP 409.

Genome Full datasets without `coding_valid` derive eligibility exclusively from Full fields: `is_coding > 0 AND codon_total_valid > 0 AND aa_total_20 > 0`, matching the existing platform fallback. Existing flags, including missing flags, are preserved. Core missing fields can be appended from Full by exact unique native ID; an existing Core column is never filled from Full. Full results use the complete Full population. Raw-field atlases preserve source zero values; scientific analyses apply their documented eligibility masks.

## Precomputation

Run commands from the project root containing `manage.py`, using the project's virtual environment. Always supply an explicit species file. The authoritative model-organism snapshot has 693 rows and 691 unique IDs. The validation list is separately identified; it does not expand the production precomputation policy to all 17,942 registered species.

```powershell
.\.venv\Scripts\python.exe manage.py materialize_sequence_visuals --species-file <691-species-file> --omics both --scope both --workers 2 --resume --publish --report <report.json>
```

The command limits native numerical threads, recycles workers after each omics dataset and processes large datasets without a concurrent second task. Resume validates the current identity before reuse. Compatible coordinate-only changes create a new immutable version without refitting unchanged descriptor models. Exact Core/Full reuse is allowed only after complete native-ID, metadata and analysis-value equality checks; otherwise Full is calculated independently. Audit-only mode does not publish or calculate new results. Never substitute `--all-registered` for the explicit model list.

## First-visit calculation

Manifest GET is read-only. The page POSTs `ensure/` with only the selected scope when the result is absent or stale. A separate hidden worker processes a deduplicated request, publishes an audited version, then exits after 45 seconds idle. Other species therefore use the same complete-population method on demand. The browser polls request status and cancels obsolete responses after species, omics or scope changes. Requests whose producer already owns a batch lock are deferred rather than reported as a scientific failure.

Failed/interrupted requests expose their state. Resolve the source error and retry `ensure/` or the explicit CLI. Do not silently switch to a sampled population or replace unavailable Full with Core. Species lacking a fingerprint component remain excluded from that cohort view with an explicit reason.

## Data and export verification

Genome has 35 positions and 146 original Core numeric fields plus 14 original metadata fields. Transcriptome has 33 positions and 74 numeric plus 12 metadata fields. The field atlas and native quantile table cover every original field; pagination changes the browser presentation only. Density bins and cluster assignments retain exact native members. CSV/TSV exports stream all eligible rows, retain source IDs and distinguish raw fields from module eligibility. Exact ECDF links use the same mask as the selected analysis; raw-field atlas ECDF links use the complete raw population. User-controlled metadata is protected against spreadsheet formula execution.

The coordinate view sorts by `seqid`, `start_1`, then native `gene_id`; G-C increments require finite nonnegative integer counts. Missing counts are excluded and reported, never replaced by zero or an unrelated score. The displayed overview is aggregated, while exact window/page and complete downloads retain native records.

## Regression execution

Use `backend.config.settings_sequence_viz_test` for Django tests. It uses a separate test database and isolated artifact root; never point fixture tests at the production database. Run all `test_sequence_viz_*` modules and the existing Proteome, Compare Core, species-atlas and feature-export regression modules before publishing application changes.

The actual browser suite is in `frontend/e2e/sequence-viz`. Start the dedicated read-only backend on 8007 from the project root:

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8007 --settings backend.config.settings_sequence_viz_browser --noreload
```

From `frontend`, start the independent development server in a second terminal and run tests in a third terminal:

```powershell
node node_modules/vite/bin/vite.js --configLoader native --config e2e/sequence-viz/vite.config.mjs
```

```powershell
node node_modules/@playwright/test/cli.js test --config e2e/sequence-viz/playwright.config.mjs
```

Both feature flags are enabled in the read-only backend settings.

The suite requires the default eight species to be prepared in both scopes. It checks complete chart positions, all Core atlas pages, real member/entity links, coordinate windows, relationship isolation, network exports, responsive widths, rapid navigation, original related pages and real SVG/4x PNG downloads. Chromium must be installed; the supplied acceptance configuration targets the deployed Windows Chrome path. Keep test-server lifecycle external so an interrupted test does not terminate a user's existing platform server.

Close only processes started for acceptance after finishing. Preserve user-owned production services and immutable backups.
