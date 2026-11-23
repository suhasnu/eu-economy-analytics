import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import pandera.errors
import pytest

from src.ingest import regionalstatistik as rs
from src.schemas.observations import ObservationSchema
from src.schemas.regionalstatistik import REGION_LEVELS, RegionalObservationSchema

TABLE = "13211-02-05-4-B"
FIXTURES = Path(__file__).parent / "fixtures" / "regionalstatistik"
METADATA = FIXTURES / f"{TABLE}_metadata.json"

HEADER = (
    "statistics_code;statistics_label;time_code;time_label;time;1_variable_code;1_variable_label;"
    "1_variable_attribute_code;1_variable_attribute_label;2_variable_code;2_variable_label;"
    "2_variable_attribute_code;2_variable_attribute_label;value;value_unit;value_variable_code;value_variable_label"
)

CONTAINED_CODES = {
    "03241001", "05334002", "10041100",
    "11001001", "11002002", "11003003", "11004004", "11005005", "11006006",
    "11007007", "11008008", "11009009", "11010010", "11011011", "11012012",
}


def fixture_bytes(level: str) -> bytes:
    return (FIXTURES / f"{TABLE}_2024_{level}_ffcsv.zip").read_bytes()


def make_zip(*rows: str) -> bytes:
    body = "﻿" + "\n".join([HEADER, *rows]) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("t_flat.csv", body.encode("utf-8"))
    return buf.getvalue()


def row(code: str, value: str, level: str = "KREISE", year: int = 2024, series: str = "ERWP06",
        unit: str = "Anzahl") -> str:
    return (
        f"13211;Arbeitsmarktstatistik;JAHR;Jahr;{year};{level};label;{code};Region {code};"
        f";;;;{value};{unit};{series};label"
    )


@pytest.fixture(scope="module")
def kreise_parsed() -> pd.DataFrame:
    return rs.parse_ffcsv(fixture_bytes("KREISE"), "KREISE")


@pytest.fixture(scope="module")
def tidy() -> dict[str, pd.DataFrame]:
    return {level: rs.tidy(fixture_bytes(level), level) for level in rs.LEVELS}


def headline_value(df: pd.DataFrame, geo: str, code: str = "ERWP06") -> float:
    rows = df[(df.geo == geo) & (df.indicator_code == code)]
    assert len(rows) == 1
    return rows["value"].iloc[0]


def test_summing_districts_does_not_reproduce_the_published_national_count(tidy):
    """Summing a lower level does not give the published aggregate, so no level is ever derived from another.

    2024 unemployed, annual average: the 400 districts add up to 2,787,125, while the published national row
    says 2,787,112. The 13 come from each level being averaged and rounded on its own. The project rule is
    to take every level from its own published request and never sum one into another.
    """
    district_sum = rs.headline(tidy["KREISE"])["value"].sum()
    national = headline_value(tidy["DINSG"], "DG")
    assert district_sum == 2_787_125
    assert national == 2_787_112
    assert district_sum != national
    assert district_sum - national == 13


def test_naive_district_sum_also_double_counts_contained_rows(kreise_parsed):
    # Hannover, Aachen and Saarbrücken are counted again inside their district rows.
    assert rs.headline(kreise_parsed)["value"].sum() == 2_839_529


def test_region_level_comes_from_the_request(tidy):
    assert {level: set(df["region_level"]) for level, df in tidy.items()} == {
        "DINSG": {"national"}, "DLAND": {"land"}, "KREISE": {"kreis"},
    }
    assert set(rs.LEVELS.values()) == set(REGION_LEVELS)


def test_regions_per_level(tidy):
    assert set(tidy["DINSG"]["geo"]) == {"DG"}
    assert set(tidy["DLAND"]["geo"]) == {f"{n:02d}" for n in range(1, 17)}
    assert tidy["KREISE"]["geo"].nunique() == 475
    for df in tidy.values():
        assert df["indicator_code"].nunique() == 13


def test_land_and_national_rates_are_the_published_values(tidy):
    land, national = tidy["DLAND"], tidy["DINSG"]
    assert headline_value(land, "09") == 285_234
    assert headline_value(land, "09", "ERWP09") == 4.0
    assert headline_value(land, "09", "ERWP10") == 3.7
    assert headline_value(land, "11", "ERWP10") == 9.7
    assert headline_value(national, "DG", "ERWP09") == 6.5
    assert headline_value(national, "DG", "ERWP10") == 6.0
    assert (land.loc[land.unit == "Prozent", "status"].isna()).all()


def test_code_length_disagreeing_with_request_fails():
    with pytest.raises(rs.RegionalstatistikError, match="do not fit the level"):
        rs.parse_ffcsv(make_zip(row("01001", "10", level="DLAND")), "DLAND")
    with pytest.raises(rs.RegionalstatistikError, match="do not fit the level"):
        rs.parse_ffcsv(make_zip(row("09", "10", level="KREISE")), "KREISE")


def test_response_level_disagreeing_with_request_fails():
    with pytest.raises(rs.RegionalstatistikError, match="requested regionalvariable DINSG"):
        rs.parse_ffcsv(make_zip(row("01", "10", level="DLAND")), "DINSG")


