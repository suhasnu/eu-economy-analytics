"""Generate dbt seeds from the config and the raw Eurostat responses.

eurostat_code_labels.csv  dimension, code, label  (labels come only in the raw JSON-stat)
indicator_headlines.csv   one row per dataset naming its headline series in staging terms
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pyarrow.parquet as pq

from src.ingest.eurostat import load_indicators

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
SEED_DIR = Path("dbt/seeds")
# Columns that are not breakdown dimensions. s_adj becomes adjustment_code in staging.
NON_BREAKDOWN = {"indicator_code", "geo", "time", "value", "unit", "s_adj", "status"}
# HICP is published unadjusted and carries no s_adj dimension; staging uses the same default.
DEFAULT_ADJUSTMENT = "NSA"


def latest_raw(code: str, raw_dir: Path = RAW_DIR) -> Path:
    stamped = re.compile(rf"{re.escape(code)}_\d{{8}}T\d{{6}}Z\.json")
    files = sorted(f for f in raw_dir.glob(f"{code}_*.json") if stamped.fullmatch(f.name))
    if not files:
        raise FileNotFoundError(f"no raw response for {code} under {raw_dir}")
    return files[-1]


def breakdown_dims(parquet: Path) -> list[str]:
    """Breakdown dimensions in the fixed alphabetical order the staging models also use."""
    return sorted(c for c in pq.read_schema(parquet).names if c not in NON_BREAKDOWN)


def code_labels(indicators: dict[str, dict], raw_dir: Path = RAW_DIR) -> list[tuple[str, str, str]]:
    labels: dict[tuple[str, str], str] = {}
    for entry in indicators.values():
        payload = json.loads(latest_raw(entry["code"], raw_dir).read_text(encoding="utf-8"))
        for dim in payload["id"]:
            if dim in ("time", "freq"):
                continue
            for code, label in payload["dimension"][dim]["category"].get("label", {}).items():
                labels.setdefault((dim, code), label)
    return sorted((d, c, label) for (d, c), label in labels.items())


def headlines(indicators: dict[str, dict], processed_dir: Path = PROCESSED_DIR) -> list[dict]:
    rows = []
    for name, entry in indicators.items():
        head = entry["headline"]
        dims = breakdown_dims(processed_dir / f"{entry['code']}.parquet")
        rows.append({
            "dataset_name": name,
            "indicator_code": entry["code"],
            "indicator_label": entry["label"],
            "headline_unit_code": head["unit"],
            "headline_adjustment_code": head.get("s_adj", DEFAULT_ADJUSTMENT),
            "headline_breakdown_code": "|".join(f"{d}={head[d]}" for d in dims),
        })
    return rows


def main() -> None:
    indicators = load_indicators()
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    with (SEED_DIR / "eurostat_code_labels.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dimension", "code", "label"])
        w.writerows(code_labels(indicators))
    rows = headlines(indicators)
    with (SEED_DIR / "indicator_headlines.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {SEED_DIR}/eurostat_code_labels.csv and {SEED_DIR}/indicator_headlines.csv")


if __name__ == "__main__":
    main()
