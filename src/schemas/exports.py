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

BriefingSchema = pa.DataFrameSchema(
    {
        "geo_code": pa.Column(str, nullable=False),
        "geo_name": pa.Column(str, nullable=False),
        "indicator_label": pa.Column(str, nullable=False),
        # The briefing picks pp or % from unit_kind, so a missing rule must fail here.
        "unit_kind": pa.Column(str, nullable=False),
        "unit_short_label": pa.Column(str, nullable=False),
        "month": pa.Column(
            "datetime64[ns]",
            pa.Check(lambda s: s.dt.day == 1, error="month must be the 1st"),
            nullable=False,
        ),
        "value": pa.Column(float, nullable=False),
    },
    unique=["geo_code", "indicator_label", "month"],
    strict=True,
    ordered=True,
    coerce=True,
)
