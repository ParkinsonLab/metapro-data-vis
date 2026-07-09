WITH sample_ecs AS (
    SELECT DISTINCT ec_normalized FROM {{ ref('int_rpkm_by_ec_tax') }}
)
SELECT DISTINCT
    s.ec_normalized,
    b.pathway_node_id,
    b.pathway_id,
    b.pathway_name,
    b.superpathway_id,
    b.superpathway_name
FROM sample_ecs s
LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
       ON s.ec_normalized = b.ec_normalized
