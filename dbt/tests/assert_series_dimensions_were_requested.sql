-- Every dimension a series carries must be one configs/indicators.yml requests for its dataset.
with carried as (
    {%- for d in breakdown_dimensions() %}
    select series_key, dataset_name, '{{ d }}' as dimension
    from {{ ref('dim_series') }}
    where {{ d }}_code is not null
    {% if not loop.last %}union all{% endif %}
    {%- endfor %}
)
select c.series_key, c.dataset_name, c.dimension
from carried as c
left join {{ ref('indicator_dimensions') }} as r
    on r.dataset_name = c.dataset_name and r.dimension = c.dimension
where r.dimension is null
