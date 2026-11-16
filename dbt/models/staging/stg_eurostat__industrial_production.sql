-- indic_bt is requested as PRD only, so the parser drops it as constant
select
    'industrial_production' as dataset_name,
    s.indicator_code,
    s.geo as geo_code,
    {{ month_start('s.time') }} as period_date,
    s.unit as unit_code,
    s.s_adj as adjustment_code,
    concat('nace_r2=', s.nace_r2) as breakdown_code,
    {{ label_or_code('nace_l', 's.nace_r2') }} as breakdown_label,
    s.value,
    s.status
from {{ source('eurostat_raw', 'raw_industrial_production') }} as s
{{ join_label('nace_r2', 's.nace_r2', 'nace_l') }}
