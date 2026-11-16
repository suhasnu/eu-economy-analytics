-- Every day between the first and last full_date is present exactly once.
with bounds as (
    select
        min(full_date) as lo,
        max(full_date) as hi,
        count(*) as n_rows,
        count(distinct full_date) as n_days
    from {{ ref('dim_date') }}
)

select *
from bounds
where n_rows != {{ dbt.datediff('lo', 'hi', 'day') }} + 1
   or n_days != n_rows
   or extract(month from lo) != 1 or extract(day from lo) != 1
   or extract(month from hi) != 12 or extract(day from hi) != 31
