-- Validity is a min/max span, so a year inside it where the code is "-" in every series would be a hidden gap.
select r.region_code, d.year
from {{ ref('fct_regional_observation') }} as f
inner join {{ ref('dim_region') }} as r on r.region_key = f.region_key
inner join {{ ref('dim_date') }} as d on d.date_key = f.date_key
where d.year between r.valid_from_year and r.valid_to_year
group by r.region_code, d.year
having count(*) = sum(case when f.status = '-' then 1 else 0 end)
