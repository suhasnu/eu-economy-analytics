-- No value in a year outside the code's validity years, and none for a code without validity years.
select r.region_code, d.year, count(*) as n_values
from {{ ref('fct_regional_observation') }} as f
inner join {{ ref('dim_region') }} as r on r.region_key = f.region_key
inner join {{ ref('dim_date') }} as d on d.date_key = f.date_key
where f.value is not null
  and (r.valid_from_year is null or d.year < r.valid_from_year or d.year > r.valid_to_year)
group by r.region_code, d.year
