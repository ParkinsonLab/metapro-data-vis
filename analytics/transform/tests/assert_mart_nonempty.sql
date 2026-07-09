{{ config(severity='error') }}
SELECT COUNT(*) AS row_count
FROM {{ ref('mart_rpkm_enriched') }}
HAVING COUNT(*) = 0
