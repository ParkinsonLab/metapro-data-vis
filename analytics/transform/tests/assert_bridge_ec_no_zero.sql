-- FAIL if any bridge row has ec_normalized = '0.0.0.0' (false-mapping guard).
{{ config(severity='error') }}
SELECT ec_normalized
FROM {{ source('reference', 'bridge_ec_pathway') }}
WHERE ec_normalized = '0.0.0.0'