def test_unknown_level_rejected():
    with pytest.raises(ValueError, match="unknown regional level"):
        rs.tablefile_params(TABLE, 2024, "REGBEZ")


def test_contained_rows_are_excluded_explicitly(kreise_parsed, tidy):
    kept, excluded = rs.drop_contained_regions(kreise_parsed)
    assert set(excluded["geo"]) == CONTAINED_CODES
    assert not set(tidy["KREISE"]["geo"]) & CONTAINED_CODES
    assert len(kept) + len(excluded) == len(kreise_parsed)


def test_drop_contained_regions_is_for_kreise_only(tidy):
    with pytest.raises(ValueError, match="KREISE level only"):
        rs.drop_contained_regions(tidy["DLAND"])


def test_every_contained_code_has_its_district(kreise_parsed):
    kreise = set(kreise_parsed.loc[kreise_parsed.geo.str.len() == 5, "geo"])
    assert rs.containing_kreis("03241001", kreise) == "03241"
    assert rs.containing_kreis("11007007", kreise) == "11000"


def test_contained_code_without_district_fails():
    df = rs.parse_ffcsv(make_zip(row("01001", "10"), row("99999001", "5")), "KREISE")
    with pytest.raises(rs.RegionalstatistikError, match="no containing district"):
        rs.drop_contained_regions(df)


def test_codes_keep_leading_zeros(tidy):
    assert "01001" in set(tidy["KREISE"]["geo"])
    assert "01" in set(tidy["DLAND"]["geo"])


def test_decimal_comma(tidy):
    assert headline_value(tidy["KREISE"], "09473", "ERWP10") == 4.3


def test_dash_marks_codes_absent_that_year(tidy):
    salzwedel = tidy["KREISE"][tidy["KREISE"].geo == "15370"]
    assert len(salzwedel) == 13
    assert salzwedel["value"].isna().all()
    assert (salzwedel["status"] == "-").all()


def test_dot_marks_unknown_or_withheld(kreise_parsed):
    mitte = kreise_parsed[kreise_parsed.geo == "11001001"]
    assert mitte["value"].isna().all() and (mitte["status"] == ".").all()


def test_x_marks_blocked_cells_and_stays_distinct():
    kreise_2019 = rs.tidy((FIXTURES / f"{TABLE}_2019_KREISE_ffcsv.zip").read_bytes(), "KREISE")
    blocked = kreise_2019[kreise_2019["status"] == "x"]
    assert sorted(blocked["geo"]) == ["12062", "16065", "16068", "16069"]
    assert set(blocked["indicator_code"]) == {"ERWP10.ARBEITSQUO07"}
    assert blocked["value"].isna().all()
    assert kreise_2019["status"].value_counts().to_dict() == {"-": 962, "x": 4}


def test_markers_are_never_zero(kreise_parsed):
    marked = kreise_parsed[kreise_parsed["status"].notna()]
    assert marked["value"].isna().all()
    assert set(marked["status"]) == {"-", "."}
    assert kreise_parsed.loc[kreise_parsed["status"].isna(), "value"].notna().all()


def test_labels_are_the_published_ones(tidy):
    series = pd.concat(tidy.values()).drop_duplicates("indicator_code").set_index("indicator_code")
    assert series["series_label"].notna().all() and series["breakdown_label"].notna().all()
    # The two rates differ only in their denominator, and the published labels say so.
    assert series.loc["ERWP09", "series_label"] == "Arbeitslosenquote bez. abh. zivile Erwerbspers."
    assert series.loc["ERWP10", "series_label"] == "Arbeitslosenquote bez. auf alle zivile Erwerbsp."
    assert series.loc["ERWP10.ARBEITSQUO05", "breakdown_label"] == "Männer"
    assert series.loc["ERWP06.ARBEITSLOS05", "series_label"] == "Arbeitslose"
    no_breakdown = series[series["breakdown_code"].isna()]
    assert sorted(no_breakdown.index) == ["ERWP06", "ERWP09", "ERWP10"]
    assert (no_breakdown["breakdown_label"] == rs.TOTAL_BREAKDOWN_LABEL).all()


@pytest.mark.parametrize("column", ["series_label", "breakdown_label"])
def test_schema_rejects_missing_label(tidy, column):
    broken = tidy["DLAND"].copy()
    broken.loc[broken.index[0], column] = None
    with pytest.raises(pandera.errors.SchemaError):
        RegionalObservationSchema.validate(broken)


def test_series_key_includes_breakdown(tidy):
    kreise = tidy["KREISE"]
    erwp06 = kreise.loc[kreise.value_variable_code == "ERWP06", "indicator_code"]
    assert erwp06.nunique() == 7
    assert "ERWP06" in set(erwp06) and "ERWP06.ARBEITSLOS05" in set(erwp06)


def test_all_levels_together_fit_both_schemas(tidy):
    combined = RegionalObservationSchema.validate(pd.concat(tidy.values(), ignore_index=True))
    assert len(combined) == (1 + 16 + 475) * 13
    assert list(combined.columns) == list(RegionalObservationSchema.columns)
    ObservationSchema.validate(combined)


