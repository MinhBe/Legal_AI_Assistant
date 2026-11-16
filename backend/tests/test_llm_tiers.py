"""Định tuyến theo mức dữ liệu (contract G2) — toàn bộ nhà cung cấp là giả, không gọi mạng."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.llm import router as r
from app.llm.context import data_class_scope, get_data_class

LEGACY = {"dahl", "gemini", "claude", "fpt"}


class Boom(RuntimeError):
    status_code = 400  # lỗi không tạm thời -> _with_retry không thử lại


@pytest.fixture
def router(monkeypatch):
    monkeypatch.setattr(r.settings, "llm_legacy_race", False)
    monkeypatch.setattr(r.settings, "local_model", "local-test")
    monkeypatch.setattr(r.settings, "deepseek_model", "deep-test")
    monkeypatch.setattr(r.settings, "deepseek_api_key", "k")
    monkeypatch.setattr(r, "_LOCAL_CACHE", [0.0, None])
    monkeypatch.setattr(r, "_probe_local", lambda: True)
    return r.LLMRouter()


def _fakes(monkeypatch, router, *, local_text='{"ok": true}', local_exc=None,
           deep_text='{"ok": false}'):
    """Thay hai hàm gọi nhà cung cấp bằng bản ghi lại (provider, model, messages)."""
    calls: list[tuple[str, str, list]] = []

    def make(provider, text, exc):
        def call(model, messages, temperature, max_tokens, task="answer"):
            calls.append((provider, model, messages))
            if exc:
                raise exc
            return r.LLMResult(text=text, provider=provider, model=model)
        return call

    monkeypatch.setattr(router, "_call_local", make("local", local_text, local_exc))
    monkeypatch.setattr(router, "_call_deepseek", make("deepseek", deep_text, None))
    return calls


MSG = [{"role": "user", "content": "Thời gian thử việc tối đa là bao lâu?"}]


def test_level_b_calls_only_local_even_when_it_fails(router, monkeypatch):
    calls = _fakes(monkeypatch, router)
    with data_class_scope("B"):
        assert router.chat(MSG).provider == "local"
    assert [c[0] for c in calls] == ["local"]

    calls = _fakes(monkeypatch, router, local_exc=Boom("local chết"))
    with data_class_scope("B"), pytest.raises(r.LocalModelUnavailable):
        router.chat(MSG)
    assert [c[0] for c in calls] == ["local"]


def test_level_a_calls_only_local_even_when_it_fails(router, monkeypatch):
    calls = _fakes(monkeypatch, router)
    with data_class_scope("A"):
        assert router.chat(MSG).provider == "local"
    assert [c[0] for c in calls] == ["local"]

    calls = _fakes(monkeypatch, router, local_exc=Boom("local chết"))
    with data_class_scope("A"), pytest.raises(r.LocalModelUnavailable):
        router.chat(MSG)
    assert [c[0] for c in calls] == ["local"]


def test_level_c_tries_local_first_then_escalates_once(router, monkeypatch):
    calls = _fakes(monkeypatch, router)
    with data_class_scope("C"):
        assert router.chat(MSG).provider == "local"
    assert [c[0] for c in calls] == ["local"]

    # local lỗi -> DeepSeek một lần
    calls = _fakes(monkeypatch, router, local_exc=Boom("local chết"))
    with data_class_scope("C"):
        assert router.chat(MSG).provider == "deepseek"
    assert [c[0] for c in calls] == ["local", "deepseek"]

    # local trả JSON hỏng (Verifier fail) cũng là lỗi -> DeepSeek một lần
    calls = _fakes(monkeypatch, router, local_text="không phải JSON")
    with data_class_scope("C"):
        res = router.chat(MSG, parse=r.parse_json)
    assert (res.provider, res.data) == ("deepseek", {"ok": False})
    assert [c[0] for c in calls] == ["local", "deepseek"]


def test_default_plan_never_uses_a_legacy_provider(router):
    for task in ("route", "lite", "answer", "draft", "report", "judge", "bulk", "unknown"):
        for level in ("A", "B", "C"):
            with data_class_scope(level):
                providers = {p for p, _ in router._plan(task)}
            assert not providers & LEGACY, (task, level, providers)


def test_run_chat_reports_local_unavailable_and_skips_deepseek(monkeypatch):
    from app.agent import pipeline

    monkeypatch.setattr(r.settings, "llm_legacy_race", False)
    monkeypatch.setattr(r.settings, "deepseek_api_key", "k")
    monkeypatch.setattr(r, "_LOCAL_CACHE", [0.0, None])
    monkeypatch.setattr(r, "_probe_local", lambda: False)
    router = r.get_router()
    calls: list = []
    monkeypatch.setattr(
        router, "_call_deepseek",
        lambda *a, **k: calls.append(a) or r.LLMResult(text="x", provider="deepseek", model="d"),
    )
    monkeypatch.setattr(pipeline, "get_router", lambda: router)

    events = list(pipeline.run_chat("Chị Lan 0912345678 nghỉ thai sản được mấy tháng?"))
    text = "".join(d["text"] for name, d in events if name == "token")
    assert "mô hình chạy trong máy" in text
    assert events[-1] == ("done", {"category": "local_unavailable"})
    assert calls == []


def test_data_class_reaches_worker_threads():
    from app.obs import metrics

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with data_class_scope("B"):
            assert metrics.submit(pool, get_data_class).result(timeout=5) == "B"
    finally:
        pool.shutdown()
