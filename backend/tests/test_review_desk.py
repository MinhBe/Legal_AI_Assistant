"""R2 — bàn duyệt luật sư: gói ca, bốn hành động, thống kê, escalation trong DB (§9.2–9.3)."""

from __future__ import annotations

import json
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

pytestmark = pytest.mark.db

Q = "Công ty sa thải tôi có đúng luật?"
DRAFT = "Theo Điều 36 BLLĐ 2019, người sử dụng lao động phải báo trước 45 ngày."
TF = {
    "event_date": "2024-01-01", "event_date_source": "câu hỏi",
    "advice_date": "2024-06-01", "as_of": "2024-01-01",
    "applicable": [], "changes_after": [], "upcoming": [],
    "transition_rules": [], "flags": [],
}
VERIFIER = {"ok": False, "checked": 2, "dropped": ["blld2019-d99"],
            "problems": [{"check": "in_force", "message": "Điều 99 đã hết hiệu lực"}]}
REASONS = [{"code": "high_stakes", "weight": 3, "message": "câu hỏi về sa thải"}]


@pytest.fixture(autouse=True)
def _clean():
    """Xoá đúng những dòng test tạo ra, kể cả khi test fail."""
    from app.db.base import SessionLocal
    from app.db.models import AnswerRecord, ReviewCase

    try:
        db = SessionLocal()
        before_cases = set(db.scalars(select(ReviewCase.id)).all())
        before_recs = set(db.scalars(select(AnswerRecord.id)).all())
        db.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"không kết nối được Postgres: {exc.__class__.__name__}")
    yield
    db = SessionLocal()
    for case_id in set(db.scalars(select(ReviewCase.id)).all()) - before_cases:
        db.execute(text("DELETE FROM review_case WHERE id = :id"), {"id": case_id})
    for rec_id in set(db.scalars(select(AnswerRecord.id)).all()) - before_recs:
        db.execute(text("DELETE FROM answer_record WHERE id = :id"), {"id": rec_id})
    db.commit()
    db.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI

    from app.api import routes

    monkeypatch.setattr(routes, "_ESC_FILE", tmp_path / "escalations.json")
    monkeypatch.setattr(routes, "_esc_imported", True)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def _any_node() -> dict | None:
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        row = db.execute(text("SELECT node_id, doc_id, text FROM legal_node LIMIT 1")).first()
    finally:
        db.close()
    return {"node_id": row.node_id, "doc_id": row.doc_id, "text": row.text} if row else None


def _mk_case(node_id: str | None = None) -> tuple[str, str]:
    """Hồ sơ câu trả lời + ca tự động; trả (case_id, record_id)."""
    from app.db.base import SessionLocal
    from app.db.models import AnswerRecord, ReviewCase

    db = SessionLocal()
    try:
        rec_id = uuid.uuid4().hex[:12]
        db.add(AnswerRecord(
            id=rec_id, thread_id="t-r2", data_class="C", question=Q, answer=DRAFT,
            advice_date=date(2024, 6, 1), event_date=None, as_of=date(2024, 1, 1),
            provisions=json.dumps([{"node_id": node_id}] if node_id else []),
            timeframe=json.dumps(TF), verifier=json.dumps(VERIFIER),
            corpus_snapshot="{}", prompt_version="qa-v1", provider="dahl",
            model="dahl-7b", category="legal",
        ))
        case_id = uuid.uuid4().hex[:16]
        db.add(ReviewCase(
            id=case_id, answer_id=rec_id, question=Q, risk_score="5",
            reasons=json.dumps(REASONS, ensure_ascii=False),
            status="pending", source="auto", thread_id="t-r2",
        ))
        db.commit()
        return case_id, rec_id
    finally:
        db.close()


def _act(client, case_id, **body):
    return client.post(f"/api/review/cases/{case_id}/act", json=body)


# ---- 1. gói ca ----
def test_package_has_draft_timeframe_verifier_and_provision_text(client):
    node = _any_node()
    case_id, _ = _mk_case(node["node_id"] if node else None)

    r = client.get(f"/api/review/cases/{case_id}/package")
    assert r.status_code == 200, r.text
    pkg = r.json()
    assert pkg["draft"] == DRAFT
    assert pkg["question"] == Q and pkg["status"] == "pending" and pkg["source"] == "auto"
    assert pkg["risk_score"] == "5"
    assert [x["code"] for x in pkg["reasons"]] == ["high_stakes"]
    assert pkg["timeframe"]["as_of"] == "2024-01-01"
    assert pkg["verifier"]["problems"][0]["message"] == "Điều 99 đã hết hiệu lực"
    assert pkg["prompt_version"] == "qa-v1" and pkg["model"] == "dahl-7b"
    assert len(pkg["provisions"]) == 1
    assert pkg["provisions"][0]["node_id"] == (node["node_id"] if node else "x")
    if node:
        assert pkg["provisions"][0]["text"] == node["text"]

    assert client.get("/api/review/cases/khongco/package").status_code == 404


# ---- 2. bốn hành động ----
def test_approve_takes_the_draft_as_is(client):
    case_id, _ = _mk_case()
    r = _act(client, case_id, action="approve")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "approved" and got["reviewer_text"] == DRAFT
    assert got["reviewed_at"] and got["diff"] is None


def test_light_edit_saves_a_diff(client):
    case_id, _ = _mk_case()
    edited = DRAFT.replace("45 ngày", "45 ngày làm việc")
    r = _act(client, case_id, action="light_edit", text=edited)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "light_edit" and got["reviewer_text"] == edited
    assert f"-{DRAFT}" in got["diff"] and f"+{edited}" in got["diff"]


