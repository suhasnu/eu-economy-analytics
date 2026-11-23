-- Every level as published: nothing here sums districts into Länder or Germany, and no rate is computed.
select
    {{ dbt_utils.generate_surrogate_key(['o.series_code']) }} as series_key,
    {{ dbt_utils.generate_surrogate_key(['o.region_code']) }} as region_key,
    {# Annual observations attach to 1 January, as monthly ones attach to the first of the month. #}
    cast(o.year * 10000 + 101 as integer) as date_key,
    o.value,
    o.status
from {{ ref('stg_regionalstatistik__observations') }} as o
