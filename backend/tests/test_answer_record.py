"""Hồ sơ câu trả lời pháp lý (T7, design §5.3)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agent import record as rec_mod

NAME, PHONE = "Trần Văn Bình", "0912345678"
MASKED_Q = "Tôi là [TÊN_1], số [SĐT_1]. Công ty cho tôi nghỉ việc trái luật."
MASKED_A = "Chào [TÊN_1], số [SĐT_1] đã ghi nhận."

TIMEFRAME = {
    "event_date": "2024-01-01",
    "event_date_source": "câu hỏi",
    "advice_date": "2024-06-01",
    "as_of": "2024-01-01",
    "applicable": [],
    "changes_after": [],
    "upcoming": [],
    "transition_rules": [],
    "flags": [],
}
VERIFIER = {"ok": True, "checked": 2, "problems": [], "dropped": []}


def _ctx(question: str = MASKED_Q) -> dict:
    return {
        "request_id": "req000000001",
        "data_class": "B",
        "prompt_version": "v1",
        "question": question,
        "_pii_mapping": {"[TÊN_1]": NAME, "[SĐT_1]": PHONE},
        "llm": [
            {"provider": "dahl", "model": "dahl-1", "error": "timeout", "won": False},
            {"provider": "gemini", "model": "gemini-x", "error": None, "won": False},
            {"provider": "dahl", "model": "dahl-2", "error": None, "won": True},
        ],
    }


def _events(answer: str = f"Chào {NAME}, số {PHONE} đã ghi nhận.") -> list[tuple[str, object]]:
    return [
        ("step", {"name": "retrieve", "label": "Đang tra cứu văn bản"}),
        ("token", {"text": answer}),
        ("section", {
            "title": "Căn cứ",
            "detail": "...",
            "citations": [{"node_id": "blld2019-d36", "display": "Điều 36", "text": "..."}],
        }),
        ("citation", {"n": 1, "node_id": "blld2019-d41", "display": "Điều 41", "text": "..."}),
        ("verifier", VERIFIER),
        ("timeframe", TIMEFRAME),
        ("done", {"category": "legal", "confidence": 0.9}),
    ]


def test_build_masks_question_and_answer_and_collects_context():
    rec = rec_mod.build(_ctx(), _events(), "thread-1")

    assert rec is not None
    assert NAME not in rec["question"] and PHONE not in rec["question"]
    assert NAME not in rec["answer"] and PHONE not in rec["answer"]
    assert "[TÊN_1]" in rec["answer"] and "[SĐT_1]" in rec["answer"]
    assert [p["node_id"] for p in rec["provisions"]] == ["blld2019-d36", "blld2019-d41"]
    assert (rec["provider"], rec["model"]) == ("dahl", "dahl-2")
    assert rec["data_class"] == "B"
    assert rec["thread_id"] == "thread-1"
    assert rec["request_id"] == "req000000001"
    assert rec["advice_date"].isoformat() == "2024-06-01"
    assert rec["event_date"].isoformat() == "2024-01-01"
    assert rec["as_of"].isoformat() == "2024-01-01"
    assert rec["timeframe"]["as_of"] == "2024-01-01"
    assert rec["verifier"] == VERIFIER
    assert rec["category"] == "legal"
    assert rec["prompt_version"] == "v1"
    assert {"last_ingest", "n_documents", "n_provisions"} == set(rec["corpus_snapshot"])
    assert len(rec["id"]) == 12


def test_build_returns_none_for_a_refusal():
    events = [
        ("token", {"text": "Không đủ căn cứ trong kho văn bản để trả lời chắc chắn câu này."}),
        ("done", {"category": "out_of_corpus", "escalate": True}),
    ]
    assert rec_mod.build(_ctx(), events, None) is None


@pytest.mark.db
def test_save_get_round_trip_and_routes(db):
    from app.db.models import AnswerRecord
    from app.main import app

    rec = rec_mod.build(_ctx(), _events(), "thread-db")
    assert rec is not None
    rec_id = rec_mod.save(db, rec)

    got = rec_mod.get(db, rec_id)
    assert got is not None
    assert got["question"] == MASKED_Q
    assert got["answer"] == MASKED_A
    assert [p["node_id"] for p in got["provisions"]] == ["blld2019-d36", "blld2019-d41"]
    assert got["timeframe"]["as_of"] == "2024-01-01"
    assert got["corpus_snapshot"]["n_documents"] >= 1
    assert any(r["id"] == rec_id and "answer" not in r for r in rec_mod.list_recent(db, 50))

    with TestClient(app) as client:
        r = client.get(f"/api/answers/{rec_id}")
        assert r.status_code == 200, r.text
        assert r.json()["question"] == MASKED_Q
        assert client.get("/api/answers/khongco").status_code == 404

    db.delete(db.get(AnswerRecord, rec_id))
    db.commit()


def _fake_chat(message, history, mode, **kwargs):
    yield ("step", {"name": "retrieve", "label": "Đang tra cứu văn bản"})
    yield ("token", {"text": "Theo Điều 36 BLLĐ 2019, người lao động phải báo trước 45 ngày."})
    yield ("citation", {"n": 1, "node_id": "blld2019-d36", "display": "Điều 36", "text": "..."})
    yield ("verifier", VERIFIER)
    yield ("timeframe", TIMEFRAME)
    yield ("done", {"category": "legal"})


def _chat(client: TestClient, monkeypatch) -> str:
    from app.api import routes

    monkeypatch.setattr(routes, "run_chat", _fake_chat)
    r = client.post("/api/chat", json={"message": "Báo trước bao nhiêu ngày?"})
    assert r.status_code == 200, r.text
    return r.text


@pytest.mark.db
def test_chat_emits_record_event_and_saves(monkeypatch):
    from app.main import app

    with TestClient(app) as client:
        body = _chat(client, monkeypatch)
        assert "event: record" in body
        rec_id = body.rsplit("event: record", 1)[1].split('"id": "')[1].split('"')[0]
        r = client.get(f"/api/answers/{rec_id}")
        assert r.status_code == 200, r.text
        assert r.json()["answer"].startswith("Theo Điều 36")

        # ảnh chụp lưu lại được xoá để không để rác trong kho
        from sqlalchemy import text

        from app.db.base import SessionLocal

        db = SessionLocal()
        db.execute(text("DELETE FROM answer_record WHERE id = :id"), {"id": rec_id})
        db.commit()
        db.close()


@pytest.mark.db
def test_chat_survives_a_failing_record_save(monkeypatch):
    from app.api import routes
    from app.main import app

    def boom(db, rec):
        raise RuntimeError("db down")

    monkeypatch.setattr(routes.record, "save", boom)
    with TestClient(app) as client:
        body = _chat(client, monkeypatch)
    assert "event: record" not in body
    assert "event: error" not in body
    assert "Theo Điều 36" in body
