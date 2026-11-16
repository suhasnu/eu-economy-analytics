{# Contiguous month spine covering every observation month. #}
{% set bounds %}select min(period_date) as lo, max(period_date) as hi from {{ ref('stg_eurostat__observations') }}{% endset %}
{% if execute %}
    {% set row = run_query(bounds).rows[0] %}
    {% set lo, hi = row[0] | string, row[1] | string %}
{% else %}
    {% set lo, hi = '1900-01-01', '1900-01-01' %}
{% endif %}

with months as (
    {{ dbt_utils.date_spine(
        datepart='month',
        start_date="cast('" ~ lo ~ "' as date)",
        end_date=dbt.dateadd('month', 1, "cast('" ~ hi ~ "' as date)")
    ) }}
),

typed as (
    select cast(date_month as date) as month_start_date from months
)

select
    cast(extract(year from month_start_date) * 100 + extract(month from month_start_date) as integer) as date_key,
    month_start_date,
    cast(extract(year from month_start_date) as integer) as year,
    cast(extract(quarter from month_start_date) as integer) as quarter,
    cast(extract(month from month_start_date) as integer) as month_number,
    {{ month_name('month_start_date') }} as month_name,
    concat(cast(extract(year from month_start_date) as string), ' Q', cast(extract(quarter from month_start_date) as string)) as year_quarter
from typed
