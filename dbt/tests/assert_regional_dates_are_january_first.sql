-- Annual rows land on 1 January, and that day exists in dim_date.
select f.date_key, count(*) as n_rows
from {{ ref('fct_regional_observation') }} as f
left join {{ ref('dim_date') }} as d on d.date_key = f.date_key
where d.date_key is null or d.month_number != 1 or not d.is_month_start
group by f.date_key
