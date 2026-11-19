from datetime import date

import pandas as pd
import pytest
from openpyxl import load_workbook

from src.report.build_workbook import build_workbook
from src.schemas.exports import BriefingSchema

GEOS = {"DE": "Germany", "EA21": "Euro area", "FR": "France", "IT": "Italy", "NL": "Netherlands", "PL": "Poland"}
INDICATORS = {
    "Consumer confidence": ("survey balance", "Balance"),
    "HICP": ("rate of change", "% y/y"),
    "Industrial production": ("index level", "Index 2021=100"),
    "Retail trade": ("index level", "Index 2021=100"),
    "Unemployment": ("ratio", "% labour force"),
}
MONTHS = pd.date_range("2025-01-01", "2026-03-01", freq="MS")
VALUE_COLUMNS = range(3, 8)
CHANGE_COLUMNS = (5, 7)


def _frame() -> pd.DataFrame:
    rows = [
        {"geo_code": g, "geo_name": name, "indicator_label": ind, "unit_kind": kind,
         "unit_short_label": unit, "month": m, "value": float(i)}
        for i, (g, name, (ind, (kind, unit)), m) in enumerate(
            (g, name, item, m) for g, name in GEOS.items() for item in INDICATORS.items() for m in MONTHS
        )
    ]
    return BriefingSchema.validate(pd.DataFrame(rows))


def _save(df: pd.DataFrame, path):
    build_workbook(df, generated=date(2026, 4, 2)).save(path)
    return load_workbook(path)


@pytest.fixture(scope="module")
def frame() -> pd.DataFrame:
    return _frame()


@pytest.fixture(scope="module")
def workbook(frame, tmp_path_factory):
    return _save(frame, tmp_path_factory.mktemp("wb") / "briefing.xlsx")


def _blocks(ws):
    """(heading row, header row, geography rows) for each indicator block."""
    header_rows = [r for r in range(1, ws.max_row + 1) if ws.cell(row=r, column=2).value == "Geography"]
    return [(h - 1, h, range(h + 1, h + 1 + len(GEOS))) for h in header_rows]


def test_three_sheets_with_only_briefing_visible(workbook):
    assert workbook.sheetnames == ["Briefing", "Data", "Months"]
    assert [ws.sheet_state for ws in workbook.worksheets] == ["visible", "hidden", "hidden"]


def test_defined_names(workbook):
    for name in ("ReportMonth", "DataKey", "DataValue", "ReportMonths"):
        assert name in workbook.defined_names
    assert workbook.defined_names["ReportMonth"].attr_text == "Briefing!$C$3"


def test_data_rows_match_frame_and_ranges_fit(workbook, frame):
    ws = workbook["Data"]
    assert ws.max_row - 1 == len(frame)
    last = len(frame) + 1
    assert workbook.defined_names["DataKey"].attr_text == f"Data!$A$2:$A${last}"
    assert workbook.defined_names["DataValue"].attr_text == f"Data!$H$2:$H${last}"
    assert all(str(ws.cell(row=r, column=1).value).startswith("=") for r in range(2, last + 1))


def test_report_month_defaults_to_latest_when_all_indicators_have_it(workbook):
    assert workbook["Briefing"]["C3"].value == MONTHS[-1].to_pydatetime()


def test_report_month_defaults_to_latest_month_every_indicator_has(frame, tmp_path):
    lagging = frame[~((frame["indicator_label"] == "HICP") & (frame["month"] == MONTHS[-1]))]
    wb = _save(lagging, tmp_path / "lagging.xlsx")
    assert wb["Briefing"]["C3"].value == MONTHS[-2].to_pydatetime()
    # The dropdown still offers every month, including the one HICP lacks.
    assert wb.defined_names["ReportMonths"].attr_text == f"Months!$A$2:$A${len(MONTHS) + 1}"
    assert wb["Months"].cell(row=len(MONTHS) + 1, column=1).value == MONTHS[-1].to_pydatetime()


def test_report_month_is_validated_against_month_list(workbook):
    validations = workbook["Briefing"].data_validations.dataValidation
    assert any(v.formula1 == "=ReportMonths" and "C3" in str(v.sqref) for v in validations)


def test_five_blocks_of_six_formula_rows(workbook):
    ws = workbook["Briefing"]
    blocks = _blocks(ws)
    assert len(blocks) == len(INDICATORS)
    for _, _, rows in blocks:
        assert [ws.cell(row=r, column=1).value for r in rows] == sorted(GEOS)
        for r in rows:
            for col in VALUE_COLUMNS:
                value = str(ws.cell(row=r, column=col).value)
                assert value.startswith("=")
                assert "XLOOKUP" not in value


def test_change_columns_are_formulas(workbook):
    ws = workbook["Briefing"]
    for _, header, rows in _blocks(ws):
        cols = [c for c in VALUE_COLUMNS if str(ws.cell(row=header, column=c).value).startswith("Change vs")]
        assert cols == list(CHANGE_COLUMNS)
        for r in rows:
            for c in cols:
                assert str(ws.cell(row=r, column=c).value).startswith("=")


def test_headings_are_label_alone_and_unit_is_in_headers(workbook):
    ws = workbook["Briefing"]
    for heading, header, _ in _blocks(ws):
        label = ws.cell(row=heading, column=2).value
        kind, unit = INDICATORS[label]
        assert ws.cell(row=header, column=3).value == f"Latest ({unit})"
        change_unit = "pp" if kind in ("rate of change", "ratio") else "points"
        assert ws.cell(row=header, column=5).value.endswith(f"({change_unit})")


def test_every_value_and_change_cell_has_a_number_format(workbook):
    ws = workbook["Briefing"]
    for _, _, rows in _blocks(ws):
        for r in rows:
            for c in VALUE_COLUMNS:
                fmt = ws.cell(row=r, column=c).number_format
                assert fmt != "General"
                assert ("+" in fmt) == (c in CHANGE_COLUMNS)


def test_page_setup(workbook):
    ws = workbook["Briefing"]
    assert ws.sheet_view.showGridLines is False
    assert ws.freeze_panes == "A5"
    assert ws.print_title_rows == "$1:$4"
    assert ws.page_setup.orientation == "landscape"
    assert ws.page_setup.fitToWidth == 1 and ws.page_setup.fitToHeight == 0
    assert ws.sheet_properties.pageSetUpPr.fitToPage
    assert str(ws.print_area).endswith(f"$G${_blocks(ws)[-1][2][-1]}")


def test_rejects_wildcard_characters_in_keys(frame):
    bad = frame.assign(indicator_label=frame["indicator_label"].where(frame["indicator_label"] != "HICP", "HICP*"))
    with pytest.raises(ValueError, match="wildcard"):
        build_workbook(bad)


def test_rejects_unit_kind_without_change_unit(frame):
    with pytest.raises(ValueError, match="CHANGE_UNITS"):
        build_workbook(frame.assign(unit_kind="count"))
