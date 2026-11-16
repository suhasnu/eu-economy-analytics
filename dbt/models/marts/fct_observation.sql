-- Keys use the same expressions as the dimensions; the relationship tests guard the match.
select
    {{ dbt_utils.generate_surrogate_key(['o.dataset_name', 'o.unit_code', 'o.adjustment_code', 'o.breakdown_code']) }} as series_key,
    {{ dbt_utils.generate_surrogate_key(['o.geo_code']) }} as geo_key,
    {# Monthly observations attach to the first day of their month in the daily dim_date. #}
    cast(
        extract(year from o.period_date) * 10000
        + extract(month from o.period_date) * 100
        + 1
        as integer
    ) as date_key,
    o.value,
    o.status,
    st.label as status_label
from {{ ref('stg_eurostat__observations') }} as o
{{ join_label('status', 'o.status', 'st') }}
