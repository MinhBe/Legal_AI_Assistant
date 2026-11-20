"""Voice intake: phát hiện và áp làm mờ, lưu theo đồng ý, chép lời tức thì (model giả)."""

import numpy as np
import pytest

from app.intake import redact
from app.intake.stt import RATE, LiveSession

TEXT = ("Tôi là Nguyễn Văn An, làm ở Công ty TNHH Hoà Bình. Chị Lan bị ung thư nên nghỉ việc. "
        "Số điện thoại 0912345678. Anh An bị sa thải.")


def _by(spans, t):
    return [s for s in spans if s["type"] == t]


def test_detect_groups_and_gendered_pseudonyms():
    spans = redact.detect(TEXT)
    names = {s["text"]: s["suggestion"] for s in _by(spans, "TÊN")}
    assert names["Nguyễn Văn An"] == "Nguyễn Văn B"
    assert names["An"] == "Nguyễn Văn B"  # cùng một người
    assert names["Lan"].startswith("Nguyễn Thị")  # "Chị Lan"
    assert _by(spans, "TỔ_CHỨC")[0]["text"] == "Công ty TNHH Hoà Bình"
    assert _by(spans, "TÌNH_TIẾT")[0]["group"] == "sensitive_fact"
    assert _by(spans, "SĐT")[0]["suggestion"] == "[số đã ẩn]"


def test_apply_default_masks_everything():
    out = redact.apply(TEXT, redact.detect(TEXT))
    for leak in ("Nguyễn Văn An", "Hoà Bình", "ung thư", "0912345678", " An "):
        assert leak not in out["text"]
    assert out["kept"] == 0


def test_apply_keep_fact_but_mask_names_inside():
    spans = redact.detect(TEXT)
    fact = _by(spans, "TÌNH_TIẾT")[0]["id"]
    out = redact.apply(TEXT, spans, {fact: {"action": "keep"}})
    assert "bị ung thư" in out["text"] and "Lan" not in out["text"]
    assert out["kept"] == 1


def test_custom_replacement_is_consistent_per_person():
    spans = redact.detect(TEXT)
    sid = next(s["id"] for s in spans if s["text"] == "Nguyễn Văn An")
    out = redact.apply(TEXT, spans, {sid: {"action": "pseudonym", "replacement": "Ông K"}})
    assert out["text"].count("Ông K") == 2


def test_spoken_lowercase():
    t = "em tên là trần thị hoa làm ở công ty may việt tiến bị nợ lương ba tháng"
    out = redact.apply(t, redact.detect(t))["text"]
    assert out == "em tên là Nguyễn Thị B làm ở Công ty X bị nợ lương ba tháng"


def test_bad_action_rejected():
    spans = redact.detect(TEXT)
    with pytest.raises(ValueError):
        redact.apply(TEXT, spans, {spans[0]["id"]: {"action": "publish"}})


def _tone(sec, amp=0.3):
    t = np.arange(int(RATE * sec)) / RATE
    return (amp * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16).tobytes()


def _silence(sec):
    return np.zeros(int(RATE * sec), dtype=np.int16).tobytes()


def test_live_session_partial_then_final():
    calls = []

    def fake(audio):
        calls.append(len(audio) / RATE)
        return f"câu {len(calls)}"

    s = LiveSession(transcribe=fake, silence_ms=600, max_segment_s=12, partial_every_s=1.0)
    ev = []
    for chunk in (_silence(0.5), _tone(2.5), _silence(1.0), _tone(1.0)):
        ev += s.feed(chunk)
    ev += s.close()
    kinds = [e["type"] for e in ev]
    assert "partial" in kinds and kinds.count("final") == 2
    first = next(e for e in ev if e["type"] == "final")
    assert 0.4 <= first["start"] <= 0.6 and first["end"] > 3.0


def test_live_session_ignores_short_noise():
    s = LiveSession(transcribe=lambda a: "x", silence_ms=300, partial_every_s=9)
    ev = s.feed(_tone(0.1) + _silence(1.0))
    assert ev == []


@pytest.mark.db
def test_submit_requires_consent_and_stores_masked(db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.db.models import IntakeRecord
    from app.intake import routes
    from app.main import app

    monkeypatch.setattr(routes, "POOL", tmp_path / "pool.jsonl")
    with TestClient(app) as client:
        rid = _submit(client)
    assert (tmp_path / "pool.jsonl").read_text(encoding="utf-8").count(rid) == 1
    db.query(IntakeRecord).filter_by(id=rid).delete()
    db.commit()


def _submit(client):
    r = client.post("/api/intake/submit", json={"text": TEXT})
    assert r.status_code == 400
    r = client.post("/api/intake/submit", json={"text": TEXT, "consent_case": True,
                                                "consent_training": True, "source": "text",
                                                "analyze": False})
    assert r.status_code == 200
    body = r.json()
    assert "Nguyễn Văn An" not in body["text"] and body["data_class"] == "C"
    assert body["consent_training"] is True
    return body["intake_id"]


def test_analyze_uses_record_data_class(monkeypatch, tmp_path):
    from app.intake import analyze

    seen = {}

    class Row:
        id, text, data_class, status = "x1", "Hỏi về [TÊN_1] bị nợ lương.", "B", "new"

    class FakeDB:
        def get(self, model, key):
            return Row

        def execute(self, q):
            class R:
                def all(self):
                    return [("Bộ luật Lao động 2019", "45/2019/QH14", "active")]
            return R()

        def commit(self):
            seen["commit"] = True

        def close(self):
            pass

    class FakeRouter:
        def chat(self, messages, task, temperature):
            from app.llm.context import get_data_class

            seen.setdefault("classes", []).append(get_data_class())
            return type("R", (), {"text": '{"corrected": "x", "units": []}'})()

    monkeypatch.setattr(analyze, "SessionLocal", FakeDB)
    monkeypatch.setattr(analyze, "get_router", FakeRouter)
    monkeypatch.setattr(analyze, "OUT", tmp_path)
    analyze.run("x1")
    assert seen["classes"] and set(seen["classes"]) == {"B"}
    assert Row.status == "failed" and seen["commit"]


def test_live_session_spaces_partials_when_cpu_is_slow():
    import time as _t

    def slow(audio):
        _t.sleep(0.2)  # mỗi lần chép tốn 0,2 s
        return "x"

    fast_cfg = dict(silence_ms=600, max_segment_s=30, partial_every_s=0.1)
    s = LiveSession(transcribe=slow, **fast_cfg)
    ev = s.feed(_tone(2.0))
    # partial cách nhau ít nhất 2 x 0,2 s thay vì mỗi 0,1 s
    assert 1 <= sum(e["type"] == "partial" for e in ev) <= 6


def test_embed_defer_writes_queue_not_vectors(tmp_path, monkeypatch):
    from app.upload import ingest as up

    monkeypatch.setattr(up, "EMBED_QUEUE", tmp_path)
    rows = [{"node_id": "d1-s1", "_ctx": "Luật X: Điều 1"}, {"node_id": "d1-s2", "_ctx": "Luật X: Điều 2"}]
    path = up.queue_embeddings("d1", rows)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and '"node_id": "d1-s1"' in lines[0]
