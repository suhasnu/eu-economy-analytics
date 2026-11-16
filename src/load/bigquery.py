"""Load processed parquet into BigQuery raw tables.

Needs BQ_PROJECT and BQ_RAW_DATASET; BQ_LOCATION defaults to EU.
Credentials come from Application Default Credentials
(gcloud auth application-default login, or GOOGLE_APPLICATION_CREDENTIALS).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from google.cloud import bigquery

from src.load.tables import PROCESSED_DIR, column_types, raw_tables


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"environment variable {name} is not set")
    return value


def load_table(client: bigquery.Client, table_id: str, parquet: Path) -> int:
    schema = [
        bigquery.SchemaField(name, bq_type, mode="REQUIRED" if name in ("indicator_code", "geo", "time", "unit") else "NULLABLE")
        for name, bq_type in column_types(parquet)
    ]
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        schema=schema,
        autodetect=False,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    with parquet.open("rb") as fh:
        job = client.load_table_from_file(fh, table_id, job_config=job_config)
    job.result()
    return client.get_table(table_id).num_rows


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load data/processed parquet into BigQuery raw tables")
    parser.add_argument("--table", help="load only this raw_<name> table")
    args = parser.parse_args(argv)

    project, dataset = _env("BQ_PROJECT"), _env("BQ_RAW_DATASET")
    location = os.environ.get("BQ_LOCATION", "EU")
    client = bigquery.Client(project=project, location=location)
    client.create_dataset(bigquery.Dataset(f"{project}.{dataset}"), exists_ok=True)

    tables = raw_tables(PROCESSED_DIR)
    if args.table:
        tables = {args.table: tables[args.table]}
    for name, parquet in tables.items():
        rows = load_table(client, f"{project}.{dataset}.{name}", parquet)
        print(f"{project}.{dataset}.{name}: {rows} rows")


if __name__ == "__main__":
    main()
