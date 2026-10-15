# PostgreSQL import and advanced search

This package now includes a real ORM schema for the stoichiometric registry.

Core tables:
- `Species`
- `OmicsDataset`
- `FeatureFile`
- `AnalysisArtifact`
- `GeneIndex`
- `TranscriptIndex`
- `ProteinIndex`
- `EntityRecord`

## Recommended PostgreSQL bootstrap

1. Start PostgreSQL.

```bash
docker compose -f docker-compose.postgres.yml up -d
```

2. Export environment variables.

```bash
cp .env.postgres.example .env
# then load the variables in your shell
```

3. Install Python dependencies and migrate.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
```

4. Import the staged two-species case into database tables.

```bash
python manage.py import_stoichdb_pipeline \
  --pipeline-root data/feature_table_case/pipeline_outputs \
  --flush
```

5. Start backend and frontend.

```bash
python manage.py runserver
cd frontend
npm install
npm run dev
```

## What is actually database-backed now

The site no longer needs to read only `index.json` and per-species JSON blobs.
When the stoichdb tables are populated, the API is served from ORM-backed tables:

- platform home statistics
- species list and species detail
- advanced species filtering
- cross-species compare
- entity search
- row-level browsing and row detail
- summary and analysis payload retrieval

File-based registry loading remains available as a fallback if the tables are empty.

## Advanced search and filter features

Species-level filters:
- free-text query
- domain
- clade text
- habitat text
- omics branch presence
- `has_all_omics`
- genome size min/max
- fingerprint range filters
- sort controls

Entity-level filters:
- row text query
- strategy cluster
- numeric feature range filters
- sortable feature columns

## Scaling to many species later

For a larger import, keep the same staged pipeline and replace the source bundle with more species.
The import workflow remains:

1. build stage outputs from feature tables
2. import species/datasets/files/indexes/rows/artifacts into PostgreSQL
3. serve the frontend from those database tables

The current schema is therefore directly reusable for future large real registries.
