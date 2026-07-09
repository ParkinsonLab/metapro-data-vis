-- Wide RPKM TSV → EC × tax_id grain. Ingest via rpkm_ingest_long(); no materialized staging table.
-- Gene aggregation: SUM(value) per (sample_id, ec_normalized, source_tax_id).

WITH long AS (
    {{ rpkm_ingest_long() }}
)
SELECT
    sample_id,
    ec_normalized,
    source_tax_id,
    SUM(value) AS value
FROM long
GROUP BY sample_id, ec_normalized, source_tax_id
