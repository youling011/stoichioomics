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
the dependencies declared in `requirements.txt`. Optional HVG dependencies are
declared in `requirements-hvg.txt` and `environment-hvg.yml`.

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

Dependency declarations are archived as authored: `requirements.txt` requests
Django >=5.1,<6.1, whereas `requirements-hvg-research-lock.txt` pins Django 4.2.29.
These files cannot be installed together unchanged. This source archive does not
resolve that pre-existing environment/version conflict or promise a clean install.

The existing frontend scientific tests refer to two real-data `.json.gz` fixtures
under `frontend/tests/{proteome,integration}/fixtures/`. Those computed data
artifacts are excluded from this code-only release; tests requiring them need
separately supplied local fixtures. The 12-row backend CSV and short test-selection
lists are retained as small regression-test inputs. Browser tests also require a
separately configured backend and the relevant data; generated reports and browser
artifacts are excluded.
