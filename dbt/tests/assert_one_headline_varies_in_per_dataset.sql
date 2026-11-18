-- Every dataset, including one with no match at all, has exactly one series with varies_in = 'headline'.
select h.dataset_name, count(s.series_key) as n_headline
from {{ ref('indicator_headlines') }} as h
left join {{ ref('dim_series') }} as s
    on s.dataset_name = h.dataset_name and s.varies_in = 'headline'
group by h.dataset_name
having count(s.series_key) != 1
