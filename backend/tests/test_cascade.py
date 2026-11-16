"""T3 — cờ "cần xác minh" lan truyền + độ tươi của kho văn bản."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import delete

from app.amend.cascade import (
    FRESH_DAYS,
    FRESH_DAYS_SANCTION,
    corpus_freshness,
    needs_verification,
)
from app.db.models import LegalDocument, LegalLink

TEST_DOC = "test_guide_doc"


@pytest.fixture
def guide_doc(db):
    """Văn bản thử còn hiệu lực, hướng dẫn BLLĐ 2012 (hết hiệu lực 2021-01-01)."""
    db.execute(delete(LegalLink).where(LegalLink.from_key == TEST_DOC))
    db.execute(delete(LegalDocument).where(LegalDocument.doc_id == TEST_DOC))
    db.add(
        LegalDocument(
            doc_id=TEST_DOC,
            title="Văn bản thử hướng dẫn",
            doc_type="nghi_dinh",
            number="01/TEST",
            effective_date=date(2013, 5, 1),
            status="active",
        )
    )
    db.add(
        LegalLink(
            from_key=TEST_DOC,
            to_key="blld2012",
            link_type="guides",
            valid_from=date(2013, 5, 1),
            source="seed",
        )
    )
    db.commit()
    yield
    db.execute(delete(LegalLink).where(LegalLink.from_key == TEST_DOC))
    db.execute(delete(LegalDocument).where(LegalDocument.doc_id == TEST_DOC))
    db.commit()


@pytest.mark.db
def test_guide_to_replaced_law_is_flagged(db, guide_doc):
    item = next(
        i for i in needs_verification(db, date(2022, 1, 1)) if i["doc_id"] == TEST_DOC
    )
    assert item["base_doc_id"] == "blld2012"
    assert item["since"] == "2021-01-01"
    assert item["base_title"] == "Bộ luật Lao động 2012"
    assert "Bộ luật Lao động 2012" in item["reason"]
    assert "cần xác minh" in item["reason"]

    assert needs_verification(db, date(2020, 6, 1)) == []


@pytest.mark.db
def test_guide_to_law_still_in_force_is_not_flagged(db):
    items = needs_verification(db, date.today())
    assert "nd145_2020" not in [i["doc_id"] for i in items]


@pytest.mark.db
def test_corpus_freshness_thresholds(db):
    base = corpus_freshness(db, date.today())
    last = date.fromisoformat(base["last_ingest"])

    fresh = corpus_freshness(db, last + timedelta(days=10))
    assert fresh["stale"] is False
    assert fresh["threshold"] == FRESH_DAYS

    stale = corpus_freshness(db, last + timedelta(days=31))
    assert stale["stale"] is True
    assert last.strftime("%d/%m/%Y") in stale["message"]
    assert "31 ngày" in stale["message"]

    sanction = corpus_freshness(db, last + timedelta(days=15), "mức xử phạt vi phạm")
    assert sanction["threshold"] == FRESH_DAYS_SANCTION
    assert sanction["stale"] is True


@pytest.mark.db
def test_resolve_has_verify_and_freshness_flag(db):
    from app.amend.timeframe import resolve

    future = date.today() + timedelta(days=365)
    tf = resolve(db, None, future)
    assert "verify" in tf
    assert isinstance(tf["verify"], list)
    assert any("Kho văn bản nạp lần cuối" in f for f in tf["flags"])


@pytest.mark.db
def test_verify_route_returns_items_and_freshness(db):
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).get("/api/law/verify", params={"as_of": "2022-01-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["as_of"] == "2022-01-01"
    assert isinstance(body["items"], list)
    assert {"last_ingest", "threshold", "stale", "message"} <= set(body["freshness"])
