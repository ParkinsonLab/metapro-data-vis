{% macro resolve_tax_id(tax_level, prefix='') %}
CASE '{{ tax_level }}'
  WHEN 'species' THEN COALESCE(
    {{ _lineage_ref('species', 'id', prefix) }},
    {{ _lineage_ref('genus', 'id', prefix) }},
    {{ _lineage_ref('family', 'id', prefix) }},
    {{ _lineage_ref('order', 'id', prefix) }},
    {{ _lineage_ref('class', 'id', prefix) }},
    {{ _lineage_ref('phylum', 'id', prefix) }},
    {{ _lineage_ref('kingdom', 'id', prefix) }}
  )
  WHEN 'genus' THEN COALESCE(
    {{ _lineage_ref('genus', 'id', prefix) }},
    {{ _lineage_ref('family', 'id', prefix) }},
    {{ _lineage_ref('order', 'id', prefix) }},
    {{ _lineage_ref('class', 'id', prefix) }},
    {{ _lineage_ref('phylum', 'id', prefix) }},
    {{ _lineage_ref('kingdom', 'id', prefix) }}
  )
  WHEN 'family' THEN COALESCE(
    {{ _lineage_ref('family', 'id', prefix) }},
    {{ _lineage_ref('order', 'id', prefix) }},
    {{ _lineage_ref('class', 'id', prefix) }},
    {{ _lineage_ref('phylum', 'id', prefix) }},
    {{ _lineage_ref('kingdom', 'id', prefix) }}
  )
  WHEN 'order' THEN COALESCE(
    {{ _lineage_ref('order', 'id', prefix) }},
    {{ _lineage_ref('class', 'id', prefix) }},
    {{ _lineage_ref('phylum', 'id', prefix) }},
    {{ _lineage_ref('kingdom', 'id', prefix) }}
  )
  WHEN 'class' THEN COALESCE(
    {{ _lineage_ref('class', 'id', prefix) }},
    {{ _lineage_ref('phylum', 'id', prefix) }},
    {{ _lineage_ref('kingdom', 'id', prefix) }}
  )
  WHEN 'phylum' THEN COALESCE(
    {{ _lineage_ref('phylum', 'id', prefix) }},
    {{ _lineage_ref('kingdom', 'id', prefix) }}
  )
  WHEN 'kingdom' THEN {{ _lineage_ref('kingdom', 'id', prefix) }}
END
{% endmacro %}
