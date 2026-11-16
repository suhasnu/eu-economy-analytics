select
    'unemployment' as dataset_name,
    s.indicator_code,
    s.geo as geo_code,
    {{ month_start('s.time') }} as period_date,
    s.unit as unit_code,
    s.s_adj as adjustment_code,
    -- breakdown dimensions in alphabetical order, matching src/load/dbt_seeds.py
    concat('age=', s.age, '|sex=', s.sex) as breakdown_code,
    concat('Age: ', {{ label_or_code('age_l', 's.age') }}, '; Sex: ', {{ label_or_code('sex_l', 's.sex') }}) as breakdown_label,
    s.value,
    s.status
from {{ source('eurostat_raw', 'raw_unemployment') }} as s
{{ join_label('age', 's.age', 'age_l') }}
{{ join_label('sex', 's.sex', 'sex_l') }}
