import re
import zipfile
from datetime import date
from xml.etree import ElementTree

import pandas as pd
import pytest
from openpyxl import load_workbook

from src.report.build_workbook import (
    HEADER_MAX_LINES,
    NUMBER_COLUMN_WIDTH,
    CHAR_WIDTH_FACTOR,
    COPYRIGHT_URL,
    DEFAULT_MONTHS,
    GEO_COLOURS,
    build_workbook,
    column_width_cm,
    main,
    month_on_month_thresholds,
    months_to_cover_chart,
    printable_height_pt,
    printable_width_cm,
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
def saved(frame, tmp_path_factory):
    path = tmp_path_factory.mktemp("wb") / "briefing.xlsx"
    build_workbook(frame, generated=date(2026, 4, 2)).save(path)
    return path


@pytest.fixture(scope="module")
def workbook(saved):
    return load_workbook(saved)


def _blocks(ws):
    """(heading row, header row, geography rows) for each indicator block."""
    header_rows = [r for r in range(1, ws.max_row + 1) if ws.cell(row=r, column=2).value == "Geography"]
    return [(h - 1, h, range(h + 1, h + 1 + len(GEOS))) for h in header_rows]


def test_sheet_order_and_visibility(workbook):
    assert workbook.sheetnames == ["Briefing", "Chart", "Settings", "Data", "Months", "Notes"]
    assert [ws.sheet_state for ws in workbook.worksheets] == [
        "visible", "visible", "visible", "hidden", "hidden", "visible"
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


def test_licence_names_geographies_outside_eu_and_efta(frame, monkeypatch):
    monkeypatch.setitem(GEO_COLOURS, "US", "000000")
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


CHART_COLOURS = {
    "Germany": "0072B2", "France": "D55E00", "Italy": "009E73",
    "Netherlands": "7B52AB", "Poland": "E69F00", "Euro area": "9AA5B1",
}
NS = {
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


def _chart_xml(path):
    # openpyxl drops charts when it loads a workbook, so read the chart part directly.
    with zipfile.ZipFile(path) as z:
        (name,) = [n for n in z.namelist() if n.startswith("xl/charts/chart")]
        return ElementTree.fromstring(z.read(name))


def _helper_block(ws):
    header = next(r for r in range(1, ws.max_row + 1) if ws.cell(row=r, column=2).value == "Month")
    return header, range(header + 1, ws.max_row + 1), range(3, ws.max_column + 1)


def test_chart_indicator_is_a_named_dropdown_defaulting_to_unemployment(workbook):
    assert workbook.defined_names["ChartIndicator"].attr_text == "Chart!$C$3"
    ws = workbook["Chart"]
    assert ws["C3"].value == "Unemployment"
    validations = ws.data_validations.dataValidation
    assert any(v.type == "list" and v.formula1 == "=IndicatorList" and "C3" in str(v.sqref) for v in validations)
    assert workbook.defined_names["IndicatorList"].attr_text == f"Settings!$A$2:$A${len(INDICATORS) + 1}"


def test_chart_title_is_the_indicator_alone(workbook):
    ws = workbook["Chart"]
    assert ws["B1"].value == "=ChartIndicator"
    assert ws["B5"].value == "Unit"
    assert "DataUnit" in ws["C5"].value and "ChartIndicator" in ws["C5"].value


def test_value_axis_title_carries_the_unit(saved):
    root = _chart_xml(saved)
    value_axis, date_axis = root.find(".//c:valAx", NS), root.find(".//c:dateAx", NS)
    assert value_axis.find("c:title/c:tx/c:strRef/c:f", NS).text == "'Chart'!$C$5"
    assert value_axis.find("c:title/c:overlay", NS).get("val") == "0"
    assert date_axis.find("c:title", NS) is None
    assert root.find("c:chart/c:title", NS) is None


def _drawing(saved):
    with zipfile.ZipFile(saved) as z:
        (drawing,) = [n for n in z.namelist() if n.startswith("xl/drawings/drawing")]
        return ElementTree.fromstring(z.read(drawing))


XDR = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"


def test_chart_sheet_page_setup(workbook, saved):
    ws = workbook["Chart"]
    _, rows, cols = _helper_block(ws)
    assert ws.page_setup.orientation == "landscape"
    assert ws.page_setup.fitToWidth == 1 and ws.page_setup.fitToHeight == 0
    assert ws.sheet_properties.pageSetUpPr.fitToPage
    assert str(ws.print_area) == f"'Chart'!$B$1:$H${rows[-1]}"
    # The chart's anchored width matches the printed columns and fits the page unscaled.
    columns_cm = sum(column_width_cm(ws.column_dimensions[c].width) for c in "BCDEFGH")
    chart_cm = int(_drawing(saved).find(f".//{XDR}ext").get("cx")) / 360000
    assert chart_cm == pytest.approx(columns_cm, abs=0.01)
    assert chart_cm <= printable_width_cm()
    # Chart on page one, working data on page two, which it fits.
    label_row = next(r for r in range(1, rows[0]) if str(ws.cell(row=r, column=2).value).startswith("Working data"))
    assert [b.id for b in ws.row_breaks.brk] == [label_row - 1]
    assert sum(ws.row_dimensions[r].height for r in range(label_row, rows[-1] + 1)) <= printable_height_pt()


def test_chart_labels_fit_their_column(workbook):
    ws = workbook["Chart"]
    assert ws.column_dimensions["B"].width >= len("Report month") * CHAR_WIDTH_FACTOR


def test_helper_block_is_36_by_6_formulas(workbook):
    ws = workbook["Chart"]
    header, rows, cols = _helper_block(ws)
    assert len(rows) == 36 and len(cols) == 6
    assert [ws.cell(row=header, column=c).value for c in cols] == list(CHART_COLOURS)
    assert ws.cell(row=rows[-1], column=2).value == "=EDATE(ReportMonth,0)"
    assert ws.cell(row=rows[0], column=2).value == "=EDATE(ReportMonth,-35)"
    for r in rows:
        for c in cols:
            value = ws.cell(row=r, column=c).value
            assert value.startswith("=IFERROR(INDEX(DataValue,MATCH(") and "ChartIndicator" in value
    assert ws.sheet_state == "visible"
    assert not any(ws.row_dimensions[r].hidden for r in rows)
    assert ws.cell(row=rows[0], column=3).fill.fgColor.rgb.endswith("F6F7F9")
    assert any(str(ws.cell(row=r, column=2).value).startswith("Working data") for r in range(1, header))


def test_chart_sits_above_helper_block(workbook, saved):
    with zipfile.ZipFile(saved) as z:
        (drawing,) = [n for n in z.namelist() if n.startswith("xl/drawings/drawing")]
        root = ElementTree.fromstring(z.read(drawing))
    xdr = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
    anchor_row = int(root.find(f".//{xdr}from/{xdr}row").text) + 1
    header, _, _ = _helper_block(workbook["Chart"])
    chart_height_rows = 11.5 / 2.54 * 72 / 15
    assert anchor_row + chart_height_rows < header - 2


def test_chart_has_six_coloured_series_reading_the_helper_block(workbook, saved):
    root = _chart_xml(saved)
    series = root.findall(".//c:lineChart/c:ser", NS)
    assert len(series) == 6
    header, rows, _ = _helper_block(workbook["Chart"])
    for ser, (name, colour), col in zip(series, CHART_COLOURS.items(), "CDEFGH"):
        ref = lambda path: ser.find(path, NS).text.replace("$", "")
        assert ref("c:tx/c:strRef/c:f") == f"'Chart'!{col}{header}"
        assert ref("c:val/c:numRef/c:f") == f"'Chart'!{col}{rows[0]}:{col}{rows[-1]}"
        assert ref("c:cat/c:numRef/c:f") == f"'Chart'!B{rows[0]}:B{rows[-1]}"
        line = ser.find("c:spPr/a:ln", NS)
        assert line.find("a:solidFill/a:srgbClr", NS).get("val") == colour, name
        assert int(line.get("w")) == 2 * 12700
        assert ser.find("c:marker/c:symbol", NS).get("val") == "none"


def test_chart_legend_axes_and_gridlines(saved):
    root = _chart_xml(saved)
    assert root.find(".//c:legend/c:legendPos", NS).get("val") == "t"
    date_axis, value_axis = root.find(".//c:dateAx", NS), root.find(".//c:valAx", NS)
    assert date_axis.find("c:majorGridlines", NS) is None
    assert value_axis.find("c:majorGridlines", NS) is not None
    for axis in (date_axis, value_axis):
        assert axis.find("c:delete", NS).get("val") == "0"
        assert axis.find(".//a:defRPr/a:solidFill/a:srgbClr", NS).get("val") == "4A5568"


def _lagging(frame, months):
    late = frame["month"].isin(MONTHS[-months:])
    return frame[~((frame["indicator_label"] == "HICP") & late)] if months else frame


@pytest.mark.parametrize("lag, needed", [(0, 36), (1, 37), (2, 38)])
def test_months_to_cover_chart(frame, lag, needed):
    assert months_to_cover_chart(_lagging(frame, lag)) == needed


def test_default_extract_is_37_months():
    assert DEFAULT_MONTHS == 37


@pytest.mark.parametrize("lag, calls", [(1, [37]), (2, [37, 38])])
def test_main_fetches_enough_months_for_the_chart(frame, lag, calls, tmp_path, monkeypatch):
    requested = []

    def fake_fetch(months):
        requested.append(months)
        return _lagging(frame, lag)

    monkeypatch.setattr("src.report.build_workbook.fetch_briefing_frame", fake_fetch)
    main(["--out", str(tmp_path / "out.xlsx")])
    assert requested == calls


def test_unknown_country_needs_a_colour(frame):
    other = frame.replace({"geo_code": {"PL": "ES"}, "geo_name": {"Poland": "Spain"}})
    with pytest.raises(ValueError, match="GEO_COLOURS"):
        build_workbook(other)


def test_rejects_wildcard_characters_in_keys(frame):
    bad = frame.assign(indicator_label=frame["indicator_label"].where(frame["indicator_label"] != "HICP", "HICP*"))
    with pytest.raises(ValueError, match="wildcard"):
        build_workbook(bad)


def test_rejects_unit_kind_without_change_unit(frame):
    with pytest.raises(ValueError, match="CHANGE_UNITS"):
        build_workbook(frame.assign(unit_kind="count"))
