select
    s.region_level,
    s.geo as region_code,
    s.geo_label as region_name,
    cast(s.time as integer) as year,
    s.indicator_code as series_code,
    s.value_variable_code,
    s.series_label,
    s.breakdown_code,
    s.breakdown_label,
    s.unit as unit_code,
    s.value,
    s.status
from {{ source('regionalstatistik_raw', 'raw_regionalstatistik') }} as s
