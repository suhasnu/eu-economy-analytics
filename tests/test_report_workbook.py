import re
from datetime import date

import pandas as pd
import pytest
from openpyxl import load_workbook

from src.report.build_workbook import (
    HEADER_MAX_LINES,
    NUMBER_COLUMN_WIDTH,
    COPYRIGHT_URL,
    build_workbook,
    month_on_month_thresholds,
    usable_page_height,
    wrapped_lines,
)
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


def test_sheet_order_and_visibility(workbook):
    assert workbook.sheetnames == ["Briefing", "Settings", "Data", "Months", "Notes"]
    assert [ws.sheet_state for ws in workbook.worksheets] == [
        "visible", "visible", "hidden", "hidden", "visible"
    ]
    assert workbook.active.title == "Briefing"


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
        cols = [c for c in VALUE_COLUMNS if str(ws.cell(row=header, column=c).value).startswith("vs ")]
        assert cols == list(CHANGE_COLUMNS)
        for r in rows:
            for c in cols:
                assert str(ws.cell(row=r, column=c).value).startswith("=")


def test_headings_are_label_alone_and_unit_is_in_headers(workbook):
    ws = workbook["Briefing"]
    for heading, header, _ in _blocks(ws):
        label = ws.cell(row=heading, column=2).value
        kind, unit = INDICATORS[label]
        change_unit = "pp" if kind in ("rate of change", "ratio") else "points"
        assert [ws.cell(row=header, column=c).value for c in range(2, 8)] == [
            "Geography",
            f"Latest ({unit})",
            "Previous month",
            f"vs previous month ({change_unit})",
            "Year earlier",
            f"vs year earlier ({change_unit})",
        ]


def test_headers_fit_two_lines(workbook):
    ws = workbook["Briefing"]
    for _, header, _ in _blocks(ws):
        for c in VALUE_COLUMNS:
            assert wrapped_lines(ws.cell(row=header, column=c).value, NUMBER_COLUMN_WIDTH) <= HEADER_MAX_LINES
        assert ws.row_dimensions[header].height < 3 * 15


def test_wrapped_lines():
    assert wrapped_lines("Previous month", 19) == 1
    assert wrapped_lines("vs previous month (points)", 19) == 2
    assert wrapped_lines("vs previous month (points)", 12) == 4
    assert wrapped_lines("x" * 30, 12) == 4


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


def test_no_block_splits_across_pages(workbook):
    ws = workbook["Briefing"]
    blocks = _blocks(ws)
    last_rows = [rows[-1] for _, _, rows in blocks]
    breaks = [b.id for b in ws.row_breaks.brk]
    assert breaks, "five blocks do not fit one landscape page, so a break is expected"
    assert set(breaks) <= set(last_rows[:-1])
    page_starts = [5] + [b + 1 for b in breaks]
    page_ends = [b for b in breaks] + [last_rows[-1]]
    for start, end in zip(page_starts, page_ends):
        height = sum(ws.row_dimensions[r].height for r in range(start, end + 1))
        assert height <= usable_page_height()


def test_source_line_names_no_internals(workbook):
    assert workbook["Briefing"]["B4"].value == (
        "Source: Eurostat. Built from the project's dbt marts, generated 02 Apr 2026."
    )


def test_notes_sheet(workbook):
    ws = workbook["Notes"]
    assert ws.sheet_state == "visible"
    text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    for phrase in ("Eurostat", "CC BY 4.0", "percentage points", "index", "schedule",
                   "euro area", "dropdown", "python -m src.report.build_workbook"):
        assert phrase in text
    assert not any(str(c.value).startswith("=") for row in ws.iter_rows() for c in row if c.value)
    assert ws.column_dimensions["B"].width >= 60
    for row in ws.iter_rows(min_col=2, max_col=2):
        cell = row[0]
        if cell.value and len(cell.value) > 100:
            assert cell.alignment.wrap_text
            assert ws.row_dimensions[cell.row].height > 15


