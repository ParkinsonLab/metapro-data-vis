-- WARN if any source_tax_id has no row in bridge_tax_rollup (tax_id not in reference).
{{ config(severity='warn') }}
SELECT DISTINCT s.source_tax_id
FROM {{ ref('stg_rpkm_long') }} s
LEFT JOIN {{ source('reference', 'bridge_tax_rollup') }} b
       ON s.source_tax_id = b.source_tax_id
WHERE b.source_tax_id IS NULL
