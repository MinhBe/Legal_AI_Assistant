"""Đo lường (V3): ghi request, gắn ngữ cảnh qua luồng pool, đánh dấu người thắng. Không cần LLM."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.obs import metrics


@pytest.fixture
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics, "_DIR", tmp_path)
    return tmp_path


def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_traced_writes_one_request_with_ttft(mdir):
    def gen():
        yield ("step", {"name": "retrieve"})
        yield ("token", {"text": "xin "})
        yield ("token", {"text": "chào"})
        yield ("done", {"category": "legal"})

    ctx = metrics.start_request("chat", mode="law", prompt_version="v1", question="hỏi gì đó")
    events = list(metrics.traced(gen(), ctx))
    assert [e[0] for e in events] == ["step", "token", "token", "done"]
    rows = _lines(mdir / "requests.jsonl")
    assert len(rows) == 1
    assert rows[0]["kind"] == "chat" and rows[0]["ttft_s"] is not None
    assert rows[0]["category"] == "legal"
    assert rows[0]["question"] == "hỏi gì đó"
    assert rows[0]["answer"] == "xin chào"  # gộp các đoạn token để Langfuse hiển thị Input/Output
    assert ctx["result"]["request_id"] == rows[0]["request_id"]


def test_submit_carries_context_into_pool_thread(mdir):
    ctx = metrics.start_request("eval")
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        with metrics.bind(ctx):
            seen = metrics.submit(pool, lambda: metrics.current()["request_id"]).result()
    finally:
        pool.shutdown()
    assert seen == ctx["request_id"]


def test_record_llm_and_mark_winner(mdir):
    ctx = metrics.start_request("chat")
    with metrics.bind(ctx):
        cid_win = metrics.record_llm(provider="dahl", model="m1", task="answer", latency_s=1.0,
                                     input_tokens=100, output_tokens=20, estimated=False)
        cid_lose = metrics.record_llm(provider="dahl", model="m2", task="answer", latency_s=2.0,
                                      input_tokens=100, output_tokens=30, estimated=False)
        metrics.mark_winner(cid_win)
    calls = {c["call_id"]: c for c in ctx["llm"]}
    assert calls[cid_win]["won"] is True
    assert calls[cid_lose]["won"] is False


def test_record_without_context_does_not_crash(mdir):
    cid = metrics.record_llm(provider="dahl", model="m", task="route", latency_s=0.1,
                             input_tokens=None, output_tokens=None, estimated=True)
    assert cid
    assert _lines(mdir / "llm_calls.jsonl")[0]["call_id"] == cid


def test_cost_ref_needs_a_price_table(monkeypatch):
    monkeypatch.setattr(metrics.settings, "llm_prices_json", "{}")
    assert metrics.cost_ref("m", 1000, 1000) is None
    monkeypatch.setattr(metrics.settings, "llm_prices_json", '{"m": {"in": 1.0, "out": 2.0}}')
    assert metrics.cost_ref("m", 1_000_000, 1_000_000) == 3.0