def test_licence_wording(workbook):
    ws = workbook["Notes"]
    rows = [c.value for row in ws.iter_rows(min_col=2, max_col=2) for c in row]
    licence = rows[rows.index("Licence") + 1]
    assert "Reuse of Eurostat data is authorised" in licence
    assert "provided the source is acknowledged" in licence
    assert "Decision 2011/833/EU" in licence
    assert "The required acknowledgement is: Source: Eurostat." in licence
    assert "CC BY 4.0 licence that Eurostat refers to covers the editorial content" in licence
    assert "not the data itself" in licence
    assert "third parties" in licence and "outside the EU and EFTA" in licence
    assert "do not affect this briefing" in licence
    assert COPYRIGHT_URL == "https://ec.europa.eu/eurostat/help/copyright-notice"
    assert COPYRIGHT_URL in licence


def test_licence_names_geographies_outside_eu_and_efta(frame):
    with_us = frame.replace({"geo_code": {"PL": "US"}, "geo_name": {"Poland": "United States"}})
    ws = build_workbook(with_us)["Notes"]
    rows = [c.value for row in ws.iter_rows(min_col=2, max_col=2) for c in row]
    licence = rows[rows.index("Licence") + 1]
    assert "United States falls under that exclusion" in licence
    assert "do not affect" not in licence


def test_settings_sheet_has_numeric_threshold_per_indicator(workbook):
    ws = workbook["Settings"]
    assert [c.value for c in ws[1]] == ["Indicator", "Threshold", "Note"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    assert sorted(r[0] for r in rows) == sorted(INDICATORS)
    for _, threshold, note in rows:
        assert isinstance(threshold, (int, float)) and threshold > 0
        assert "Editable" in note
    assert workbook.defined_names["ThresholdValue"].attr_text == f"Settings!$B$2:$B${len(rows) + 1}"
    assert workbook.defined_names["ThresholdIndicator"].attr_text == f"Settings!$A$2:$A${len(rows) + 1}"


def test_thresholds_are_two_sd_of_consecutive_month_changes():
    months = pd.date_range("2025-01-01", periods=4, freq="MS")
    base = {"indicator_label": "X", "unit_kind": "ratio", "unit_short_label": "%", "geo_name": "n"}
    rows = [{**base, "geo_code": "DE", "month": m, "value": v} for m, v in zip(months, [0.0, 1.0, 3.0, 6.0])]
    # FR skips a month: its 0 -> 10 jump spans two months and must not count.
    rows += [{**base, "geo_code": "FR", "month": months[i], "value": v} for i, v in [(0, 0.0), (2, 10.0), (3, 11.0)]]
    changes = pd.Series([1.0, 2.0, 3.0, 1.0])
    assert month_on_month_thresholds(pd.DataFrame(rows)) == {"X": round(2 * changes.std(), 1)}


def test_large_changes_flagged_from_settings(workbook):
    ws = workbook["Briefing"]
    rules = {str(cf.sqref): cf.rules for cf in ws.conditional_formatting}
    for _, _, rows in _blocks(ws):
        change_range = f"E{rows[0]}:E{rows[-1]}"
        assert change_range in rules
        (rule,) = rules[change_range]
        formula = rule.formula[0]
        assert "ThresholdValue" in formula and "ThresholdIndicator" in formula
        assert "ABS(" in formula
        # Apart from cell references and MATCH's exact-match 0, no number appears.
        literals = re.findall(r"\d+(?:\.\d+)?", re.sub(r"\$?[A-Z]+\$?\d+", "", formula))
        assert set(literals) <= {"0"}
        assert rule.dxf.fill.fgColor.rgb.endswith("FDF0D5")
        assert rule.dxf.font.b
    year_columns = [r for r in rules if r.startswith("G")]
    assert not year_columns


def test_rejects_wildcard_characters_in_keys(frame):
    bad = frame.assign(indicator_label=frame["indicator_label"].where(frame["indicator_label"] != "HICP", "HICP*"))
    with pytest.raises(ValueError, match="wildcard"):
        build_workbook(bad)


def test_rejects_unit_kind_without_change_unit(frame):
    with pytest.raises(ValueError, match="CHANGE_UNITS"):
        build_workbook(frame.assign(unit_kind="count"))
