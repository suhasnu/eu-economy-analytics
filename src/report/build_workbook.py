"""Build the monthly briefing workbook from fetch_briefing_frame.

Briefing  the main sheet: ReportMonth, then one block per indicator of INDEX/MATCH
          formulas, so picking another ReportMonth recalculates everything
Settings  visible, one editable flagging threshold per indicator
Data      hidden, the frame plus a key column, referenced through DataKey and DataValue
Months    hidden, the months in the data, the list ReportMonth is validated against
Notes     visible, plain prose on sources, units, release timing and regeneration

Colours and fonts follow powerbi/theme/eu-economy-theme.json.
"""

from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.pagebreak import Break
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from src.report.extract import fetch_briefing_frame

DEFAULT_OUT = Path("build/eu-economy-briefing.xlsx")
TITLE = "EU economy monthly briefing"

DATA_COLUMNS = ["geo_code", "geo_name", "indicator_label", "unit_kind", "unit_short_label", "month", "value"]
REPORT_MONTH_CELL = "C3"
TITLE_ROWS = 4
FIRST_BLOCK_ROW = TITLE_ROWS + 2
LAST_COLUMN = "G"
CHANGE_COLUMNS = (5, 7)

# A change in a rate or ratio is in percentage points; a change in an index level or a
# survey balance is in points of that scale, not a percentage.
CHANGE_UNITS = {
    "rate of change": "pp",
    "ratio": "pp",
    "index level": "points",
    "survey balance": "points",
}

VALUE_FORMAT = "#,##0.0"
CHANGE_FORMAT = "+#,##0.0;-#,##0.0;0.0"
MONTH_FORMAT = "mmm yyyy"

ACCENT = "0072B2"
FOREGROUND = "1B2733"
LABEL = "4A5568"
BAND = "F3F7FA"
RULE = "E6E9EC"
FONT_FACE = "Segoe UI"

BODY_FONT = Font(name=FONT_FACE, size=11, color=FOREGROUND)
TITLE_FONT = Font(name=f"{FONT_FACE} Semibold", size=15, color=ACCENT)
HEADING_FONT = Font(name=f"{FONT_FACE} Semibold", size=12, color=ACCENT)
HEADER_FONT = Font(name=FONT_FACE, size=11, bold=True, color="FFFFFF")
SOURCE_FONT = Font(name=FONT_FACE, size=10, color=LABEL)
HEADER_FILL = PatternFill("solid", fgColor=ACCENT)
BAND_FILL = PatternFill("solid", fgColor=BAND)
ROW_RULE = Border(bottom=Side(style="thin", color=RULE))
WRAP = Alignment(wrap_text=True, vertical="top")

# Width in Excel character units for C:G; headers wrap within it instead of widening the page.
NUMBER_COLUMN_WIDTH = 19
NOTES_COLUMN_WIDTH = 90
# Segoe UI runs a little wider than the Calibri metrics Excel sizes columns by.
CHAR_WIDTH_FACTOR = 1.15
LINE_HEIGHT_PT = 15

# Every Briefing row gets an explicit height: Excel does not re-fit row heights for
# wrapped text in a file it did not write, and the page breaks are computed from these.
TITLE_ROW_HEIGHTS = {1: 24, 2: 12, 3: 18, 4: 16}
SPACER_HEIGHT = 15
HEADING_HEIGHT = 22
BODY_HEIGHT = 18
HEADER_MAX_LINES = 2

# Notes prose is mostly lower case, narrower on average than the digits column widths
# are measured in, so it needs a smaller factor than the headers.
PROSE_WIDTH_FACTOR = 1.0
NOTES_GAP_HEIGHT = 6

COPYRIGHT_URL = "https://ec.europa.eu/eurostat/help/copyright-notice"
# Eurostat codes; Greece is EL. Decides which licence sentence the Notes sheet carries.
EU_MEMBERS = frozenset(
    "AT BE BG CY CZ DE DK EE EL ES FI FR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split()
)
EFTA_MEMBERS = frozenset("CH IS LI NO".split())
EU_AGGREGATE_PATTERN = r"^(EA|EU)"

THRESHOLD_SIGMAS = 2
FLAG_FILL = PatternFill(start_color="FDF0D5", end_color="FDF0D5", fill_type="solid")
FLAG_FONT = Font(bold=True)

