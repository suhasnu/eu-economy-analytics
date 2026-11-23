"""Regionalstatistik GENESIS REST API (ffcsv) ingestion, one synchronous request per year and regional level.

Every level comes from its own published request. Nothing here sums a lower level into a higher one, and no
rate is ever computed from counts: Prozent rows are the published rates at each level.
"""

from __future__ import annotations

import argparse
import io
import os
import zipfile
from pathlib import Path

import pandas as pd
import requests

from src.schemas.observations import ObservationSchema
from src.schemas.regionalstatistik import MARKERS, RegionalObservationSchema

BASE_URL = "https://www.regionalstatistik.de/genesisws/rest/2020"
DEFAULT_TABLE = "13211-02-05-4-B"
DEFAULT_START_YEAR = 2015
RAW_SUBDIR = Path("raw") / "regionalstatistik"

# GENESIS regionalvariable -> region_level. The level is whatever the request asked for.
LEVELS = {"DINSG": "national", "DLAND": "land", "KREISE": "kreis"}
# Code shapes each level may return; checked against the request, never used to assign the level.
CODE_PATTERNS = {"DINSG": r"DG", "DLAND": r"\d{2}", "KREISE": r"\d{5}|\d{8}"}
# KREISE also returns three cities (Hannover, Aachen, Saarbrücken) and the twelve Berlin boroughs as 8-digit
# rows. Each lies inside a 5-digit district row of the same response, so keeping them double counts.
CONTAINED_CODE_LENGTH = 8
TOTAL_BREAKDOWN_LABEL = "insgesamt"

CODE, LABEL = "1_variable_attribute_code", "1_variable_attribute_label"
OUTPUT_COLUMNS = list(RegionalObservationSchema.columns)


class RegionalstatistikError(RuntimeError):
    """The API answered with a JSON status instead of data, or the data broke an expectation."""


def _auth_headers() -> dict[str, str]:
    try:
        user, password = os.environ["REGIO_USER"], os.environ["REGIO_PASSWORD"]
    except KeyError:
        raise RegionalstatistikError("REGIO_USER and REGIO_PASSWORD must be set") from None
    return {"username": user, "password": password, "Content-Type": "application/x-www-form-urlencoded"}


def _post(endpoint: str, data: dict[str, str]) -> requests.Response:
    # POST with credentials in headers keeps them out of URLs and server access logs.
    resp = requests.post(f"{BASE_URL}/{endpoint}", headers=_auth_headers(), data=data, timeout=300)
    if not resp.ok:
        # Rejected credentials come back as HTTP 404 with a GENESIS status body; surface that code.
        if "json" in resp.headers.get("Content-Type", ""):
            _raise_for_status_payload(resp, endpoint)
        resp.raise_for_status()
    return resp


def _raise_for_status_payload(resp: requests.Response, what: str) -> dict:
    """Return the JSON body if its status is a success; GENESIS reports most errors as HTTP 200 + JSON."""
    try:
        payload = resp.json()
    except ValueError:
        raise RegionalstatistikError(f"{what}: unexpected non-JSON response") from None
    # Data and catalogue answers nest the status; HTTP-level errors (e.g. rejected login) put it at the top.
    status = payload.get("Status") or payload
    if status.get("Code") != 0:
        # Only Code and Content: the echoed Parameter block is masked, but there is no reason to pass it on.
        raise RegionalstatistikError(f"{what}: GENESIS status {status.get('Code')}: {status.get('Content')}")
    return payload


def latest_year(table: str = DEFAULT_TABLE) -> int:
    payload = _raise_for_status_payload(
        _post("metadata/table", {"name": table, "area": "all", "language": "de"}), f"metadata {table}"
    )
    return int(payload["Object"]["Time"]["To"])


def raw_path(table: str, year: int, level: str, data_dir: Path = Path("data")) -> Path:
    return data_dir / RAW_SUBDIR / f"{table}_{year}_{level}.zip"


def tablefile_params(table: str, year: int, level: str) -> dict[str, str]:
    if level not in LEVELS:
        raise ValueError(f"unknown regional level {level!r}, expected one of {sorted(LEVELS)}")
    return {
        "name": table,
        "area": "all",
        "format": "ffcsv",
        "startyear": str(year),
        "endyear": str(year),
        "regionalvariable": level,
        "language": "de",
        "job": "false",
    }


