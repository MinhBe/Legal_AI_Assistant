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
    _cloud_env(monkeypatch)
    monkeypatch.setattr(r, "_LOCAL_CACHE", [0.0, None])
    monkeypatch.setattr(r, "_probe_local", lambda: True)
    return r.LLMRouter()


def _cloud_env(monkeypatch, *, key="k", fallbacks=""):
    """Tuyến đám mây giả: key nằm trong biến TEST_CLOUD_KEY, DeepSeek cũ tắt, không đọc /keys thật."""
    monkeypatch.setattr(r.settings, "cloud_llm_keys_dir", "")
    monkeypatch.setattr(r, "_KEYS", r.KeyRotation())
    monkeypatch.setattr(r.settings, "cloud_llm_api_key_env", "TEST_CLOUD_KEY")
    if key:
        monkeypatch.setenv("TEST_CLOUD_KEY", key)
    else:
        monkeypatch.delenv("TEST_CLOUD_KEY", raising=False)
    monkeypatch.setattr(r.settings, "cloud_llm_model", "cloud-test")
    monkeypatch.setattr(r.settings, "cloud_llm_fallback_models", fallbacks)
    monkeypatch.setattr(r.settings, "cloud_first_for_c", False)
    monkeypatch.setattr(r.settings, "deepseek_api_key", None)


def _fakes(monkeypatch, router, *, local_text='{"ok": true}', local_exc=None,
           deep_text='{"ok": false}', cloud_exc=None):
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
    monkeypatch.setattr(router, "_call_cloud", make("cloud", deep_text, cloud_exc))
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
        assert router.chat(MSG).provider == "cloud"
    assert [c[0] for c in calls] == ["local", "cloud"]

    # local trả JSON hỏng (Verifier fail) cũng là lỗi -> DeepSeek một lần
    calls = _fakes(monkeypatch, router, local_text="không phải JSON")
    with data_class_scope("C"):
        res = router.chat(MSG, parse=r.parse_json)
    assert (res.provider, res.data) == ("cloud", {"ok": False})
    assert [c[0] for c in calls] == ["local", "cloud"]


def test_default_plan_never_uses_a_legacy_provider(router):
    for task in ("route", "lite", "answer", "draft", "report", "judge", "bulk", "unknown"):
        for level in ("A", "B", "C"):
            with data_class_scope(level):
                providers = {p for p, _ in router._plan(task)}
            assert not providers & LEGACY, (task, level, providers)


