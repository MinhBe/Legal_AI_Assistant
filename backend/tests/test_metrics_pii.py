"""Nhật ký đo lường (requests.jsonl, Langfuse) không được lưu PII thô."""

from __future__ import annotations

from app.obs import metrics

NAME, PHONE = "Trần Văn Bình", "0912345678"


def _capture(monkeypatch) -> list[tuple[str, dict]]:
    rows: list[tuple[str, dict]] = []
    monkeypatch.setattr(metrics, "_write", lambda name, row: rows.append((name, row)))
    from app.obs import lf

    sent: list[dict] = []
    monkeypatch.setattr(lf, "send", lambda row, calls: sent.append(row))
    monkeypatch.setattr(metrics, "_LF_SENT", sent, raising=False)
    return rows


def test_chat_request_row_has_masked_question_answer_and_level(monkeypatch):
    from app.agent import pipeline

    def fake_chat(message, history, mode, *, original=None):
        assert NAME not in message and PHONE not in message
        # LLM nhắc lại placeholder; pipeline trả tên thật cho client
        yield ("token", {"text": "Chào [TÊN_1], số [SĐT_1] đã ghi nhận."})
        yield ("done", {})

    monkeypatch.setattr(pipeline, "_chat", fake_chat)
    rows = _capture(monkeypatch)
    question = f"Tôi là {NAME}, số điện thoại {PHONE}. Công ty cho tôi nghỉ không báo trước."
    ctx = metrics.start_request("chat", question=question)
    events = list(metrics.traced(pipeline.run_chat(question), ctx))

    client_text = "".join(d["text"] for e, d in events if e == "token")
    assert NAME in client_text and PHONE in client_text  # client vẫn thấy tên thật

    [(name, row)] = [r for r in rows if r[0] == "requests.jsonl"]
    dumped = repr(row)
    assert NAME not in dumped and PHONE not in dumped
    assert row["data_class"] == "B"
    assert "[TÊN_1]" in row["question"] and "[SĐT_1]" in row["answer"]
    assert not any(k.startswith("_") for k in row)
    assert metrics._LF_SENT and NAME not in repr(metrics._LF_SENT[0])


def test_request_outside_gateway_is_still_masked(monkeypatch):
    rows = _capture(monkeypatch)
    ctx = metrics.start_request("report", question=f"Liên hệ số {PHONE}")
    metrics.end_request(ctx)
    [(_, row)] = rows
    assert PHONE not in row["question"]