A4_SHORT_SIDE_IN = 8.27
MARGIN_SIDE_IN = 0.5
MARGIN_TOP_BOTTOM_IN = 0.6


def block_headers(unit: str, change_unit: str) -> list[str]:
    return [
        "Geography",
        f"Latest ({unit})",
        "Previous month",
        f"vs previous month ({change_unit})",
        "Year earlier",
        f"vs year earlier ({change_unit})",
    ]


def wrapped_lines(text: str, width: float, char_factor: float = CHAR_WIDTH_FACTOR) -> int:
    """Lines Excel needs to show `text` wrapped at word boundaries in a column `width` wide."""
    capacity = (width - 1) / char_factor
    lines, used = 0, None
    for word in text.split():
        if used is not None and used + 1 + len(word) <= capacity:
            used += 1 + len(word)
        else:
            spans = math.ceil(len(word) / capacity)
            lines += spans
            used = len(word) - (spans - 1) * capacity
    return max(lines, 1)


def _month_key(offset: int) -> str:
    # YEAR and MONTH rather than TEXT(..., "yyyy-mm"): TEXT format codes are localised,
    # so "yyyy" would not be understood by a German or French Excel.
    month = f"EDATE(ReportMonth,{offset})"
    return f'YEAR({month})&"-"&TEXT(MONTH({month}),"00")'


def _lookup(geo_cell: str, indicator_cell: str, offset: int) -> str:
    key = f'{geo_cell}&"|"&{indicator_cell}&"|"&{_month_key(offset)}'
    return f'=IFERROR(INDEX(DataValue,MATCH({key},DataKey,0)),"")'


def _difference(now: str, then: str) -> str:
    return f'=IF(OR({now}="",{then}=""),"",{now}-{then})'


def _define(wb: Workbook, name: str, sheet: str, ref: str) -> None:
    wb.defined_names[name] = DefinedName(name, attr_text=f"{sheet}!{ref}")


def _check_frame(df: pd.DataFrame) -> None:
    # MATCH with match type 0 treats * ? and ~ in the lookup value as wildcards.
    for column in ("geo_code", "indicator_label"):
        bad = df.loc[df[column].str.contains(r"[*?~]", regex=True), column].unique()
        if len(bad):
            raise ValueError(f"{column} values would act as MATCH wildcards: {list(bad)}")
    unknown = set(df["unit_kind"]) - set(CHANGE_UNITS)
    if unknown:
        raise ValueError(f"no change unit for unit_kind {sorted(unknown)}; add it to CHANGE_UNITS")


def default_report_month(df: pd.DataFrame) -> pd.Timestamp:
    """Latest month in which every indicator has data, so no block opens empty."""
    per_month = df.groupby("month")["indicator_label"].nunique()
    complete = per_month[per_month == df["indicator_label"].nunique()]
    if complete.empty:
        raise ValueError("no month has data for every indicator")
    return pd.Timestamp(complete.index.max())