def test_run_chat_reports_local_unavailable_and_skips_deepseek(monkeypatch):
    from app.agent import pipeline

    monkeypatch.setattr(r.settings, "llm_legacy_race", False)
    _cloud_env(monkeypatch)
    monkeypatch.setattr(r, "_LOCAL_CACHE", [0.0, None])
    monkeypatch.setattr(r, "_probe_local", lambda: False)
    router = r.get_router()
    calls: list = []
    monkeypatch.setattr(
        router, "_call_cloud",
        lambda *a, **k: calls.append(a) or r.LLMResult(text="x", provider="cloud", model="d"),
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


def test_run_chat_keeps_level_when_resumed_in_fresh_contexts(monkeypatch):
    """Starlette chạy mỗi next() trong một bản sao context mới: mức B phải còn ở mọi
    bước, và không được báo lỗi "created in a different Context"."""
    import contextvars

    from app.agent import pipeline

    seen: list[str] = []

    def fake_chat(message, history, mode, *, original=None):
        for i in range(3):
            seen.append(get_data_class())
            yield ("token", {"text": f"{i}"})
        seen.append(get_data_class())
        yield ("done", {})

    monkeypatch.setattr(pipeline, "_chat", fake_chat)
    gen = pipeline.run_chat("Anh Trần Văn Bình 0912345678 bị cho nghỉ việc không báo trước")
    events = []
    base = contextvars.copy_context()
    while True:
        try:
            events.append(base.copy().run(next, gen))
        except StopIteration:
            break
    assert seen == ["B"] * 4
    assert events[-1] == ("done", {})
    assert get_data_class() == "C"


# ---- tuyến đám mây trung lập nhà cung cấp (CLOUD_LLM_*) ----

def test_level_c_walks_cloud_fallback_models_in_order(router, monkeypatch):
    _cloud_env(monkeypatch, fallbacks="cloud-2,cloud-3")
    seen: list[str] = []

    def cloud(model, messages, temperature, max_tokens, task="answer"):
        seen.append(model)
        if model != "cloud-3":
            raise Boom(f"{model} lỗi")
        return r.LLMResult(text="ok", provider="cloud", model=model)

    monkeypatch.setattr(router, "_call_local", lambda *a, **k: (_ for _ in ()).throw(Boom("local")))
    monkeypatch.setattr(router, "_call_cloud", cloud)
    with data_class_scope("C"):
        assert router.chat(MSG).model == "cloud-3"
    assert seen == ["cloud-test", "cloud-2", "cloud-3"]


def test_cloud_first_for_c_puts_local_last(router, monkeypatch):
    monkeypatch.setattr(r.settings, "cloud_first_for_c", True)
    with data_class_scope("C"):
        assert router._plan("answer") == [("cloud", "cloud-test"), ("local", "local-test")]


@pytest.mark.parametrize("level", ["A", "B"])
def test_a_b_never_reach_cloud_even_when_cloud_first(router, monkeypatch, level):
    monkeypatch.setattr(r.settings, "cloud_first_for_c", True)
    calls = _fakes(monkeypatch, router, local_exc=Boom("local chết"))
    with data_class_scope(level):
        assert router._plan("answer") == [("local", "local-test")]
        with pytest.raises(r.LocalModelUnavailable):
            router.chat(MSG)
    assert [c[0] for c in calls] == ["local"]


def test_default_route_points_at_dahl_by_env_name(monkeypatch):
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.cloud_llm_base_url == "https://inference.dahl.global/v1"
    assert s.cloud_llm_api_key_env == "Dahl_token_1"
    assert s.cloud_llm_keys_dir == "/keys"
    monkeypatch.setattr(s, "cloud_llm_keys_dir", "")  # không đọc thư mục key thật
    monkeypatch.setenv("DAHL_TOKEN_1", "dahl-k")  # tên không phân biệt hoa thường
    monkeypatch.setattr(s, "deepseek_api_key", "ds-k")
    route = s.cloud_route()
    assert route.base_url.startswith("https://inference.dahl.global")
    assert route.models[0] == s.cloud_llm_model and route.source == "Dahl_token_1"
    assert "dahl-k" not in repr(route)  # key không lộ khi in/log


def test_deepseek_vars_are_only_a_fallback_alias(monkeypatch):
    from app.config import Settings

    s = Settings(_env_file=None)
    monkeypatch.setattr(s, "cloud_llm_keys_dir", "")
    monkeypatch.setattr(s, "cloud_llm_api_key_env", "TEST_NO_SUCH_KEY")
    monkeypatch.delenv("TEST_NO_SUCH_KEY", raising=False)
    assert s.cloud_route() is None
    monkeypatch.setattr(s, "deepseek_api_key", "ds-k")
    route = s.cloud_route()
    assert route.base_url == s.deepseek_base_url and route.models == [s.deepseek_model]
    assert route.source == "DEEPSEEK_API_KEY"


def test_no_cloud_key_means_level_c_is_local_only(router, monkeypatch):
    _cloud_env(monkeypatch, key="")
    assert router.available_providers() == {"local": True, "cloud": False}
    with data_class_scope("C"):
        assert router._plan("answer") == [("local", "local-test")]


def test_call_cloud_sends_reasoning_effort_and_rejects_non_vietnamese(router, monkeypatch):
    monkeypatch.setattr(r.settings, "cloud_llm_reasoning_effort", "low")
    monkeypatch.setattr(r.settings, "cloud_llm_min_tokens", 4096)
    got: dict = {}

    def fake_openai(provider, base_url, api_key, model, messages, temperature, max_tokens, **kw):
        got.update(provider=provider, max_tokens=max_tokens, **kw)
        return r.LLMResult(text=got.get("reply", "Câu trả lời"), provider=provider, model=model)

    monkeypatch.setattr(router, "_call_openai", fake_openai)
    assert router._call_cloud("m", MSG, 0.0, 100).text == "Câu trả lời"
    assert got["provider"] == "cloud" and got["max_tokens"] == 4096
    assert got["extra_body"] == {"reasoning_effort": "low"}

    monkeypatch.setattr(router, "_call_openai",
                        lambda *a, **k: r.LLMResult(text="这是中文", provider="cloud", model="m"))
    with pytest.raises(r.LLMError):
        router._call_cloud("m", MSG, 0.0, None)


# ---- thư mục key + xoay vòng + cho key nghỉ ----

class HTTPErr(RuntimeError):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


def _key_dir(tmp_path, monkeypatch, n=3):
    d = tmp_path / "keys"
    d.mkdir()
    lines = [f"Dahl_token_{i} = key-{i}" for i in range(n)]
    (d / "dahl.keys").write_text("# bộ key thử\n" + "\n".join(lines) + "\n\n", encoding="utf-8")
    (d / ".cool-dahl-0").write_text("trạng thái, không phải key", encoding="utf-8")  # tệp ẩn bị bỏ
    (d / "bare.keys").write_text("key-bare\n", encoding="utf-8")
    monkeypatch.setattr(r.settings, "cloud_llm_keys_dir", str(d))
    return d


def _recording_openai(router, monkeypatch, fail: dict[str, Exception]):
    used: list[str] = []

    def fake(provider, base_url, api_key, model, messages, temperature, max_tokens, **kw):
        assert kw.get("retry") is False  # đổi key thay vì thử lại cùng key
        used.append(api_key)
        if api_key in fail:
            raise fail[api_key]
        return r.LLMResult(text="Trả lời", provider="cloud", model=model)

    monkeypatch.setattr(router, "_call_openai", fake)
    return used


def test_key_dir_loads_name_value_and_bare_lines_and_skips_hidden(tmp_path, monkeypatch):
    from app.config import load_key_dir

    d = _key_dir(tmp_path, monkeypatch)
    keys = load_key_dir(str(d))
    assert keys == ("key-bare", "key-0", "key-1", "key-2")
    route = r.settings.cloud_route()
    assert route.api_keys == keys and route.source == str(d)
    assert "key-0" not in repr(route)
    assert load_key_dir(str(tmp_path / "không-có")) == ()


def test_keys_rotate_round_robin_per_call(router, tmp_path, monkeypatch):
    _key_dir(tmp_path, monkeypatch)
    used = _recording_openai(router, monkeypatch, {})
    for _ in range(5):
        router._call_cloud("m", MSG, 0.0, None)
    assert used == ["key-bare", "key-0", "key-1", "key-2", "key-bare"]


def test_exhausted_key_cools_long_and_next_key_answers(router, tmp_path, monkeypatch):
    _key_dir(tmp_path, monkeypatch)
    used = _recording_openai(router, monkeypatch, {"key-bare": HTTPErr(402)})
    assert router._call_cloud("m", MSG, 0.0, None).text == "Trả lời"
    assert used == ["key-bare", "key-0"]
    used.clear()
    for _ in range(4):  # key hết hạn mức không được dùng lại trong lúc nghỉ
        router._call_cloud("m", MSG, 0.0, None)
    assert "key-bare" not in used
    assert r._KEYS._cool_until[0] - r.time.monotonic() > r.KeyRotation.LONG - 5


def test_busy_or_timeout_key_cools_short(router, tmp_path, monkeypatch):
    _key_dir(tmp_path, monkeypatch)
    _recording_openai(router, monkeypatch, {"key-bare": HTTPErr(429), "key-0": TimeoutError("hết giờ")})
    router._call_cloud("m", MSG, 0.0, None)
    left = {i: t - r.time.monotonic() for i, t in r._KEYS._cool_until.items()}
    assert set(left) == {(0, "m"), (1, "m")} and all(0 < s <= r.KeyRotation.SHORT for s in left.values())
    assert r._KEYS.order(4, "model-khác") != []  # key vẫn dùng được cho model khác


def test_request_error_does_not_burn_other_keys(router, tmp_path, monkeypatch):
    _key_dir(tmp_path, monkeypatch)
    used = _recording_openai(router, monkeypatch, {"key-bare": HTTPErr(404)})
    with pytest.raises(HTTPErr):
        router._call_cloud("m", MSG, 0.0, None)
    assert used == ["key-bare"] and not r._KEYS._cool_until


def test_all_keys_failing_escalates_to_next_model(router, tmp_path, monkeypatch):
    _key_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(r.settings, "cloud_llm_fallback_models", "m2")
    monkeypatch.setattr(router, "_call_local", lambda *a, **k: (_ for _ in ()).throw(Boom("local")))
    fails = {k: HTTPErr(503) for k in ("key-bare", "key-0", "key-1", "key-2")}
    calls: list[tuple[str, str]] = []

    def fake(provider, base_url, api_key, model, messages, temperature, max_tokens, **kw):
        calls.append((model, api_key))
        if model == "cloud-test":
            raise fails[api_key]
        return r.LLMResult(text="Trả lời m2", provider="cloud", model=model)

    monkeypatch.setattr(router, "_call_openai", fake)
    with data_class_scope("C"):
        res = router.chat(MSG)
    assert res.model == "m2"
    assert [m for m, _ in calls].count("cloud-test") == 4
    # mọi key đang nghỉ với cloud-test, nên lần sau bỏ qua thẳng sang m2, không gọi lại model lỗi
    calls.clear()
    with data_class_scope("C"):
        assert router.chat(MSG).model == "m2"
    assert [m for m, _ in calls] == ["m2"]


@pytest.mark.parametrize("level", ["A", "B"])
def test_a_b_never_use_key_dir(router, tmp_path, monkeypatch, level):
    _key_dir(tmp_path, monkeypatch)
    monkeypatch.setattr(r.settings, "cloud_first_for_c", True)
    used = _recording_openai(router, monkeypatch, {})
    monkeypatch.setattr(router, "_call_local", lambda *a, **k: (_ for _ in ()).throw(Boom("local")))
    with data_class_scope(level), pytest.raises(r.LocalModelUnavailable):
        router.chat(MSG)
    assert used == []


def test_key_values_never_logged(router, tmp_path, monkeypatch):
    from loguru import logger

    _key_dir(tmp_path, monkeypatch)
    _recording_openai(router, monkeypatch, {"key-bare": HTTPErr(402)})
    out: list[str] = []
    sink = logger.add(out.append, level="DEBUG")
    try:
        router._call_cloud("m", MSG, 0.0, None)
    finally:
        logger.remove(sink)
    text = "".join(out)
    assert "key #0" in text and "key-bare" not in text and "key-0" not in text


def test_gemini_keys_spread_evenly_with_pacing(monkeypatch):
    rt = r.LLMRouter.__new__(r.LLMRouter)
    rt._gemini_keys = ["g1", "g2", "g3"]
    rt._gemini_idx = 0
    monkeypatch.setattr(r.settings, "gemini_key_min_interval_s", 0.0)
    monkeypatch.setattr(r.settings, "gemini_key_daily_cap", 2)
    got = [rt._next_gemini_key() for _ in range(6)]
    assert got == ["g1", "g2", "g3", "g1", "g2", "g3"]
    assert rt.gemini_usage() == [2, 2, 2]
    with pytest.raises(r.LLMError):
        rt._next_gemini_key()  # mọi key chạm hạn mức ngày


def test_gemini_429_cools_that_key_only(monkeypatch):
    rt = r.LLMRouter.__new__(r.LLMRouter)
    rt._gemini_keys = ["g1", "g2"]
    rt._gemini_idx = 0
    monkeypatch.setattr(r.settings, "gemini_key_min_interval_s", 0.0)
    assert rt._next_gemini_key() == "g1"
    rt._gemini_cooldown(HTTPErr(429))
    assert [rt._next_gemini_key() for _ in range(2)] == ["g2", "g2"]
