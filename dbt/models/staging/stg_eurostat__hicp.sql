select
    'hicp' as dataset_name,
    s.indicator_code,
    s.geo as geo_code,
    {{ month_start('s.time') }} as period_date,
    s.unit as unit_code,
    -- HICP is published unadjusted and has no s_adj dimension
    'NSA' as adjustment_code,
    concat('coicop18=', s.coicop18) as breakdown_code,
    {{ label_or_code('coicop_l', 's.coicop18') }} as breakdown_label,
    s.value,
    s.status
from {{ source('eurostat_raw', 'raw_hicp') }} as s
{{ join_label('coicop18', 's.coicop18', 'coicop_l') }}
