{% set datasets = ['unemployment', 'hicp', 'industrial_production', 'retail_trade', 'consumer_confidence'] %}
{% for d in datasets %}
select * from {{ ref('stg_eurostat__' ~ d) }}
{% if not loop.last %}union all{% endif %}
{% endfor %}
