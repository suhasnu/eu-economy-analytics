-- A flag Eurostat starts using after the seed was generated would otherwise show unexplained.
select status, count(*) as n_rows
from {{ ref('fct_observation') }}
where status is not null and status_label is null
group by status
