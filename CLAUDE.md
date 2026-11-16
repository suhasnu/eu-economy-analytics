# EU Economy Analytics

Eurostat and Destatis economic indicators, landed to parquet, modelled in
BigQuery with dbt, surfaced in Power BI and Excel.

## Conventions
- Python 3.11+, requests, pandas, pyarrow, pandera, pytest
- Raw API responses land unchanged under data/raw, parsed output under data/processed
- Every ingestion function returns a DataFrame validated by a Pandera schema
- Comments only where a decision is not obvious from the code
- No secrets in the repo, tokens come from the environment

## Layout
src/ingest/    one module per source
src/schemas/   Pandera schemas
src/load/      BigQuery loader, local DuckDB mirror, dbt seed generator
configs/       indicators.yml, the datasets to ingest
dbt/           dbt project, staging and star schema marts
tests/         pytest, fixtures under tests/fixtures
data/          gitignored except data/sample