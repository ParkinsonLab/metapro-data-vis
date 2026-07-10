from __future__ import annotations

import pytest

from api.ann_order import ann_labels_ordered
from testing.fake_rpkm_fixture import SAMPLE_ID, bridges_available, skip_reason

pytestmark = pytest.mark.skipif(not bridges_available(), reason=skip_reason())


def _db_conn(fake_rpkm_db):
    import duckdb
    from pathlib import Path

    db = Path(__file__).resolve().parents[2] / f"transform/runs/{SAMPLE_ID}/sample.duckdb"
    return duckdb.connect(str(db), read_only=True)


def test_ann_labels_ordered_superpathway_alphabetical(fake_rpkm_db):
    conn = _db_conn(fake_rpkm_db)
    try:
        labels = ann_labels_ordered(
            conn, ann_level="superpathway", where_sql="TRUE", params=[]
        )
        assert labels == sorted(labels)
        assert len(labels) > 0
    finally:
        conn.close()


def test_ann_labels_ordered_pathway_hierarchical(fake_rpkm_db):
    conn = _db_conn(fake_rpkm_db)
    try:
        labels = ann_labels_ordered(
            conn, ann_level="pathway", where_sql="TRUE", params=[]
        )
        assert len(labels) > 1
        expected = [
            r[0]
            for r in conn.execute(
                """
                SELECT display_label FROM (
                    SELECT DISTINCT
                        superpathway_name,
                        pathway_name,
                        CASE
                          WHEN ec_normalized = '0.0.0.0' OR pathway_id IS NULL
                          THEN 'Unmapped EC'
                          ELSE pathway_name
                        END AS display_label
                    FROM mart_rpkm_enriched
                )
                ORDER BY superpathway_name ASC NULLS LAST, pathway_name ASC NULLS LAST
                """
            ).fetchall()
        ]
        assert labels == expected
    finally:
        conn.close()
