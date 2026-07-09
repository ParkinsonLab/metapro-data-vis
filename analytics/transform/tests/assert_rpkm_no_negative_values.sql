{{ config(severity='error') }}
SELECT ec_normalized, source_tax_id, value
FROM {{ ref('int_rpkm_by_ec_tax') }}
WHERE value < 0
