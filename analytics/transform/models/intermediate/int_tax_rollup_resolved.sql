-- Joins int_rpkm_pathway with bridge_tax_rollup on source_tax_id.
-- All 7 requested_rank values are stored — no resolution logic at upload.
-- Mart filters to the desired requested_rank + pathway_level.
-- Physical ordering: ORDER BY requested_rank, pathway_level, pathway_key
-- enables DuckDB zone-map skipping: ~6/7 row groups skipped per mart run (1 rank of 7 selected).
--
-- NOTE: source_tax_ids absent from bridge_tax_rollup produce requested_rank = NULL here.
-- These rows are excluded by the mart's WHERE requested_rank = var('tax_rank') filter.
-- The warn_rpkm_tax_id_resolvable test (Task 7) quantifies the affected mass.

SELECT
    p.sample_id,
    p.ec_normalized,
    p.source_tax_id,
    p.value,
    p.pathway_level,
    p.pathway_key,
    p.pathway_label,
    t.requested_rank,
    t.resolved_tax_id,
    t.resolved_tax_rank,
    t.resolved_tax_label
FROM {{ ref('int_rpkm_pathway') }} p
LEFT JOIN {{ source('reference', 'bridge_tax_rollup') }} t
       ON p.source_tax_id = t.source_tax_id
ORDER BY t.requested_rank, p.pathway_level, p.pathway_key
