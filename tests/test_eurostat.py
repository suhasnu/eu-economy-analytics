import json
import math
from pathlib import Path

import pandas as pd
import pandera.errors
import pytest

from src.ingest.eurostat import parse_jsonstat
from src.schemas.observations import ObservationSchema

FIXTURE = Path(__file__).parent / "fixtures" / "eurostat_jsonstat_sample.json"


@pytest.fixture
def parsed() -> pd.DataFrame:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_jsonstat(payload, indicator_code="une_rt_m")


def test_columns_keep_varying_dims_and_drop_constant(parsed):
    assert list(parsed.columns) == ["indicator_code", "geo", "time", "value", "unit", "sex", "status"]
    assert "freq" not in parsed.columns


def test_one_row_per_value_or_status_position(parsed):
    assert len(parsed) == 7


def test_positions_decode_using_category_index(parsed):
    def obs(unit, sex, time):
        rows = parsed[(parsed.unit == unit) & (parsed.sex == sex) & (parsed.time == time)]
        assert len(rows) == 1
        return rows.iloc[0]

    assert obs("PC_ACT", "T", "2026-10").value == 4.0
    assert obs("PC_ACT", "F", "2026-09").value == 3.6
    assert obs("THS_PER", "T", "2026-09").value == 1700.0
    last = obs("THS_PER", "F", "2026-10")
    assert last.value == 720.0 and last.status == "p"


def test_status_only_position_has_null_value(parsed):
    row = parsed[parsed.status == "c"].iloc[0]
    assert (row.unit, row.sex, row.time) == ("PC_ACT", "F", "2026-10")
    assert math.isnan(row.value)


def test_indicator_and_geo_populated(parsed):
    assert (parsed.indicator_code == "une_rt_m").all()
    assert (parsed.geo == "DE").all()


def test_schema_rejects_null_geo():
    df = pd.DataFrame(
        {"indicator_code": ["une_rt_m"], "geo": [None], "time": ["2026-10"], "value": [3.9], "unit": ["PC_ACT"]}
    )
    with pytest.raises(pandera.errors.SchemaError):
        ObservationSchema.validate(df)
