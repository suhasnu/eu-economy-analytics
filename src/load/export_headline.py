"""Export the headline series from the BigQuery marts to CSV for the web dashboard.

One row per dataset, geography and month. Needs BQ_PROJECT; BQ_DBT_DATASET
defaults to analytics and BQ_LOCATION to EU, matching dbt/profiles.yml.
Credentials come from Application Default Credentials.
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

import pandas as pd
from google.cloud import bigquery

from src.schemas.exports import HeadlineExportSchema

DEFAULT_OUT = Path("data/exports/headline_series.csv")
DEFAULT_SINCE = "2015-01"


def build_query(project: str, marts_dataset: str) -> str:
    marts = f"`{project}.{marts_dataset}`"
    return f"""
select
    s.short_label as indicator,
    g.geo_code,
    g.geo_name as geo_label,
    d.month_start_date,
    f.value,
    s.unit_short_label,
    f.status
from {marts}.fct_observation as f
inner join {marts}.dim_series as s on s.series_key = f.series_key
inner join {marts}.dim_geo as g on g.geo_key = f.geo_key
inner join {marts}.dim_date as d on d.date_key = f.date_key
where s.is_headline
  and d.month_start_date >= @since
order by s.dataset_name, g.geo_code, d.month_start_date
"""


def parse_month(text: str) -> date:
    try:
        year, month = (int(part) for part in text.split("-"))
        return date(year, month, 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM, got {text!r}") from exc


def fetch_headline(client: bigquery.Client, project: str, marts_dataset: str, since: date) -> pd.DataFrame:
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("since", "DATE", since)]
    )
    df = client.query(build_query(project, marts_dataset), job_config=job_config).to_dataframe()
    return HeadlineExportSchema.validate(df)


def write_csv(df: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, date_format="%Y-%m-%d")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export headline series from BigQuery to CSV")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output CSV (default {DEFAULT_OUT})")
    parser.add_argument(
        "--since", type=parse_month, default=parse_month(DEFAULT_SINCE),
        help=f"first month to include, YYYY-MM (default {DEFAULT_SINCE})",
    )
    args = parser.parse_args(argv)

    project = os.environ.get("BQ_PROJECT")
    if not project:
        raise SystemExit("environment variable BQ_PROJECT is not set")
    # dbt appends the +schema config to the target dataset: <dataset>_marts.
    marts_dataset = f"{os.environ.get('BQ_DBT_DATASET', 'analytics')}_marts"
    client = bigquery.Client(project=project, location=os.environ.get("BQ_LOCATION", "EU"))

    df = fetch_headline(client, project, marts_dataset, args.since)
    write_csv(df, args.out)
    print(f"{args.out}: {len(df)} rows, {args.out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
