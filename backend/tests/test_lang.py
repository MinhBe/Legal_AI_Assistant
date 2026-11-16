"""ML1 — câu hỏi tiếng Anh/Nhật/Trung, trả lời bằng ngôn ngữ người hỏi. Toàn bộ là giả."""

from __future__ import annotations

import contextvars
from datetime import date

import pytest

from app.agent import pipeline, qa, verifier
from app.agent.lang import NAMES, answer_instruction, detect
from app.agent.verifier import verify
from app.llm import router as r
from app.llm.context import answer_lang_scope, get_answer_lang

# ---- detect ----

@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Thời gian thử việc tối đa là bao lâu?", "vi"),
        ("What is the maximum probation period?", "en"),
        ("有給休暇は何日ありますか？", "ja"),
        ("试用期最长是多少天", "zh"),
        ("Theo Nghị định 145/2020/NĐ-CP thì giờ làm thêm tối đa là bao nhiêu?", "vi"),
    ],
)
def test_detect(text, want):
    assert detect(text) == want


def test_detect_defaults_to_vietnamese():
    assert detect("") == "vi"


# ---- answer_instruction ----

def test_no_instruction_for_vietnamese():
    assert answer_instruction("vi") == ""


@pytest.mark.parametrize("code", ["en", "ja", "zh"])
def test_instruction_names_the_language(code):
    assert NAMES[code] in answer_instruction(code)


# ---- router: chỉ từ chối chữ Hán/kana khi không phải ja/zh ----

def _cloud_router(monkeypatch):
    monkeypatch.setattr(r.settings, "cloud_llm_keys_dir", "")
    monkeypatch.setattr(r, "_KEYS", r.KeyRotation())
    monkeypatch.setattr(r.settings, "cloud_llm_api_key_env", "TEST_CLOUD_KEY")
    monkeypatch.setenv("TEST_CLOUD_KEY", "k")
    monkeypatch.setattr(r.settings, "cloud_llm_model", "cloud-test")
    monkeypatch.setattr(r.settings, "cloud_llm_fallback_models", "")
    monkeypatch.setattr(r.settings, "deepseek_api_key", None)
    return r.LLMRouter()


MSG = [{"role": "user", "content": "x"}]


def _reply(monkeypatch, router, text):
    monkeypatch.setattr(
        router, "_call_openai",
        lambda *a, **k: r.LLMResult(text=text, provider="cloud", model="m"),
    )


def test_japanese_reply_accepted_only_when_answer_lang_is_ja(monkeypatch):
    router = _cloud_router(monkeypatch)
    _reply(monkeypatch, router, "有給休暇は年間12日です。")
    with answer_lang_scope("ja"):
        assert router._call_cloud("m", MSG, 0.0, 100).text == "有給休暇は年間12日です。"
    with answer_lang_scope("vi"), pytest.raises(r.LLMError):
        router._call_cloud("m", MSG, 0.0, 100)


@pytest.mark.parametrize("code", ["vi", "ja"])
def test_hangul_reply_always_rejected(monkeypatch, code):
    router = _cloud_router(monkeypatch)
    _reply(monkeypatch, router, "연차 휴가는 12일입니다.")
    with answer_lang_scope(code), pytest.raises(r.LLMError):
        router._call_cloud("m", MSG, 0.0, 100)


# ---- pipeline: ngôn ngữ sống qua từng bước next() ----

def test_run_chat_keeps_answer_lang_when_resumed_in_fresh_contexts(monkeypatch):
    seen: list[str] = []

    def fake_chat(message, history, mode, *, original=None):
        for i in range(3):
            seen.append(get_answer_lang())
            yield ("token", {"text": f"{i}"})
        seen.append(get_answer_lang())
        yield ("done", {})

    monkeypatch.setattr(pipeline, "_chat", fake_chat)
    gen = pipeline.run_chat("有給休暇は何日ありますか？")
    events = []
    base = contextvars.copy_context()
    while True:
        try:
            events.append(base.copy().run(next, gen))
        except StopIteration:
            break
    assert seen == ["ja"] * 4
    assert events[-1] == ("done", {})
    assert get_answer_lang() == "vi"


# ---- qa: chỉ dẫn ngôn ngữ trong prompt ----

HITS = [{"node_id": "blld2019-d25-k1", "display": "Điều 25", "text": "Thử việc không quá 60 ngày."}]


