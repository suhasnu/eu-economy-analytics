"""Pull the headline series the monthly Excel briefing needs out of the dbt marts.

Runs against BigQuery when BQ_PROJECT and BQ_DBT_DATASET are set (BQ_LOCATION
defaults to EU), otherwise against the local DuckDB mirror that
`dbt build --target local` writes to data/local/warehouse.duckdb.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import duckdb
import pandas as pd
from google.cloud import bigquery

from src.load.duckdb_local import DB_PATH
from src.schemas.exports import BriefingSchema

DEFAULT_OUT = Path("build/briefing_data.csv")
# dbt appends the +schema config to the target schema; the local profile's target schema is analytics.
LOCAL_MARTS = "analytics_marts"

# {marts} and {months} are filled per target: the qualified dataset and the dialect's
# parameter marker. Months are compared as year * 12 + month because the two dialects
# disagree on date interval arithmetic (DuckDB's date_sub returns a difference, not a date).
QUERY = """
with headline as (
    select
        g.geo_code,
        g.geo_name,
        s.indicator_label,
        s.unit_kind,
        s.unit_short_label,
        d.month_start_date as month,
        extract(year from d.month_start_date) * 12 + extract(month from d.month_start_date) as month_index,
        f.value
    from {marts}.fct_observation as f
    inner join {marts}.dim_series as s on s.series_key = f.series_key
    inner join {marts}.dim_geo as g on g.geo_key = f.geo_key
    inner join {marts}.dim_date as d on d.date_key = f.date_key
    where s.is_headline
      and f.value is not null
)

select geo_code, geo_name, indicator_label, unit_kind, unit_short_label, month, value
from headline
where month_index > (select max(month_index) from headline) - {months}
order by geo_code, indicator_label, month
"""


def build_query(marts: str, months_param: str) -> str:
    return QUERY.format(marts=marts, months=months_param)


def _bigquery_frame(project: str, dbt_dataset: str, months: int) -> pd.DataFrame:
    client = bigquery.Client(project=project, location=os.environ.get("BQ_LOCATION", "EU"))
    sql = build_query(f"`{project}.{dbt_dataset}_marts`", "@months")
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("months", "INT64", months)]
    )
    return client.query(sql, job_config=job_config).to_dataframe()


def _duckdb_frame(db_path: Path, months: int) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} not found; run `dbt build --target local` from dbt/")
    with duckdb.connect(str(db_path), read_only=True) as con:
        return con.execute(build_query(LOCAL_MARTS, "$months"), {"months": months}).df()


def fetch_briefing_frame(months: int = 36) -> pd.DataFrame:
    """Headline series per geo and month for the `months` months up to the latest month in the data.

    The window ends at the latest month any headline series has, not today, so a series
    that publishes later than the others has one or two fewer months in the frame.
    """
    if months < 1:
        raise ValueError(f"months must be at least 1, got {months}")
    project, dbt_dataset = os.environ.get("BQ_PROJECT"), os.environ.get("BQ_DBT_DATASET")
    if project and dbt_dataset:
        df = _bigquery_frame(project, dbt_dataset, months)
    else:
        df = _duckdb_frame(DB_PATH, months)
    return BriefingSchema.validate(df)


def write_csv(df: pd.DataFrame, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, date_format="%Y-%m-%d")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Extract the monthly briefing data from the dbt marts to CSV")
    parser.add_argument("--months", type=int, default=36, help="months of history up to the latest (default 36)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output CSV (default {DEFAULT_OUT})")
    args = parser.parse_args(argv)

    df = fetch_briefing_frame(args.months)
    write_csv(df, args.out)
    print(f"{args.out}: {len(df)} rows, {df['month'].min():%Y-%m} to {df['month'].max():%Y-%m}")


if __name__ == "__main__":
    main()
