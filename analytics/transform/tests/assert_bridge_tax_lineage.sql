-- FAIL if bridge_tax_lineage is empty or any rank label column is entirely null.
{{ config(severity='error') }}
SELECT 1 AS failure
WHERE NOT EXISTS (SELECT 1 FROM {{ source('reference', 'bridge_tax_lineage') }} LIMIT 1)
   OR NOT EXISTS (
       SELECT 1 FROM {{ source('reference', 'bridge_tax_lineage') }}
       WHERE kingdom_label IS NOT NULL LIMIT 1
   )
   OR NOT EXISTS (
       SELECT 1 FROM {{ source('reference', 'bridge_tax_lineage') }}
       WHERE phylum_label IS NOT NULL LIMIT 1
   )
   OR NOT EXISTS (
       SELECT 1 FROM {{ source('reference', 'bridge_tax_lineage') }}
       WHERE class_label IS NOT NULL LIMIT 1
   )
   OR NOT EXISTS (
       SELECT 1 FROM {{ source('reference', 'bridge_tax_lineage') }}
       WHERE order_label IS NOT NULL LIMIT 1
   )
   OR NOT EXISTS (
       SELECT 1 FROM {{ source('reference', 'bridge_tax_lineage') }}
       WHERE family_label IS NOT NULL LIMIT 1
   )
   OR NOT EXISTS (
       SELECT 1 FROM {{ source('reference', 'bridge_tax_lineage') }}
       WHERE genus_label IS NOT NULL LIMIT 1
   )
   OR NOT EXISTS (
       SELECT 1 FROM {{ source('reference', 'bridge_tax_lineage') }}
       WHERE species_label IS NOT NULL LIMIT 1
   )
