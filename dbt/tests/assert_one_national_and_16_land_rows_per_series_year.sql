-- Every series and year has exactly one published national row and one published row per Land.
with expected as (
    select s.series_key, y.date_key, l.region_level, l.n_expected
    from {{ ref('dim_regional_series') }} as s
    cross join (select distinct date_key from {{ ref('fct_regional_observation') }}) as y
    cross join (
        select 'national' as region_level, 1 as n_expected
        union all
        select 'land' as region_level, 16 as n_expected
    ) as l
),

actual as (
    select f.series_key, f.date_key, r.region_level, count(*) as n_rows
    from {{ ref('fct_regional_observation') }} as f
    inner join {{ ref('dim_region') }} as r on r.region_key = f.region_key
    where r.region_level in ('national', 'land')
    group by f.series_key, f.date_key, r.region_level
)

select e.series_key, e.date_key, e.region_level, e.n_expected, coalesce(a.n_rows, 0) as n_rows
from expected as e
left join actual as a
    on a.series_key = e.series_key and a.date_key = e.date_key and a.region_level = e.region_level
where coalesce(a.n_rows, 0) != e.n_expected
