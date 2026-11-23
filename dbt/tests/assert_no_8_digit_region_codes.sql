-- KREISE also returns 8-digit cities and Berlin boroughs that lie inside district rows. Ingestion drops
-- them; one reaching the mart would be counted twice.
select r.region_code, count(f.region_key) as n_fact_rows
from {{ ref('dim_region') }} as r
left join {{ ref('fct_regional_observation') }} as f on f.region_key = r.region_key
where length(r.region_code) = 8
group by r.region_code
