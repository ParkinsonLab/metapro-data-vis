-- FAIL if bridge_tax_rollup does not have exactly 7 distinct requested_rank values.
{{ config(severity='error') }}
SELECT COUNT(DISTINCT requested_rank) AS n_ranks
FROM {{ source('reference', 'bridge_tax_rollup') }}
HAVING COUNT(DISTINCT requested_rank) != 7
