"""Golden set v2: đúng lược đồ, không lỗi, nhãn thời gian khớp kho luật thật."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from app.eval.golden import TARGETS, group_counts, load_golden, validate

ROWS = load_golden()


def test_file_loads():
    assert len(ROWS) > 50
    assert all(r["id"] for r in ROWS)


def test_validate_is_clean():
    assert validate(ROWS) == []


def test_ids_are_unique():
    ids = [r["id"] for r in ROWS]
    assert len(ids) == len(set(ids))


def test_every_row_is_unreviewed():
    assert [r["id"] for r in ROWS if r["reviewed"] is not False] == []


def test_group_counts_cover_every_row():
    counts = group_counts(ROWS)
    assert set(counts) == set(TARGETS)
    assert sum(counts.values()) == len(ROWS)


def test_group_5_has_time_traps_with_event_dates():
    rows = [r for r in ROWS if r["group"] == 5]
    assert len(rows) >= 10
    assert [r["id"] for r in rows if not r["event_date"]] == []


def test_e03_carries_the_audit_note():
    rows = [r for r in ROWS if r["id"] == "E03"]
    assert len(rows) == 1
    assert "audit E03" in rows[0]["note"]
    assert rows[0]["expected_action"] == "refuse"


@pytest.mark.db
def test_validate_against_db(db):
    assert validate(ROWS, db) == []


@pytest.mark.db
def test_group_5_expected_nodes_are_in_force_on_event_date(db):
    rows = [r for r in ROWS if r["group"] == 5]
    for row in rows:
        when = date.fromisoformat(row["event_date"])
        for prov in row["expected_provisions"]:
            node = db.execute(
                text(
                    """
                    SELECT n.effective_from, n.effective_to, d.effective_date, d.expired_date
                    FROM legal_node n JOIN legal_document d ON d.doc_id = n.doc_id
                    WHERE n.node_id = :id
                    """
                ),
                {"id": prov["node_id"]},
            ).one()
            eff_from, eff_to, doc_from, doc_to = node
            assert eff_from is None or eff_from <= when, row["id"]
            assert eff_to is None or eff_to > when, row["id"]
            assert doc_from is None or doc_from <= when, row["id"]
            assert doc_to is None or doc_to > when, row["id"]
