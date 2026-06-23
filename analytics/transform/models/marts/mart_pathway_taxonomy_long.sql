WITH filtered AS (
    SELECT *
    FROM {{ ref('int_tax_rollup_resolved') }}
    WHERE pathway_level  = '{{ var("pathway_level") }}'
      AND requested_rank = '{{ var("tax_rank") }}'
)
{{ mart_pathway_taxonomy_agg('filtered') }}
