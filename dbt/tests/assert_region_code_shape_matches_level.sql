select region_code, region_level
from {{ ref('dim_region') }}
where not coalesce(
    case region_level
        when 'national' then {{ regex_full_match('region_code', 'DG') }}
        when 'land' then {{ regex_full_match('region_code', '[0-9]{2}') }}
        when 'kreis' then {{ regex_full_match('region_code', '[0-9]{5}') }}
    end,
    false
)
