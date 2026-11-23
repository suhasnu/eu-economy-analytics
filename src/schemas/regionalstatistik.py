import pandas as pd
import pandera.pandas as pa

MARKERS = {
    "-": "code does not exist in that year",
    ".": "value unknown or withheld",
    "x": "cell blocked because the figure would not be meaningful",
}

# Code shape for each level in the tidy output. 8-digit KREISE rows never reach it.
GEO_PATTERN_BY_LEVEL = {"national": r"^DG$", "land": r"^\d{2}$", "kreis": r"^\d{5}$"}
REGION_LEVELS = list(GEO_PATTERN_BY_LEVEL)


def _geo_fits_level(df):
    fits = pd.Series(False, index=df.index)
    for level, pattern in GEO_PATTERN_BY_LEVEL.items():
        at_level = df["region_level"] == level
        fits |= at_level & df["geo"].str.match(pattern)
    return fits


RegionalObservationSchema = pa.DataFrameSchema(
    {
        # value_variable_code, joined with the breakdown code when there is one (ERWP06.ARBEITSLOS05).
        "indicator_code": pa.Column(str, pa.Check.str_matches(r"^[A-Z0-9]+(\.[A-Z0-9]+)?$"), nullable=False),
        # DG, a 2-digit Land key, or a 5-digit district key (first five AGS digits). Leading zeros matter.
        "geo": pa.Column(str, pa.Check.str_matches(r"^(DG|\d{2}|\d{5})$"), nullable=False),
        "time": pa.Column(str, pa.Check.str_matches(r"^\d{4}$"), nullable=False),
        "value": pa.Column(float, pa.Check.ge(0), nullable=True),
        "unit": pa.Column(str, pa.Check.isin(["Anzahl", "Prozent"]), nullable=False),
        "status": pa.Column(str, pa.Check.isin(list(MARKERS)), nullable=True),
        "geo_label": pa.Column(str, nullable=False),
        # From the request that produced the row; the geo shape must agree with it.
        "region_level": pa.Column(str, pa.Check.isin(REGION_LEVELS), nullable=False),
        "value_variable_code": pa.Column(str, nullable=False),
        # value_variable_label as published, e.g. "Arbeitslosenquote bez. abh. zivile Erwerbspers.".
        "series_label": pa.Column(str, nullable=False),
        "breakdown_code": pa.Column(str, nullable=True),
        # 2_variable_attribute_label as published; "insgesamt" for series without a breakdown.
        "breakdown_label": pa.Column(str, nullable=False),
        "table_code": pa.Column(str, nullable=False),
    },
    checks=[
        # A marker replaces the value, it never sits beside one, and a marker is never read as zero.
        pa.Check(lambda df: df["value"].isna() == df["status"].notna(), error="value is null exactly when status is set"),
        pa.Check(_geo_fits_level, error="geo code shape does not match region_level"),
    ],
    unique=["region_level", "indicator_code", "geo", "time"],
    strict=True,
    ordered=True,
    coerce=True,
)
