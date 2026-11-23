-- Records why no level is derived from another. For the headline count (ERWP06, unemployed) the
-- districts never add up to the published national row, because each level is averaged and rounded
-- on its own (2024: 2,787,125 summed against 2,787,112 published). Fails for any year where they
-- match or the national row is missing. Headline only: a breakdown can match by chance
-- (ERWP06.ARBEITSLOS14 in 2016), which would not make summing valid.
with headline as (
    select f.date_key, r.region_level, f.value
    from {{ ref('fct_regional_observation') }} as f
    inner join {{ ref('dim_regional_series') }} as s on s.series_key = f.series_key
    inner join {{ ref('dim_region') }} as r on r.region_key = f.region_key
    where s.series_code = 'ERWP06'
),

by_year as (
    select
        date_key,
        sum(case when region_level = 'kreis' then value end) as district_sum,
        max(case when region_level = 'national' then value end) as published_national
    from headline
    group by date_key
)

select *
from by_year
where published_national is null or district_sum = published_national
