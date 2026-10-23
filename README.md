# Stoichioomics

Source-only snapshot of the active Stoichioomics platform: Django/DRF backend,
Vue 3/Vite frontend, PostgreSQL schema migrations, analysis engines, feature
extractors, data-ingestion utilities, and platform release builders.

本仓库保存当前平台所需的代码、算法、数据库迁移和配置模板。
不包含生产数据库、大型组学文件、用户上传、已计算结果或探索性案例数据。
这是代码归档版本，不是开箱即用的完整数据平台分发包。

## Layout

| Path | Contents |
| --- | --- |
| `backend/` | API, models/migrations, analysis engines, validation, existing tests |
| `frontend/` | Vue pages/components, SVG assets, Vite config and npm lockfile |
| `scripts/` | Platform ingestion, analysis, indexing, release and validation utilities |
| `tools/feature_extractors/` | Genome, transcriptome and proteome extraction algorithms |
| `tools/phylo-tools.Dockerfile` | Optional phylogenetic tool environment |
| `shared/schemas/` | Runtime feature registries and display contracts |
| `configs/templates/` | Input sample-sheet format templates |
| `docs/`, `shared/docs/` | Selected technical and release contracts |
| `SOURCE_MANIFEST.json` | Exported file hashes, original locations, and sanitization reasons |

## Configuration

Use Python 3.11 and Node.js with npm. Copy `.env.example` to `.env` in the project
root, set your own PostgreSQL connection values and Django secret, and install
the dependencies declared in the unified `requirements.txt`. The legacy HVG
entry points and `environment-hvg.yml` refer to that same manifest.

Run commands from the repository root. The root environment template sets
`STOICH_FEATURE_EXTRACTOR_ROOT=tools/feature_extractors` so the unchanged backend
can locate the three bundled extractor modules. Use an absolute local path if
starting the backend from a different working directory. Django reads the root
`.env`; `backend/.env.example` is retained only as an existing module template.

`docker-compose.postgres.yml` describes PostgreSQL 16 using a named volume and
reads its password from your local environment. The `.docker.yml` and
`.gdrive.yml` variants retain the original deployment-specific storage choices;
they are alternatives, not files to run together. The `.docker.yml` variant
expects an existing external volume; the `.gdrive.yml` variant requires editing
the host data-directory mount for another machine. No volume data is included.

## Code setup reference

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env with private values before starting services.
docker compose -f docker-compose.postgres.yml up -d
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

In a separate terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

These are setup references, not a claim that the production platform can be
recreated from code alone. Database-backed pages and analysis/download workflows
need separately provisioned data. Many ingestion and release scripts retain
their original local paths and require review before execution elsewhere.
In particular, do not run database migration/flush or release-generation scripts
against an existing deployment without inspecting their arguments.

## Snapshot scope

The original `proj` is the sole platform source. The three extractor modules
were copied from the adjacent feature-extractor code directory because the
backend loads them at runtime. Core application and algorithm code was copied
byte-for-byte, except for removal of hardcoded credential defaults. Changes and
file origins are recorded in `SOURCE_MANIFEST.json`.

Excluded: PostgreSQL and SQLite databases/backups, raw/feature datasets, generated
case artifacts, toy configuration bundles, uploaded files, runtime/workspace
outputs, dependency environments, build output, report-writing scripts, Word
documents, discussion/optimization reports, and the old README's bundled-demo
instructions. Formal case/release **builder code** remains because current API
modules and tests reference it; the corresponding case **data** is excluded.

No license was inferred or added by this source export.

## Optimization snapshot — 2026-10-23

This update preserves the unified HVG research workflow, Core comparison runs,
and proteome/genome/transcriptome/cross-omics visualizations from the active
platform. It includes the new database migration, runtime figure/field contracts,
frontend test scripts and end-to-end test configuration, optional requirement
files, and the corresponding operational documentation. No production data or
precomputed visualization payloads are shipped.

`HVG_RESEARCH_ENABLED=1` in the environment templates preserves the active
platform's non-secret feature switch. Existing source and algorithms are not
refactored by this export. Local paths in documented case configurations remain
as authored and refer to datasets that are not included.

The previous dependency conflict was resolved in the 2026-10-24 snapshot.
`requirements.txt` is now the single authoritative exact-pin manifest, including
Django 5.2.18. The three legacy requirement entry points include that same file.
`scripts/verify_dependencies.py` checks the installed interpreter against it;
`deploy/requirements-production.txt` additionally pins uWSGI on Linux.

The existing frontend scientific tests refer to two real-data `.json.gz` fixtures
under `frontend/tests/{proteome,integration}/fixtures/`. Those computed data
artifacts are excluded from this code-only release; tests requiring them need
separately supplied local fixtures. The 12-row backend CSV and short test-selection
lists are retained as small regression-test inputs. Browser tests also require a
separately configured backend and the relevant data; generated reports and browser
artifacts are excluded.

## Dependency and deployment snapshot — 2026-10-24

This optimization commit archives the authored dependency unification and
deployment adaptation. It includes the opt-in production settings/URL overlay,
readiness endpoint, explicit environment-file loading, Nginx/uWSGI/systemd
templates, configuration renderer, read-only preflight tool, isolated validation
helpers, and their regression tests. Lifecycle, atomic JSON/cache, portable path
checks and adjacent-float histogram fixes are copied from the active source.

See [`deploy/README.md`](deploy/README.md). The templates require target-specific
Linux paths, a domain, certificates and a private environment file outside the
repository. `deploy/production.env.example` contains placeholders only. The
renderer writes configuration files; this archive operation does not install,
start or restart services, provision certificates, or migrate any database.

`DJANGO_SETTINGS_MODULE=backend.config.settings_production` explicitly selects
the production overlay. `DJANGO_ENV_FILE` selects a private environment file;
production defaults prevent accidental loading of the development `.env`.
Set `STOICH_FEATURE_EXTRACTOR_ROOT` to the absolute installed location of this
repository's `tools/feature_extractors` directory when using production settings.

Deployment evidence/logs, local environment manifests, upgrade audit reports,
private configurations, generated service files, database contents and real
data fixtures are excluded. The included validation helper code is synthetic
test infrastructure. No Linux service deployment or full production-data
reproduction is implied by this source archive.
