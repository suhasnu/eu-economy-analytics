-- At most one headline observation per dataset, geo and month. Grouping by dataset
-- rather than series also catches two series both flagged as one dataset's headline.
select s.dataset_name, f.geo_key, f.date_key, count(*) as n_rows
from {{ ref('fct_observation') }} as f
inner join {{ ref('dim_series') }} as s on s.series_key = f.series_key
where s.is_headline
group by s.dataset_name, f.geo_key, f.date_key
having count(*) > 1
