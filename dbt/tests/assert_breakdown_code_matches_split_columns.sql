-- Rebuild breakdown_code from the split columns; staging packs dimensions in alphabetical order.
with rebuilt as (
    select
        series_key,
        breakdown_code,
        substr(
            ''
            {%- for d in breakdown_dimensions() | sort %}
            || coalesce('|{{ d }}=' || {{ d }}_code, '')
            {%- endfor %},
            2
        ) as rebuilt_code
    from {{ ref('dim_series') }}
)
select series_key, breakdown_code, rebuilt_code
from rebuilt
where rebuilt_code != breakdown_code
