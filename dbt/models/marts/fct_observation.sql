-- Keys use the same expressions as the dimensions; the relationship tests guard the match.
select
    {{ dbt_utils.generate_surrogate_key(['o.dataset_name', 'o.unit_code', 'o.adjustment_code', 'o.breakdown_code']) }} as series_key,
    {{ dbt_utils.generate_surrogate_key(['o.geo_code']) }} as geo_key,
    cast(extract(year from o.period_date) * 100 + extract(month from o.period_date) as integer) as date_key,
    o.value,
    o.status,
    st.label as status_label
from {{ ref('stg_eurostat__observations') }} as o
{{ join_label('status', 'o.status', 'st') }}
