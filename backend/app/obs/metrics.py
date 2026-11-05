"""Đo mỗi request và mỗi lời gọi LLM -> data/metrics/*.jsonl (+ Langfuse nếu bật).

Truyền ngữ cảnh qua luồng: generator SSE chạy từng bước ở các luồng khác nhau, và
router đua model trong ThreadPoolExecutor, nên ContextVar không tự đi theo.
- traced(gen, ctx): gắn ctx trong lúc chạy MỖI bước của generator.
- submit(pool, fn, *a): bắt ctx ở luồng gọi, gắn lại trong luồng của pool.
"""
from __future__ import annotations

import contextvars
import json
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import get_settings

settings = get_settings()
_DIR = Path("/app/data/metrics")
_REQ: contextvars.ContextVar[dict | None] = contextvars.ContextVar("req", default=None)
_WRITE = threading.Lock()


def _write(name: str, row: dict) -> None:
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        with _WRITE, (_DIR / name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:  # noqa: BLE001 — đo lường không được làm hỏng app
        logger.warning("Ghi metrics lỗi: {}", exc)


def start_request(kind: str, **attrs: Any) -> dict:
    return {"request_id": uuid.uuid4().hex[:12], "kind": kind, "t0": time.monotonic(),
            "ts": datetime.now(UTC).isoformat(), "ttft_s": None, "llm": [],
            "lock": threading.Lock(), **attrs}


def current() -> dict | None:
    return _REQ.get()


@contextmanager
def bind(ctx: dict | None):
    tok = _REQ.set(ctx)
    try:
        yield
    finally:
        _REQ.reset(tok)


def submit(pool, fn, *args, **kwargs):
    ctx = current()

    def run():
        with bind(ctx):
            return fn(*args, **kwargs)
    return pool.submit(run)


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 3.5))  # chỉ dùng khi nhà cung cấp không trả usage


def record_llm(*, provider: str, model: str, task: str, latency_s: float,
               input_tokens: int | None, output_tokens: int | None, estimated: bool,
               attempts: int = 1, error: str | None = None, reasoning_tokens: int | None = None) -> str:
    """Ghi một lời gọi LLM (kể cả model THUA cuộc đua). Trả về call_id."""
    ctx = current()
    call = {"call_id": uuid.uuid4().hex[:10], "request_id": ctx and ctx["request_id"],
            "ts": datetime.now(UTC).isoformat(), "provider": provider, "model": model,
            "task": task, "latency_s": round(latency_s, 3), "input_tokens": input_tokens,
            "output_tokens": output_tokens, "reasoning_tokens": reasoning_tokens,
            "estimated": estimated, "attempts": attempts, "error": error, "won": False,
            "prompt_version": ctx and ctx.get("prompt_version"),
            "cost_ref_usd": cost_ref(model, input_tokens, output_tokens)}
    if ctx is not None:
        with ctx["lock"]:
            ctx["llm"].append(call)
    _write("llm_calls.jsonl", call)
    return call["call_id"]


def mark_winner(call_id: str | None) -> None:
    ctx = current()
    if ctx is None or not call_id:
        return
    with ctx["lock"]:
        for c in ctx["llm"]:
            if c["call_id"] == call_id:
                c["won"] = True
    _write("llm_winners.jsonl", {"call_id": call_id, "request_id": ctx["request_id"]})


def cost_ref(model: str, tin: int | None, tout: int | None) -> float | None:
    """Chi phí quy đổi theo bảng giá LLM_PRICES_JSON (USD / 1 triệu token).
    Dahl miễn phí, nên đây là chi phí NẾU trả theo giá tham chiếu, không phải tiền thật."""
    try:
        prices = json.loads(settings.llm_prices_json or "{}")
    except ValueError:
        return None
    p = prices.get(model)
    if not p or tin is None or tout is None:
        return None
    return round(tin / 1e6 * p["in"] + tout / 1e6 * p["out"], 6)


def end_request(ctx: dict, **attrs: Any) -> dict:
    calls = ctx["llm"]
    ok = [c for c in calls if not c["error"]]
    won = [c for c in ok if c["won"]]

    def tok(cs):
        return sum((c["input_tokens"] or 0) + (c["output_tokens"] or 0) for c in cs)

    row = {k: v for k, v in ctx.items() if k not in ("t0", "llm", "lock", "result")}
    row.update(attrs)
    row.update({
        "total_s": round(time.monotonic() - ctx["t0"], 3),
        "n_llm_calls": len(calls), "n_llm_errors": len(calls) - len(ok),
        "tokens_all": tok(ok), "tokens_winners": tok(won),
        "race_overhead": round(tok(ok) / tok(won), 2) if tok(won) else None,
        "cost_ref_usd": round(sum(c["cost_ref_usd"] or 0 for c in ok), 6),
        "any_estimated": any(c["estimated"] for c in ok),
    })
    _write("requests.jsonl", row)
    from app.obs import lf  # module này tự bỏ qua khi Langfuse tắt

    lf.send(row, calls)
    return row


def traced(gen, ctx: dict):
    """Bọc generator sự kiện (name, data) của qa: gắn ctx ở mỗi bước, đo ttft, ghi khi xong."""
    it = iter(gen)
    try:
        while True:
            with bind(ctx):
                try:
                    ev = next(it)
                except StopIteration:
                    break
            if ctx["ttft_s"] is None and ev[0] == "token":
                ctx["ttft_s"] = round(time.monotonic() - ctx["t0"], 3)
            if ev[0] == "done" and isinstance(ev[1], dict):
                ctx["category"] = ev[1].get("category", ctx.get("category"))
            yield ev
    finally:
        ctx["result"] = end_request(ctx)
