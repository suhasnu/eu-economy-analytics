{# True when the whole of expr matches pattern. #}
{% macro regex_full_match(expr, pattern) %}{{ return(adapter.dispatch('regex_full_match')(expr, pattern)) }}{% endmacro %}

{% macro default__regex_full_match(expr, pattern) %}regexp_full_match({{ expr }}, '{{ pattern }}'){% endmacro %}

{% macro bigquery__regex_full_match(expr, pattern) %}regexp_contains({{ expr }}, r'^(?:{{ pattern }})$'){% endmacro %}
