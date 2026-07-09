{% macro aggregate_pathway_tax(from_relation, tax_level, ann_level) %}
SELECT
    sample_id,
    {{ resolve_tax_id(tax_level) }}       AS resolved_tax_id,
    {{ resolve_tax_label(tax_level) }}    AS resolved_tax_label,
    {{ canonical_pathway_label(
        ann_level,
        'ec_normalized',
        'pathway_id',
        'pathway_name',
        'superpathway_name'
    ) }}                                  AS pathway_label,
    SUM(value)                            AS value
FROM {{ from_relation }}
GROUP BY
    sample_id,
    {{ resolve_tax_id(tax_level) }},
    {{ resolve_tax_label(tax_level) }},
    {{ canonical_pathway_label(
        ann_level,
        'ec_normalized',
        'pathway_id',
        'pathway_name',
        'superpathway_name'
    ) }}
{% endmacro %}