def fetch_year(table: str, year: int, level: str, data_dir: Path = Path("data")) -> Path:
    """Download one year at one regional level as ffcsv and write the zip unchanged. Returns its path."""
    resp = _post("data/tablefile", tablefile_params(table, year, level))
    if not resp.content.startswith(b"PK"):
        # Status 98 here means even one year is over the synchronous limit.
        _raise_for_status_payload(resp, f"{table} {year} {level}")
        raise RegionalstatistikError(f"{table} {year} {level}: success status but no zip in the response")
    out = raw_path(table, year, level, data_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename, so an interrupted download never looks like a year that is already present.
    tmp = out.with_suffix(".part")
    tmp.write_bytes(resp.content)
    tmp.replace(out)
    return out


def read_ffcsv(zip_bytes: bytes) -> pd.DataFrame:
    """Every column of the single CSV in an ffcsv zip, as strings."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        members = [n for n in z.namelist() if n.endswith(".csv")]
        if len(members) != 1:
            raise RegionalstatistikError(f"expected one CSV in the zip, found {members}")
        text = z.read(members[0]).decode("utf-8-sig")
    return pd.read_csv(io.StringIO(text), sep=";", dtype=str, keep_default_na=False)


def _parse_values(raw: pd.Series) -> tuple[pd.Series, pd.Series]:
    is_marker = raw.isin(list(MARKERS))
    numeric = raw.str.fullmatch(r"\d+(,\d+)?")
    unknown = raw[~is_marker & ~numeric]
    if not unknown.empty:
        raise RegionalstatistikError(f"unrecognised value markers: {sorted(unknown.unique())[:10]}")
    value = pd.to_numeric(raw.where(~is_marker).str.replace(",", ".", regex=False), errors="raise")
    status = raw.where(is_marker)
    return value.astype("float64"), status


def _check_level(raw: pd.DataFrame, level: str) -> None:
    returned = set(raw["1_variable_code"])
    if returned != {level}:
        raise RegionalstatistikError(f"requested regionalvariable {level}, response has {sorted(returned)}")
    bad = raw.loc[~raw[CODE].str.fullmatch(CODE_PATTERNS[level]), CODE]
    if not bad.empty:
        raise RegionalstatistikError(f"{level}: codes that do not fit the level: {sorted(bad.unique())[:10]}")


def parse_ffcsv(zip_bytes: bytes, level: str, table: str = DEFAULT_TABLE) -> pd.DataFrame:
    """Every row of one level's response, one row per observation, region_level taken from the request."""
    if level not in LEVELS:
        raise ValueError(f"unknown regional level {level!r}, expected one of {sorted(LEVELS)}")
    raw = read_ffcsv(zip_bytes)
    _check_level(raw, level)

    value, status = _parse_values(raw["value"])
    breakdown = raw["2_variable_attribute_code"].mask(raw["2_variable_attribute_code"] == "")
    # Series without a breakdown publish an empty label; name them as the total. A breakdown code with an
    # empty label stays null so the schema rejects it.
    breakdown_label = raw["2_variable_attribute_label"].mask(raw["2_variable_attribute_label"] == "")
    breakdown_label = breakdown_label.where(breakdown.notna(), TOTAL_BREAKDOWN_LABEL)
    df = pd.DataFrame(
        {
            "indicator_code": raw["value_variable_code"].where(
                breakdown.isna(), raw["value_variable_code"] + "." + breakdown
            ),
            "geo": raw[CODE],
            "time": raw["time"],
            "value": value,
            "unit": raw["value_unit"],
            "status": status,
            "geo_label": raw[LABEL],
            "region_level": LEVELS[level],
            "value_variable_code": raw["value_variable_code"],
            "series_label": raw["value_variable_label"].mask(raw["value_variable_label"] == ""),
            "breakdown_code": breakdown,
            "breakdown_label": breakdown_label,
            "table_code": table,
        }
    )
    return df.sort_values(["indicator_code", "geo", "time"]).reset_index(drop=True)


def containing_kreis(code: str, kreise: set[str]) -> str | None:
    """The 5-digit row an 8-digit code lies in. Berlin's boroughs sit under 11000, not under their own prefix."""
    for candidate in (code[:5], code[:2] + "000"):
        if candidate in kreise:
            return candidate
    return None


def drop_contained_regions(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split KREISE rows into (kept, excluded). Fails if an excluded code has no district row to be counted in."""
    if set(df["region_level"]) != {"kreis"}:
        raise ValueError("drop_contained_regions applies to the KREISE level only")
    contained = df["geo"].str.len() == CONTAINED_CODE_LENGTH
    kreise = set(df.loc[~contained, "geo"])
    excluded = df[contained]
    orphans = sorted({c for c in excluded["geo"] if containing_kreis(c, kreise) is None})
    if orphans:
        raise RegionalstatistikError(f"codes below district level with no containing district: {orphans}")
    return df[~contained].reset_index(drop=True), excluded.reset_index(drop=True)


def tidy(zip_bytes: bytes, level: str, table: str = DEFAULT_TABLE) -> pd.DataFrame:
    df = parse_ffcsv(zip_bytes, level, table)
    if level == "KREISE":
        df, _ = drop_contained_regions(df)
    ObservationSchema.validate(df)
    return RegionalObservationSchema.validate(df[OUTPUT_COLUMNS])


def headline(df: pd.DataFrame, value_variable_code: str = "ERWP06") -> pd.DataFrame:
    return df[(df["value_variable_code"] == value_variable_code) & df["breakdown_code"].isna()]


def ingest(
    table: str, start: int, end: int, data_dir: Path = Path("data"), levels: tuple[str, ...] = tuple(LEVELS)
) -> tuple[pd.DataFrame, list[tuple[int, str]]]:
    """Fetch missing (year, level) slices, then rebuild the processed parquet from every raw slice in range."""
    slices = [(year, level) for year in range(start, end + 1) for level in levels]
    fetched = []
    for year, level in slices:
        if not raw_path(table, year, level, data_dir).exists():
            fetch_year(table, year, level, data_dir)
            fetched.append((year, level))
    frames = [tidy(raw_path(table, y, lv, data_dir).read_bytes(), lv, table) for y, lv in slices]
    df = RegionalObservationSchema.validate(pd.concat(frames, ignore_index=True))
    out = data_dir / "processed" / f"{table}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df, fetched


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest a Regionalstatistik table, one year and level per request")
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--start", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end", type=int, help="last year; defaults to the latest year in the table metadata")
    args = parser.parse_args(argv)

    end = args.end if args.end is not None else latest_year(args.table)
    df, fetched = ingest(args.table, args.start, end)
    print(f"{args.table} {args.start}-{end}: fetched {len(fetched)} slices {fetched or ''}".rstrip())
    counts = df.groupby("region_level")["geo"].nunique().to_dict()
    print(f"{len(df)} rows, {df['indicator_code'].nunique()} series, regions per level {counts}")


if __name__ == "__main__":
    main()
