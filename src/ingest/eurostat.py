"""Eurostat dissemination API (JSON-stat 2.0) ingestion."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml

from src.schemas.observations import ObservationSchema

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
CONFIG_PATH = Path("configs/indicators.yml")
REQUIRED_KEYS = ("name", "code", "label", "short_label", "filters", "headline")
ALWAYS_KEPT = ("geo", "time", "unit")

Filters = dict[str, str | list[str]]


def load_indicators(path: Path = CONFIG_PATH) -> dict[str, dict]:
    """Return config entries keyed by name, with the shared geo list merged into each filter set."""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = {}
    for entry in config["indicators"]:
        missing = [k for k in REQUIRED_KEYS if k not in entry]
        if missing:
            raise ValueError(f"indicator {entry.get('name', '?')} is missing {missing}")
        entry["filters"] = {"geo": config["geo"], **entry["filters"]}
        entries[entry["name"]] = entry
    return entries


def fetch_dataset(code: str, filters: Filters | None = None, raw_dir: Path | None = None) -> dict:
    """Return the JSON-stat payload; if raw_dir is given, also write the response bytes unchanged."""
    params = {"format": "JSON", "lang": "EN", **(filters or {})}
    resp = requests.get(f"{BASE_URL}/{code}", params=params, timeout=120)
    resp.raise_for_status()
    if raw_dir is not None:
        raw_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (raw_dir / f"{code}_{stamp}.json").write_bytes(resp.content)
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"{code}: {payload['error']}")
    return payload


def check_filters(payload: dict, filters: Filters) -> list[str]:
    """List filter dimensions or codes the API did not return; Eurostat drops unknown codes silently."""
    problems = []
    for dim, wanted in filters.items():
        if dim not in payload["dimension"]:
            problems.append(f"dimension {dim!r} not in response (has {payload['id']})")
            continue
        returned = payload["dimension"][dim]["category"]["index"]
        absent = [c for c in ([wanted] if isinstance(wanted, str) else wanted) if c not in returned]
        if absent:
            problems.append(f"{dim}: requested {absent} not returned")
    return problems


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


def headline_rows(df: pd.DataFrame, headline: dict[str, str]) -> pd.DataFrame:
    """Rows of the headline series. A headline key whose column was dropped was constant in the response."""
    mask = pd.Series(True, index=df.index)
    for dim, code in headline.items():
        if dim in df.columns:
            mask &= df[dim] == code
    return df[mask]


def ingest(entry: dict, data_dir: Path = Path("data")) -> pd.DataFrame:
    code = entry["code"]
    payload = fetch_dataset(code, entry["filters"], raw_dir=data_dir / "raw")
    for problem in check_filters(payload, entry["filters"]):
        print(f"WARNING {entry['name']} ({code}): {problem}", file=sys.stderr)
    df = parse_jsonstat(payload, indicator_code=code)
    out = data_dir / "processed" / f"{code}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def main(argv: list[str] | None = None) -> None:
    indicators = load_indicators()
    parser = argparse.ArgumentParser(description="Ingest Eurostat indicators from configs/indicators.yml")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--indicator", choices=sorted(indicators))
    group.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)

    names = list(indicators) if args.all else [args.indicator]
    for name in names:
        df = ingest(indicators[name])
        extra = [c for c in df.columns if c not in ObservationSchema.columns]
        print(f"{name:<22} {indicators[name]['code']:<14} {len(df):>7} rows  extra dims: {extra}")


if __name__ == "__main__":
    main()
