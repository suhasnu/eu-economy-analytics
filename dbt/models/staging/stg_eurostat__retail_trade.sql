select
    'retail_trade' as dataset_name,
    s.indicator_code,
    s.geo as geo_code,
    {{ month_start('s.time') }} as period_date,
    s.unit as unit_code,
    s.s_adj as adjustment_code,
    concat('indic_bt=', s.indic_bt, '|nace_r2=', s.nace_r2) as breakdown_code,
    concat({{ label_or_code('indic_l', 's.indic_bt') }}, '; ', {{ label_or_code('nace_l', 's.nace_r2') }}) as breakdown_label,
    s.value,
    s.status
from {{ source('eurostat_raw', 'raw_retail_trade') }} as s
{{ join_label('indic_bt', 's.indic_bt', 'indic_l') }}
{{ join_label('nace_r2', 's.nace_r2', 'nace_l') }}
