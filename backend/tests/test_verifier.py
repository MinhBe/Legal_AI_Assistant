"""T5 — Verifier: trích dẫn có thật, còn hiệu lực tại ngày sự kiện, khớp nguyên văn."""

from __future__ import annotations

from datetime import date

import pytest

from app.agent import guard, qa, verifier
from app.agent.verifier import verify
from app.llm.context import data_class_scope

T36 = "Người sử dụng lao động có quyền đơn phương chấm dứt hợp đồng lao động trong trường hợp sau đây."
T41 = "Người sử dụng lao động đơn phương chấm dứt hợp đồng lao động phải báo trước cho người lao động."

NODES = {
    "blld2019-d36-k1": {
        "node_id": "blld2019-d36-k1", "doc_id": "blld2019", "article_no": 36,
        "title": "Bộ luật Lao động 2019", "text": T36,
        "effective_from": date(2021, 1, 1), "effective_to": None,
    },
    "blld2012-d41-k1": {
        "node_id": "blld2012-d41-k1", "doc_id": "blld2012", "article_no": 41,
        "title": "Bộ luật Lao động 2012", "text": T41,
        "effective_from": date(2013, 5, 1), "effective_to": None,
    },
}

VERSIONS = {
    "blld2019-d36-k1": [{"valid_from": date(2021, 1, 1), "valid_to": None}],
    "blld2012-d41-k1": [{"valid_from": date(2013, 5, 1), "valid_to": date(2021, 1, 1)}],
}

HITS = [
    {"node_id": "blld2019-d36-k1", "display": "Điều 36 (BLLĐ 2019)", "text": T36},
    {"node_id": "blld2012-d41-k1", "display": "Điều 41 (BLLĐ 2012)", "text": T41},
]

DAY = date(2022, 1, 1)


@pytest.fixture(autouse=True)
def fake_lookups(monkeypatch):
    """Thay hai truy vấn DB bằng bảng tra cố định; verify() vẫn chạy nguyên vẹn."""
    monkeypatch.setattr(verifier, "_node_row", lambda db, nid: NODES.get(nid))
    monkeypatch.setattr(verifier, "_version_rows", lambda db, nid: VERSIONS.get(nid, []))


def _result(summary="Theo điều luật.", *ids):
    return {"summary": summary, "citation_node_ids": list(ids)}


def test_valid_citation_is_ok():
    res = verify(None, _result("Theo Điều 36.", "blld2019-d36-k1"), HITS, DAY)
    assert res["ok"] is True
    assert res["checked"] == 1
    assert res["problems"] == [] and res["dropped"] == []


def test_out_of_force_citation_is_dropped():
    res = verify(None, _result("Theo Điều 41.", "blld2012-d41-k1"), HITS, DAY)
    assert res["ok"] is False
    assert [p["check"] for p in res["problems"]] == ["in_force"]
    assert res["dropped"] == ["blld2012-d41-k1"]
    assert res["problems"][0]["message"] == (
        "Điều 41 (BLLĐ 2012) không còn hiệu lực tại ngày 01/01/2022"
    )


def test_unknown_citation_fails_exists():
    res = verify(None, _result("x", "blld2019-d36-k1", "khong-co"), HITS, DAY)
    assert res["ok"] is False
    assert res["problems"][0]["check"] == "exists"
    assert res["problems"][0]["node_id"] == "khong-co"
    assert res["dropped"] == ["khong-co"]
    assert res["checked"] == 2


def test_node_in_corpus_but_not_retrieved_fails_exists():
    res = verify(None, _result("x", "blld2012-d41-k1"), HITS[:1], DAY)
    assert res["problems"][0]["check"] == "exists"


def test_verbatim_quote_passes():
    res = verify(None, _result(f"Luật ghi: «{T36}»", "blld2019-d36-k1"), HITS, DAY)
    assert res["ok"] is True


