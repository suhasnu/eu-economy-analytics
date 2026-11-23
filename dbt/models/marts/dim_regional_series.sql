with series as (
    select distinct
        series_code,
        value_variable_code,
        series_label,
        breakdown_code,
        breakdown_label,
        unit_code
    from {{ ref('stg_regionalstatistik__observations') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['s.series_code']) }} as series_key,
    s.series_code,
    s.value_variable_code,
    s.series_label,
    s.breakdown_code,
    s.breakdown_label,
    -- || rather than concat, so a missing short label gives null (caught by not_null) instead of a shorter
    -- label that could pass for another series.
    case
        when s.breakdown_code is null then vv.short_label
        else vv.short_label || ' · ' || bd.short_label
    end as display_label,
    s.unit_code,
    r.unit_kind,
    r.aggregation,
    r.aggregation_short,
    r.aggregation_description
from series as s
left join {{ ref('unit_aggregation_rules') }} as r on r.unit_code = s.unit_code
{{ join_short_label('regional_value_variable', 's.value_variable_code', 'vv') }}
{{ join_short_label('regional_breakdown', 's.breakdown_code', 'bd') }}
