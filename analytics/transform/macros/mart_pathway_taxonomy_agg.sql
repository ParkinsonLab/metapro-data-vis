{% macro mart_pathway_taxonomy_agg(from_relation) %}
SELECT
    sample_id,
    pathway_level,
    pathway_key,
    ANY_VALUE(COALESCE(pathway_label, 'Unmapped EC'))   AS pathway_label,
    resolved_tax_id,
    ANY_VALUE(resolved_tax_label)                       AS resolved_tax_label,
    ANY_VALUE(resolved_tax_rank)                        AS resolved_tax_rank,
    SUM(value)                                          AS value
FROM {{ from_relation }}
GROUP BY sample_id, pathway_level, pathway_key, resolved_tax_id
{% endmacro %}
