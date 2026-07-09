-- FAIL if any aggregated row has a real taxon label but null resolved_tax_id.
{{ config(severity='error') }}
WITH agg AS (
    {{ aggregate_pathway_tax(ref('mart_rpkm_enriched'), var('tax_rank'), var('pathway_level')) }}
)
SELECT resolved_tax_label, resolved_tax_id
FROM agg
WHERE resolved_tax_label != 'Unclassified'
  AND resolved_tax_id IS NULL
