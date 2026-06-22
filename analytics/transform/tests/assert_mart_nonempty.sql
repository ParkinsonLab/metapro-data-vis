{{ config(severity='error') }}
SELECT COUNT(*) AS row_count
FROM {{ ref('mart_pathway_taxonomy_long') }}
HAVING COUNT(*) = 0
