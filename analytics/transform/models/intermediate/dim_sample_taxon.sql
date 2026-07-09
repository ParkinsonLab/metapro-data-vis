WITH sample_tax_ids AS (
    SELECT DISTINCT source_tax_id FROM {{ ref('int_rpkm_by_ec_tax') }}
)
SELECT
    s.source_tax_id,
    COALESCE(b.display_name, CAST(s.source_tax_id AS VARCHAR)) AS display_name,
    b.kingdom_id, b.kingdom_label,
    b.phylum_id,  b.phylum_label,
    b.class_id,   b.class_label,
    b.order_id,   b.order_label,
    b.family_id,  b.family_label,
    b.genus_id,   b.genus_label,
    b.species_id, b.species_label
FROM sample_tax_ids s
LEFT JOIN {{ source('reference', 'bridge_tax_lineage') }} b
       ON s.source_tax_id = b.tax_id
