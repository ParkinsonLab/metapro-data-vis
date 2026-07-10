-- WARN if any sample tax_id is unknown to bridge_tax_lineage (no lineage resolved).
{{ config(severity='warn') }}
SELECT source_tax_id, display_name
FROM {{ ref('dim_sample_taxon') }}
WHERE display_name = CAST(source_tax_id AS VARCHAR)
  AND kingdom_id IS NULL
  AND phylum_id IS NULL
  AND class_id IS NULL
  AND order_id IS NULL
  AND family_id IS NULL
  AND genus_id IS NULL
  AND species_id IS NULL
