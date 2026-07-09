-- FAIL if any bridge-mapped EC has null pathway_id in the enriched mart.
{{ config(severity='error') }}
SELECT ec_normalized, pathway_id
FROM {{ ref('mart_rpkm_enriched') }}
WHERE ec_normalized != '0.0.0.0'
  AND pathway_id IS NULL
  AND ec_normalized IN (
      SELECT DISTINCT ec_normalized
      FROM {{ source('reference', 'bridge_ec_pathway') }}
  )
