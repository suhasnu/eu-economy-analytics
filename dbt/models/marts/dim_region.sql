with obs as (
    select * from {{ ref('stg_regionalstatistik__observations') }}
),

window_years as (
    select min(year) as lo, max(year) as hi from obs
),

-- A code exists in a year when it carries a value. "." and "x" alone do not count:
-- 05313 Aachen, Stadt (alt) has only "." and "-" in 2017-18, decades after the merger.
regions as (
    select
        region_level,
        region_code,
        region_name,
        min(case when value is not null then year end) as valid_from_year,
        max(case when value is not null then year end) as valid_to_year
    from obs
    group by region_level, region_code, region_name
),

named as (
    select
        r.*,
        count(*) over (partition by r.region_name) > 1 as name_is_shared,
        case
            when r.valid_from_year is null
                then concat('no values ', cast(w.lo as string), '–', cast(w.hi as string))
            when r.valid_from_year = r.valid_to_year then cast(r.valid_from_year as string)
            else concat(cast(r.valid_from_year as string), '–', cast(r.valid_to_year as string))
        end as validity_text
    from regions as r
    cross join window_years as w
)

select
    {{ dbt_utils.generate_surrogate_key(['region_code']) }} as region_key,
    region_code,
    region_level,
    case region_level
        when 'land' then region_code
        when 'kreis' then substr(region_code, 1, 2)
    end as land_code,
    region_name,
    case when name_is_shared then concat(region_name, ' (', validity_text, ')') else region_name end as display_name,
    valid_from_year,
    valid_to_year
from named