def test_unknown_marker_fails():
    with pytest.raises(rs.RegionalstatistikError, match="unrecognised value markers"):
        rs.parse_ffcsv(make_zip(row("01001", "/")), "KREISE")


def test_schema_rejects_value_beside_marker(tidy):
    broken = tidy["KREISE"].copy()
    broken.loc[broken.index[0], "status"] = "."
    broken.loc[broken.index[0], "value"] = 1.0
    with pytest.raises(pandera.errors.SchemaError):
        RegionalObservationSchema.validate(broken)


def test_schema_rejects_geo_that_does_not_match_level(tidy):
    broken = tidy["DLAND"].copy()
    broken["region_level"] = "kreis"
    with pytest.raises(pandera.errors.SchemaError):
        RegionalObservationSchema.validate(broken)


class FakeResponse:
    def __init__(self, content: bytes, content_type: str, status: int = 200):
        self.content = content
        self.status_code = status
        self.ok = status < 400
        self.headers = {"Content-Type": content_type}

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv("REGIO_USER", "user-xyz")
    monkeypatch.setenv("REGIO_PASSWORD", "secret-xyz")


def status_body(code: int, content: str, nested: bool = True) -> bytes:
    if not nested:
        # Shape of the real HTTP 404 answers: rejected login, and the application server being down.
        return json.dumps({"Code": code, "Content": content, "Type": "ERROR"}).encode()
    params = {"username": "********************", "password": "********************"}
    return json.dumps({"Status": {"Code": code, "Content": content}, "Parameter": params}).encode()


@pytest.mark.parametrize("level", list(rs.LEVELS))
def test_fetch_writes_zip_unchanged_and_sends_header_credentials(monkeypatch, tmp_path, credentials, level):
    calls = []
    content = fixture_bytes(level)

    def fake_post(url, headers, data, timeout):
        calls.append((url, headers, data))
        return FakeResponse(content, "application/zip")

    monkeypatch.setattr(rs.requests, "post", fake_post)
    path = rs.fetch_year(TABLE, 2024, level, tmp_path)
    assert path == tmp_path / "raw" / "regionalstatistik" / f"{TABLE}_2024_{level}.zip"
    assert path.read_bytes() == content
    url, headers, data = calls[0]
    assert headers["username"] == "user-xyz" and headers["password"] == "secret-xyz"
    assert "secret-xyz" not in url and "secret-xyz" not in json.dumps(data)
    assert data["regionalvariable"] == level
    assert data["startyear"] == data["endyear"] == "2024" and data["job"] == "false"


@pytest.mark.parametrize(
    "status, http, nested",
    [(98, 200, True), (2, 404, False), (15, 401, False), (15, 401, True)],
)
def test_status_errors_raise_without_credentials(monkeypatch, tmp_path, credentials, status, http, nested):
    body = status_body(status, "Fehler", nested)
    monkeypatch.setattr(rs.requests, "post", lambda *a, **k: FakeResponse(body, "application/json", http))
    with pytest.raises(rs.RegionalstatistikError, match=f"status {status}") as err:
        rs.fetch_year(TABLE, 2024, "KREISE", tmp_path)
    assert "secret-xyz" not in str(err.value) and "user-xyz" not in str(err.value)
    assert not list(tmp_path.rglob("*.zip"))


def test_missing_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("REGIO_USER", raising=False)
    monkeypatch.delenv("REGIO_PASSWORD", raising=False)
    with pytest.raises(rs.RegionalstatistikError, match="must be set"):
        rs.fetch_year(TABLE, 2024, "KREISE", tmp_path)


def test_latest_year_from_metadata(monkeypatch, credentials):
    monkeypatch.setattr(
        rs.requests, "post", lambda *a, **k: FakeResponse(METADATA.read_bytes(), "application/json")
    )
    assert rs.latest_year() == 2025


def test_ingest_skips_slices_already_in_raw(monkeypatch, tmp_path):
    codes = {"DINSG": ["DG"], "DLAND": ["01", "11"], "KREISE": ["01001", "11000", "11001001"]}

    def slice_zip(year: int, level: str) -> bytes:
        return make_zip(*(row(c, "10", level=level, year=year) for c in codes[level]))

    for level in rs.LEVELS:
        path = rs.raw_path(TABLE, 2023, level, tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(slice_zip(2023, level))

    def fake_fetch(t, year, level, data_dir):
        rs.raw_path(t, year, level, data_dir).write_bytes(slice_zip(year, level))

    monkeypatch.setattr(rs, "fetch_year", fake_fetch)
    df, fetched = rs.ingest(TABLE, 2023, 2024, tmp_path)
    assert fetched == [(2024, "DINSG"), (2024, "DLAND"), (2024, "KREISE")]
    assert sorted(df["time"].unique()) == ["2023", "2024"]
    assert set(df["geo"]) == {"DG", "01", "11", "01001", "11000"}
    assert pd.read_parquet(tmp_path / "processed" / f"{TABLE}.parquet").equals(df)
