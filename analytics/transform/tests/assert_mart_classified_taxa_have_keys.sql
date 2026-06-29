-- FAIL if any row has a real taxon label but null resolved_tax_id.
{{ config(severity='error') }}
SELECT resolved_tax_label, resolved_tax_id
FROM {{ ref('mart_pathway_taxonomy_long') }}
WHERE resolved_tax_label != 'Unclassified'
  AND resolved_tax_id IS NULL
