{{ config(severity='error') }}
-- Fails when mart_rpkm_enriched has no rows. User-facing text is derived from the test name
-- in analytics/testing/dbt_failure_messages.py.
SELECT COUNT(*) AS row_count
FROM {{ ref('mart_rpkm_enriched') }}
HAVING COUNT(*) = 0
