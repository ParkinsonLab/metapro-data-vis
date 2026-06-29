-- Collapse multiple genes with the same (ec_normalized, source_tax_id) before pathway join.
-- Gene aggregation step — see spec §5.1.

SELECT
    sample_id,
    ec_normalized,
    source_tax_id,
    SUM(value) AS value
FROM {{ ref('stg_rpkm_long') }}
GROUP BY sample_id, ec_normalized, source_tax_id