def test_altered_quote_fails():
    altered = "Người sử dụng lao động có quyền đơn phương chấm dứt trong mọi trường hợp."
    res = verify(None, _result(f"Luật ghi: «{altered}»", "blld2019-d36-k1"), HITS, DAY)
    assert res["ok"] is False
    assert [p["check"] for p in res["problems"]] == ["quotes"]
    assert altered in res["problems"][0]["message"]


def test_short_quote_is_ignored():
    res = verify(None, _result("Điều «36» nói về đơn phương.", "blld2019-d36-k1"), HITS, DAY)
    assert res["ok"] is True


def test_quote_style_and_whitespace_are_tolerated(monkeypatch):
    node = dict(NODES["blld2019-d36-k1"], text="Bên thuê  có quyền — chấm dứt hợp đồng trước hạn.")
    monkeypatch.setitem(NODES, "blld2019-d36-k1", node)
    monkeypatch.setitem(HITS[0], "text", node["text"])
    res = verify(
        None,
        _result("Luật ghi: “Bên thuê có quyền - chấm dứt hợp đồng trước hạn.”", "blld2019-d36-k1"),
        HITS, DAY,
    )
    assert res["ok"] is True


def test_section_quote_uses_its_own_citations():
    result = {
        "summary": "Mở đầu.",
        "sections": [{"title": "Báo trước", "detail": f"«{T36}»", "citation_node_ids": ["blld2012-d41-k1"]}],
        "citation_node_ids": [],
    }
    res = verify(None, result, HITS, DAY)
    checks = [p["check"] for p in res["problems"]]
    # Điều 41 hết hiệu lực -> không được dùng làm chỗ dựa cho đoạn trích của mục
    assert checks == ["in_force", "quotes"]
    assert res["dropped"] == ["blld2012-d41-k1"]


class _Router:
    def __init__(self, replies: list[str]):
        self.replies = replies
        self.calls: list[list[dict]] = []

    def chat(self, msgs, task, temperature=0.0, parse=None):
        self.calls.append(msgs)
        text = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return type("R", (), {"data": parse(text)})()

    def extract_json(self, msgs, task="route"):
        return {"issues": []}


BOTH = '{"summary": "Theo Điều 36 và Điều 41.", "citation_node_ids": ["blld2019-d36-k1", "blld2012-d41-k1"]}'
ONLY_2019 = '{"summary": "Theo Điều 36.", "citation_node_ids": ["blld2019-d36-k1"]}'


def _patch(monkeypatch, router):
    monkeypatch.setattr(qa, "get_router", lambda: router)
    monkeypatch.setattr(qa, "search_with_history", lambda *a, **k: HITS)
    monkeypatch.setattr(
        guard, "classify", lambda *a: {"category": guard.LEGAL, "suggested": "", "reason": ""}
    )


def test_answer_class_c_retries_once_and_drops_out_of_force(monkeypatch):
    router = _Router([BOTH, ONLY_2019])
    _patch(monkeypatch, router)

    events = list(qa.answer_with_citations("Tôi bị sa thải ngày 05/03/2022"))
    kinds = [e for e, _ in events]

    assert [d["node_id"] for e, d in events if e == "citation"] == ["blld2019-d36-k1"]
    assert kinds.index("verifier") == kinds.index("timeframe") - 1
    v = next(d for e, d in events if e == "verifier")
    assert v["ok"] is True and v["dropped"] == []
    assert len(router.calls) == 2
    assert "Bản trả lời trước sai căn cứ" in router.calls[1][-1]["content"]


def test_answer_class_b_calls_generator_once(monkeypatch):
    router = _Router([BOTH])
    _patch(monkeypatch, router)

    with data_class_scope("B"):
        events = list(qa.answer_with_citations("Tôi bị sa thải ngày 05/03/2022"))

    assert [d["node_id"] for e, d in events if e == "citation"] == ["blld2019-d36-k1"]
    v = next(d for e, d in events if e == "verifier")
    assert v["dropped"] == ["blld2012-d41-k1"]
    assert not v["ok"]
    assert len(router.calls) == 1
