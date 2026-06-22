-- Filters int_tax_rollup_resolved to the configured (pathway_level, tax_rank) slice,
-- then aggregates by pathway + resolved taxon.
--
-- GROUP BY uses IDs only; labels are carried via ANY_VALUE() since they are
-- functionally dependent on their IDs.
--
-- IMPORTANT: WHERE requested_rank = var('tax_rank') is the correctness guard.
-- Without it, the same resolved_tax_id could appear for multiple requested_rank values
-- (exact at 'class', fallback at 'phylum'), causing double-counting.
--
-- ec_normalized is NOT in the GROUP BY or output: all unmapped ECs for the same taxon
-- collapse into one 'Unmapped EC' bucket per pathway_key IS NULL + resolved_tax_id.

SELECT
    sample_id,
    pathway_level,
    pathway_key,
    ANY_VALUE(COALESCE(pathway_label, 'Unmapped EC'))   AS pathway_label,
    resolved_tax_id,
    ANY_VALUE(resolved_tax_label)                       AS resolved_tax_label,
    ANY_VALUE(resolved_tax_rank)                        AS resolved_tax_rank,
    SUM(value)                                          AS value
FROM {{ ref('int_tax_rollup_resolved') }}
WHERE pathway_level  = '{{ var("pathway_level") }}'
  AND requested_rank = '{{ var("tax_rank") }}'
GROUP BY sample_id, pathway_level, pathway_key, resolved_tax_id
