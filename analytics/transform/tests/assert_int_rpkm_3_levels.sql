-- FAIL if int_rpkm_pathway does not contain exactly 3 distinct pathway_level values.
-- Guards against UNION ALL branch being accidentally dropped.
{{ config(severity='error') }}
SELECT COUNT(DISTINCT pathway_level) AS n_levels
FROM {{ ref('int_rpkm_pathway') }}
HAVING COUNT(DISTINCT pathway_level) != 3
