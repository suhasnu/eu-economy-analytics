with geos as (
    select distinct geo_code from {{ ref('stg_eurostat__observations') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['g.geo_code']) }} as geo_key,
    g.geo_code,
    coalesce(l.label, g.geo_code) as geo_name,
    -- EA*/EU* codes are Eurostat multi-country aggregates, not countries
    (g.geo_code like 'EA%' or g.geo_code like 'EU%') as is_aggregate,
    case when g.geo_code like 'EA%' or g.geo_code like 'EU%' then 'aggregate' else 'country' end as geo_type
from geos as g
{{ join_label('geo', 'g.geo_code', 'l') }}
