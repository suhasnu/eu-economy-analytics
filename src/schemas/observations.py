import pandera.pandas as pa

ObservationSchema = pa.DataFrameSchema(
    {
        "indicator_code": pa.Column(str, nullable=False),
        "geo": pa.Column(str, nullable=False),
        "time": pa.Column(str, nullable=False),
        "value": pa.Column(float, nullable=True),
        "unit": pa.Column(str, nullable=False),
        "status": pa.Column(str, nullable=True, required=False),
    },
    # Varying dimensions (sex, age, s_adj, ...) differ per dataset, so they pass through.
    strict=False,
    coerce=True,
)