def test_answer_messages_carry_the_language_instruction():
    with answer_lang_scope("en"):
        content = qa._answer_messages(HITS, "", "How long is probation?")[1]["content"]
    assert "tiếng Anh" in content
    assert content.index("tiếng Anh") < content.index("Trả về đúng JSON")
    with answer_lang_scope("vi"):
        assert "Viết `summary`" not in qa._answer_messages(HITS, "", "Thử việc bao lâu?")[1]["content"]


# ---- verifier: bản dịch không bị đòi khớp nguyên văn ----

T36 = "Người sử dụng lao động có quyền đơn phương chấm dứt hợp đồng lao động trong trường hợp sau đây."
T41 = "Người sử dụng lao động đơn phương chấm dứt hợp đồng lao động phải báo trước cho người lao động."

NODES = {
    "blld2019-d36-k1": {"node_id": "blld2019-d36-k1", "article_no": 36,
                        "title": "Bộ luật Lao động 2019", "text": T36,
                        "effective_from": None, "effective_to": None},
    "blld2012-d41-k1": {"node_id": "blld2012-d41-k1", "article_no": 41,
                        "title": "Bộ luật Lao động 2012", "text": T41,
                        "effective_from": None, "effective_to": None},
}
VERSIONS = {
    "blld2019-d36-k1": [{"valid_from": date(2021, 1, 1), "valid_to": None}],
    "blld2012-d41-k1": [{"valid_from": date(2013, 5, 1),
                         "valid_to": date(2021, 1, 1)}],
}
VERIFIER_HITS = [
    {"node_id": "blld2019-d36-k1", "display": "Điều 36 (BLLĐ 2019)", "text": T36},
    {"node_id": "blld2012-d41-k1", "display": "Điều 41 (BLLĐ 2012)", "text": T41},
]


@pytest.fixture(autouse=True)
def fake_lookups(monkeypatch):
    monkeypatch.setattr(verifier, "_node_row", lambda db, nid: NODES.get(nid))
    monkeypatch.setattr(verifier, "_version_rows", lambda db, nid: VERSIONS.get(nid, []))


TRANSLATED = {
    "summary": "«Người sử dụng lao động có thể chấm dứt hợp đồng»",
    "citation_node_ids": ["blld2019-d36-k1"],
}


def test_verifier_skips_quotes_for_translation():
    with answer_lang_scope("ja"):
        assert verify(None, TRANSLATED, VERIFIER_HITS, date(2022, 1, 1))["ok"] is True
    with answer_lang_scope("vi"):
        assert verify(None, TRANSLATED, VERIFIER_HITS, date(2022, 1, 1))["ok"] is False


def test_verifier_still_drops_out_of_force_citation_for_translation():
    res = {"summary": "訳", "citation_node_ids": ["blld2012-d41-k1"]}
    with answer_lang_scope("ja"):
        out = verify(None, res, VERIFIER_HITS, date(2022, 1, 1))
    assert out["dropped"] == ["blld2012-d41-k1"]
    assert [p["check"] for p in out["problems"]] == ["in_force"]


def test_foreign_question_with_hits_is_not_blocked_as_out_of_corpus(monkeypatch):
    from app.agent import guard, qa
    from app.llm.context import answer_lang_scope

    monkeypatch.setattr(guard, "classify", lambda *a, **k: {
        "category": guard.OUT_OF_CORPUS, "suggested": "", "reason": ""})
    monkeypatch.setattr(qa, "search_with_history", lambda *a, **k: [
        {"node_id": "blld2019-d25-k2", "doc_id": "blld2019", "display": "Điều 25", "text": "60 ngày", "heading": ""}])
    monkeypatch.setattr(qa, "_generate", lambda *a, **k: {
        "summary": "最長60日です。", "citation_node_ids": ["blld2019-d25-k2"]})
    monkeypatch.setattr(qa, "_run_verify", lambda *a, **k: {"ok": True, "checked": 1, "problems": [], "dropped": []})
    with answer_lang_scope("ja"):
        events = list(qa.answer_with_citations("試用期間は最長どのくらいですか？", []))
    assert "citation" in [e for e, _ in events]
    with answer_lang_scope("vi"):  # tiếng Việt: giữ nguyên kết luận của bộ phân loại
        events = list(qa.answer_with_citations("Câu hỏi ngoài kho", []))
    assert events[-1][1].get("category") == guard.OUT_OF_CORPUS
