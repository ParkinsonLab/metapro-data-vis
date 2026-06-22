{{ config(severity='error') }}
SELECT gene_id, source_tax_id, value
FROM {{ ref('stg_rpkm_long') }}
WHERE value < 0
