-- Keys use the same expressions as the dimensions; the relationship tests guard the match.
select
    {{ dbt_utils.generate_surrogate_key(['dataset_name', 'unit_code', 'adjustment_code', 'breakdown_code']) }} as series_key,
    {{ dbt_utils.generate_surrogate_key(['geo_code']) }} as geo_key,
    cast(extract(year from period_date) * 100 + extract(month from period_date) as integer) as date_key,
    value,
    status
from {{ ref('stg_eurostat__observations') }}
