"""Mirror the BigQuery raw tables into a local DuckDB file so the dbt project can run offline."""

from __future__ import annotations

import os
from pathlib import Path

import duckdb

from src.load.tables import column_types, raw_tables

DB_PATH = Path("data/local/warehouse.duckdb")
DUCKDB_TYPES = {"STRING": "VARCHAR", "FLOAT64": "DOUBLE"}


def main(db_path: Path = DB_PATH, schema: str | None = None) -> None:
    # Same default as the dbt source, so the local target reads what this writes.
    schema = schema or os.environ.get("BQ_RAW_DATASET", "raw")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(f"create schema if not exists {schema}")
    for name, parquet in raw_tables().items():
        cols = ", ".join(f"{c} {DUCKDB_TYPES[t]}" for c, t in column_types(parquet))
        con.execute(f"create or replace table {schema}.{name} ({cols})")
        con.execute(f"insert into {schema}.{name} by name select * from read_parquet(?)", [str(parquet)])
        print(f"{schema}.{name}: {con.execute(f'select count(*) from {schema}.{name}').fetchone()[0]} rows")
    con.close()


if __name__ == "__main__":
    main()
