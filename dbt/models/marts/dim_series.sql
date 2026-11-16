with series as (
    select distinct
        dataset_name,
        indicator_code,
        unit_code,
        adjustment_code,
        breakdown_code,
        breakdown_label
    from {{ ref('stg_eurostat__observations') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['s.dataset_name', 's.unit_code', 's.adjustment_code', 's.breakdown_code']) }} as series_key,
    s.dataset_name,
    s.indicator_code,
    h.indicator_label,
    s.unit_code,
    {{ label_or_code('unit_l', 's.unit_code') }} as unit_label,
    s.adjustment_code,
    {{ label_or_code('adj_l', 's.adjustment_code') }} as adjustment_label,
    s.breakdown_code,
    s.breakdown_label,
    concat(
        h.indicator_label, ' | ', s.breakdown_label, ' | ',
        {{ label_or_code('unit_l', 's.unit_code') }}, ' | ',
        {{ label_or_code('adj_l', 's.adjustment_code') }}
    ) as series_label,
    coalesce(
        s.unit_code = h.headline_unit_code
        and s.adjustment_code = h.headline_adjustment_code
        and s.breakdown_code = h.headline_breakdown_code,
        false
    ) as is_headline,
    r.unit_kind,
    r.aggregation,
    r.aggregation_description
from series as s
left join {{ ref('indicator_headlines') }} as h on h.dataset_name = s.dataset_name
left join {{ ref('unit_aggregation_rules') }} as r on r.unit_code = s.unit_code
{{ join_label('unit', 's.unit_code', 'unit_l') }}
{{ join_label('s_adj', 's.adjustment_code', 'adj_l') }}
