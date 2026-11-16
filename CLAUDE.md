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
tests/         pytest, fixtures under tests/fixtures
data/          gitignored except data/sample