select
    'consumer_confidence' as dataset_name,
    s.indicator_code,
    s.geo as geo_code,
    {{ month_start('s.time') }} as period_date,
    s.unit as unit_code,
    s.s_adj as adjustment_code,
    concat('indic=', s.indic) as breakdown_code,
    {{ label_or_code('indic_l', 's.indic') }} as breakdown_label,
    s.value,
    s.status
from {{ source('eurostat_raw', 'raw_consumer_confidence') }} as s
{{ join_label('indic', 's.indic', 'indic_l') }}
