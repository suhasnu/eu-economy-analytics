-- A series with no split dimension means breakdown_code holds a dimension dim_series does not split out.
select series_key, breakdown_code
from {{ ref('dim_series') }}
where {% for d in breakdown_dimensions() %}{{ d }}_code is null{% if not loop.last %} and {% endif %}{% endfor %}
