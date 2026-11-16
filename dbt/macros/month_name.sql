{% macro month_name(date_expr) %}{{ return(adapter.dispatch('month_name')(date_expr)) }}{% endmacro %}

{% macro default__month_name(date_expr) %}monthname({{ date_expr }}){% endmacro %}

{% macro bigquery__month_name(date_expr) %}format_date('%B', {{ date_expr }}){% endmacro %}
