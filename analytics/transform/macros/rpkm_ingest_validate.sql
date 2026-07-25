{# analytics/transform/macros/rpkm_ingest_validate.sql #}
{% macro rpkm_ingest_validate_sql(rpkm_path, sample_id) %}
{% set safe_path = rpkm_path | replace("'", "''") %}
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
        cols AS (
            SELECT column_name
            FROM (DESCRIBE SELECT * FROM wide)
        ),
        required AS (
            SELECT unnest(['GeneID', 'Length', 'Reads', 'EC#', 'RPKM']) AS col
        ),
        missing AS (
            SELECT r.col
            FROM required r
            LEFT JOIN cols c ON c.column_name = r.col
            WHERE c.column_name IS NULL
        ),
        stats AS (
            SELECT
                (SELECT COUNT(*) FROM wide) AS row_count,
                (SELECT string_agg(col, ', ' ORDER BY col) FROM missing) AS missing_cols
        )
        SELECT
            CASE
                WHEN row_count = 0 THEN error('RPKM file is empty')
                WHEN missing_cols IS NOT NULL THEN error(
                    'RPKM file missing required columns: ' || missing_cols
                )
                ELSE 1
            END AS ok
        FROM stats
{% endmacro %}

{% macro rpkm_ingest_validate() %}
{% set rpkm_path = var('rpkm_path') %}
{% set sample_id = var('sample_id') %}
{% if not rpkm_path %}
    {{ exceptions.raise_compiler_error("dbt var 'rpkm_path' is required") }}
{% endif %}
{% if not sample_id %}
    {{ exceptions.raise_compiler_error("dbt var 'sample_id' is required") }}
{% endif %}
{% do run_query(rpkm_ingest_validate_sql(rpkm_path, sample_id)) %}
{% endmacro %}
