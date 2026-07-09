{% macro _lineage_ref(rank, suffix, prefix='') -%}
{%- if prefix -%}{{ prefix }}.{{ rank }}_{{ suffix }}{%- else -%}{{ rank }}_{{ suffix }}{%- endif -%}
{%- endmacro %}
