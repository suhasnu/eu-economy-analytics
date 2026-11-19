"""Build the monthly briefing workbook from fetch_briefing_frame.

Briefing  the one visible sheet: ReportMonth, then one block per indicator of
          INDEX/MATCH formulas, so picking another ReportMonth recalculates everything
Data      hidden, the frame plus a key column, referenced through DataKey and DataValue
Months    hidden, the months in the data, the list ReportMonth is validated against

Colours and fonts follow powerbi/theme/eu-economy-theme.json.
"""

from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from src.report.extract import fetch_briefing_frame

DEFAULT_OUT = Path("build/eu-economy-briefing.xlsx")
TITLE = "EU economy monthly briefing"
SOURCE = "Source: Eurostat, via the eu-economy dbt marts"

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

# Width in Excel character units for C:G; headers wrap within it instead of widening the page.
NUMBER_COLUMN_WIDTH = 17
# Segoe UI runs a little wider than the Calibri metrics Excel sizes columns by.
CHAR_WIDTH_FACTOR = 1.15
LINE_HEIGHT_PT = 15


def block_headers(unit: str, change_unit: str) -> list[str]:
    return [
        "Geography",
        f"Latest ({unit})",
        "Previous month",
        f"Change vs previous month ({change_unit})",
        "Same month a year earlier",
        f"Change vs a year earlier ({change_unit})",
    ]


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
    ws["B4"] = f"{SOURCE}. Generated {generated:%d %b %Y}."
    ws["B4"].font = SOURCE_FONT


def _header_lines(text: str, width: int) -> int:
    return math.ceil(len(text) * CHAR_WIDTH_FACTOR / (width - 1))


def _write_blocks(ws: Worksheet, df: pd.DataFrame) -> int:
    """Write one block per indicator and return the last row used."""
    # Column A carries the lookup keys (indicator_label on heading rows, geo_code on
    # geography rows) so the formulas reference cells instead of quoted literals.
    geos = df[["geo_code", "geo_name"]].drop_duplicates().sort_values("geo_code")
    indicators = (
        df[["indicator_label", "unit_kind", "unit_short_label"]]
        .drop_duplicates()
        .sort_values("indicator_label")
    )

    row = FIRST_BLOCK_ROW
    for indicator in indicators.itertuples(index=False):
        heading_row, header_row = row, row + 1
        ws.cell(row=heading_row, column=1, value=indicator.indicator_label)
        ws.cell(row=heading_row, column=2, value=indicator.indicator_label).font = HEADING_FONT

        headers = block_headers(indicator.unit_short_label, CHANGE_UNITS[indicator.unit_kind])
        for col, text in enumerate(headers, start=2):
            cell = ws.cell(row=header_row, column=col, value=text)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(
                horizontal="left" if col == 2 else "right", vertical="center", wrap_text=True
            )
        lines = max(_header_lines(text, NUMBER_COLUMN_WIDTH) for text in headers[1:])
        ws.row_dimensions[header_row].height = lines * LINE_HEIGHT_PT + 6

        indicator_cell = f"$A${heading_row}"
        for i, geo in enumerate(geos.itertuples(index=False)):
            r = header_row + 1 + i
            geo_cell = f"$A{r}"
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
        row = header_row + 1 + len(geos) + 1
    return row - 2


def _size_columns(ws: Worksheet, df: pd.DataFrame) -> None:
    ws.column_dimensions["A"].hidden = True
    # The title and source line overflow into the empty cells beside them, and block
    # headings into their empty row, so only geography names and the label must fit in B.
    longest = max(df["geo_name"].str.len().max(), len("Geography"), len("Report month"))
    ws.column_dimensions["B"].width = math.ceil(longest * CHAR_WIDTH_FACTOR) + 2
    for col in "CDEFG":
        ws.column_dimensions[col].width = NUMBER_COLUMN_WIDTH


def _set_up_page(ws: Worksheet, last_row: int) -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = f"A{TITLE_ROWS + 1}"
    ws.print_area = f"B1:{LAST_COLUMN}{last_row}"
    ws.print_title_rows = f"1:{TITLE_ROWS}"
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = ws.page_margins.right = 0.5
    ws.page_margins.top = ws.page_margins.bottom = 0.6
    ws.page_margins.header = ws.page_margins.footer = 0.3


def build_workbook(df: pd.DataFrame, generated: date | None = None) -> Workbook:
    if df.empty:
        raise ValueError("briefing frame is empty")
    _check_frame(df)
    months = [pd.Timestamp(m) for m in sorted(df["month"].unique())]

    wb = Workbook()
    briefing = wb.active
    briefing.title = "Briefing"
    _write_data(wb, df)
    _write_months(wb, months)
    _write_title(briefing, default_report_month(df), generated or date.today())
    last_row = _write_blocks(briefing, df)
    _size_columns(briefing, df)
    _set_up_page(briefing, last_row)
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
