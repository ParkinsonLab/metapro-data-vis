-- FAIL if any row has a real pathway name but null pathway_key.
{{ config(severity='error') }}
SELECT pathway_label, pathway_key
FROM {{ ref('mart_pathway_taxonomy_long') }}
WHERE pathway_label != 'Unmapped EC'
  AND pathway_key IS NULL
