{#
  Use the model's configured +schema name verbatim (bronze / silver / gold)
  instead of dbt's default "<target>_<schema>" concatenation. This keeps the
  medallion layers in clean, predictable schemas that the KPI registry and the
  retrieval layer can address as gold.<table>.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
