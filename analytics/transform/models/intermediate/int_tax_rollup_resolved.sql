-- Joins int_rpkm_pathway with bridge_tax_rollup on source_tax_id.
-- All 7 requested_rank values are stored — no resolution logic at upload.
-- Mart filters to the desired requested_rank + pathway_level.
-- Physical ordering: ORDER BY requested_rank, pathway_level, pathway_key
-- enables DuckDB zone-map skipping (~20/21 row groups per mart run).

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
