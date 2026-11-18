-- Recount differences against the is_headline row, independently of how dim_series derives varies_in:
-- a named dimension must be the only difference, and null must mean two or more.
with diffs as (
    select
        s.series_key,
        s.varies_in,
        {%- for name, col in series_dimensions() %}
        case when s.{{ col }} is distinct from h.{{ col }} then 1 else 0 end as diff_{{ name }},
        {%- endfor %}
        0
        {%- for name, col in series_dimensions() %} + case when s.{{ col }} is distinct from h.{{ col }} then 1 else 0 end{% endfor %} as n_diff
    from {{ ref('dim_series') }} as s
    join {{ ref('dim_series') }} as h on h.dataset_name = s.dataset_name and h.is_headline
)
select series_key, varies_in, n_diff
from diffs
where (varies_in is null and n_diff < 2)
    or (varies_in = 'headline' and n_diff != 0)
    or (
        varies_in != 'headline'
        and not (
            n_diff = 1
            and case varies_in
                {%- for name, col in series_dimensions() %}
                when '{{ name }}' then diff_{{ name }}
                {%- endfor %}
            end = 1
        )
    )
