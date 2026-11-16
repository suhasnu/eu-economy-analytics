import pandera.pandas as pa

HeadlineExportSchema = pa.DataFrameSchema(
    {
        "indicator": pa.Column(str, nullable=False),
        "geo_code": pa.Column(str, nullable=False),
        "geo_label": pa.Column(str, nullable=False),
        "month_start_date": pa.Column(
            "datetime64[ns]",
            pa.Check(lambda s: s.dt.day == 1, error="month_start_date must be the 1st"),
            nullable=False,
        ),
        "value": pa.Column(float, nullable=False),
        "unit_short_label": pa.Column(str, nullable=False),
        "status": pa.Column(str, nullable=True),
    },
    # indicator is the headline short_label, and each dataset has exactly one headline series.
    unique=["indicator", "geo_code", "month_start_date"],
    strict=True,
    ordered=True,
    coerce=True,
)
