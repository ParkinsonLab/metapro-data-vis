WITH sample_ecs AS (
    SELECT DISTINCT ec_normalized FROM {{ ref('int_rpkm_by_ec_tax') }}
),
joined AS (
    SELECT
        s.ec_normalized,
        b.pathway_node_id,
        b.pathway_id,
        b.pathway_name,
        b.superpathway_id,
        b.superpathway_name,
        ROW_NUMBER() OVER (
            PARTITION BY s.ec_normalized
            ORDER BY b.pathway_node_id NULLS LAST
        ) AS rn
    FROM sample_ecs s
    LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
           ON s.ec_normalized = b.ec_normalized
)
SELECT
    ec_normalized,
    pathway_node_id,
    pathway_id,
    pathway_name,
    superpathway_id,
    superpathway_name
FROM joined
WHERE rn = 1
