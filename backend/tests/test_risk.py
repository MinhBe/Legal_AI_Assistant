"""R1 — chấm điểm rủi ro bằng quy tắc và hàng đợi duyệt tự động (design §9.1, §15.3)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agent import risk

VERIFIER_OK = {"ok": True, "checked": 3, "problems": [], "dropped": []}
VERIFIER_BAD = {"ok": False, "checked": 3, "problems": [{"check": "in_force", "message": "hết hiệu lực"}],
                "dropped": []}
DONE_OK = {"category": "legal", "confidence": 0.9}
PLAIN_Q = "Nghỉ phép năm được bao nhiêu ngày?"


def _cites(n: int = 3) -> list[tuple[str, object]]:
    return [("citation", {"n": i, "node_id": f"blld2019-d36-k{i}", "display": f"Điều {i}"})
            for i in range(1, n + 1)]


def _tf(**over) -> dict:
    tf = {
        "event_date": "2024-01-01", "event_date_source": "câu hỏi",
        "advice_date": "2024-06-01", "as_of": "2024-01-01",
        "applicable": [], "changes_after": [], "upcoming": [],
        "transition_rules": [], "flags": [],
    }
    tf.update(over)
    return tf


def _events(tf: dict | None = None, verifier: dict | None = None,
            done: dict | None = None, cites: list | None = None) -> list[tuple[str, object]]:
    return [
        ("token", {"text": "Theo Bộ luật Lao động 2019, ..."}),
        *(cites if cites is not None else _cites()),
        ("verifier", verifier or VERIFIER_OK),
        ("timeframe", tf or _tf()),
        ("done", done or DONE_OK),
    ]


def _near_tf() -> dict:
    advice = date(2024, 6, 1)
    event = advice - timedelta(days=350)  # trong khoảng 11–12 tháng trước ngày tư vấn
    return _tf(event_date=event.isoformat(), as_of=event.isoformat())


def _codes(r: dict) -> list[str]:
    return [x["code"] for x in r["reasons"]]


# ---- bảng trọng số: mỗi lý do một mình ----
@pytest.mark.parametrize(("question", "events", "code", "weight"), [
    ("Công ty sa thải tôi có đúng luật?", _events(), "high_stakes", 3),
    (PLAIN_Q, _events(tf=_near_tf()), "near_limitation", 3),
    (PLAIN_Q, _events(tf=_tf(transition_rules=[{"doc_key": "nd145", "condition": "x", "outcome": "new_law"}])),
     "transition", 2),
    (PLAIN_Q, _events(cites=_cites(1)), "low_retrieval", 2),
    (PLAIN_Q, _events(verifier=VERIFIER_BAD), "verifier", 3),
    (PLAIN_Q, _events(tf=_tf(flags=["Xử phạt hành chính chưa có quy tắc chuyển tiếp"])),
     "sanction_no_rule", 3),
])
def test_each_reason_fires_alone(question, events, code, weight):
    r = risk.score(question, events)
    assert _codes(r) == [code], r
    assert r["reasons"][0]["weight"] == weight
    assert r["score"] == weight


def test_transition_fires_on_upcoming_too():
    r = risk.score(PLAIN_Q, _events(tf=_tf(upcoming=[{"doc_id": "blld2025"}])))
    assert _codes(r) == ["transition"]


def test_low_retrieval_fires_on_low_confidence():
    r = risk.score(PLAIN_Q, _events(done={"category": "legal", "confidence": 0.5}))
    assert _codes(r) == ["low_retrieval"]


def test_near_limitation_fires_on_question_wording():
    r = risk.score("Vụ của tôi còn trong thời hiệu không?", _events())
    assert _codes(r) == ["near_limitation"]


def test_reasons_add_up():
    events = _events(
        tf=_tf(transition_rules=[{"doc_key": "nd145", "condition": "x", "outcome": "new_law"}]),
        verifier=VERIFIER_BAD, cites=_cites(1),
    )
    r = risk.score("Tôi bị chấm dứt hợp đồng, có được bồi thường?", events)
    assert _codes(r) == ["high_stakes", "transition", "low_retrieval", "verifier"]
    assert r["score"] == 3 + 2 + 2 + 3
    assert r["queue"] is True


def test_out_of_scope_words_are_infinite_and_queue():
    r = risk.score("Người quản lý đòi quà tặng thì có phải hối lộ không?", _events())
    assert _codes(r) == ["out_of_scope"]
    assert r["score"] == "inf" and r["queue"] is True


def test_out_of_corpus_category_is_infinite():
    r = risk.score(PLAIN_Q, _events(done={"category": "out_of_corpus"}))
    assert _codes(r) == ["out_of_scope"]
    assert r["score"] == "inf"


def test_distress_is_infinite():
    r = risk.score("Tôi tuyệt vọng quá, muốn chết cho xong.", _events())
    assert _codes(r) == ["distress"]
    assert r["score"] == "inf" and r["queue"] is True


def test_plain_question_scores_zero_and_does_not_queue():
    r = risk.score(PLAIN_Q, _events())
    assert r == {"score": 0, "queue": False, "reasons": []}


def test_threshold_is_three():
    three = risk.score("Công ty sa thải tôi có đúng luật?", _events())
    assert three["score"] == 3 and three["queue"] is True
    two = risk.score(PLAIN_Q, _events(cites=_cites(1)))
    assert two["score"] == 2 and two["queue"] is False


# ---- luồng chat: chấm điểm, tạo ca, đọc lại ----
def _fake_chat(message, history, mode, **kwargs):
    yield ("step", {"name": "retrieve", "label": "Đang tra cứu văn bản"})
    yield ("token", {"text": "Công ty sa thải bạn phải báo trước 45 ngày theo Điều 36."})
    yield ("citation", {"n": 1, "node_id": "blld2019-d36", "display": "Điều 36", "text": "..."})
    yield ("verifier", VERIFIER_OK)
    yield ("timeframe", _tf())
    yield ("done", {"category": "legal", "confidence": 0.9})


@pytest.mark.db
def test_chat_queues_a_high_risk_case(monkeypatch):
    from sqlalchemy import text

    from app.api import routes
    from app.db.base import SessionLocal
    from app.main import app

    monkeypatch.setattr(routes, "run_chat", _fake_chat)
    with TestClient(app) as client:
        body = client.post(
            "/api/chat", json={"message": "Công ty sa thải tôi có đúng luật?"}
        ).text
        assert "event: risk" in body
        payload = json.loads(body.split("event: risk", 1)[1].split("data: ", 1)[1].split("\n", 1)[0])
        assert payload["score"] == 5 and payload["queue"] is True
        case_id = payload["case_id"]
        rec_id = body.rsplit("event: record", 1)[1].split('"id": "')[1].split('"')[0]

        listed = client.get("/api/review/cases", params={"status": "pending"})
        assert listed.status_code == 200
        assert case_id in [c["id"] for c in listed.json()]

        got = client.get(f"/api/review/cases/{case_id}")
        assert got.status_code == 200, got.text
        case = got.json()
        assert (case["answer_id"], case["source"], case["status"]) == (rec_id, "auto", "pending")
        assert case["risk_score"] == "5"
        assert [x["code"] for x in case["reasons"]] == ["high_stakes", "low_retrieval"]
        assert case["answer"]["id"] == rec_id

        assert client.get("/api/review/cases/khongco").status_code == 404

    db = SessionLocal()
    db.execute(text("DELETE FROM review_case WHERE id = :id"), {"id": case_id})
    db.execute(text("DELETE FROM answer_record WHERE id = :id"), {"id": rec_id})
    db.commit()
    db.close()


@pytest.mark.parametrize("q", [
    "Biểu mẫu hợp đồng lao động theo quy định mới?",
    "Đại biểu công đoàn có quyền gì?",
    "Điều tra tai nạn lao động do ai thực hiện?",
])
def test_ordinary_words_are_not_out_of_scope(q):
    from app.agent.risk import score

    r = score(q, [("citation", {"node_id": "a"}), ("citation", {"node_id": "b"}),
                  ("timeframe", {}), ("done", {})])
    assert r["score"] != "inf", r


@pytest.mark.parametrize("q", ["Sếp đòi quà biếu mới ký hợp đồng", "Tôi đang bị điều tra hình sự vì hối lộ"])
def test_bribery_phrases_are_out_of_scope(q):
    from app.agent.risk import score

    assert score(q, [("timeframe", {}), ("done", {})])["score"] == "inf"
