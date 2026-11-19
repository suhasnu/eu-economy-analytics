import pandas as pd
import pytest

from src.load.duckdb_local import DB_PATH
from src.report.extract import build_query, fetch_briefing_frame

pytestmark = pytest.mark.skipif(
    not DB_PATH.exists(), reason="local DuckDB mirror not built; run dbt build --target local"
)


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("BQ_PROJECT", raising=False)
        mp.delenv("BQ_DBT_DATASET", raising=False)
        return fetch_briefing_frame()


def test_covers_five_indicators_and_six_geos(frame):
    assert frame["indicator_label"].nunique() == 5
    assert frame["geo_code"].nunique() == 6


def test_month_is_first_of_month(frame):
    assert (frame["month"].dt.day == 1).all()


def test_one_row_per_geo_indicator_month(frame):
    assert not frame.duplicated(["geo_code", "indicator_label", "month"]).any()


def test_unit_kind_never_null(frame):
    assert frame["unit_kind"].notna().all()


def test_window_is_36_months_ending_at_latest_month(frame):
    months = frame["month"].drop_duplicates()
    assert len(months) == 36
    assert months.min() == months.max() - pd.DateOffset(months=35)


def test_window_follows_months_argument(monkeypatch):
    monkeypatch.delenv("BQ_PROJECT", raising=False)
    monkeypatch.delenv("BQ_DBT_DATASET", raising=False)
    assert fetch_briefing_frame(months=12)["month"].nunique() == 12


def test_one_query_serves_both_targets():
    bq = build_query("`proj.analytics_marts`", "@months")
    local = build_query("analytics_marts", "$months")
    assert bq.replace("`proj.analytics_marts`", "M").replace("@months", "P") == local.replace(
        "analytics_marts", "M"
    ).replace("$months", "P")
