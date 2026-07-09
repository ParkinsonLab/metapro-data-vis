{% macro resolve_tax_label(tax_level, prefix='') %}
CASE '{{ tax_level }}'
  WHEN 'species' THEN COALESCE(
    {{ _lineage_ref('species', 'label', prefix) }},
    {{ _lineage_ref('genus', 'label', prefix) }},
    {{ _lineage_ref('family', 'label', prefix) }},
    {{ _lineage_ref('order', 'label', prefix) }},
    {{ _lineage_ref('class', 'label', prefix) }},
    {{ _lineage_ref('phylum', 'label', prefix) }},
    {{ _lineage_ref('kingdom', 'label', prefix) }},
    'Unclassified'
  )
  WHEN 'genus' THEN COALESCE(
    {{ _lineage_ref('genus', 'label', prefix) }},
    {{ _lineage_ref('family', 'label', prefix) }},
    {{ _lineage_ref('order', 'label', prefix) }},
    {{ _lineage_ref('class', 'label', prefix) }},
    {{ _lineage_ref('phylum', 'label', prefix) }},
    {{ _lineage_ref('kingdom', 'label', prefix) }},
    'Unclassified'
  )
  WHEN 'family' THEN COALESCE(
    {{ _lineage_ref('family', 'label', prefix) }},
    {{ _lineage_ref('order', 'label', prefix) }},
    {{ _lineage_ref('class', 'label', prefix) }},
    {{ _lineage_ref('phylum', 'label', prefix) }},
    {{ _lineage_ref('kingdom', 'label', prefix) }},
    'Unclassified'
  )
  WHEN 'order' THEN COALESCE(
    {{ _lineage_ref('order', 'label', prefix) }},
    {{ _lineage_ref('class', 'label', prefix) }},
    {{ _lineage_ref('phylum', 'label', prefix) }},
    {{ _lineage_ref('kingdom', 'label', prefix) }},
    'Unclassified'
  )
  WHEN 'class' THEN COALESCE(
    {{ _lineage_ref('class', 'label', prefix) }},
    {{ _lineage_ref('phylum', 'label', prefix) }},
    {{ _lineage_ref('kingdom', 'label', prefix) }},
    'Unclassified'
  )
  WHEN 'phylum' THEN COALESCE(
    {{ _lineage_ref('phylum', 'label', prefix) }},
    {{ _lineage_ref('kingdom', 'label', prefix) }},
    'Unclassified'
  )
  WHEN 'kingdom' THEN COALESCE(
    {{ _lineage_ref('kingdom', 'label', prefix) }},
    'Unclassified'
  )
END
{% endmacro %}
