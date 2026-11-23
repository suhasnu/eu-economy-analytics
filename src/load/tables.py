"""Which processed parquet goes to which raw table, and its column types."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from src.ingest.eurostat import load_indicators
from src.ingest.regionalstatistik import DEFAULT_TABLE as REGIONAL_TABLE

PROCESSED_DIR = Path("data/processed")


def raw_tables(processed_dir: Path = PROCESSED_DIR) -> dict[str, Path]:
    """raw_<name> -> parquet path, for every configured Eurostat indicator plus the Regionalstatistik table."""
    tables = {f"raw_{name}": processed_dir / f"{e['code']}.parquet" for name, e in load_indicators().items()}
    tables["raw_regionalstatistik"] = processed_dir / f"{REGIONAL_TABLE}.parquet"
    return tables


def column_types(parquet: Path) -> list[tuple[str, str]]:
    """(column, 'STRING' | 'FLOAT64') from the parquet schema; anything else is a contract break."""
    out = []
    for field in pq.read_schema(parquet):
        if pa.types.is_string(field.type) or pa.types.is_large_string(field.type):
            out.append((field.name, "STRING"))
        elif pa.types.is_floating(field.type):
            out.append((field.name, "FLOAT64"))
        else:
            raise TypeError(f"{parquet.name}: column {field.name} has unexpected type {field.type}")
    return out
