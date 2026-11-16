{# Eurostat monthly periods arrive as 'YYYY-MM'. #}
{% macro month_start(period_col) %}cast(concat({{ period_col }}, '-01') as date){% endmacro %}

{# Left join to the label seed for one dimension; select `<alias>.label` afterwards. #}
{% macro join_label(dimension, code_col, alias) %}
left join {{ ref('eurostat_code_labels') }} as {{ alias }}
  on {{ alias }}.dimension = '{{ dimension }}' and {{ alias }}.code = {{ code_col }}
{% endmacro %}

{% macro label_or_code(alias, code_col) %}coalesce({{ alias }}.label, {{ code_col }}){% endmacro %}

{# Left join to the hand-maintained short label seed; select `<alias>.short_label` afterwards. #}
{% macro join_short_label(dimension, code_col, alias) %}
left join {{ ref('code_short_labels') }} as {{ alias }}
  on {{ alias }}.dimension = '{{ dimension }}' and {{ alias }}.code = {{ code_col }}
{% endmacro %}
