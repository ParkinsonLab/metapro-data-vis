-- LEFT JOIN with bridge_ec_pathway; UNION ALL three pathway levels.
-- Each branch SELECT DISTINCT deduplicates fan-out at the level's grain.
-- Unmapped ECs (pathway_key IS NULL) appear once per pathway_level.
-- Physical ordering: ORDER BY pathway_level, pathway_key for zone-map skipping.

WITH base AS (
    SELECT * FROM {{ ref('int_rpkm_by_ec_tax') }}
),
superpathway_branch AS (
    SELECT DISTINCT
        base.sample_id,
        base.ec_normalized,
        base.source_tax_id,
        base.value,
        'superpathway'                                  AS pathway_level,
        CAST(b.superpathway_id AS VARCHAR)              AS pathway_key,
        b.superpathway_name                             AS pathway_label
    FROM base
    LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
           ON base.ec_normalized = b.ec_normalized
),
pathway_branch AS (
    SELECT DISTINCT
        base.sample_id,
        base.ec_normalized,
        base.source_tax_id,
        base.value,
        'pathway'                                       AS pathway_level,
        CAST(b.pathway_id AS VARCHAR)                   AS pathway_key,
        b.pathway_name                                  AS pathway_label
    FROM base
    LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
           ON base.ec_normalized = b.ec_normalized
),
pathway_node_branch AS (
    SELECT DISTINCT
        base.sample_id,
        base.ec_normalized,
        base.source_tax_id,
        base.value,
        'pathway_node'                                  AS pathway_level,
        b.pathway_node_id                               AS pathway_key,
        NULL::VARCHAR                                   AS pathway_label
    FROM base
    LEFT JOIN {{ source('reference', 'bridge_ec_pathway') }} b
           ON base.ec_normalized = b.ec_normalized
)

SELECT * FROM superpathway_branch
UNION ALL
SELECT * FROM pathway_branch
UNION ALL
SELECT * FROM pathway_node_branch
ORDER BY pathway_level, pathway_key
