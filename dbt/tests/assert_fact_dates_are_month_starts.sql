-- Fact rows must land on a dim_date row that is a month start (existence is also covered by the relationships test).
select f.date_key, count(*) as n_rows
from {{ ref('fct_observation') }} as f
left join {{ ref('dim_date') }} as d on d.date_key = f.date_key
where d.date_key is null or not d.is_month_start
group by f.date_key
