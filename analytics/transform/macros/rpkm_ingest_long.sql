{# analytics/transform/macros/rpkm_ingest_long.sql #}
{% macro rpkm_ingest_long() %}
{% set rpkm_path = var('rpkm_path') %}
{% set sample_id = var('sample_id') %}
{% if not rpkm_path %}
    {{ exceptions.raise_compiler_error("dbt var 'rpkm_path' is required") }}
{% endif %}
{% if not sample_id %}
    {{ exceptions.raise_compiler_error("dbt var 'sample_id' is required") }}
{% endif %}
{% set safe_path = rpkm_path | replace("'", "''") %}
{% set safe_sample_id = sample_id | replace("'", "''") %}
        WITH wide AS (
            SELECT *
            FROM read_csv(
                '{{ safe_path }}',
                sep = '\t',
                header = true,
                all_varchar = true,
                nullstr = ['', 'NA', 'null', 'NULL', 'None', 'none']
            )
        ),
        unpivoted AS (
            UNPIVOT wide
            ON COLUMNS(* EXCLUDE ("GeneID", "Length", "Reads", "EC#", "RPKM", "Unclassified"))
            INTO NAME source_tax_id_col VALUE value_str
        ),
        normalized AS (
            SELECT
                '{{ safe_sample_id }}'::VARCHAR                          AS sample_id,
                "GeneID"                                                AS gene_id,
                CASE
                    WHEN "EC#" IS NULL                                  THEN '0.0.0.0'
                    WHEN UPPER("EC#") LIKE 'EC:%'                       THEN TRIM(SUBSTRING("EC#", 4))
                    ELSE "EC#"
                END                                                     AS ec_normalized,
                TRY_CAST(source_tax_id_col AS BIGINT)                   AS source_tax_id,
                TRY_CAST(value_str AS DOUBLE)                           AS value
            FROM unpivoted
        )
        SELECT sample_id, gene_id, ec_normalized, source_tax_id, value
        FROM normalized
        WHERE value > 0
          AND source_tax_id IS NOT NULL
{% endmacro %}
