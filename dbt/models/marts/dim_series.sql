{# breakdown_code is 'dim=code|dim=code'; no dataset has more than two breakdown dims.
   A part dropped here would make short labels collide, which the unique test catches. #}
{% set n_parts = 2 %}

with series as (
    select distinct
        dataset_name,
        indicator_code,
        unit_code,
        adjustment_code,
        breakdown_code,
        breakdown_label
    from {{ ref('stg_eurostat__observations') }}
),

parts as (
    select
        s.*
        {%- for i in range(1, n_parts + 1) %},
        nullif({{ dbt.split_part(dbt.split_part('s.breakdown_code', "'|'", i), "'='", 1) }}, '') as part_{{ i }}_dimension,
        nullif({{ dbt.split_part(dbt.split_part('s.breakdown_code', "'|'", i), "'='", 2) }}, '') as part_{{ i }}_code
        {%- endfor %}
    from series as s
),

-- A part belongs in the short label only if it takes more than one value within the dataset.
varying as (
    select
        dataset_name,
        count(distinct unit_code) > 1 as unit_varies,
        count(distinct adjustment_code) > 1 as adjustment_varies
        {%- for i in range(1, n_parts + 1) %},
        count(distinct part_{{ i }}_code) > 1 as part_{{ i }}_varies
        {%- endfor %}
    from parts
    group by dataset_name
),

labelled as (
    select
        p.*,
        h.indicator_label,
        h.indicator_short_label,
        h.headline_unit_code,
        h.headline_adjustment_code,
        h.headline_breakdown_code,
        {{ label_or_code('unit_l', 'p.unit_code') }} as unit_label,
        {{ label_or_code('adj_l', 'p.adjustment_code') }} as adjustment_label,
        coalesce(unit_s.short_label, unit_l.label, p.unit_code) as unit_short,
        coalesce(adj_s.short_label, adj_l.label, p.adjustment_code) as adjustment_short,
        {%- for i in range(1, n_parts + 1) %}
        coalesce(p{{ i }}_s.short_label, p{{ i }}_l.label, p.part_{{ i }}_code) as part_{{ i }}_short,
        {%- endfor %}
        v.unit_varies,
        v.adjustment_varies
        {%- for i in range(1, n_parts + 1) %},
        v.part_{{ i }}_varies
        {%- endfor %}
    from parts as p
    left join {{ ref('indicator_headlines') }} as h on h.dataset_name = p.dataset_name
    left join varying as v on v.dataset_name = p.dataset_name
    {{ join_label('unit', 'p.unit_code', 'unit_l') }}
    {{ join_label('s_adj', 'p.adjustment_code', 'adj_l') }}
    {{ join_short_label('unit', 'p.unit_code', 'unit_s') }}
    {{ join_short_label('s_adj', 'p.adjustment_code', 'adj_s') }}
    {%- for i in range(1, n_parts + 1) %}
    left join {{ ref('eurostat_code_labels') }} as p{{ i }}_l
        on p{{ i }}_l.dimension = p.part_{{ i }}_dimension and p{{ i }}_l.code = p.part_{{ i }}_code
    left join {{ ref('code_short_labels') }} as p{{ i }}_s
        on p{{ i }}_s.dimension = p.part_{{ i }}_dimension and p{{ i }}_s.code = p.part_{{ i }}_code
    {%- endfor %}
)

select
    {{ dbt_utils.generate_surrogate_key(['s.dataset_name', 's.unit_code', 's.adjustment_code', 's.breakdown_code']) }} as series_key,
    s.dataset_name,
    s.indicator_code,
    s.indicator_label,
    s.unit_code,
    s.unit_label,
    s.unit_short as unit_short_label,
    s.adjustment_code,
    s.adjustment_label,
    s.breakdown_code,
    s.breakdown_label,
    concat(
        s.indicator_label, ' | ', s.breakdown_label, ' | ',
        s.unit_label, ' | ', s.adjustment_label
    ) as series_label,
    -- || rather than concat: DuckDB's concat skips nulls, and a skipped piece must drop its separator too.
    s.indicator_short_label
    {%- for piece in range(1, n_parts + 1) %}
        || coalesce(' · ' || case when s.part_{{ piece }}_varies then s.part_{{ piece }}_short end, '')
    {%- endfor %}
        || coalesce(' · ' || case when s.unit_varies then s.unit_short end, '')
        || coalesce(' · ' || case when s.adjustment_varies then s.adjustment_short end, '')
    as short_label,
    coalesce(
        s.unit_code = s.headline_unit_code
        and s.adjustment_code = s.headline_adjustment_code
        and s.breakdown_code = s.headline_breakdown_code,
        false
    ) as is_headline,
    r.unit_kind,
    r.aggregation,
    r.aggregation_description
from labelled as s
left join {{ ref('unit_aggregation_rules') }} as r on r.unit_code = s.unit_code
