import argparse
from datetime import date

import pandas as pd
import pandera.errors
import pytest

from src.load.export_headline import build_query, parse_month, write_csv
from src.schemas.exports import HeadlineExportSchema


def _rows(**overrides):
    row = {
        "indicator": "HICP · All items",
        "geo_code": "DE",
        "geo_label": "Germany",
        "month_start_date": pd.Timestamp("2015-01-01"),
        "value": 1.5,
        "unit_short_label": "% y/y",
        "status": None,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_parse_month():
    assert parse_month("2015-01") == date(2015, 1, 1)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_month("2015")


def test_query_reads_model_columns_and_parameterises_since():
    sql = build_query("proj", "analytics_marts")
    assert "`proj.analytics_marts`.dim_series" in sql
    assert "s.unit_short_label" in sql
    assert "@since" in sql
    assert "code_short_labels" not in sql


def test_schema_rejects_duplicate_dataset_geo_month():
    df = pd.concat([_rows(), _rows(value=2.0)], ignore_index=True)
    with pytest.raises(pandera.errors.SchemaError):
        HeadlineExportSchema.validate(df)


def test_schema_rejects_mid_month_date():
    with pytest.raises(pandera.errors.SchemaError):
        HeadlineExportSchema.validate(_rows(month_start_date=pd.Timestamp("2015-01-15")))


def test_csv_writes_iso_dates_and_empty_status(tmp_path):
    out = tmp_path / "nested" / "headline.csv"
    write_csv(HeadlineExportSchema.validate(_rows()), out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "indicator,geo_code,geo_label,month_start_date,value,unit_short_label,status"
    assert lines[1] == "HICP · All items,DE,Germany,2015-01-01,1.5,% y/y,"
