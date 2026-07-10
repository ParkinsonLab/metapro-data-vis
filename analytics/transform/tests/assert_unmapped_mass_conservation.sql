-- WARN if the unmapped value total in the mart differs from the upstream
-- unmapped total by more than 0.01%.
-- Unmapped upstream = ec_tax rows whose ec_normalized has no bridge match.
-- Unmapped mart = rows where pathway_id IS NULL.
{{ config(severity='warn') }}

WITH upstream_unmapped AS (
    SELECT SUM(value) AS total
    FROM {{ ref('int_rpkm_by_ec_tax') }}
    WHERE ec_normalized NOT IN (
        SELECT DISTINCT ec_normalized FROM {{ source('reference', 'bridge_ec_pathway') }}
    )
),
mart_unmapped AS (
    SELECT SUM(value) AS total
    FROM {{ ref('mart_rpkm_enriched') }}
    WHERE pathway_id IS NULL
),
comparison AS (
    SELECT
        u.total                     AS upstream_total,
        m.total                     AS mart_total,
        ABS(u.total - m.total)
            / NULLIF(u.total, 0)    AS relative_delta
    FROM upstream_unmapped u, mart_unmapped m
)
SELECT upstream_total, mart_total, relative_delta
FROM comparison
WHERE relative_delta > 0.0001
   OR upstream_total IS NULL
   OR mart_total IS NULL
