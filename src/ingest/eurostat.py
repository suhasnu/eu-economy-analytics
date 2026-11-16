"""Eurostat dissemination API (JSON-stat 2.0) ingestion."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import pandas as pd
import requests

from src.schemas.observations import ObservationSchema

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
ALWAYS_KEPT = ("geo", "time", "unit")


def fetch_dataset(
    code: str, filters: dict[str, str | list[str]] | None = None, raw_dir: Path | None = None
) -> dict:
    """Return the JSON-stat payload; if raw_dir is given, also write the response bytes unchanged."""
    params = {"format": "JSON", "lang": "EN", **(filters or {})}
    resp = requests.get(f"{BASE_URL}/{code}", params=params, timeout=60)
    resp.raise_for_status()
    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        tag = "_".join(f"{k}-{'+'.join(v) if isinstance(v, list) else v}" for k, v in sorted((filters or {}).items()))
        (raw_dir / f"{code}_{tag}_{stamp}.json".replace("__", "_")).write_bytes(resp.content)
    return resp.json()


def parse_jsonstat(payload: dict, indicator_code: str | None = None) -> pd.DataFrame:
    """Flatten a JSON-stat 2.0 dataset to one row per observation."""
    dim_ids: list[str] = payload["id"]
    sizes: list[int] = payload["size"]
    codes_per_dim = []
    for d in dim_ids:
        index = payload["dimension"][d]["category"]["index"]
        codes_per_dim.append(sorted(index, key=index.get))

    values = payload.get("value", {})
    statuses = payload.get("status", {})
    # The API may return value/status as dense lists instead of sparse dicts.
    if isinstance(values, list):
        values = {str(i): v for i, v in enumerate(values) if v is not None}
    if isinstance(statuses, list):
        statuses = {str(i): s for i, s in enumerate(statuses) if s is not None}

    # Only positions carrying a value or a status flag; the rest are absent from the source.
    positions = sorted({int(k) for k in values} | {int(k) for k in statuses})

    # Row-major strides: last dimension varies fastest.
    strides = [1] * len(sizes)
    for i in range(len(sizes) - 2, -1, -1):
        strides[i] = strides[i + 1] * sizes[i + 1]

    records = []
    for pos in positions:
        row = {d: codes_per_dim[i][(pos // strides[i]) % sizes[i]] for i, d in enumerate(dim_ids)}
        row["value"] = values.get(str(pos))
        row["status"] = statuses.get(str(pos))
        records.append(row)

    varying = [d for d, n in zip(dim_ids, sizes) if n > 1 and d not in ALWAYS_KEPT]
    columns = ["indicator_code", "geo", "time", "value", "unit", *varying, "status"]
    df = pd.DataFrame.from_records(records, columns=[*dim_ids, "value", "status"])
    df["indicator_code"] = indicator_code or payload.get("extension", {}).get("id")
    df["value"] = df["value"].astype("float64")
    return ObservationSchema.validate(df[columns].reset_index(drop=True))


def ingest(code: str, filters: dict[str, str | list[str]], data_dir: Path = Path("data")) -> pd.DataFrame:
    payload = fetch_dataset(code, filters, raw_dir=data_dir / "raw")
    df = parse_jsonstat(payload, indicator_code=code)
    out = data_dir / "processed" / f"{code}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


if __name__ == "__main__":
    result = ingest("une_rt_m", {"geo": "DE"})
    print(f"{len(result)} rows")
    print(result.head())
