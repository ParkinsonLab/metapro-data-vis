{% macro canonical_pathway_label(ann_level, ec_col, pathway_id_col, pathway_name_col, superpathway_name_col) %}
CASE
  WHEN {{ ec_col }} = '0.0.0.0' OR {{ pathway_id_col }} IS NULL THEN 'Unmapped EC'
  WHEN '{{ ann_level }}' = 'pathway_node' THEN {{ ec_col }}
  WHEN '{{ ann_level }}' = 'superpathway' THEN {{ superpathway_name_col }}
  ELSE {{ pathway_name_col }}
END
{% endmacro %}
