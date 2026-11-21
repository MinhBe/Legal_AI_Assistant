"""Đăng ký theo dõi văn bản mới theo lĩnh vực: SQLite trong bộ nhớ, không cần Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import IntelItem
from app.intel import subscribe


@pytest.fixture
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    IntelItem.__table__.create(eng)
    subscribe.IntelSubscription.__table__.create(eng)
    s = sessionmaker(bind=eng)()
    now = datetime.now(timezone.utc)
    s.add_all([
        IntelItem(id="a1", source="congbao", url="u1", title="Nghị định quy định mức lương tối thiểu đối với người lao động",
                  number="293/2025/NĐ-CP", labor_hint=True, first_seen=now - timedelta(days=2)),
        IntelItem(id="a2", source="vbpl", url="u2", title="Thông tư hướng dẫn cấp giấy chứng nhận quyền sử dụng đất",
                  number="10/2026/TT-BTNMT", first_seen=now - timedelta(days=1)),
        IntelItem(id="a3", source="vbpl", url="u3", title="Quyết định về thuế thu nhập cá nhân và giảm trừ gia cảnh",
                  number="01/2026/QĐ-TTg", first_seen=now),
    ])
    s.commit()
    yield s
    s.close()


def test_feed_filters_by_domain_and_keyword(db):
    sub = subscribe.create(db, "u:minh", "", ["dat_dai"], [])
    ids = [i["id"] for i in subscribe.feed(db, sub)["items"]]
    assert ids == ["a2"]
    sub2 = subscribe.create(db, "u:minh", "Lương", [], ["lương tối thiểu"])
    f = subscribe.feed(db, sub2)
    assert [i["id"] for i in f["items"]] == ["a1"]
    assert 'từ khoá "lương tối thiểu"' in f["items"][0]["why"]


def test_labor_hint_and_multi_domain(db):
    sub = subscribe.create(db, "c:abc", "", ["lao_dong", "thue_tncn"], [])
    f = subscribe.feed(db, sub)
    assert [i["id"] for i in f["items"]] == ["a3", "a1"]   # mới nhất trước
    assert f["subscription"]["unread"] == 2
    assert sub.name == "Lao động, Thuế thu nhập cá nhân"


def test_mark_read_clears_unread(db):
    sub = subscribe.create(db, "u:minh", "", ["lao_dong"], [])
    subscribe.mark_read(db, sub)
    f = subscribe.feed(db, sub)
    assert f["subscription"]["unread"] == 0 and f["items"][0]["unread"] is False


def test_validation_and_ownership(db):
    with pytest.raises(ValueError):
        subscribe.create(db, "u:minh", "", ["khong_co"], [])
    with pytest.raises(ValueError):
        subscribe.create(db, "u:minh", "", [], ["  "])
    sub = subscribe.create(db, "u:minh", "", ["dan_su"], [])
    assert subscribe.get(db, "u:other", sub.id) is None
    assert subscribe.owner_of({"username": None, "client_id": "x"}) == "c:x"


def test_routes_end_to_end(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.db.base import get_db
    from app.intel.subscribe_routes import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    h = {"X-Client-Id": "browser-1"}
    assert len(c.get("/api/intel/domains").json()["domains"]) == 7
    sid = c.post("/api/intel/subscriptions", json={"domains": ["dat_dai"]}, headers=h).json()["id"]
    assert c.get(f"/api/intel/subscriptions/{sid}/feed", headers=h).json()["items"][0]["id"] == "a2"
    assert c.get(f"/api/intel/subscriptions/{sid}/feed", headers={"X-Client-Id": "other"}).status_code == 404
    assert c.get("/api/intel/subscriptions", headers=h).json()["subscriptions"][0]["unread"] == 1
    assert c.post("/api/intel/subscriptions", json={"domains": []}, headers=h).status_code == 422
    assert c.delete(f"/api/intel/subscriptions/{sid}", headers=h).json() == {"deleted": sid}