def _write_data(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Data")
    ws.sheet_state = "hidden"
    ws.append(["key", *DATA_COLUMNS])
    month_col = get_column_letter(DATA_COLUMNS.index("month") + 2)
    for i, row in enumerate(df[DATA_COLUMNS].itertuples(index=False), start=2):
        key = f'=B{i}&"|"&D{i}&"|"&YEAR({month_col}{i})&"-"&TEXT(MONTH({month_col}{i}),"00")'
        ws.append([key, row.geo_code, row.geo_name, row.indicator_label, row.unit_kind,
                   row.unit_short_label, row.month.to_pydatetime(), float(row.value)])
        ws[f"{month_col}{i}"].number_format = "yyyy-mm-dd"
    last = len(df) + 1
    value_col = get_column_letter(len(DATA_COLUMNS) + 1)
    table = Table(displayName="BriefingData", ref=f"A1:{value_col}{last}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)
    ws.add_table(table)
    _define(wb, "DataKey", "Data", f"$A$2:$A${last}")
    _define(wb, "DataValue", "Data", f"${value_col}$2:${value_col}${last}")


def _write_months(wb: Workbook, months: list[pd.Timestamp]) -> None:
    ws = wb.create_sheet("Months")
    ws.sheet_state = "hidden"
    ws.append(["month"])
    for i, month in enumerate(months, start=2):
        ws.cell(row=i, column=1, value=month.to_pydatetime()).number_format = MONTH_FORMAT
    _define(wb, "ReportMonths", "Months", f"$A$2:$A${len(months) + 1}")


def _write_title(ws: Worksheet, report_month: pd.Timestamp, generated: date) -> None:
    ws["B1"] = TITLE
    ws["B1"].font = TITLE_FONT
    ws["B3"] = "Report month"
    ws["B3"].font = BODY_FONT
    cell = ws[REPORT_MONTH_CELL]
    cell.value = report_month.to_pydatetime()
    cell.number_format = MONTH_FORMAT
    cell.font = Font(name=FONT_FACE, size=11, bold=True, color=FOREGROUND)
    cell.alignment = Alignment(horizontal="left")
    validation = DataValidation(
        type="list", formula1="=ReportMonths", allow_blank=False,
        showErrorMessage=True, errorTitle="Report month", error="Pick a month from the list.",
    )
    ws.add_data_validation(validation)
    validation.add(REPORT_MONTH_CELL)
    ws["B4"] = f"Source: Eurostat. Built from the project's dbt marts, generated {generated:%d %b %Y}."
    ws["B4"].font = SOURCE_FONT
    for row, height in TITLE_ROW_HEIGHTS.items():
        ws.row_dimensions[row].height = height


def _write_blocks(ws: Worksheet, df: pd.DataFrame) -> list[range]:
    """Write one block per indicator and return each block's rows, heading to last geography."""
    # Column A carries the lookup keys (indicator_label on heading rows, geo_code on
    # geography rows) so the formulas reference cells instead of quoted literals.
    geos = df[["geo_code", "geo_name"]].drop_duplicates().sort_values("geo_code")
    indicators = (
        df[["indicator_label", "unit_kind", "unit_short_label"]]
        .drop_duplicates()
        .sort_values("indicator_label")
    )

    blocks = []
    row = FIRST_BLOCK_ROW
    for indicator in indicators.itertuples(index=False):
        ws.row_dimensions[row - 1].height = SPACER_HEIGHT
        heading_row, header_row = row, row + 1
        ws.cell(row=heading_row, column=1, value=indicator.indicator_label)
        ws.cell(row=heading_row, column=2, value=indicator.indicator_label).font = HEADING_FONT
        ws.row_dimensions[heading_row].height = HEADING_HEIGHT

        headers = block_headers(indicator.unit_short_label, CHANGE_UNITS[indicator.unit_kind])
        lines = max(wrapped_lines(text, NUMBER_COLUMN_WIDTH) for text in headers[1:])
        if lines > HEADER_MAX_LINES:
            raise ValueError(f"headers for {indicator.indicator_label} need {lines} lines: {headers}")
        for col, text in enumerate(headers, start=2):
            cell = ws.cell(row=header_row, column=col, value=text)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(
                horizontal="left" if col == 2 else "right", vertical="center", wrap_text=True
            )
        ws.row_dimensions[header_row].height = HEADER_MAX_LINES * LINE_HEIGHT_PT + 6

        indicator_cell = f"$A${heading_row}"
        for i, geo in enumerate(geos.itertuples(index=False)):
            r = header_row + 1 + i
            geo_cell = f"$A{r}"
            ws.row_dimensions[r].height = BODY_HEIGHT
            ws.cell(row=r, column=1, value=geo.geo_code)
            ws.cell(row=r, column=2, value=geo.geo_name)
            ws.cell(row=r, column=3, value=_lookup(geo_cell, indicator_cell, 0))
            ws.cell(row=r, column=4, value=_lookup(geo_cell, indicator_cell, -1))
            ws.cell(row=r, column=5, value=_difference(f"C{r}", f"D{r}"))
            ws.cell(row=r, column=6, value=_lookup(geo_cell, indicator_cell, -12))
            ws.cell(row=r, column=7, value=_difference(f"C{r}", f"F{r}"))
            for col in range(2, 8):
                cell = ws.cell(row=r, column=col)
                cell.font = BODY_FONT
                cell.border = ROW_RULE
                if i % 2:
                    cell.fill = BAND_FILL
                if col > 2:
                    cell.number_format = CHANGE_FORMAT if col in CHANGE_COLUMNS else VALUE_FORMAT
        last_geo_row = header_row + len(geos)
        blocks.append(range(heading_row, last_geo_row + 1))
        row = last_geo_row + 2
    return blocks


def usable_page_height() -> float:
    """Printable height of a landscape A4 page in points, less the repeated title rows."""
    printable = (A4_SHORT_SIDE_IN - 2 * MARGIN_TOP_BOTTOM_IN) * 72
    return printable - sum(TITLE_ROW_HEIGHTS.values())


def _break_pages(ws: Worksheet, blocks: list[range]) -> None:
    # Heights are measured at 100% scale. Fit-to-width only ever shrinks the sheet, so a
    # page that holds these rows at 100% still holds them when printed.
    def height(rows: range) -> float:
        return sum(ws.row_dimensions[r].height for r in rows)

    available = usable_page_height()
    used = 0.0
    for i, block in enumerate(blocks):
        spacer = range(block.start - 1, block.start)
        needed = height(spacer) + height(block)
        if used and used + needed > available:
            # Break after the previous block, so the spacer row opens the new page
            # instead of spilling onto it as a page of its own.
            ws.row_breaks.append(Break(id=blocks[i - 1].stop - 1))
            used = 0.0
        used += needed


def _size_columns(ws: Worksheet, df: pd.DataFrame) -> None:
    ws.column_dimensions["A"].hidden = True
    # The title and source line overflow into the empty cells beside them, and block
    # headings into their empty row, so only geography names and the label must fit in B.
    longest = max(df["geo_name"].str.len().max(), len("Geography"), len("Report month"))
    ws.column_dimensions["B"].width = math.ceil(longest * CHAR_WIDTH_FACTOR) + 2
    for col in "CDEFG":
        ws.column_dimensions[col].width = NUMBER_COLUMN_WIDTH


def _set_up_page(ws: Worksheet, last_column: str, last_row: int, landscape: bool) -> None:
    ws.sheet_view.showGridLines = False
    ws.print_area = f"B1:{last_column}{last_row}"
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE if landscape else ws.ORIENTATION_PORTRAIT
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = MARGIN_SIDE_IN
    ws.page_margins.top = ws.page_margins.bottom = MARGIN_TOP_BOTTOM_IN
    ws.page_margins.header = ws.page_margins.footer = 0.3


def _licence_text(df: pd.DataFrame) -> str:
    geos = df[["geo_code", "geo_name"]].drop_duplicates()
    is_eu = geos["geo_code"].isin(EU_MEMBERS) | geos["geo_code"].str.match(EU_AGGREGATE_PATTERN)
    is_efta = geos["geo_code"].isin(EFTA_MEMBERS)
    outside = geos.loc[~(is_eu | is_efta), "geo_name"].tolist()
    if outside:
        scope = (
            f"Data for {', '.join(outside)} falls under that exclusion, so check the notice "
            "before reusing those figures commercially."
        )
    elif is_efta.any():
        scope = f"These exclusions do not affect this briefing: all {len(geos)} geographies are in the EU or EFTA."
    else:
        scope = (
            f"These exclusions do not affect this briefing: all {len(geos)} geographies are EU "
            "member states or the euro area, an aggregate of EU members."
        )
    return (
        "Reuse of Eurostat data is authorised, free of charge, provided the source is "
        "acknowledged, under European Commission Decision 2011/833/EU on the reuse of "
        "Commission documents. The required acknowledgement is: Source: Eurostat. Any copy or "
        "extract of this briefing should keep it. The CC BY 4.0 licence that Eurostat refers "
        "to covers the editorial content of the Eurostat website, not the data itself. "
        "Eurostat excludes from commercial reuse data supplied by third parties and data for "
        f"countries outside the EU and EFTA. {scope} Full terms: {COPYRIGHT_URL}"
    )


def notes_sections(df: pd.DataFrame) -> list[tuple[str, str]]:
    indicators = sorted(df["indicator_label"].unique())
    n = len(indicators)
    return [
        (
            "Where the data comes from",
            "Every figure is a monthly statistic published by Eurostat, the statistical office of "
            "the European Union, taken from its public dissemination API. The briefing uses the "
            f"headline series of {n} indicators: {'; '.join(indicators)}. Figures are shown as "
            "Eurostat published them on the date this file was generated; later revisions by "
            "Eurostat are not reflected until the file is regenerated.",
        ),
        ("Licence", _licence_text(df)),
        (
            "Flagged changes",
            "A month-on-month change is highlighted when its size, up or down, exceeds the "
            "threshold for its indicator on the Settings sheet. Highlighting marks an unusually "
            "large move, not a good or bad one. Each threshold starts at two standard deviations "
            "of that indicator's month-on-month changes across all geographies over the months in "
            "this file; edit a threshold on the Settings sheet and the flags update immediately.",
        ),
        (
            "Units of the change columns",
            "The change columns are plain differences between two published values, never "
            "percentages. For rates and ratios, such as the HICP annual rate of change and the "
            "unemployment rate, the difference is in percentage points (pp): unemployment moving "
            "from 6.0% to 6.3% is a rise of 0.3 pp, which is also a relative rise of 5%, so the "
            "two must not be confused. For index levels (2021 = 100) and survey balances, the "
            "difference is in points of that scale. An index rising from 105.0 to 107.1 has risen "
            "2.1 points, which is a 2.0% increase; points and percent agree only when the earlier "
            "level is exactly 100. A survey balance is the share of positive answers minus the "
            "share of negative ones, so its change is in balance points.",
        ),
        (
            "Why the report month can trail the newest data",
            "Eurostat publishes each indicator on its own schedule. Survey results and inflation "
            "figures appear soon after the month ends, while production, retail trade and labour "
            f"market figures follow some weeks later. The report month therefore opens on the "
            f"latest month for which all {n} indicators have been published, so every block shows "
            "figures. Newer months for the faster indicators remain available in the dropdown.",
        ),
        (
            "Why one cell can be empty",
            "Eurostat compiles the euro area aggregate from its members' national data and can "
            "publish it later than some of the members. In a given month a country can therefore "
            "show a value while the euro area row is still blank. A blank cell means the figure "
            "was not yet published when the file was generated; it does not mean zero. The change "
            "columns are blank whenever either of the two values they compare is missing.",
        ),
        (
            "Changing the report month and regenerating the file",
            "To look at another month, select the Report month cell on the Briefing sheet and pick "
            "a month from its dropdown; every figure on the sheet recalculates. Only months "
            "present in the data are offered. To bring in newly published data, refresh the "
            "project's dbt marts and then regenerate the workbook from the project directory with "
            "python -m src.report.build_workbook, which writes build/eu-economy-briefing.xlsx. "
            "It reads from BigQuery when BQ_PROJECT and BQ_DBT_DATASET are set and from the local "
            "DuckDB copy otherwise; --months sets how many months of history are included "
            "(36 by default).",
        ),
    ]


def _write_notes(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Notes")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = NOTES_COLUMN_WIDTH
    ws["B1"] = "Notes"
    ws["B1"].font = TITLE_FONT
    ws.row_dimensions[1].height = TITLE_ROW_HEIGHTS[1]
    row = 3
    for heading, text in notes_sections(df):
        ws.cell(row=row, column=2, value=heading).font = HEADING_FONT
        ws.row_dimensions[row].height = HEADING_HEIGHT
        body = ws.cell(row=row + 1, column=2, value=text)
        body.font = BODY_FONT
        body.alignment = WRAP
        lines = wrapped_lines(text, NOTES_COLUMN_WIDTH, PROSE_WIDTH_FACTOR)
        ws.row_dimensions[row + 1].height = lines * LINE_HEIGHT_PT + 2
        ws.row_dimensions[row + 2].height = NOTES_GAP_HEIGHT
        row += 3
    _set_up_page(ws, "B", row - 2, landscape=False)


def month_on_month_thresholds(df: pd.DataFrame) -> dict[str, float]:
    """Two standard deviations of each indicator's month-on-month changes, pooled across geos.

    Only changes between consecutive months count, so a gap in a series does not produce a
    two-month change. Rounded to the one decimal the sheet displays, and never below 0.1 so a
    flat series does not flag every non-zero change.
    """
    d = df.sort_values(["indicator_label", "geo_code", "month"])
    d = d.assign(month_index=d["month"].dt.year * 12 + d["month"].dt.month)
    by_series = d.groupby(["indicator_label", "geo_code"])
    consecutive = by_series["month_index"].diff() == 1
    changes = d.assign(change=by_series["value"].diff())[consecutive]
    spread = changes.groupby("indicator_label")["change"].std()
    missing = sorted(set(d["indicator_label"]) - set(spread.dropna().index))
    if missing:
        raise ValueError(f"too few consecutive months to set a threshold for {missing}")
    return {label: max(round(THRESHOLD_SIGMAS * sd, 1), 0.1) for label, sd in spread.items()}


def _write_settings(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Settings")
    ws.sheet_view.showGridLines = False
    headers = ["Indicator", "Threshold", "Note"]
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=text)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
    units = df.drop_duplicates("indicator_label").set_index("indicator_label")["unit_kind"]
    thresholds = month_on_month_thresholds(df)
    for row, (label, threshold) in enumerate(sorted(thresholds.items()), start=2):
        change_unit = CHANGE_UNITS[units[label]]
        ws.cell(row=row, column=1, value=label).font = BODY_FONT
        value = ws.cell(row=row, column=2, value=threshold)
        value.font = BODY_FONT
        value.number_format = "0.0"
        ws.cell(
            row=row, column=3,
            value=f"Editable. Flags a month-on-month change larger than this, in {change_unit}, either way.",
        ).font = BODY_FONT
    last = len(thresholds) + 1
    validation = DataValidation(
        type="decimal", operator="greaterThanOrEqual", formula1="0", allow_blank=False,
        showErrorMessage=True, errorTitle="Threshold", error="Enter a number of 0 or more.",
    )
    ws.add_data_validation(validation)
    validation.add(f"B2:B{last}")
    ws.column_dimensions["A"].width = math.ceil(max(map(len, thresholds)) * CHAR_WIDTH_FACTOR) + 2
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 78
    _define(wb, "ThresholdIndicator", "Settings", f"$A$2:$A${last}")
    _define(wb, "ThresholdValue", "Settings", f"$B$2:$B${last}")


def _flag_large_changes(ws: Worksheet, blocks: list[range]) -> None:
    # Through defined names: conditional formats cannot point at another sheet directly in
    # older Excel, and a name keeps the threshold live when Settings is edited.
    col = get_column_letter(CHANGE_COLUMNS[0])
    for block in blocks:
        first, last = block.start + 2, block.stop - 1
        threshold = f"INDEX(ThresholdValue,MATCH($A${block.start},ThresholdIndicator,0))"
        formula = f"IF(ISNUMBER({col}{first}),ABS({col}{first})>{threshold},FALSE)"
        ws.conditional_formatting.add(
            f"{col}{first}:{col}{last}",
            FormulaRule(formula=[formula], fill=FLAG_FILL, font=FLAG_FONT, stopIfTrue=False),
        )


def build_workbook(df: pd.DataFrame, generated: date | None = None) -> Workbook:
    if df.empty:
        raise ValueError("briefing frame is empty")
    _check_frame(df)
    months = [pd.Timestamp(m) for m in sorted(df["month"].unique())]

    wb = Workbook()
    briefing = wb.active
    briefing.title = "Briefing"
    _write_settings(wb, df)
    _write_data(wb, df)
    _write_months(wb, months)
    _write_title(briefing, default_report_month(df), generated or date.today())
    blocks = _write_blocks(briefing, df)
    _size_columns(briefing, df)
    _set_up_page(briefing, LAST_COLUMN, blocks[-1].stop - 1, landscape=True)
    briefing.freeze_panes = f"A{TITLE_ROWS + 1}"
    briefing.print_title_rows = f"1:{TITLE_ROWS}"
    briefing.print_options.horizontalCentered = True
    _break_pages(briefing, blocks)
    _flag_large_changes(briefing, blocks)
    _write_notes(wb, df)
    _define(wb, "ReportMonth", "Briefing", "$C$3")
    # openpyxl stores formulas without cached results; this makes Excel compute them on open.
    wb.calculation.fullCalcOnLoad = True
    return wb


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the monthly briefing workbook")
    parser.add_argument("--months", type=int, default=36, help="months of history in the Data sheet (default 36)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output workbook (default {DEFAULT_OUT})")
    args = parser.parse_args(argv)

    df = fetch_briefing_frame(args.months)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    build_workbook(df).save(args.out)
    print(f"{args.out}: {len(df)} data rows, report month {default_report_month(df):%b %Y}")


if __name__ == "__main__":
    main()
