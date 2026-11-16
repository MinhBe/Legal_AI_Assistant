"""Contract G1 — che PII trước khi tới LLM bên ngoài. Thuần Python, không DB/LLM."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.gateway.classify import classify, gate
from app.gateway.pii import mask, unmask

PARAGRAPH = (
    "Tôi là ông Nguyễn Văn Thử, CCCD 001203004567, SĐT 0912 345 678, email "
    "thu.nv@example.com, STK 1903 4567 8901 23 tại Techcombank, lương 12.500.000 đồng, "
    "trú tại số 12 ngõ 34 phố Mẫu, phường An Bình, quận Thử, Hà Nội."
)
SECRETS = [
    "Nguyễn Văn Thử",
    "001203004567",
    "0912 345 678",
    "thu.nv@example.com",
    "1903 4567 8901 23",
    "12.500.000 đồng",
    "số 12 ngõ 34 phố Mẫu, phường An Bình, quận Thử, Hà Nội",
]
LEGAL = (
    "Theo khoản 1 Điều 36 Bộ luật Lao động số 45/2019/QH14 và Nghị định "
    "145/2020/NĐ-CP, người lao động được báo trước 30 ngày; Quyết định số "
    "05/2016/QĐNV-KD ngày 25/11/2016 bồi thường 02 tháng tiền lương."
)


def _squash(text: str) -> str:
    return "".join(text.split())


def test_masks_every_entity_type_and_round_trips():
    m = mask(PARAGRAPH)
    flat = _squash(m.text)
    for secret in SECRETS:
        assert _squash(secret) not in flat, secret
    assert set(m.counts) == {"TÊN", "CCCD", "SĐT", "EMAIL", "STK", "TIỀN", "ĐỊA_CHỈ"}
    assert all(n == 1 for n in m.counts.values())
    assert unmask(m.text, m.mapping) == PARAGRAPH


def test_same_value_same_placeholder_and_numbers_are_per_type():
    m = mask("anh Trần Văn Bình gọi anh Trần Văn Bình; chị Lê Thị Hoa gọi lại")
    assert m.text.count("[TÊN_1]") == 2
    assert "[TÊN_2]" in m.text and m.counts == {"TÊN": 2}


def test_legal_text_is_untouched():
    m = mask(LEGAL)
    assert m.text == LEGAL
    assert m.counts == {}


def test_classify_and_gate():
    assert classify("Thời gian thử việc tối đa là bao lâu?") == "C"
    assert classify("Chị Lan 0912345678 nghỉ thai sản được mấy tháng?") == "B"
    assert classify("nội dung tệp", source="upload") == "A"
    with pytest.raises(PermissionError, match="class A must not reach an external LLM"):
        gate("nội dung tệp", source="upload")


class RecordingRouter:
    """Ghi lại đúng những gì được gửi tới LLM, trả câu trả lời có placeholder."""

    def __init__(self):
        self.seen: list[list[dict]] = []

    def available_providers(self):
        return {"fake": True}

    def stream(self, messages, task="answer"):
        self.seen.append(messages)
        yield "Chào [TÊN_1], đã nhận [SĐT_1] và [CCCD_1]."


def test_run_chat_masks_before_the_llm_and_unmasks_the_client(monkeypatch):
    from app.agent import pipeline, qa

    router = RecordingRouter()
    monkeypatch.setattr(pipeline, "get_router", lambda: router)
    monkeypatch.setattr(qa, "get_router", lambda: router)
    monkeypatch.setattr(pipeline, "_data_loaded", lambda: False)

    message = "Tôi là Nguyễn Văn Thử, SĐT 0912 345 678, CCCD 001203004567. Nghỉ phép thế nào?"
    events = list(pipeline.run_chat(message))

    sent = _squash(str(router.seen))
    for secret in ("Nguyễn Văn Thử", "0912345678", "001203004567"):
        assert _squash(secret) not in sent, secret

    text = "".join(d["text"] for name, d in events if name == "token")
    assert "Nguyễn Văn Thử" in text and "0912 345 678" in text


def test_gateway_preview_route():
    from app.main import app

    r = TestClient(app).post(
        "/api/gateway/preview", json={"text": "CCCD 001203004567, SĐT 0912345678"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data_class"] == "B"
    assert "001203004567" not in _squash(body["masked"])
    assert body["counts"] == {"CCCD": 1, "SĐT": 1}
