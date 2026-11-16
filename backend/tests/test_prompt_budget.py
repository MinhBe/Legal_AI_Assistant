"""Giới hạn độ dài câu hỏi và cắt lịch sử để prompt cho mô hình trong máy vừa ngữ cảnh 8192."""

from __future__ import annotations

from app.agent import followup
from app.agent.followup import (
    CHARS_PER_TOKEN,
    MAX_QUESTION_TOKENS,
    PROMPT_BUDGET_TOKENS,
    est_tokens,
    history_block,
    history_budget,
)


def test_too_long_question_is_refused_without_any_llm(monkeypatch):
    from app.agent import pipeline

    monkeypatch.setattr(pipeline, "_chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gọi _chat")))
    long_q = "Người lao động bị cho nghỉ việc. " * 400  # khoảng 13.200 ký tự
    assert est_tokens(long_q) > MAX_QUESTION_TOKENS
    events = list(pipeline.run_chat(long_q))
    text = "".join(d["text"] for e, d in events if e == "token")
    assert "Câu hỏi quá dài" in text and "rút gọn" in text
    assert events[-1] == ("done", {"category": "too_long"})


def test_question_at_the_limit_goes_through(monkeypatch):
    from app.agent import pipeline

    monkeypatch.setattr(pipeline, "_chat", lambda *a, **k: iter([("done", {})]))
    q = "a" * int(MAX_QUESTION_TOKENS * CHARS_PER_TOKEN)
    assert list(pipeline.run_chat(q)) == [("done", {})]


def _turns(n: int, size: int) -> list[dict[str, str]]:
    out = []
    for i in range(n):
        out.append({"role": "user", "content": f"Hỏi {i} " + "x" * size})
        out.append({"role": "assistant", "content": f"Đáp {i}"})
    return out


def test_history_drops_oldest_turns_first(monkeypatch):
    monkeypatch.setattr(followup, "_HISTORY_TURNS", 5)
    hist = _turns(5, 2000)
    block = history_block(hist, max_tokens=1700)  # 4.250 ký tự: vừa 2 lượt cuối
    assert len(block) <= 1700 * CHARS_PER_TOKEN
    assert "Hỏi 4" in block and "Hỏi 3" in block and "Hỏi 0" not in block


def test_single_huge_turn_keeps_its_tail():
    hist = [{"role": "user", "content": "ĐẦU " + "y" * 20000 + " CUỐI"}]
    block = history_block(hist, max_tokens=100)
    assert len(block) <= 100 * CHARS_PER_TOKEN and block.endswith("CUỐI") and "ĐẦU" not in block


def test_zero_budget_gives_empty_history():
    assert history_block(_turns(2, 50), max_tokens=0) == ""


def test_no_budget_keeps_old_behaviour():
    hist = _turns(2, 50)
    assert history_block(hist) == history_block(hist, max_tokens=None)


def test_whole_prompt_stays_under_budget_with_longest_question(monkeypatch):
    """Câu hỏi dài nhất được phép + lịch sử rất dài: phần câu hỏi + lịch sử không vượt
    phần ngân sách còn lại sau khi giữ chỗ cho chỉ dẫn và điều luật."""
    q = "z" * int(MAX_QUESTION_TOKENS * CHARS_PER_TOKEN)
    convo = history_block(_turns(2, 30000), max_tokens=history_budget(q))
    assert est_tokens(q) + est_tokens(convo) <= PROMPT_BUDGET_TOKENS - followup.CONTEXT_RESERVE_TOKENS