def test_light_edit_requires_a_text(client):
    case_id, _ = _mk_case()
    assert _act(client, case_id, action="light_edit", text="  ").status_code == 422


def test_heavy_edit_requires_a_label_and_records_it(client):
    case_id, _ = _mk_case()
    assert _act(client, case_id, action="heavy_edit", text="Bản mới").status_code == 422
    assert _act(client, case_id, action="heavy_edit", text="Bản mới",
                labels=["khong_co"]).status_code == 422

    r = _act(client, case_id, action="heavy_edit", text="Bản mới",
             labels=["sai_phien_ban"], reason="dùng luật đã hết hiệu lực")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "heavy_edit" and got["error_labels"] == ["sai_phien_ban"]
    assert "dùng luật đã hết hiệu lực" in got["diff"] and "+Bản mới" in got["diff"]


def test_reject_requires_a_reason(client):
    case_id, _ = _mk_case()
    assert _act(client, case_id, action="reject").status_code == 422
    r = _act(client, case_id, action="reject", reason="Ngoài phạm vi", labels=["khac"])
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "rejected" and got["reply"] == "Ngoài phạm vi"
    assert got["error_labels"] == ["khac"] and got["reviewer_text"] is None


def test_acting_twice_is_a_conflict(client):
    case_id, _ = _mk_case()
    assert _act(client, case_id, action="approve").status_code == 200
    assert _act(client, case_id, action="reject", reason="muộn").status_code == 409
    assert client.get(f"/api/review/cases/{case_id}/package").json()["status"] == "approved"


# ---- 3. escalation vẫn đúng hợp đồng cũ ----
def test_escalation_roundtrip_on_the_table(client):
    esc = client.post("/api/escalate", json={"question": "BLLĐ 2026 nói gì về sa thải?"}).json()
    pkg = client.get(f"/api/review/cases/{esc['id']}/package").json()
    assert pkg["draft"] is None and pkg["source"] == "user" and pkg["question"]

    listed = client.get("/api/escalations").json()
    row = next(r for r in listed if r["id"] == esc["id"])
    assert set(row) == {"id", "question", "thread_id", "status", "created_at", "reply", "resolved_at"}
    assert row["status"] == "pending" and row["reply"] is None

    reply = "Chưa có BLLĐ 2026; hiện áp dụng Điều 125 BLLĐ 2019."
    assert client.patch(f"/api/escalations/{esc['id']}",
                        json={"status": "approved", "reply": reply}).status_code == 200
    got = client.get(f"/api/escalations/{esc['id']}").json()
    assert got["status"] == "approved" and got["reply"] == reply and got["resolved_at"]

    other = client.post("/api/escalate", json={"question": "q2"}).json()
    assert client.patch(f"/api/escalations/{other['id']}",
                        json={"status": "denied", "reply": "Ngoài phạm vi"}).json()["status"] == "denied"
    assert client.get(f"/api/escalations/{other['id']}").json()["status"] == "denied"


# ---- 4. nhập escalations.json một lần ----
def test_import_json_escalations_is_idempotent(tmp_path):
    from app.db.base import SessionLocal
    from app.db.models import ReviewCase
    from app.review import service as review

    pending, approved, denied = (uuid.uuid4().hex[:16] for _ in range(3))
    path = tmp_path / "escalations.json"
    path.write_text(json.dumps([
        {"id": pending, "question": "q1", "thread_id": "t1", "status": "pending",
         "created_at": "2026-11-05T04:27:34+00:00"},
        {"id": approved, "question": "q2", "status": "approved", "reply": "đã trả lời",
         "created_at": "2026-11-05T08:48:10+00:00", "resolved_at": "2026-11-05T08:48:45+00:00"},
        {"id": denied, "question": "q3", "status": "denied", "reply": "ngoài phạm vi"},
    ]), encoding="utf-8")

    db = SessionLocal()
    try:
        assert review.import_json_escalations(db, path) == 3
        assert review.import_json_escalations(db, path) == 0
        rows = {c.id: c for c in db.scalars(
            select(ReviewCase).where(ReviewCase.id.in_([pending, approved, denied]))
        )}
        assert rows[pending].status == "pending" and rows[pending].source == "user"
        assert rows[approved].status == "approved" and rows[approved].reply == "đã trả lời"
        assert rows[approved].reviewed_at is not None
        assert rows[denied].status == "rejected" and rows[denied].reply == "ngoài phạm vi"
    finally:
        db.close()


# ---- 5. thống kê ----
def test_stats_count_statuses_and_labels(client):
    before = client.get("/api/review/stats").json()
    labels = client.get("/api/review/labels").json()
    assert labels["sai_trich_dan"] == "Sai trích dẫn"

    approved_id, _ = _mk_case()
    assert _act(client, approved_id, action="approve").status_code == 200
    edited_id, _ = _mk_case()
    assert _act(client, edited_id, action="heavy_edit", text="Bản mới",
                labels=["sai_tinh_toan"], reason="tính sai").status_code == 200

    after = client.get("/api/review/stats").json()
    assert after["total"] == before["total"] + 2
    assert after["by_status"]["approved"] == before["by_status"]["approved"] + 1
    assert after["by_status"]["heavy_edit"] == before["by_status"]["heavy_edit"] + 1
    assert (after["by_label"].get("sai_tinh_toan", 0)
            == before["by_label"].get("sai_tinh_toan", 0) + 1)
    assert 0 <= after["approved_rate"] <= 1
