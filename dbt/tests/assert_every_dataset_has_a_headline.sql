-- Fails when a seeded headline no longer matches exactly one staged series,
-- e.g. the breakdown order in staging drifted from src/load/dbt_seeds.py.
select h.dataset_name
from {{ ref('indicator_headlines') }} as h
left join {{ ref('dim_series') }} as s on s.dataset_name = h.dataset_name and s.is_headline
group by h.dataset_name
having count(s.series_key) <> 1
