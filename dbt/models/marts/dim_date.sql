{# Contiguous daily spine over whole calendar years, as Power BI needs to mark it as a date table. #}
{# Years across both sources: Eurostat months and Regionalstatistik years. #}
{% set bounds %}
select min(lo) as lo_year, max(hi) as hi_year
from (
    select
        cast(min(extract(year from period_date)) as integer) as lo,
        cast(max(extract(year from period_date)) as integer) as hi
    from {{ ref('stg_eurostat__observations') }}
    union all
    select min(year) as lo, max(year) as hi
    from {{ ref('stg_regionalstatistik__observations') }}
) as years
{% endset %}
{% if execute %}
    {% set row = run_query(bounds).rows[0] %}
    {% set lo_year, hi_year = row[0] | int, row[1] | int %}
{% else %}
    {% set lo_year, hi_year = 1900, 1900 %}
{% endif %}

with days as (
    {# end_date is exclusive, so 1 January of the following year ends the spine on 31 December. #}
    {{ dbt_utils.date_spine(
        datepart='day',
        start_date="cast('" ~ lo_year ~ "-01-01' as date)",
        end_date="cast('" ~ (hi_year + 1) ~ "-01-01' as date)"
    ) }}
),

typed as (
    select cast(date_day as date) as full_date from days
),

with_month as (
    select
        full_date,
        cast({{ dbt.date_trunc('month', 'full_date') }} as date) as month_start_date
    from typed
)

select
    cast(
        extract(year from full_date) * 10000
        + extract(month from full_date) * 100
        + extract(day from full_date)
        as integer
    ) as date_key,
    full_date,
    cast(extract(year from full_date) as integer) as year,
    cast(extract(quarter from full_date) as integer) as quarter,
    cast(extract(month from full_date) as integer) as month_number,
    {{ month_name('full_date') }} as month_name,
    month_start_date,
    full_date = month_start_date as is_month_start
from with_month
