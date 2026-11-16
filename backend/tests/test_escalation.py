"""Phê duyệt có người thật: gửi -> chờ -> chuyên gia duyệt/từ chối -> chat đọc lại kết quả.

Từ R2 escalation nằm trong bảng `review_case`; hình dạng HTTP giữ nguyên.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.api import routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI

    from app.db.base import SessionLocal
    from app.db.models import ReviewCase

    monkeypatch.setattr(routes, "_ESC_FILE", tmp_path / "escalations.json")
    monkeypatch.setattr(routes, "_esc_imported", True)  # không nhập tệp thật vào DB test
    db = SessionLocal()
    before = set(db.scalars(select(ReviewCase.id)).all())
    db.close()
    app = FastAPI()
    app.include_router(routes.router)
    yield TestClient(app)
    db = SessionLocal()
    for case_id in set(db.scalars(select(ReviewCase.id)).all()) - before:
        db.execute(text("DELETE FROM review_case WHERE id = :id"), {"id": case_id})
    db.commit()
    db.close()


def test_full_loop_approved_with_expert_reply(client):
    esc = client.post("/api/escalate", json={"question": "Bộ luật Lao động 2026 nói gì về sa thải?"}).json()
    assert client.get(f"/api/escalations/{esc['id']}").json()["status"] == "pending"

    r = client.patch(f"/api/escalations/{esc['id']}",
                     json={"status": "approved", "reply": "Chưa có BLLĐ 2026; hiện áp dụng Điều 125 BLLĐ 2019."})
    assert r.status_code == 200
    got = client.get(f"/api/escalations/{esc['id']}").json()
    assert got["status"] == "approved" and "Điều 125" in got["reply"] and got["resolved_at"]


def test_approve_requires_an_answer(client):
    esc = client.post("/api/escalate", json={"question": "q"}).json()
    r = client.patch(f"/api/escalations/{esc['id']}", json={"status": "approved", "reply": "  "})
    assert r.status_code == 422
    assert client.get(f"/api/escalations/{esc['id']}").json()["status"] == "pending"


def test_deny_with_reason_and_reject_unknown_status(client):
    esc = client.post("/api/escalate", json={"question": "q"}).json()
    assert client.patch(f"/api/escalations/{esc['id']}", json={"status": "maybe"}).status_code == 422
    r = client.patch(f"/api/escalations/{esc['id']}", json={"status": "denied", "reply": "Ngoài phạm vi"})
    assert r.json()["status"] == "denied" and r.json()["reply"] == "Ngoài phạm vi"


def test_unknown_id_is_404(client):
    assert client.get("/api/escalations/nope").status_code == 404


def test_legacy_32_char_id_still_resolves_and_question_is_masked(client):
    r = client.post("/api/escalate", json={"question": "Tôi là Trần Văn Bình, SĐT 0912345678, bị nợ lương"})
    esc_id = r.json()["id"]
    got = client.get(f"/api/escalations/{esc_id}").json()
    assert "0912345678" not in got["question"] and "Trần Văn Bình" not in got["question"]
    # thẻ cũ trong trình duyệt giữ id 32 ký tự: phần đầu khớp thì vẫn tra được
    assert client.get(f"/api/escalations/{esc_id}{'0' * 16}").status_code == 200
