"""ML2 — câu không dấu: thử cách đọc tiếng Việt và tiếng Anh, giữ cái khớp hơn. Toàn bộ là giả."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent import pipeline
from app.agent.lang import choose_reading, is_unaccented, restore_diacritics, vi_ratio
from app.llm.context import get_answer_lang

VI_QUESTION = "thoi gian thu viec toi da la bao lau"
VI_RESTORED = "Thời gian thử việc tối đa là bao lâu"
EN_QUESTION = "what is the maximum probation period"


class FakeRouter:
    """Trả một câu cố định cho lượt thêm dấu; ghi lại lời gọi."""

    def __init__(self, reply: str = VI_RESTORED, exc: Exception | None = None):
        self.reply = reply
        self.exc = exc
        self.calls: list[tuple[list, str]] = []

    def chat(self, messages, *, task="answer"):
        self.calls.append((messages, task))
        if self.exc:
            raise self.exc
        return SimpleNamespace(text=self.reply)


def fake_search(*, vi: float = 0.5, en: float = 0.5):
    """Truy hồi giả: điểm cố định cho bản tiếng Việt và bản tiếng Anh."""

    def search(query, *, top_k=5):
        score = vi if query.strip() == VI_RESTORED else en
        return [{"node_id": f"n{i}", "score": score} for i in range(top_k)]

    return search


# ---- is_unaccented ----

@pytest.mark.parametrize(
    ("text", "want"),
    [
        (VI_QUESTION, True),
        ("Thời gian thử việc tối đa là bao lâu?", False),
        ("有給休暇は何日ありますか？", False),
        ("thoi gian", False),
        ("", False),
    ],
)
def test_is_unaccented(text, want):
    assert is_unaccented(text) is want


# ---- vi_ratio ----

def test_vi_ratio_high_for_unaccented_vietnamese():
    assert vi_ratio("thoi gian thu viec toi da la bao lau") >= 0.5


def test_vi_ratio_low_for_english():
    assert vi_ratio(EN_QUESTION) < 0.2


# ---- restore_diacritics ----

@pytest.mark.parametrize(
    "reply",
    [
        "",  # rỗng
        VI_QUESTION,  # không có dấu
        "Thời gian thử việc là bao lâu?",  # lệch số từ > 20 %
    ],
)
def test_restore_rejects_bad_output(reply):
    router = FakeRouter(reply)
    assert restore_diacritics(router, VI_QUESTION) is None
    assert router.calls[0][1] == "route"  # đúng task tuyến rẻ


def test_restore_accepts_good_output():
    router = FakeRouter(VI_RESTORED)
    assert restore_diacritics(router, VI_QUESTION) == VI_RESTORED


# ---- choose_reading ----

def test_choose_reading_vi_wins():
    out = choose_reading(FakeRouter(), fake_search(vi=0.9, en=0.9), VI_QUESTION)
    assert out["lang"] == "vi"
    assert out["text"] == VI_RESTORED
    assert out["vi_ratio"] >= 0.5


def test_choose_reading_en_wins():
    out = choose_reading(FakeRouter(), fake_search(vi=0.4, en=0.9), EN_QUESTION)
    assert out["lang"] == "en"
    assert out["text"] == EN_QUESTION


def test_choose_reading_ties_on_equal_scores_and_neutral_words():
    neutral = "what is thoi gian probation period"
    out = choose_reading(FakeRouter(), fake_search(vi=0.5, en=0.5), neutral)
    assert 0.2 <= out["vi_ratio"] < 0.5
    assert out["scores"]["vi"] == out["scores"]["en"]
    assert out["lang"] == "tie"


# ---- run_chat: chọn cách đọc trước khi trả lời ----

@pytest.fixture
def fake_chat(monkeypatch):
    seen: list[tuple[str, str]] = []

    def _chat(message, history, mode, *, original=None, use_uploads=False):
        seen.append((message, get_answer_lang()))
        yield ("done", {})

    monkeypatch.setattr(pipeline, "_chat", _chat)
    return seen


def test_run_chat_uses_restored_vietnamese(monkeypatch, fake_chat):
    monkeypatch.setattr(pipeline, "get_router", lambda: FakeRouter())
    monkeypatch.setattr(pipeline, "_reading_search", fake_search(vi=0.9, en=0.9))
    events = list(pipeline.run_chat(VI_QUESTION))
    assert fake_chat == [(VI_RESTORED, "vi")]
    reading = [d for e, d in events if e == "reading"]
    assert reading and reading[0]["lang"] == "vi" and reading[0]["vi_text"] == VI_RESTORED


def test_run_chat_keeps_english(monkeypatch, fake_chat):
    monkeypatch.setattr(pipeline, "get_router", lambda: FakeRouter(reply=VI_RESTORED))
    monkeypatch.setattr(pipeline, "_reading_search", fake_search(vi=0.4, en=0.9))
    events = list(pipeline.run_chat(EN_QUESTION))
    assert fake_chat == [(EN_QUESTION, "en")]
    assert [d["lang"] for e, d in events if e == "reading"] == ["en"]


def test_run_chat_asks_which_language_on_tie(monkeypatch, fake_chat):
    monkeypatch.setattr(pipeline, "get_router", lambda: FakeRouter())
    monkeypatch.setattr(pipeline, "_reading_search", fake_search(vi=0.5, en=0.5))
    events = list(pipeline.run_chat("what is thoi gian probation period"))
    assert fake_chat == []  # không gọi LLM trả lời
    assert events[-1] == ("done", {"category": "clarify_language"})
    assert "tiếng Anh" in events[0][1]["text"]


def test_restoration_call_runs_at_the_question_data_class(monkeypatch):
    """Câu không dấu có SĐT (mức B): bước thêm dấu chỉ được chạy với mức B (trong máy)."""
    from app.agent import pipeline
    from app.llm.context import get_data_class

    seen: list[str] = []

    def fake_choose(router, search, text):
        seen.append(get_data_class())
        return {"lang": "vi", "text": text, "vi_text": text, "scores": {}, "vi_ratio": 1.0}

    monkeypatch.setattr(pipeline, "choose_reading", fake_choose)
    monkeypatch.setattr(pipeline, "_chat", lambda *a, **k: iter([("done", {})]))
    list(pipeline.run_chat("toi bi cong ty sa thai, so dien thoai 0912345678, duoc boi thuong gi"))
    assert seen == ["B"]
