"""T1 — provision_version, transition_rule, legal_link trên kho thật."""

from datetime import date

import pytest
from sqlalchemy import text

from app.amend.store import law_as_of
from app.amend.versions import (
    STATUSES,
    backfill,
    create_tables,
    in_force_at,
    status_at,
    versions_for,
)
from app.db.base import engine

TODAY = date(2026, 11, 16)


@pytest.fixture(scope="module", autouse=True)
def _tables(db):
    create_tables(engine)


def _count(db, table: str) -> int:
    return db.execute(text(f"SELECT count(*) FROM {table}")).scalar() or 0


def test_status_at_before_inside_after():
    assert status_at(date(2021, 1, 1), None, date(2020, 6, 1)) == "not_yet_in_force"
    assert status_at(date(2021, 1, 1), None, date(2021, 1, 1)) == "in_force"
    assert status_at(date(2013, 5, 1), date(2021, 1, 1), date(2020, 6, 1)) == "in_force"
    assert status_at(date(2013, 5, 1), date(2021, 1, 1), date(2021, 1, 1)) == "repealed"
    assert status_at(None, None, date(2022, 1, 1)) == "in_force"
    assert set(STATUSES) == {
        "in_force",
        "partly_in_force",
        "pending_amendment",
        "not_yet_in_force",
        "repealed",
    }


@pytest.mark.db
def test_backfill_one_version_per_non_upload_node(db):
    counts = backfill(db, today=TODAY)
    expected = db.execute(
        text(
            "SELECT count(*) FROM legal_node n JOIN legal_document d ON d.doc_id = n.doc_id "
            "WHERE coalesce(d.doc_type, '') <> 'upload'"
        )
    ).scalar()
    assert counts["provision_version"] == expected
    assert _count(db, "provision_version") == expected

    old = [tuple(r) for r in db.execute(
        text("SELECT DISTINCT valid_to, status FROM provision_version WHERE doc_id = 'blld2012'")
    )]
    assert old == [(date(2021, 1, 1), "repealed")]

    new = [tuple(r) for r in db.execute(
        text("SELECT DISTINCT valid_to, status FROM provision_version WHERE doc_id = 'blld2019'")
    )]
    assert new == [(None, "in_force")]

    assert [v["status"] for v in versions_for(db, "blld2019-d220")] == ["in_force"]


@pytest.mark.db
def test_backfill_twice_gives_same_counts(db):
    backfill(db, today=TODAY)
    first = {t: _count(db, t) for t in ("provision_version", "legal_link", "transition_rule")}
    backfill(db, today=TODAY)
    second = {t: _count(db, t) for t in ("provision_version", "legal_link", "transition_rule")}
    assert second == first


@pytest.mark.db
def test_in_force_at_switches_from_2012_to_2019_code(db):
    backfill(db, today=TODAY)
    old = in_force_at(db, date(2020, 6, 1))
    assert any(k.startswith("blld2012-") for k in old)
    assert not any(k.startswith("blld2019-") for k in old)

    new = in_force_at(db, date(2022, 1, 1))
    assert any(k.startswith("blld2019-") for k in new)
    assert not any(k.startswith("blld2012-") for k in new)


@pytest.mark.db
def test_seed_link_and_transition_rule(db):
    backfill(db, today=TODAY)
    seed = [
        tuple(r)
        for r in db.execute(
            text(
                "SELECT valid_from, source FROM legal_link WHERE from_key = 'nd145_2020' "
                "AND to_key = 'blld2019' AND link_type = 'guides'"
            )
        )
    ]
    assert seed == [(date(2021, 2, 1), "seed")]
    assert _count_link_cites(db) >= 1

    rule = db.execute(
        text("SELECT doc_key, outcome, provision_ref, note FROM transition_rule")
    ).one()
    assert rule.doc_key == "blld2019"
    assert rule.outcome == "mixed"
    assert rule.provision_ref == "blld2019-d220"
    assert "cần đối chiếu" in rule.note


def _count_link_cites(db) -> int:
    return db.execute(text("SELECT count(*) FROM legal_link WHERE link_type = 'cites'")).scalar() or 0


@pytest.mark.db
def test_law_as_of_unchanged_by_backfill(db):
    day = date(2020, 6, 1)
    before = len(law_as_of(db, day))
    backfill(db, today=TODAY)
    assert len(law_as_of(db, day)) == before
