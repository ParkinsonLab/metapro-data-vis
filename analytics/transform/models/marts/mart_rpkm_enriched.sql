-- Enriched RPKM mart: int_rpkm_by_ec_tax grain with sample-scoped EC and taxonomy dims.
-- APIs read this table only (see spec §4.5).

SELECT
    r.sample_id,
    r.ec_normalized,
    r.source_tax_id,
    r.value,
    e.pathway_node_id,
    e.pathway_id,
    e.pathway_name,
    e.superpathway_id,
    e.superpathway_name,
    t.display_name,
    t.kingdom_id, t.kingdom_label,
    t.phylum_id,  t.phylum_label,
    t.class_id,   t.class_label,
    t.order_id,   t.order_label,
    t.family_id,  t.family_label,
    t.genus_id,   t.genus_label,
    t.species_id, t.species_label
FROM {{ ref('int_rpkm_by_ec_tax') }} r
LEFT JOIN {{ ref('dim_sample_ec') }} e USING (ec_normalized)
LEFT JOIN {{ ref('dim_sample_taxon') }} t USING (source_tax_id)
ORDER BY superpathway_id, pathway_id, ec_normalized, source_tax_id
